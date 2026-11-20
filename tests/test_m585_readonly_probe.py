#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).parents[1] / "scripts" / "m585_readonly_probe.py"
spec = importlib.util.spec_from_file_location("m585_readonly_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(probe)


class FakeTransport:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []

    def query(self, request):
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        kind = probe.classify_response(result, request)
        if kind == "hidpp-error":
            raise probe.HidppError(f"device returned HID++ error 0x{result[5]:02X}")
        if kind != "response":
            raise probe.HidppError(f"fake transport returned {kind}")
        return result


def root_response(feature_index=9):
    return bytes((0x11, 0xFF, 0x00, 0x01, feature_index)) + bytes(15)


def status_response(count=2, current=0):
    return bytes.fromhex("11ff0901{:02x}{:02x}0000000000000000000000000000".format(count, current))


def feature_response(feature_index, function, data):
    if len(data) > 16:
        raise ValueError("fake HID++ payload is too long")
    return bytes((0x11, 0xFF, feature_index, function | probe.SOFTWARE_ID)) + bytes(data) + bytes(16 - len(data))


def root_index_response(feature_id, feature_index):
    assert 0x0001 <= feature_id <= 0xFFFF
    return feature_response(0, 0, bytes((feature_index, 0)))


def hosts_state_response(flags=1, count=2, current=1):
    return feature_response(10, 0x00, bytes((flags, 0, count, current)))


def host_descriptor_response(host, paired=1, name_length=20, maximum_length=20):
    return feature_response(10, 0x10, bytes((host, paired, 0, 0, name_length, maximum_length)))


def wrong_slot_descriptor_response():
    return feature_response(10, 0x10, bytes((1, 1, 0, 0, 12, 24)))


def host_name_response(host, offset, payload):
    return feature_response(10, 0x30, bytes((host, offset)) + payload)


class M585ProbeTests(unittest.TestCase):
    def test_strict_selection_requires_one_exact_collection(self):
        base = {"vendor_id": 0x046D, "product_id": 0xB01B, "usage_page": 1, "usage": 6, "path": b"a"}
        exact = dict(base, usage_page=0xFF43, usage=0x0202)
        self.assertIs(probe.select_vendor_collection([base, exact]), exact)
        with self.assertRaises(probe.HidppError):
            probe.select_vendor_collection([base])
        with self.assertRaises(probe.HidppError):
            probe.select_vendor_collection([exact, dict(exact, path=b"b")])

    def test_valid_readonly_sequence(self):
        transport = FakeTransport([root_response(9), status_response(2, 0)])
        index, root = probe.query_root_change_host_index(transport)
        status, status_response_bytes = probe.query_change_host_status(transport, index)
        self.assertEqual((index, root[4]), (9, 9))
        self.assertEqual(status, {"host_count": 2, "current_host_index": 0})
        self.assertEqual(len(transport.requests), 2)
        self.assertTrue(all(request[0:4] == bytes((0x11, 0xFF, request[2], request[3])) for request in transport.requests))

    def test_root_unsupported_never_sends_status_request(self):
        for response in (root_response(0), root_response(0xF0)):
            transport = FakeTransport([response])
            with self.assertRaises(probe.HidppError):
                probe.query_root_change_host_index(transport)
            self.assertEqual(len(transport.requests), 1)

    def test_timeout_and_error_fail_closed(self):
        transport = FakeTransport([probe.HidppTimeout("timeout")])
        with self.assertRaises(probe.HidppTimeout):
            probe.query_root_change_host_index(transport)
        self.assertEqual(len(transport.requests), 1)

        error = error_response()
        transport = FakeTransport([error])
        with self.assertRaises(probe.HidppError):
            probe.query_root_change_host_index(transport)
        self.assertEqual(len(transport.requests), 1)

    def test_bad_status_fail_closed(self):
        for response in (status_response(0, 0), status_response(4, 3), status_response(2, 2)):
            transport = FakeTransport([response])
            with self.assertRaises(probe.HidppError):
                probe.query_change_host_status(transport, 9)
            self.assertEqual(len(transport.requests), 1)

    def test_hosts_info_readonly_sequence_is_whitelisted(self):
        first_name = b"lazy-windows" + b"0" * 2
        second_name = b"mac-mini-name"
        transport = FakeTransport([
            root_index_response(0x1815, 10),
            hosts_state_response(),
            host_descriptor_response(0, name_length=14),
            host_name_response(0, 0, first_name[:14]),
            host_descriptor_response(1, name_length=13),
            host_name_response(1, 0, second_name),
        ])
        result = probe.read_hosts_info_with_transport(transport)
        self.assertEqual([host["name"] for host in result["hosts"]], ["lazy-windows00", "mac-mini-name"])
        allowed_functions = {0x00, 0x10, 0x30}
        self.assertEqual(transport.requests[0][4:6], bytes((0x18, 0x15)))
        self.assertTrue(all(request[2] == 10 for request in transport.requests[1:]))
        self.assertTrue(all(request[3] & 0x0F in {1} for request in transport.requests))
        self.assertTrue(all(request[3] & 0xF0 in allowed_functions for request in transport.requests))
        self.assertFalse(any(request[3] & 0xF0 == 0x40 for request in transport.requests))

    def test_hosts_info_capability_gate_fails_closed(self):
        transport = FakeTransport([
            root_index_response(0x1815, 10),
            hosts_state_response(flags=0),
        ])
        with self.assertRaises(probe.HidppError):
            probe.query_hosts_info_state(transport, 10)
        self.assertEqual(len(transport.requests), 1)

    def test_bad_host_descriptor_fails_closed(self):
        for descriptor in (host_descriptor_response(0, name_length=33), host_descriptor_response(0, name_length=21, maximum_length=20)):
            transport = FakeTransport([descriptor])
            with self.assertRaises(probe.HidppError):
                probe.query_host_descriptor(transport, 10, 0)
            self.assertEqual(len(transport.requests), 1)

    def test_host_descriptor_slot_mismatch_fails_closed(self):
        transport = FakeTransport([wrong_slot_descriptor_response()])
        with self.assertRaises(probe.HidppError) as context:
            probe.query_host_descriptor(transport, 10, 0)
        self.assertIn("host descriptor slot mismatch", str(context.exception))
        self.assertEqual(len(transport.requests), 1)

    def test_host_name_context_mismatch_fails_closed(self):
        transport = FakeTransport([host_name_response(1, 0, b"wrong")])
        with self.assertRaises(probe.HidppError):
            probe.query_host_name_piece(transport, 10, 0, 0, 14)
        self.assertEqual(len(transport.requests), 1)

    def test_response_classifier_rejects_wrong_frames(self):
        request = probe.make_request(0, 0, bytes((0x18, 0x14)))
        self.assertEqual(probe.classify_response(root_response(9), request), "response")
        self.assertEqual(probe.classify_response(error_response(), request), "hidpp-error")
        self.assertEqual(probe.classify_response(root_response(9)[:-1], request), "wrong-length")
        wrong_report = bytes([0x10]) + root_response(9)[1:]
        self.assertEqual(probe.classify_response(wrong_report, request), "wrong-report-id")
        wrong_device = bytes([0x11, 0x01]) + root_response(9)[2:]
        self.assertEqual(probe.classify_response(wrong_device, request), "wrong-device-number")
        unrelated = bytes([0x11, 0xFF, 0x02, 0x11]) + root_response(9)[4:]
        self.assertEqual(probe.classify_response(unrelated, request), "unrelated")


def error_response():
    return bytes((0x11, 0xFF, 0xFF, 0x00, 0x01, 0x02)) + bytes(14)


if __name__ == "__main__":
    unittest.main()
