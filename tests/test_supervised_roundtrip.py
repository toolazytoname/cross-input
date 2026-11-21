import importlib.util
import pathlib
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("roundtrip", ROOT / "scripts/supervised_roundtrip.py")
roundtrip = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roundtrip)


class RoundTripTests(unittest.TestCase):
    def test_different_round_must_not_reuse_windows_event(self):
        calls = []
        mac = iter([
            {"attempt_id": "a", "result": "submitted"},
            {"attempt_id": "b", "result": "submitted"},
        ])
        windows = iter([
            ['{"event":"switch-submitted","target":"MAC_SLOT_1"}'],
            [],
        ])
        roundtrip.mac_attempts = lambda: [next(mac)]
        roundtrip.windows_events = lambda env: next(windows)
        self.assertEqual(roundtrip.mac_attempts(), [{"attempt_id": "a", "result": "submitted"}])
        self.assertEqual(roundtrip.windows_events({}), ['{"event":"switch-submitted","target":"MAC_SLOT_1"}'])

    def test_event_filter_excludes_bootstrap_only_lines(self):
        source = (ROOT / "scripts/supervised_roundtrip.py").read_text()
        self.assertIn("mac_before", source)
        self.assertIn("windows_before", source)
        self.assertIn("exactly one Mac-to-Windows", source)
        self.assertIn("auditable Windows-to-Mac", source)

    def test_pointer_probe_uses_interactive_task_and_checks_result(self):
        source = (ROOT / "scripts/supervised_roundtrip.py").read_text()
        self.assertIn('"register-start", "pointer-test"', source)
        self.assertIn('"LastTaskResult"', source)
        self.assertIn('"status", "pointer-test"', source)


if __name__ == "__main__":
    unittest.main()
