"""Authenticated key-event transport. No key values or text are logged."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


VERSION = 1
EVENT_TYPES = {"key", "release_all", "ping"}
KEY_NAMES = {
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "space", "return", "tab", "escape", "backspace", "delete",
    "left", "right", "up", "down", "home", "end", "pageup", "pagedown", "insert",
    "shift", "control", "option", "command", "capslock",
    "leftshift", "rightshift", "leftcontrol", "rightcontrol", "leftoption", "rightoption", "leftcommand", "rightcommand",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "minus", "equal", "leftbracket", "rightbracket", "backslash", "semicolon", "quote", "comma", "period", "slash", "grave",
}


@dataclass(frozen=True)
class KeyEvent:
    kind: str
    sequence: int
    nonce: str
    timestamp_ms: int
    key: Optional[str] = None
    pressed: Optional[bool] = None
    flags: int = 0
    session: str = ""


def encode_event(event: KeyEvent, secret: bytes) -> bytes:
    if event.kind not in EVENT_TYPES or event.sequence < 1 or len(event.nonce) != 32 or len(event.session) != 36:
        raise ValueError("invalid keyboard event")
    if event.kind == "key" and (event.key not in KEY_NAMES or not isinstance(event.pressed, bool)):
        raise ValueError("invalid key or state")
    body = {
        "version": VERSION, "kind": event.kind, "sequence": event.sequence,
        "nonce": event.nonce, "timestamp_ms": event.timestamp_ms,
        "key": event.key, "pressed": event.pressed, "flags": event.flags,
        "session": event.session,
    }
    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.b64encode(payload) + b"." + hmac.new(secret, payload, hashlib.sha256).hexdigest().encode("ascii") + b"\n"


def decode_event(data: bytes, secret: bytes) -> KeyEvent:
    try:
        encoded, digest = data.rstrip(b"\n").split(b".", 1)
        payload = base64.b64decode(encoded, validate=True)
        if not hmac.compare_digest(digest, hmac.new(secret, payload, hashlib.sha256).hexdigest().encode("ascii")):
            raise ValueError("authentication failed")
        body = json.loads(payload)
        event = KeyEvent(body["kind"], body["sequence"], body["nonce"], body["timestamp_ms"], body.get("key"), body.get("pressed"), body.get("flags", 0), body["session"])
        encode_event(event, secret)
        if body["version"] != VERSION or abs(time.time() * 1000 - event.timestamp_ms) > 10000 or not isinstance(event.flags, int) or event.flags < 0 or event.flags > 0x00FF0000:
            raise ValueError("stale event")
        return event
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid keyboard frame") from error


class KeySender:
    def __init__(self, host: str, port: int, secret_path: Path):
        self.host = host
        self.port = port
        self.secret = secret_path.read_bytes().strip()
        self.sequence = 0
        self.session = str(uuid.uuid4())

    def send(self, kind: str, key: Optional[str] = None, pressed: Optional[bool] = None, flags: int = 0) -> None:
        self.sequence += 1
        event = KeyEvent(kind, self.sequence, secrets.token_hex(16), int(time.time() * 1000), key, pressed, flags, self.session)
        with socket.create_connection((self.host, self.port), 2) as connection:
            connection.settimeout(2)
            connection.sendall(encode_event(event, self.secret))
            if connection.recv(32) != b"ok\n":
                raise OSError("keyboard receiver rejected event")
