#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

import importlib.util

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "m585_single_switch_experiment.py"
spec = importlib.util.spec_from_file_location("m585_single_switch_experiment", SCRIPT)
experiment = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(experiment)


DEVICE = {
    "path": b"fake-m585",
    "vendor_id": 0x046D,
    "product_id": 0xB01B,
    "serial_number": "7A09C04B5120EA18",
    "manufacturer_string": "Logitech",
    "product_string": "M585/M590",
    "usage_page": 0xFF43,
    "usage": 0x0202,
    "interface_number": -1,
}


def hidpp_response(feature_index, function, data):
    if len(data) > 16:
        raise ValueError("fake HID++ payload too long")
    request_function = function | 0x01
    return (
        bytes((0x11, 0xFF, feature_index, request_function))
        + bytes(data)
        + bytes(16 - len(data))
    )


class FakeM585Transport:
    def __init__(self, *, current_host=1, target_status=1):
        self.current_host = current_host
        self.target_status = target_status
        self.queries = []
        self.writes = []
        self.opened = False

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def query(self, request):
        self.queries.append(request)
        feature = request[2]
        function = request[3] & 0xF0
        if request[2:4] == bytes((0x00, 0x01)) and request[4:6] == bytes((0x18, 0x14)):
            return hidpp_response(0, 0, bytes((9, 0)))
        if request[2:4] == bytes((0x00, 0x01)) and request[4:6] == bytes((0x18, 0x15)):
            return hidpp_response(0, 0, bytes((10, 0)))
        if feature == 9 and function == 0x00:
            return hidpp_response(9, 0x00, bytes((2, self.current_host)))
        if feature == 10 and function == 0x00:
            return hidpp_response(10, 0x00, bytes((0x13, 0, 2, self.current_host)))
        if feature == 10 and function == 0x10 and request[4] == 0:
            return hidpp_response(
                10,
                0x10,
                bytes((0, self.target_status, 0, 0, 12, 24)),
            )
        if feature == 10 and function == 0x10 and request[4] == 1:
            return hidpp_response(10, 0x10, bytes((1, 1, 0, 0, 15, 24)))
        if feature == 10 and function == 0x30 and request[4] == 0:
            return hidpp_response(10, 0x30, bytes((0, request[5])) + b"LAZY-WINDOWS")
        if feature == 10 and function == 0x30 and request[4] == 1 and request[5] == 0:
            return hidpp_response(10, 0x30, bytes((1, 0)) + "lazy的Mac Mini".encode("utf-8")[:14])
        if feature == 10 and function == 0x30 and request[4] == 1 and request[5] == 14:
            return hidpp_response(10, 0x30, bytes((1, 14)) + "i".encode("utf-8"))
        raise AssertionError(f"unexpected fake query {request.hex()}")

    def submit_no_reply(self, request):
        self.writes.append(request)
        return len(request)


class FailingWriteTransport(FakeM585Transport):
    def submit_no_reply(self, request):
        self.writes.append(request)
        raise experiment.HidppError("fake write transport failure")


