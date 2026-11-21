#!/usr/bin/env python3
import importlib.util
import pathlib
import socket
import threading
import time
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "text_clipboard_sync.py"
spec = importlib.util.spec_from_file_location("text_clipboard_sync", SCRIPT)
sync = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(sync)


class FakeClipboard:
    def __init__(self, text=""):
        self.text = text
        self.set_calls = []

    def get(self):
        return self.text

    def set(self, text):
        self.text = text
        self.set_calls.append(text)


class TextClipboardSyncTests(unittest.TestCase):
    def make_engine(self, clipboard=None, minute_limit=8):
        engine = sync.SyncEngine(
            "mac",
            clipboard or FakeClipboard(),
            "192.168.1.8",
            8791,
            b"x" * 32,
            max_sends_per_minute=minute_limit,
        )
        return engine

    def make_message(self, payload=b"hello", host="windows", sequence=1, timestamp_ms=None, nonce=None):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return sync.PeerMessage(
            version=1,
            host=host,
            sequence=sequence,
            timestamp_ms=timestamp_ms or int(time.time() * 1000),
            nonce=nonce or "n" * 32,
            payload=payload,
        )

    def test_authenticated_frame_round_trip_and_tamper_rejection(self):
        secret = b"a" * 32
        message = self.make_message("中文 clipboard".encode("utf-8"))
        wire = sync.encode_message(message, secret)
        decoded = sync.decode_message(wire, secret)
        self.assertEqual(decoded.payload, message.payload)
        tampered = wire[:-1] + (b"0" if wire[-1:] != b"0" else b"1")
        with self.assertRaises(sync.ClipboardSyncError):
            sync.decode_message(tampered, secret)

    def test_receiver_applies_utf8_once_and_rejects_duplicate_sequence(self):
        clipboard = FakeClipboard()
        engine = self.make_engine(clipboard)
        message = self.make_message("first")
        self.assertEqual(engine.receive(message)["status"], "applied")
        self.assertEqual(clipboard.text, "first")
        self.assertEqual(engine.receive(message)["status"], "duplicate")
        self.assertEqual(len(clipboard.set_calls), 1)

    def test_applied_remote_change_is_suppressed_as_local_change(self):
        clipboard = FakeClipboard("applied-by-peer")
        engine = self.make_engine(clipboard)
        fingerprint = engine.fingerprint(clipboard.text)
        engine.last_applied_remote = ("windows", 4, fingerprint)
        sent = []
        engine.send_message = lambda message: sent.append(message)
        self.assertFalse(engine.poll_and_send(now=1000))
        self.assertEqual(sent, [])

    def test_empty_clipboard_is_not_sent(self):
        engine = self.make_engine(FakeClipboard(""))
        engine.send_message = lambda message: self.fail("empty clipboard should not be sent")
        self.assertFalse(engine.poll_and_send())

    def test_local_change_sends_once_and_deduplicates_same_text(self):
        clipboard = FakeClipboard("local-change")
        engine = self.make_engine(clipboard)
        sent = []
        engine.send_message = lambda message: sent.append(message)
        self.assertTrue(engine.poll_and_send(now=1000))
        self.assertFalse(engine.poll_and_send(now=1001))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].payload, b"local-change")

    def test_rate_limit_and_oversize_text_are_visible(self):
        clipboard = FakeClipboard()
        engine = self.make_engine(clipboard, minute_limit=2)
        sent = []
        engine.send_message = lambda message: sent.append(message)
        clipboard.text = "one"
        self.assertTrue(engine.poll_and_send(now=1000))
        clipboard.text = "two"
        self.assertTrue(engine.poll_and_send(now=1001))
        clipboard.text = "three"
        self.assertFalse(engine.poll_and_send(now=1002))
        self.assertEqual(len(sent), 2)
        clipboard.text = "x" * (sync.MAX_TEXT_BYTES + 1)
        self.assertFalse(engine.poll_and_send(now=1003))
        self.assertTrue(any(event["event"] == "local-text-too-large" for event in engine.event_log))

    def test_host_sequence_persists_across_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            sequence_file = pathlib.Path(temporary) / "mac.sequence"
            first = self.make_engine(FakeClipboard("first"))
            first.sequence_file = sequence_file
            first.send_message = lambda message: None
            first.poll_and_send(now=1000)
            second = sync.SyncEngine(
                "mac",
                FakeClipboard("second"),
                "192.168.1.8",
                8791,
                b"x" * 32,
                sequence_file=sequence_file,
                initial_sequence=sync.load_sequence(sequence_file),
            )
            second.send_message = lambda message: None
            second.poll_and_send(now=1001)
            self.assertEqual(first.sequence, 1)
            self.assertEqual(second.sequence, 2)
            self.assertEqual(sync.load_sequence(sequence_file), 2)

    def test_protocol_rejects_old_timestamp_wrong_host_and_oversize_payload(self):
        engine = self.make_engine()
        old = self.make_message(timestamp_ms=int(time.time() * 1000) - 6000)
        self.assertEqual(engine.receive(old)["reason"], "timestamp-out-of-range")
        self_message = self.make_message(host="mac")
        self.assertEqual(engine.receive(self_message)["reason"], "self-host")
        large = self.make_message(payload=b"x" * (sync.MAX_TEXT_BYTES + 1))
        wire = sync.encode_message(large, b"x" * 32)
        with self.assertRaisesRegex(sync.ClipboardSyncError, "exceeds"):
            sync.decode_message(wire, b"x" * 32)

    def test_invalid_utf8_is_rejected_without_changing_clipboard(self):
        clipboard = FakeClipboard("unchanged")
        engine = self.make_engine(clipboard)
        message = self.make_message(payload=b"\xff\xfe")
        self.assertEqual(engine.receive(message)["reason"], "apply-failed")
        self.assertEqual(clipboard.text, "unchanged")

    def test_replayed_nonce_with_a_new_sequence_is_rejected(self):
        clipboard = FakeClipboard("unchanged")
        engine = self.make_engine(clipboard)
        timestamp = int(time.time() * 1000)
        first = self.make_message(payload=b"first", sequence=1, timestamp_ms=timestamp)
        replay = self.make_message(payload=b"replay", sequence=2, timestamp_ms=timestamp, nonce=first.nonce)
        self.assertEqual(engine.receive(first)["status"], "applied")
        self.assertEqual(engine.receive(replay)["reason"], "replayed-nonce")
        self.assertEqual(clipboard.text, "first")

    def test_configured_engine_rejects_unexpected_authenticated_host(self):
        clipboard = FakeClipboard("unchanged")
        engine = sync.SyncEngine(
            "mac",
            clipboard,
            "192.168.1.8",
            8791,
            b"x" * 32,
            expected_peer_host="windows",
        )
        self.assertEqual(engine.receive(self.make_message(host="other"))["reason"], "unexpected-host")
        self.assertEqual(clipboard.text, "unchanged")

    def test_wire_round_trip_accepts_duplicate_for_same_text_after_lost_response(self):
        receiver_clipboard = FakeClipboard()
        receiver = sync.SyncEngine("windows", receiver_clipboard, "127.0.0.1", 0, b"x" * 32)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        server = threading.Thread(target=receiver.serve, args=(listener,), daemon=True)
        server.start()
        sender = sync.SyncEngine("mac", FakeClipboard("first"), "127.0.0.1", port, b"x" * 32)
        try:
            sender.send_message(self.make_message(payload=b"first", host="mac"))
            second = self.make_message(payload=b"first", host="mac", sequence=2)
            sender.send_message(second)
        finally:
            receiver.stop_event.set()
            server.join(timeout=2)
            listener.close()
        self.assertEqual(receiver_clipboard.set_calls, ["first"])
        self.assertEqual(receiver.last_applied_remote[2], sender.fingerprint("first"))

    def test_lost_response_retries_same_text_and_acknowledges_duplicate(self):
        clipboard = FakeClipboard("retry-me")
        sender = self.make_engine(clipboard)
        attempts = []

        def lose_first_response(message):
            attempts.append(message)
            if len(attempts) == 1:
                raise sync.ClipboardSyncError("invalid peer response")

        sender.send_message = lose_first_response
        with self.assertRaises(sync.ClipboardSyncError):
            sender.poll_and_send(now=1000)
        self.assertEqual(sender.pending_text, "retry-me")
        self.assertTrue(sender.poll_and_send(now=1002))
        self.assertIsNone(sender.pending_text)
        self.assertEqual(len(attempts), 2)
        self.assertGreater(attempts[1].sequence, attempts[0].sequence)

    def test_duplicate_sequence_response_identifies_payload(self):
        engine = self.make_engine()
        message = self.make_message(payload=b"first")
        self.assertEqual(engine.receive(message)["status"], "applied")
        response = engine.receive(message)
        self.assertEqual(response["status"], "duplicate")
        self.assertEqual(response["fingerprint"], engine.fingerprint("first"))

    def test_cli_rejects_wildcard_and_public_addresses(self):
        for address in ("0.0.0.0", "8.8.8.8"):
            with self.assertRaisesRegex(sync.ClipboardSyncError, "private"):
                sync.validate_private_ipv4_address(address, "listen address")
        self.assertEqual(sync.validate_private_ipv4_address("192.168.1.4", "peer address"), "192.168.1.4")


if __name__ == "__main__":
    unittest.main()
