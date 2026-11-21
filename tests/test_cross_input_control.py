import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("control", ROOT / "scripts/cross_input_control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class ControlTests(unittest.TestCase):
    def test_window_close_and_buttons_restore_input(self):
        source = (ROOT / "scripts/cross_input_control.py").read_text()
        self.assertIn('root.protocol("WM_DELETE_WINDOW", shutdown)', source)
        self.assertIn('text="Recover mouse to Mac", command=recover', source)
        self.assertIn('command=shutdown', source)

    def test_stop_restores_deskflow_and_clears_all_pid_files(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = pathlib.Path(directory)
            for name in control.SERVICES:
                (runtime / (name + ".pid")).write_text(str(os.getpid()))
            with mock.patch.object(control, "RUNTIME", runtime), mock.patch.object(control, "MAC_PLIST", runtime / "missing.plist"), mock.patch("os.kill") as kill, mock.patch("subprocess.run"):
                control.stop()
                self.assertEqual(kill.call_count, 0)
                self.assertEqual(list(runtime.glob("*.pid")), [])

    def test_commands_use_fixed_entries(self):
        self.assertEqual(len(control.SERVICES), 3)
        for command in control.SERVICES.values():
            self.assertTrue((ROOT / command[1]).is_file())


if __name__ == "__main__":
    unittest.main()
