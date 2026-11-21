import importlib.util
import pathlib
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("forwarder", ROOT / "scripts/mac_keyboard_forwarder.py")
forwarder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forwarder)


class FakeSender:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail

    def send(self, *args):
        if self.fail:
            raise OSError("offline")
        self.events.append(args)


class KeyboardForwarderTests(unittest.TestCase):
    def make_tap(self, sender, remote=True):
        state = mock.Mock()
        state.update.return_value = remote
        with mock.patch("ctypes.cdll.LoadLibrary"):
            return forwarder.MacKeyTap(sender, state)

    def test_mac_focus_passes_event_without_send(self):
        sender = FakeSender()
        tap = self.make_tap(sender, False)
        self.assertFalse(tap.forward("a", True))
        self.assertEqual(sender.events, [])

    def test_failed_send_passes_event_back_and_forces_health_recheck(self):
        sender = FakeSender(True)
        tap = self.make_tap(sender)
        self.assertFalse(tap.forward("a", True))
        self.assertEqual(tap.state.last_check, 0)
        self.assertFalse(tap.state.remote)

    def test_return_releases_pressed_keys(self):
        sender = FakeSender()
        tap = self.make_tap(sender)
        self.assertTrue(tap.forward("a", True))
        tap.state.update.return_value = False
        self.assertFalse(tap.forward("b", True))
        self.assertEqual(sender.events[-1], ("release_all",))

    def test_all_mapped_keys_are_supported_by_protocol(self):
        from keyboard_protocol import KEY_NAMES
        self.assertEqual(set(forwarder.MAC_TO_KEY.values()) - KEY_NAMES, set())


if __name__ == "__main__":
    unittest.main()