class M585SingleSwitchTests(unittest.TestCase):
    def run_case(self, *, apply=False, current_host=1, target_status=1, guard=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = pathlib.Path(temporary.name)
        transport = FakeM585Transport(current_host=current_host, target_status=target_status)

        def factory(selected):
            self.assertEqual(selected["serial_number"], experiment.EXPECTED_SERIAL)
            return transport

        result = experiment.run_experiment(
            [dict(DEVICE)],
            apply=apply,
            authorization_confirmed=True,
            physical_rollback_ready=True,
            guard_path=guard or root / "guard.json",
            log_path=root / "log.json",
            transport_factory=factory,
        )
        return result, transport, root

    def test_dry_run_preflight_never_writes(self):
        result, transport, _ = self.run_case(apply=False)
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(result["change_host_feature_index"], 9)
        self.assertEqual(result["hosts_info_feature_index"], 10)
        self.assertEqual(result["hosts"][0]["name"], "LAZY-WINDOWS")
        self.assertEqual(result["hosts"][1]["name"], "lazy的Mac Mini")
        self.assertEqual(transport.writes, [])
        expected = bytes.fromhex(result["would_submit"])
        self.assertEqual(expected[:4], bytes((0x11, 0xFF, 9, 0x11)))
        self.assertEqual(expected[4], 0)

    def test_apply_submits_exactly_once(self):
        result, transport, root = self.run_case(apply=True)
        self.assertEqual(len(transport.writes), 1)
        request = transport.writes[0]
        self.assertEqual(request[:4], bytes((0x11, 0xFF, 9, 0x11)))
        self.assertEqual(request[4], 0)
        self.assertTrue((root / "guard.json").exists())
        self.assertFalse(result["switch_report_submit"]["retry"])
        self.assertTrue(result["switch_report_submit"]["no_reply_expected"])

    def test_current_slot_mismatch_blocks_write(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        transport = FakeM585Transport(current_host=0)
        with self.assertRaises(experiment.HidppError) as context:
            experiment.run_experiment(
                [dict(DEVICE)],
                apply=True,
                authorization_confirmed=True,
                physical_rollback_ready=True,
                guard_path=pathlib.Path(temporary.name) / "guard.json",
                log_path=pathlib.Path(temporary.name) / "log.json",
                transport_factory=lambda selected: transport,
            )
        self.assertIn("CHANGE_HOST state mismatch", str(context.exception))
        self.assertEqual(transport.writes, [])
        self.assertFalse((pathlib.Path(temporary.name) / "guard.json").exists())

    def test_target_unavailable_blocks_write(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        transport = FakeM585Transport(target_status=0)
        with self.assertRaises(experiment.HidppError) as context:
            experiment.run_experiment(
                [dict(DEVICE)],
                apply=True,
                authorization_confirmed=True,
                physical_rollback_ready=True,
                guard_path=pathlib.Path(temporary.name) / "guard.json",
                log_path=pathlib.Path(temporary.name) / "log.json",
                transport_factory=lambda selected: transport,
            )
        self.assertIn("target slot 0 is not marked paired", str(context.exception))
        self.assertEqual(transport.writes, [])
        self.assertFalse((pathlib.Path(temporary.name) / "guard.json").exists())

    def test_existing_guard_blocks_before_transport(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        guard = pathlib.Path(temporary.name) / "guard.json"
        guard.write_text("{}")

        def forbidden_factory(selected):
            raise AssertionError("transport must not be created when guard exists")

        result = experiment.run_experiment(
            [dict(DEVICE)],
            apply=True,
            authorization_confirmed=True,
            physical_rollback_ready=True,
            guard_path=guard,
            log_path=pathlib.Path(temporary.name) / "log.json",
            transport_factory=forbidden_factory,
        )
        self.assertTrue(result["blocked_before_any_hid_io"])

    def test_failed_submit_is_not_retried_and_guard_remains(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        transport = FailingWriteTransport()
        guard = pathlib.Path(temporary.name) / "guard.json"
        result = experiment.run_experiment(
            [dict(DEVICE)],
            apply=True,
            authorization_confirmed=True,
            physical_rollback_ready=True,
            guard_path=guard,
            log_path=pathlib.Path(temporary.name) / "log.json",
            transport_factory=lambda selected: transport,
        )
        self.assertEqual(len(transport.writes), 1)
        self.assertTrue(guard.exists())
        self.assertTrue(result["switch_submit_attempted"])
        self.assertEqual(result["switch_submit_error"]["error_type"], "HidppError")
        self.assertIn("fake write transport failure", result["switch_submit_error"]["detail"])
        self.assertIsNone(result["switch_report_submit"]["bytes_submitted"])
        self.assertIn("ambiguous", result["switch_report_submit"]["meaning"])

    def test_missing_authorization_blocks_before_transport(self):
        def forbidden_factory(selected):
            raise AssertionError("unauthorized apply must not create transport")

        result = experiment.run_experiment(
            [dict(DEVICE)],
            apply=True,
            authorization_confirmed=False,
            physical_rollback_ready=True,
            guard_path=pathlib.Path("unused-guard.json"),
            log_path=pathlib.Path("unused-log.json"),
            transport_factory=forbidden_factory,
        )
        self.assertTrue(result["blocked_before_any_hid_io"])

    def test_wrong_serial_or_duplicate_collection_fails(self):
        wrong = dict(DEVICE, serial_number="OTHER")
        with self.assertRaises(experiment.HidppError):
            experiment.select_expected_collection([wrong])
        with self.assertRaises(experiment.HidppError):
            experiment.select_expected_collection([dict(DEVICE), dict(DEVICE)])

    def test_apply_requires_target_name_even_when_other_confirmations_exist(self):
        original_argv = sys.argv
        sys.argv = [
            "m585_single_switch_experiment.py",
            "--apply",
            "--confirm-single-send",
            "--user-ready-rollback",
        ]
        try:
            args = experiment.parse_args()
        finally:
            sys.argv = original_argv
        self.assertIsNone(args.expected_target_name)

    def test_default_mode_performs_no_hid_enumeration_or_io(self):
        original_argv = sys.argv
        original_enumerate = experiment.enumerate_mouse
        sys.argv = ["m585_single_switch_experiment.py"]
        experiment.enumerate_mouse = lambda: (_ for _ in ()).throw(
            AssertionError("default mode must not enumerate HID")
        )
        output = StringIO()
        try:
            with redirect_stdout(output):
                experiment.main()
        finally:
            experiment.enumerate_mouse = original_enumerate
            sys.argv = original_argv
        result = json.loads(output.getvalue())
        self.assertEqual(result["mode"], "plan-only")
        self.assertFalse(result["hid_io_performed"])


if __name__ == "__main__":
    unittest.main()
