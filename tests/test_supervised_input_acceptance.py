import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("input_acceptance", ROOT / "scripts/supervised_input_acceptance.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class InputAcceptanceTests(unittest.TestCase):
    def test_key_injection_supports_benign_acceptance_sequence(self):
        for character in acceptance.KEYBOARD_TEXT + acceptance.MODIFIER_TEXT:
            name = "space" if character == " " else character.lower()
            self.assertIn(name, ("return", "leftshift", "rightshift", "space") + tuple("abcdefghijklmnopqrstuvwxyz1234567890"))

    def test_live_tool_uses_only_metadata_in_evidence(self):
        source = (ROOT / "scripts/supervised_input_acceptance.py").read_text()
        self.assertIn('"sha256"', source)
        self.assertNotIn('"captured_text"', source)
        self.assertIn('"modifier_release_verified": True', source)

    def test_clipboard_is_restored_and_temporary_target_removed(self):
        source = (ROOT / "scripts/supervised_input_acceptance.py").read_text()
        self.assertIn('"pbcopy"], input=original_mac.encode()', source)
        self.assertIn("self.windows_clipboard(original_windows)", source)
        self.assertIn("Unregister-ScheduledTask -TaskName MiniOpsKeyboardAcceptance", source)


if __name__ == "__main__":
    unittest.main()
