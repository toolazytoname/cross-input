import base64
import importlib.util
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("keyboard_protocol", ROOT / "scripts/keyboard_protocol.py")
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


class KeyboardProtocolTests(unittest.TestCase):
    def test_round_trip_and_tamper_rejection(self):
        event = protocol.KeyEvent("key", 1, "a" * 32, 1000, "a", True, session="12345678-1234-1234-1234-123456789012")
        wire = protocol.encode_event(event, b"s" * 32)
        self.assertNotIn(b'"key":"a"', wire)
        with self.assertRaises(ValueError):
            protocol.decode_event(wire, b"wrong" * 8)

    def test_unknown_key_and_event_rejected(self):
        with self.assertRaises(ValueError):
            protocol.encode_event(protocol.KeyEvent("key", 1, "a" * 32, 1, "not-a-key", True, session="12345678-1234-1234-1234-123456789012"), b"s" * 32)
        with self.assertRaises(ValueError):
            protocol.encode_event(protocol.KeyEvent("type-text", 1, "a" * 32, 1, session="12345678-1234-1234-1234-123456789012"), b"s" * 32)

    def test_windows_key_table_and_release(self):
        source = (ROOT / "scripts/windows_input_service.ps1").read_text()
        for token in ("release_all", "Down.Clear", "SESSION_UNAVAILABLE", "SendInput", "Nonces", "LastSequence"):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
