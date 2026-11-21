#!/usr/bin/env python3
"""Synchronize bounded UTF-8 clipboard text between the Mac mini and 3090."""

import argparse
import base64
import collections
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


MAX_TEXT_BYTES = 256 * 1024
PROTOCOL_VERSION = 1
DEFAULT_PORT = 8791


class ClipboardSyncError(RuntimeError):
    pass


class MacClipboard:
    def get(self) -> Optional[str]:
        completed = subprocess.run(
            ["/usr/bin/pbpaste"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2,
            check=False,
        )
        if completed.returncode != 0:
            raise ClipboardSyncError("pbpaste failed with exit code " + str(completed.returncode))
        return completed.stdout.decode("utf-8", errors="strict")

    def set(self, text: str) -> None:
        completed = subprocess.run(
            ["/usr/bin/pbcopy"],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=2,
            check=False,
        )
        if completed.returncode != 0:
            raise ClipboardSyncError("pbcopy failed with exit code " + str(completed.returncode))


class WindowsClipboard:
    def get(self) -> Optional[str]:
        command = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
            "$text = Get-Clipboard -Raw; "
            "if ($null -ne $text) { [Console]::Out.Write($text) }"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3,
            check=False,
        )
        if completed.returncode != 0:
            raise ClipboardSyncError("Get-Clipboard failed with exit code " + str(completed.returncode))
        return completed.stdout.decode("utf-8", errors="strict")

    def set(self, text: str) -> None:
        command = (
            "$encoded = [Console]::In.ReadToEnd().Trim(); "
            "$bytes = [Convert]::FromBase64String($encoded); "
            "$text = [System.Text.Encoding]::UTF8.GetString($bytes); "
            "Set-Clipboard -Value $text"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            input=base64.b64encode(text.encode("utf-8")).decode("ascii"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=3,
            check=False,
        )
        if completed.returncode != 0:
            raise ClipboardSyncError("Set-Clipboard failed with exit code " + str(completed.returncode))


@dataclass(frozen=True)
class PeerMessage:
    version: int
    host: str
    sequence: int
    timestamp_ms: int
    nonce: str
    payload: bytes


def encode_message(message: PeerMessage, secret: bytes) -> bytes:
    body = {
        "version": message.version,
        "host": message.host,
        "sequence": message.sequence,
        "timestamp_ms": message.timestamp_ms,
        "nonce": message.nonce,
        "payload": base64.b64encode(message.payload).decode("ascii"),
    }
    body_json = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret, body_json, hashlib.sha256).hexdigest().encode("ascii")
    return str(len(body_json)).encode("ascii") + b" " + body_json + b" " + digest


def decode_message(data: bytes, secret: bytes) -> PeerMessage:
    try:
        header, body_json, digest = data.split(b" ", 2)
        body_length = int(header)
    except (ValueError, TypeError) as error:
        raise ClipboardSyncError("malformed message header") from error
    if body_length <= 0 or body_length > MAX_TEXT_BYTES * 4 or len(body_json) != body_length:
        raise ClipboardSyncError("invalid message length")
    expected_digest = hmac.new(secret, body_json, hashlib.sha256).hexdigest().encode("ascii")
    if not hmac.compare_digest(digest, expected_digest):
        raise ClipboardSyncError("invalid message authentication")
    try:
        body = json.loads(body_json.decode("utf-8"))
        payload = base64.b64decode(body["payload"], validate=True)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ClipboardSyncError("invalid message body") from error
    if not isinstance(body, dict):
        raise ClipboardSyncError("unsupported message identity")
    valid_identity = (
        body.get("version") == PROTOCOL_VERSION
        and isinstance(body.get("host"), str)
        and 1 <= len(body["host"]) <= 32
        and isinstance(body.get("sequence"), int)
        and not isinstance(body.get("sequence"), bool)
        and body["sequence"] > 0
        and isinstance(body.get("timestamp_ms"), int)
        and not isinstance(body.get("timestamp_ms"), bool)
        and isinstance(body.get("nonce"), str)
        and 16 <= len(body["nonce"]) <= 64
    )
    if not valid_identity:
        raise ClipboardSyncError("unsupported message identity")
    if len(payload) > MAX_TEXT_BYTES:
        raise ClipboardSyncError("clipboard text exceeds 256 KiB")
    return PeerMessage(
        version=int(body["version"]),
        host=body["host"],
        sequence=int(body["sequence"]),
        timestamp_ms=int(body["timestamp_ms"]),
        nonce=str(body["nonce"]),
        payload=payload,
    )


