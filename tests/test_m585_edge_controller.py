#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
import threading
import socket
import time
import unittest
from datetime import datetime, timedelta, timezone


SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "m585_edge_controller.py"
RUNNER = pathlib.Path(__file__).parents[1] / "scripts" / "run_windows_hid_protocol_probe.sh"
spec = importlib.util.spec_from_file_location("m585_edge_controller", SCRIPT)
controller = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(controller)


class FakeClock:
    def __init__(self):
        self.now_ms = 0

    def __call__(self):
        return self.now_ms


def sample(at_ms, x=0, event_type=5, button=False, modifier=False):
    return controller.EdgeSample(
        timestamp_ms=at_ms,
        x=x,
        y=450,
        event_type=event_type,
        button_pressed=button,
        modifier_pressed=modifier,
    )


class M585EdgeControllerTests(unittest.TestCase):
    def test_mac_uses_real_windows_peer_health_not_offline_tests(self):
        source = SCRIPT.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn('WINDOWS_HEALTH_ENTRY), "peer-health"]', source)
        self.assertIn("[WindowsHidProtocolProbe]::RunWindowsPeerHealth()", runner)
        self.assertIn("M585_EDGE_WINDOWS_HEALTH_PATH", runner)
        self.assertIn("controller_ready", source)
        self.assertIn("expires_at_utc", source)
        self.assertIn('ssh_alias="${M585_SSH_ALIAS:-Administrator@192.168.1.8}"', runner)

    def test_mac_watch_advertises_exit_and_manual_return(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"stop": "Ctrl+C"', source)
        self.assertIn('"manual_to_windows": str(MAC_SWITCH_ENTRY)', source)
        self.assertIn('"event": "controller-stopped"', source)
        self.assertIn('"event": "health-bind-failed"', source)

    def test_live_edge_is_immediate_and_stalled_stream_uses_dwell_bound(self):
        clock = FakeClock()
        arbiter = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=400), clock)
        self.assertTrue(arbiter.observe(sample(0), 0)["trigger"])

        clock = FakeClock()
        arbiter = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=400), clock)
        clock.now_ms = 400
        self.assertEqual(arbiter.observe(sample(1), 0)["reason"], "dwelling")
        clock.now_ms = 401
        self.assertTrue(arbiter.observe(sample(399), 0)["trigger"])
        self.assertEqual(arbiter.state, "SWITCHING_TO_WINDOWS")

        arbiter2 = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=400), FakeClock())
        arbiter2.observe(sample(0, button=True), 0)
        self.assertFalse(arbiter2.observe(sample(1000, button=True), 0)["trigger"])
        arbiter3 = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=400), FakeClock())
        arbiter3.observe(sample(0, modifier=True), 0)
        self.assertFalse(arbiter3.observe(sample(1000, modifier=True), 0)["trigger"])

    def test_drag_and_wrong_event_do_not_consume_dwell(self):
        arbiter = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=400), FakeClock())
        arbiter.observe(sample(0, event_type=6), 0)
        arbiter.observe(sample(500, event_type=6), 0)
        self.assertEqual(arbiter.state, "READY_MAC")

    def test_stale_queued_edge_never_switches(self):
        clock = FakeClock()
        clock.now_ms = 1000
        arbiter = controller.EdgeArbiter(controller.EdgeConfig(), clock)
        self.assertEqual(arbiter.observe(sample(0), 0)["reason"], "stale-input-sample")
        self.assertEqual(arbiter.state, "READY_MAC")

    def test_cooldown_and_slot_based_recovery(self):
        clock = FakeClock()
        arbiter = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=0, cooldown_ms=2500), clock)
        clock.now_ms = 1000
        self.assertTrue(arbiter.observe(sample(1000), 0)["trigger"])
        arbiter.mark_submit_completed()
        self.assertEqual(arbiter.submit_completed_at, 1000)
        self.assertTrue(arbiter.rearm_requires_leave_edge)
        arbiter.mark_return_ready()
        self.assertEqual(arbiter.observe(sample(3000), 0)["reason"], "rearm-requires-leave-edge")
        clock.now_ms = 3000
        self.assertFalse(arbiter.observe(sample(3000, x=100), 0)["trigger"])
        clock.now_ms = 3499
        self.assertEqual(arbiter.observe(sample(3499), 0)["reason"], "cooldown")
        clock.now_ms = 3500
        self.assertTrue(arbiter.observe(sample(3500), 0)["trigger"])

    def test_display_edge_comes_from_actual_frames_not_fixed_resolution(self):
        frames = [
            {"index": 1, "x": 0.0, "width": 1440.0},
            {"index": 2, "x": -1920.0, "width": 1920.0},
        ]
        self.assertEqual(controller.choose_left_edge(frames), -1920.0)
        self.assertEqual(controller.choose_left_edge(frames, 1), 0.0)
        self.assertEqual(controller.choose_left_edge(frames, 2), -1920.0)

    def test_post_submit_poll_requires_absence_then_two_slot_confirmations(self):
        clock = FakeClock()
        config = controller.EdgeConfig(dwell_ms=0, cooldown_ms=2500, switch_stability_ms=5000)
        arbiter = controller.EdgeArbiter(config, clock)
        status = controller.ControllerStatus()
        status.update(controller_running=True)
        clock.now_ms = 1000
        self.assertTrue(arbiter.observe(sample(1000), 0)["trigger"])
        arbiter.mark_submit_completed()

        still_mac = {"ok": True, "current_host_index": 1, "host_count": 2, "device_present": True, "outcome": "present-slot-1"}
        result = controller.apply_mac_slot_poll(arbiter, status, still_mac, config, 2000, 0, 0)
        self.assertEqual(result["state"], "SWITCHING_TO_WINDOWS")
        self.assertFalse(status.snapshot()["ready"])

        absent = {"ok": False, "device_present": False, "outcome": "device-absent"}
        result = controller.apply_mac_slot_poll(arbiter, status, absent, config, 2100, 0, 0)
        self.assertEqual(result["state"], "MOUSE_ABSENT_AFTER_SWITCH")
        self.assertFalse(status.snapshot()["ready"])

        result = controller.apply_mac_slot_poll(arbiter, status, still_mac, config, 5900, 0, 0)
        self.assertEqual(result["state"], "MOUSE_ABSENT_AFTER_SWITCH")
        self.assertEqual(result["return_confirmations"], 1)
        self.assertFalse(status.snapshot()["ready"])

        result = controller.apply_mac_slot_poll(arbiter, status, still_mac, config, 6000, 1, 0)
        self.assertEqual(result["state"], "READY_MAC")
        self.assertTrue(status.snapshot()["ready"])
        self.assertTrue(arbiter.rearm_requires_leave_edge)
        self.assertEqual(arbiter.observe(sample(6000), 0)["reason"], "rearm-requires-leave-edge")

    def test_no_departure_and_query_failures_have_distinct_recovery_behavior(self):
        clock = FakeClock()
        config = controller.EdgeConfig(switch_stability_ms=5000, query_failure_limit=3)
        arbiter = controller.EdgeArbiter(config, clock)
        status = controller.ControllerStatus()
        status.update(controller_running=True)
        clock.now_ms = 1000
        arbiter.begin_attempt()
        arbiter.mark_submit_completed()
        still_mac = {"ok": True, "current_host_index": 1, "host_count": 2, "device_present": True, "outcome": "present-slot-1"}
        result = controller.apply_mac_slot_poll(arbiter, status, still_mac, config, 5999, 0, 0)
        self.assertEqual(result["state"], "SWITCHING_TO_WINDOWS")
        result = controller.apply_mac_slot_poll(arbiter, status, still_mac, config, 6000, 0, 0)
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")

        query_failed = {"ok": False, "device_present": None, "outcome": "query-failed"}
        arbiter2 = controller.EdgeArbiter(config, FakeClock())
        status2 = controller.ControllerStatus()
        status2.update(controller_running=True, state="READY_MAC", mouse_current_slot=1)
        result = controller.apply_mac_slot_poll(arbiter2, status2, query_failed, config, 1000, 0, 0)
        self.assertEqual(result["state"], "READY_MAC")
        self.assertFalse(status2.snapshot()["ready"])
        result = controller.apply_mac_slot_poll(arbiter2, status2, query_failed, config, 2000, 0, 2)
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")

    def test_post_switch_absence_becomes_mac_return_target(self):
        clock = FakeClock()
        config = controller.EdgeConfig(switch_stability_ms=5000, return_confirmations_required=2)
        arbiter = controller.EdgeArbiter(config, clock)
        status = controller.ControllerStatus()
        status.update(controller_running=True)
        clock.now_ms = 1000
        arbiter.begin_attempt()
        arbiter.mark_submit_completed()
        absent = {"ok": False, "device_present": False, "outcome": "device-absent"}

        result = controller.apply_mac_slot_poll(arbiter, status, absent, config, 2100, 0, 0)
        self.assertEqual(result["state"], "MOUSE_ABSENT_AFTER_SWITCH")
        self.assertEqual(result["return_confirmations"], 1)
        self.assertFalse(status.snapshot()["ready"])

        result = controller.apply_mac_slot_poll(arbiter, status, absent, config, 6000, 1, 0)
        self.assertEqual(result["state"], "READY_MAC_RETURN_TARGET")
        self.assertEqual(result["return_confirmations"], 2)
        status.update(ready=arbiter.state == "READY_MAC_RETURN_TARGET", return_target_ready=True)
        self.assertTrue(status.snapshot()["ready"])
        self.assertTrue(status.snapshot()["return_target_ready"])
        self.assertEqual(arbiter.observe(sample(6000, x=100), 0)["reason"], "not-at-edge")
        self.assertEqual(arbiter.observe(sample(6000, x=0), 0)["reason"], "state-READY_MAC_RETURN_TARGET")

        slot = {"ok": True, "current_host_index": 1, "host_count": 2, "device_present": True, "outcome": "present-slot-1"}
        result = controller.apply_mac_slot_poll(arbiter, status, slot, config, 6100, 0, 0)
        self.assertEqual(result["state"], "READY_MAC_RETURN_TARGET")
        arbiter.mark_return_ready()
        status.update(ready=arbiter.state == "READY_MAC", mouse_current_slot=1)
        status.update(return_target_ready=False)
        self.assertTrue(status.snapshot()["ready"])
        self.assertFalse(status.snapshot()["return_target_ready"])

    def test_target_unavailable_is_not_auto_recovered_by_a_slot_poll(self):
        arbiter = controller.EdgeArbiter(controller.EdgeConfig(), FakeClock())
        status = controller.ControllerStatus()
        status.update(controller_running=True)
        arbiter.mark_target_unavailable()
        slot = {"ok": True, "current_host_index": 1, "host_count": 2, "device_present": True, "outcome": "present-slot-1"}
        result = controller.apply_mac_slot_poll(arbiter, status, slot, controller.EdgeConfig(), 1000, 0, 0)
        self.assertEqual(result["state"], "TARGET_UNAVAILABLE")
        self.assertFalse(status.snapshot()["ready"])

    def test_startup_recovery_requires_running_tap_stability_and_two_slot_confirmations(self):
        config = controller.EdgeConfig(switch_stability_ms=5000, return_confirmations_required=2)
        arbiter = controller.EdgeArbiter(config, FakeClock())
        status = controller.ControllerStatus()
        arbiter.mark_recovery_required(at_ms=1000)
        slot = {"ok": True, "current_host_index": 1, "host_count": 2, "device_present": True, "outcome": "present-slot-1"}

        result = controller.apply_mac_slot_poll(arbiter, status, slot, config, 3000, 0, 3)
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertEqual(result["return_confirmations"], 0)
        self.assertFalse(status.snapshot()["ready"])

        status.update(controller_running=True)
        result = controller.apply_mac_slot_poll(arbiter, status, slot, config, 5500, 0, 0)
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertEqual(result["return_confirmations"], 1)

        result = controller.apply_mac_slot_poll(arbiter, status, slot, config, 6000, 1, 0)
        self.assertEqual(result["state"], "READY_MAC")
        self.assertEqual(result["return_confirmations"], 2)
        self.assertTrue(status.snapshot()["ready"])
        self.assertTrue(arbiter.rearm_requires_leave_edge)
        self.assertEqual(arbiter.observe(sample(6000), 0)["reason"], "rearm-requires-leave-edge")

    def test_recovery_confirmations_reset_on_query_failure_and_wrong_slot(self):
        config = controller.EdgeConfig(switch_stability_ms=5000, return_confirmations_required=2)
        arbiter = controller.EdgeArbiter(config, FakeClock())
        status = controller.ControllerStatus()
        status.update(controller_running=True)
        arbiter.mark_recovery_required(at_ms=1000)
        slot = {"ok": True, "current_host_index": 1, "host_count": 2, "device_present": True, "outcome": "present-slot-1"}

        result = controller.apply_mac_slot_poll(arbiter, status, slot, config, 5500, 0, 0)
        self.assertEqual(result["return_confirmations"], 1)
        query_failed = {"ok": False, "device_present": None, "outcome": "query-failed"}
        result = controller.apply_mac_slot_poll(arbiter, status, query_failed, config, 6500, 1, 0)
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertEqual(result["return_confirmations"], 0)

        result = controller.apply_mac_slot_poll(arbiter, status, slot, config, 7000, 0, 0)
        wrong_slot = {"ok": False, "current_host_index": 0, "host_count": 2, "device_present": True, "outcome": "present-wrong-slot"}
        result = controller.apply_mac_slot_poll(arbiter, status, wrong_slot, config, 7500, 1, 0)
        self.assertEqual(result["state"], "RECOVERY_REQUIRED")
        self.assertEqual(result["return_confirmations"], 0)
        self.assertFalse(status.snapshot()["ready"])

    def test_native_api_signatures_are_fixed(self):
        tap = controller.MacEventTap(__import__("queue").Queue())
        self.assertEqual(tap.core_graphics.CGEventGetLocation.argtypes, [controller.ctypes.c_void_p])
        self.assertEqual(tap.core_graphics.CGEventGetDoubleValueField.argtypes, [controller.ctypes.c_void_p, controller.ctypes.c_uint32])
        self.assertIsNotNone(tap.core_graphics.CGEventGetLocation.restype)
        self.assertEqual(tap.core_foundation.CFMachPortCreateRunLoopSource.argtypes[-1], controller.ctypes.c_long)
        self.assertEqual(tap.core_foundation.CFRunLoopAddSource.argtypes, [controller.ctypes.c_void_p] * 3)

    def test_event_button_and_modifier_masks_are_separate_and_fields_are_public(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(controller.MacEventTap.MOUSE_BUTTON_MASK, 0x000000FF)
        self.assertEqual(controller.MacEventTap.MODIFIER_MASK & 0x000000FF, 0)
        self.assertIn("CGEventGetDoubleValueField(event, 2)", source)
        self.assertIn("pressure > 0.0", source)
        self.assertNotIn("for field in (100, 101, 102)", source)
        self.assertNotIn("_source_buttons()", source)
        self.assertNotIn("CGEventSourceButtonState", source)

    def test_device_absence_is_distinguished_from_duplicate_and_query_failure(self):
        original = controller.run_json_command
        try:
            controller.run_json_command = lambda command, timeout: {
                "ok": False,
                "returncode": 1,
                "stderr_tail": "expected exactly one vendor collection ... found 2",
                "stdout_tail": "",
            }
            result = controller.read_mac_slot("")
            self.assertIsNone(result["device_present"])
            self.assertEqual(result["outcome"], "query-failed")

            controller.run_json_command = lambda command, timeout: {
                "ok": False,
                "error": "TimeoutExpired",
                "stderr_tail": "",
                "stdout_tail": "",
            }
            result = controller.read_mac_slot("")
            self.assertIsNone(result["device_present"])
            self.assertEqual(result["outcome"], "query-failed")

            controller.run_json_command = lambda command, timeout: {
                "ok": False,
                "returncode": 1,
                "stderr_tail": "M585/M590 serial 7A09C04B5120EA18 is not present",
                "stdout_tail": "",
            }
            result = controller.read_mac_slot("")
            self.assertFalse(result["device_present"])
            self.assertEqual(result["outcome"], "device-absent")

            controller.run_json_command = lambda command, timeout: {
                "ok": False,
                "returncode": 1,
                "stderr_tail": "M585/M590 is not connected",
                "stdout_tail": "",
            }
            result = controller.read_mac_slot("")
            self.assertFalse(result["device_present"])
            self.assertEqual(result["outcome"], "device-absent")
        finally:
            controller.run_json_command = original

    def test_windows_peer_health_distinguishes_target_and_return_readiness(self):
        now = datetime(2026, 11, 20, 4, 0, 0, 500000, tzinfo=timezone.utc)
        base = {
            "schema": 1,
            "controller": "windows-peer-health-v1",
            "controller_ready": True,
            "ready": True,
            "return_ready": False,
            "desktop": {"available": True, "state": "INTERACTIVE_DESKTOP_ACCESSIBLE"},
            "mouse": {
                "present": False,
                "current_host_index": None,
                "host_count": None,
                "slot_evidence_verified": False,
                "readonly_result": "mouse-absent",
            },
            "generated_at_utc": now.isoformat(),
            "expires_at_utc": (now + timedelta(seconds=5)).isoformat(),
            "hid_output_report_sent": False,
        }
        evaluated = controller.evaluate_windows_peer_health(base, now)
        self.assertTrue(evaluated["ok"])
        self.assertFalse(evaluated["return_ready"])

        seven_digit = json.loads(json.dumps(base))
        seven_digit["generated_at_utc"] = now.strftime("%Y-%m-%dT%H:%M:%S") + ".1234567Z"
        seven_digit["expires_at_utc"] = (now + timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S") + ".1234567Z"
        self.assertTrue(controller.evaluate_windows_peer_health(seven_digit, now)["ok"])
        windows_slightly_ahead = json.loads(json.dumps(base))
        windows_slightly_ahead["generated_at_utc"] = (now + timedelta(milliseconds=750)).isoformat()
        windows_slightly_ahead["expires_at_utc"] = (now + timedelta(seconds=5)).isoformat()
        self.assertTrue(controller.evaluate_windows_peer_health(windows_slightly_ahead, now)["ok"])

        ready = json.loads(json.dumps(base))
        ready["return_ready"] = True
        ready["mouse"].update({
            "present": True,
            "current_host_index": 0,
            "host_count": 2,
            "slot_evidence_verified": True,
        })
        evaluated = controller.evaluate_windows_peer_health(ready, now)
        self.assertTrue(evaluated["ok"])
        self.assertTrue(evaluated["return_ready"])

        expired = json.loads(json.dumps(ready))
        expired["expires_at_utc"] = (now - timedelta(seconds=1)).isoformat()
        self.assertFalse(controller.evaluate_windows_peer_health(expired, now)["ok"])

        old_test_payload = {"passed": True}
        self.assertFalse(controller.evaluate_windows_peer_health(old_test_payload, now)["ok"])

    def test_dry_run_logs_attempt_without_protocol_or_peer_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            arbiter = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=0), FakeClock())
            log = controller.AttemptLog(root / "events.jsonl")
            queue = __import__("queue").Queue()
            queue.put(sample(0))
            thread = threading.Thread(
                target=controller.process_samples,
                args=(queue, arbiter, 0.0, log, "", True, controller.EdgeConfig(), lambda: self.fail("peer must not run"), controller.ControllerStatus(), threading.Lock()),
                daemon=True,
            )
            thread.start()
            deadline = time.monotonic() + 2
            while not (root / "events.jsonl").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            record = json.loads((root / "events.jsonl").read_text().splitlines()[0])
            self.assertEqual(record["result"], "dry-run-would-switch")
            self.assertEqual(record["target"], "WINDOWS_SLOT_0")
            self.assertEqual(record["current_slot_evidence"]["meaning"], "dry-run did not query HID++")
            self.assertTrue(record["attempt_id"].startswith("auto-edge-"))

    def test_real_path_uses_slot_peer_and_fixed_entry_before_submit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            arbiter = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=0), FakeClock())
            log = controller.AttemptLog(root / "events.jsonl")
            original_read = controller.read_mac_slot
            original_submit = controller.submit_mac_switch
            submit_calls = []
            controller.read_mac_slot = lambda python: {"ok": True, "current_host_index": 1, "host_count": 2}
            def slow_submit(python, attempt_id):
                submit_calls.append((python, attempt_id))
                return {"ok": True, "bytes_submitted": 20, "attempt_count": 1}
            controller.submit_mac_switch = slow_submit
            try:
                queue = __import__("queue").Queue()
                queue.put(sample(0))
                thread = threading.Thread(
                    target=controller.process_samples,
                    args=(queue, arbiter, 0.0, log, "", False, controller.EdgeConfig(), lambda: {"ok": True}, controller.ControllerStatus(), threading.Lock()),
                    daemon=True,
                )
                thread.start()
                deadline = time.monotonic() + 2
                while not (root / "events.jsonl").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                record = json.loads((root / "events.jsonl").read_text().splitlines()[0])
            finally:
                controller.read_mac_slot = original_read
                controller.submit_mac_switch = original_submit
            self.assertEqual(record["result"], "submitted")
            self.assertEqual(record["current_slot_evidence"]["current_host_index"], 1)
            self.assertEqual(record["peer_health"], {"ok": True})
            self.assertTrue(record["submitted_at"])
            self.assertEqual(len(submit_calls), 1)

    def test_slow_submit_and_stale_continuous_edge_submit_only_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            clock = FakeClock()
            arbiter = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=0, cooldown_ms=2500), clock)
            log = controller.AttemptLog(root / "events.jsonl")
            queue = __import__("queue").Queue()
            queue.put(sample(0))
            for _ in range(10):
                queue.put(sample(1))
            original_read = controller.read_mac_slot
            original_submit = controller.submit_mac_switch
            submit_calls = []
            controller.read_mac_slot = lambda python: {"ok": True, "current_host_index": 1, "host_count": 2}
            def slow_submit(python, attempt_id):
                submit_calls.append(attempt_id)
                clock.now_ms += 8000
                return {"ok": True, "bytes_submitted": 20, "attempt_count": 1}
            controller.submit_mac_switch = slow_submit
            try:
                thread = threading.Thread(
                    target=controller.process_samples,
                    args=(queue, arbiter, 0.0, log, "", False, controller.EdgeConfig(), lambda: {"ok": True}, controller.ControllerStatus(), threading.Lock()),
                    daemon=True,
                )
                thread.start()
                deadline = time.monotonic() + 2
                while not (root / "events.jsonl").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                while not queue.empty() and time.monotonic() < deadline:
                    time.sleep(0.01)
            finally:
                controller.read_mac_slot = original_read
                controller.submit_mac_switch = original_submit
            self.assertEqual(len(submit_calls), 1)
            self.assertEqual(arbiter.submit_completed_at, 8000)
            self.assertTrue(arbiter.rearm_requires_leave_edge)

    def test_ambiguous_submit_waits_for_device_departure_instead_of_permanent_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            arbiter = controller.EdgeArbiter(controller.EdgeConfig(dwell_ms=0), FakeClock())
            log = controller.AttemptLog(root / "events.jsonl")
            original_read = controller.read_mac_slot
            original_submit = controller.submit_mac_switch
            controller.read_mac_slot = lambda python: {"ok": True, "current_host_index": 1, "host_count": 2}
            controller.submit_mac_switch = lambda python, attempt_id: {
                "ok": False,
                "attempt_reached": True,
                "returncode": 1,
                "bytes_submitted": None,
                "attempt_count": 1,
                "error_type": "HidppError",
                "detail": "short write: sent -1 of 20 bytes",
                "stderr_tail": "HidppError: short write",
            }
            try:
                queue = __import__("queue").Queue()
                queue.put(sample(0))
                status = controller.ControllerStatus()
                thread = threading.Thread(
                    target=controller.process_samples,
                    args=(queue, arbiter, 0.0, log, "", False, controller.EdgeConfig(), lambda: {"ok": True}, status, threading.Lock()),
                    daemon=True,
                )
                thread.start()
                deadline = time.monotonic() + 2
                while not (root / "events.jsonl").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                record = json.loads((root / "events.jsonl").read_text().splitlines()[0])
            finally:
                controller.read_mac_slot = original_read
                controller.submit_mac_switch = original_submit
            self.assertEqual(record["result"], "submit-ambiguous")
            self.assertEqual(record["submit_evidence"]["error_type"], "HidppError")
            self.assertIn("short write", record["submit_evidence"]["detail"])
            self.assertEqual(arbiter.state, "SWITCHING_TO_WINDOWS")
            self.assertEqual(status.snapshot()["poll_outcome"], "awaiting-departure-after-ambiguous-submit")

    def test_controller_lock_is_exclusive(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "controller.lock"
            with controller.ControllerLock(path):
                with self.assertRaises(RuntimeError):
                    with controller.ControllerLock(path):
                        pass

    def test_health_server_reports_only_verified_mac_readiness(self):
        status = controller.ControllerStatus()
        health = controller.HealthServer("127.0.0.1", 0, status)
        thread = threading.Thread(target=health.serve, daemon=True)
        thread.start()
        try:
            with socket.create_connection(("127.0.0.1", health.server.getsockname()[1]), timeout=2) as connection:
                connection.sendall(b"\n")
                payload = json.loads(connection.makefile("rb").readline())
            self.assertFalse(payload["ready"])
            status.update(state="READY_MAC", mouse_current_slot=1, ready=True)
            self.assertFalse(status.snapshot()["ready"])
            status.update(controller_running=True, state="READY_MAC", mouse_current_slot=1, ready=True)
            with socket.create_connection(("127.0.0.1", health.server.getsockname()[1]), timeout=2) as connection:
                connection.sendall(b"\n")
                payload = json.loads(connection.makefile("rb").readline())
            self.assertTrue(payload["ready"])
            self.assertEqual(payload["mouse_current_slot"], 1)
        finally:
            health.stop()

    def test_health_server_port_failure_is_visible_to_caller(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            with self.assertRaises(OSError):
                controller.HealthServer("127.0.0.1", port, controller.ControllerStatus())
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()
