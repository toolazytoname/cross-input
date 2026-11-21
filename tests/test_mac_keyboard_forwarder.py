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

    def test_timer_releases_when_mouse_returns_without_key_event(self):
        sender = FakeSender()
        state = mock.Mock()
        state.release_if_returned.return_value = True
        with mock.patch("ctypes.cdll.LoadLibrary"):
            tap = forwarder.MacKeyTap(sender, state)
        tap.remote_keys_down = True
        self.assertTrue(state.release_if_returned())
        tap.release_all()
        self.assertEqual(sender.events, [("release_all",)])

    def test_all_mapped_keys_are_supported_by_protocol(self):
        from keyboard_protocol import KEY_NAMES
        self.assertEqual(set(forwarder.MAC_TO_KEY.values()) - KEY_NAMES, set())

    def test_left_and_right_modifiers_have_independent_windows_keys(self):
        source = (ROOT / "scripts/mac_keyboard_forwarder.py").read_text()
        receiver = (ROOT / "scripts/windows_input_service.ps1").read_text()
        self.assertIn('56: "leftshift"', source)
        self.assertIn('60: "rightshift"', source)
        self.assertIn('Add("leftshift",0xA0)', receiver)
        self.assertIn('Add("rightshift",0xA1)', receiver)
        self.assertIn('Add("rightcommand",0x5C)', receiver)

    def test_modifier_flags_changed_event_is_forwarded(self):
        sender = FakeSender()
        tap = self.make_tap(sender)
        tap.cg.CGEventGetIntegerValueField.return_value = 56
        tap.cg.CGEventGetFlags.return_value = 0x20002
        self.assertIsNone(tap.callback(None, 12, object(), None))
        self.assertEqual(sender.events[-1], ("key", "leftshift", True, 0x20000))
        tap.cg.CGEventGetFlags.return_value = 0
        self.assertIsNone(tap.callback(None, 12, object(), None))
        self.assertEqual(sender.events[-1], ("key", "leftshift", False, 0))

    def test_tap_disable_releases_remote_keys(self):
        sender = FakeSender()
        tap = self.make_tap(sender)
        tap.down.add("a")
        event = object()
        self.assertIs(tap.callback(None, 0xFFFFFFFE, event, None), event)
        self.assertEqual(sender.events[-1], ("release_all",))
        self.assertEqual(tap.down, set())


if __name__ == "__main__":
    unittest.main()