class SyncEngine:
    def __init__(
        self,
        local_host: str,
        clipboard,
        peer_address: str,
        peer_port: int,
        secret: bytes,
        poll_seconds: float = 0.5,
        send_timeout_seconds: float = 2.0,
        max_sends_per_minute: int = 8,
        status_interval_seconds: float = 10.0,
        emit_events: bool = False,
        sequence_file: Optional[Path] = None,
        initial_sequence: int = 0,
        expected_peer_host: Optional[str] = None,
    ):
        self.local_host = local_host
        self.expected_peer_host = expected_peer_host
        self.clipboard = clipboard
        self.peer_address = peer_address
        self.peer_port = peer_port
        self.secret = secret
        self.poll_seconds = poll_seconds
        self.send_timeout_seconds = send_timeout_seconds
        self.max_sends_per_minute = max_sends_per_minute
        self.status_interval_seconds = status_interval_seconds
        self.emit_events = emit_events
        self.sequence_file = sequence_file
        self.sequence = max(0, initial_sequence)
        self.last_sent_fingerprint: Optional[str] = None
        self.pending_text: Optional[str] = None
        self.last_applied_remote: Optional[Tuple[str, int, str]] = None
        self.remote_sequences: Dict[str, int] = {}
        self.remote_delivery_fingerprints: Dict[Tuple[str, int], str] = {}
        self.remote_fingerprints = collections.OrderedDict()
        self.remote_nonces = collections.OrderedDict()
        self.send_times: List[float] = []
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.event_log: List[Dict[str, object]] = []
        self.event_print_lock = threading.Lock()

    def fingerprint(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        payload = text.encode("utf-8")
        if len(payload) > MAX_TEXT_BYTES:
            return "__too_large__"
        return hashlib.sha256(payload).hexdigest()

    def record(self, event: str, **metadata) -> None:
        entry = {"event": event, "host": self.local_host, "utc": time.time(), **metadata}
        self.event_log.append(entry)
        if len(self.event_log) > 500:
            del self.event_log[:250]
        if self.emit_events:
            with self.event_print_lock:
                print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")), flush=True)

    def poll_and_send(self, now: Optional[float] = None) -> bool:
        current_time = time.time() if now is None else now
        text = self.clipboard.get()
        if not isinstance(text, str):
            raise ClipboardSyncError("clipboard adapter returned non-text content")
        current_fingerprint = self.fingerprint(text)
        if text is None or current_fingerprint in (None, "__too_large__"):
            if current_fingerprint == "__too_large__":
                self.record("local-text-too-large", size_bytes=len(text.encode("utf-8")))
            return False

        if self.pending_text is not None and current_fingerprint == self.fingerprint(self.pending_text):
            # A lost response leaves delivery uncertain. Retry the latest local
            # clipboard change with a fresh sequence; the peer deduplicates it.
            pass
        elif self.pending_text is not None:
            self.pending_text = None
            self.last_sent_fingerprint = None
            self.last_applied_remote = None

        if self.last_applied_remote is not None:
            remote_host, remote_sequence, applied_fingerprint = self.last_applied_remote
            if current_fingerprint == applied_fingerprint:
                self.record("remote-change-suppressed", peer=remote_host, sequence=remote_sequence)
                return False
        if current_fingerprint == self.last_sent_fingerprint:
            return False

        with self.lock:
            cutoff = current_time - 60
            self.send_times = [stamp for stamp in self.send_times if stamp >= cutoff]
            if len(self.send_times) >= self.max_sends_per_minute:
                self.record("send-rate-limited", queued=False)
                return False
            self.sequence += 1
            sequence = self.sequence
            self.send_times.append(current_time)
            if self.sequence_file is not None:
                save_sequence(self.sequence_file, sequence)

        message = PeerMessage(
            version=PROTOCOL_VERSION,
            host=self.local_host,
            sequence=sequence,
            timestamp_ms=int(current_time * 1000),
            nonce=secrets.token_hex(16),
            payload=text.encode("utf-8"),
        )
        self.pending_text = text
        self.send_message(message)
        self.pending_text = None
        self.last_sent_fingerprint = current_fingerprint
        self.record(
            "sent",
            sequence=sequence,
            size_bytes=len(message.payload),
            fingerprint=current_fingerprint,
        )
        return True

    def send_message(self, message: PeerMessage) -> None:
        wire = encode_message(message, self.secret)
        with socket.create_connection((self.peer_address, self.peer_port), self.send_timeout_seconds) as connection:
            connection.settimeout(self.send_timeout_seconds)
            connection.sendall(wire)
            response = read_json_response(connection)
        try:
            result = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ClipboardSyncError("invalid peer response") from error
        fingerprint = hashlib.sha256(message.payload).hexdigest()
        duplicate_for_same_text = (
            result.get("status") == "duplicate"
            and result.get("fingerprint") == fingerprint
        )
        if result.get("status") != "applied" and not duplicate_for_same_text:
            raise ClipboardSyncError("peer rejected message: " + str(result.get("reason")))

    def run(self, listen_address: str) -> None:
        try:
            self.serve_and_poll(listen_address)
        except KeyboardInterrupt:
            self.stop_event.set()
            self.record("stopped", reason="sigint-ctrl-c")

    def receive(self, message: PeerMessage) -> Dict[str, object]:
        now_ms = int(time.time() * 1000)
        if abs(now_ms - message.timestamp_ms) > 5000:
            return {"status": "rejected", "reason": "timestamp-out-of-range"}
        if message.host == self.local_host:
            return {"status": "rejected", "reason": "self-host"}
        if self.expected_peer_host is not None and message.host != self.expected_peer_host:
            return {"status": "rejected", "reason": "unexpected-host"}
        payload_fingerprint = hashlib.sha256(message.payload).hexdigest()
        with self.lock:
            last_sequence = self.remote_sequences.get(message.host, 0)
            if message.sequence <= last_sequence:
                return {
                    "status": "duplicate",
                    "sequence": message.sequence,
                    "fingerprint": self.remote_delivery_fingerprints.get((message.host, message.sequence)),
                }
            if (message.host, payload_fingerprint) in self.remote_fingerprints:
                return {"status": "duplicate", "fingerprint": payload_fingerprint}
            self.remote_sequences[message.host] = message.sequence
            self.remote_delivery_fingerprints[(message.host, message.sequence)] = payload_fingerprint
            self.remote_fingerprints[(message.host, payload_fingerprint)] = message.sequence
            nonce_key = (message.host, message.nonce)
            if nonce_key in self.remote_nonces:
                return {"status": "duplicate", "reason": "replayed-nonce"}
            self.remote_nonces[nonce_key] = message.sequence
            while len(self.remote_fingerprints) > 256:
                self.remote_fingerprints.popitem(last=False)
            while len(self.remote_nonces) > 512:
                self.remote_nonces.popitem(last=False)

        try:
            text = message.payload.decode("utf-8", errors="strict")
            self.clipboard.set(text)
        except (UnicodeDecodeError, ClipboardSyncError) as error:
            self.record("apply-failed", peer=message.host, sequence=message.sequence, reason=type(error).__name__)
            return {"status": "rejected", "reason": "apply-failed"}
        self.last_applied_remote = (message.host, message.sequence, payload_fingerprint)
        self.record(
            "applied",
            peer=message.host,
            sequence=message.sequence,
            size_bytes=len(message.payload),
            fingerprint=payload_fingerprint,
        )
        return {"status": "applied", "sequence": message.sequence}

    def serve(self, listener: socket.socket) -> None:
        listener.settimeout(0.5)
        while not self.stop_event.is_set():
            try:
                connection, peer = listener.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(3.0)
                try:
                    request = read_frame(connection)
                    message = decode_message(request, self.secret)
                    response = self.receive(message)
                except (OSError, ClipboardSyncError) as error:
                    response = {"status": "rejected", "reason": type(error).__name__}
                connection.sendall(json.dumps(response, separators=(",", ":")).encode("utf-8"))

    def run(self, listen_address: str) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((listen_address, self.peer_port))
        listener.listen(4)
        server_thread = threading.Thread(target=self.serve, args=(listener,), daemon=True)
        server_thread.start()
        self.record("started", listen_address=listen_address, peer=self.peer_address)
        next_status = time.monotonic() + self.status_interval_seconds
        try:
            while not self.stop_event.is_set():
                try:
                    self.poll_and_send()
                except (OSError, ClipboardSyncError, subprocess.SubprocessError) as error:
                    self.record("poll-failed", reason=type(error).__name__)
                if time.monotonic() >= next_status:
                    self.record(
                        "status",
                        sequence=self.sequence,
                        remote_sequences=dict(self.remote_sequences),
                        last_sent_fingerprint=self.last_sent_fingerprint,
                    )
                    next_status = time.monotonic() + self.status_interval_seconds
                self.stop_event.wait(self.poll_seconds)
        finally:
            self.stop_event.set()
            listener.close()
            server_thread.join(timeout=1.0)
            self.record("stopped")


def read_json_response(connection: socket.socket) -> bytes:
    chunks = []
    total = 0
    while total < 4096:
        chunk = connection.recv(min(4096 - total, 1024))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if total >= 4096:
        raise ClipboardSyncError("peer response too large")
    return b"".join(chunks)


def read_frame(connection: socket.socket) -> bytes:
    header = b""
    while b" " not in header:
        byte = connection.recv(1)
        if not byte:
            raise ClipboardSyncError("connection closed before header")
        header += byte
        if len(header) > 12:
            raise ClipboardSyncError("header too long")
    try:
        body_length = int(header.strip())
    except ValueError as error:
        raise ClipboardSyncError("invalid header") from error
    if body_length <= 0 or body_length > MAX_TEXT_BYTES * 4:
        raise ClipboardSyncError("body too large")
    body = read_exact(connection, body_length)
    separator = read_exact(connection, 1)
    digest = read_exact(connection, 64)
    if separator != b" ":
        raise ClipboardSyncError("invalid frame separator")
    return header + body + separator + digest


def read_exact(connection: socket.socket, length: int) -> bytes:
    chunks = []
    remaining = length
    while remaining:
        chunk = connection.recv(min(remaining, 65536))
        if not chunk:
            raise ClipboardSyncError("connection closed before body")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def load_secret(path: Path) -> bytes:
    secret = path.read_bytes().strip()
    if len(secret) < 32:
        raise ClipboardSyncError("secret file must contain at least 32 bytes")
    return secret


def write_secret(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    path.write_bytes(secret)
    path.chmod(0o600)
    return secret


def load_sequence(path: Path) -> int:
    try:
        value = int(path.read_text(encoding="ascii").strip())
    except (FileNotFoundError, ValueError):
        return 0
    return value if value > 0 else 0


def save_sequence(path: Path, sequence: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(str(sequence) + "\n", encoding="ascii")
    temporary.replace(path)


def validate_private_ipv4_address(value: str, label: str) -> str:
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError as error:
        raise ClipboardSyncError(label + " is not an IPv4 address") from error
    if address.is_unspecified or address.is_multicast or not (address.is_loopback or address.is_private):
        raise ClipboardSyncError(label + " must be a loopback or private IPv4 address")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync bounded UTF-8 clipboard text over an authenticated LAN channel")
    parser.add_argument("--host", choices=("mac", "windows"), required=True)
    parser.add_argument("--listen", required=True, help="private LAN address to bind; do not bind 0.0.0.0")
    parser.add_argument("--peer", required=True, help="peer private LAN address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--secret-file", type=Path, required=True)
    parser.add_argument(
        "--sequence-file",
        type=Path,
        help="persistent host-local sequence file; defaults to <secret-file>.sequence",
    )
    parser.add_argument("--generate-secret", action="store_true")
    parser.add_argument("--status-interval", type=float, default=10.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    listen_address = validate_private_ipv4_address(args.listen, "listen address")
    peer_address = validate_private_ipv4_address(args.peer, "peer address")
    if not 1024 <= args.port <= 65535:
        raise ClipboardSyncError("port must be between 1024 and 65535")
    if args.status_interval <= 0:
        raise ClipboardSyncError("status interval must be positive")
    if args.generate_secret:
        write_secret(args.secret_file)
    secret = load_secret(args.secret_file)
    sequence_file = args.sequence_file or args.secret_file.with_name(args.secret_file.name + ".sequence")
    clipboard = MacClipboard() if args.host == "mac" else WindowsClipboard()
    engine = SyncEngine(
        args.host,
        clipboard,
        peer_address,
        args.port,
        secret,
        status_interval_seconds=args.status_interval,
        emit_events=True,
        sequence_file=sequence_file,
        initial_sequence=load_sequence(sequence_file),
        expected_peer_host=("windows" if args.host == "mac" else "mac"),
    )
    try:
        engine.run(listen_address)
    except (OSError, ClipboardSyncError, subprocess.SubprocessError) as error:
        print(json.dumps({"event": "startup-failed", "reason": type(error).__name__}), flush=True)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
