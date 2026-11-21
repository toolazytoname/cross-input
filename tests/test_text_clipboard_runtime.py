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
        adapter = clipboard.WindowsClipboard()
        result = mock.Mock(returncode=0, stdout=base64.b64encode("中文".encode()), stderr=b"")
        with mock.patch("subprocess.run", return_value=result) as run:
            self.assertEqual(adapter.get(), "中文")
        command = run.call_args.args[0][-1]
        self.assertIn("UnicodeText", command)
        self.assertIn("ToBase64String", command)


if __name__ == "__main__":
    unittest.main()
