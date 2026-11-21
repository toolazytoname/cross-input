import base64
import importlib.util
import os
import pathlib
import socket
import tempfile
import threading
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("clipboard", ROOT / "scripts/text_clipboard_sync.py")
clipboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clipboard)


class Adapter:
    def get(self): return ""
    def set(self, text): pass


class RuntimeTests(unittest.TestCase):
    def test_receive_only_runtime_starts_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = pathlib.Path(directory) / "secret"
            secret.write_bytes(b"x" * 32)
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            listener.close()
            engine = clipboard.SyncEngine("windows", Adapter(), "127.0.0.1", port, secret.read_bytes(), receive_only=True, status_interval_seconds=60)
            thread = threading.Thread(target=engine.run, args=("127.0.0.1",), daemon=True)
            thread.start()
            deadline = threading.Event()
            for _ in range(30):
                if deadline.wait(0.02): break
                try:
                    with socket.create_connection(("127.0.0.1", port), 0.1): break
                except OSError: pass
            else: self.fail("receiver did not start")
            engine.stop_event.set()
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_windows_adapter_emits_utf8_without_command_echo(self):
        with mock.patch.object(clipboard, "load_windows_library") as library:
            adapter = clipboard.WindowsClipboard()
            user32 = library.return_value
            user32.OpenClipboard.return_value = True
            user32.GetClipboardData.return_value = 13
            kernel32 = mock.Mock()
            library.side_effect = [user32, kernel32]
            kernel32.GlobalLock.return_value = 123
            with mock.patch("ctypes.wstring_at", return_value="中文"):
                self.assertEqual(adapter.get(), "中文")
        user32.CloseClipboard.assert_called_once()

    def test_failed_apply_does_not_suppress_retry(self):
        adapter = mock.Mock()
        adapter.set.side_effect = clipboard.ClipboardSyncError("busy")
        engine = clipboard.SyncEngine("mac", adapter, "127.0.0.1", 8791, b"x" * 32)
        message = clipboard.PeerMessage(1, "windows", 1, int(__import__("time").time() * 1000), "a" * 32, "中文".encode())
        self.assertEqual(engine.receive(message)["status"], "rejected")
        self.assertIsNone(engine.last_applied_remote)


if __name__ == "__main__":
    unittest.main()
