#!/usr/bin/env python3
"""Enumerate M585/M590 and optionally make strictly read-only HID++ queries."""

import argparse
import ctypes
import json
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import hid

LOGITECH_VENDOR_ID = 0x046D
M585_M590_PRODUCT_ID = 0xB01B
LOGITECH_VENDOR_USAGE_PAGE = 0xFF43
LOGITECH_VENDOR_USAGE = 0x0202
HIDPP_LONG_REPORT_ID = 0x11
BLUETOOTH_DEVICE_NUMBER = 0xFF
SOFTWARE_ID = 0x01
ROOT_FEATURE_INDEX = 0x00
ROOT_GET_FEATURE_FUNCTION = 0x00
CHANGE_HOST_FEATURE_ID = 0x1814
CHANGE_HOST_GET_STATUS_FUNCTION = 0x00
HOSTS_INFO_FEATURE_ID = 0x1815
HOSTS_INFO_GET_INFO_FUNCTION = 0x00
HOSTS_INFO_GET_DESCRIPTOR_FUNCTION = 0x10
HOSTS_INFO_GET_NAME_FUNCTION = 0x30
HIDPP_PACKET_SIZE = 20
MAX_HOST_NAME_LENGTH = 32


class HidppError(Exception):
    pass


class HidppTimeout(HidppError):
    pass


def device_dictionary(device: Dict[str, Any]) -> Dict[str, Any]:
    return {key: device[key] for key in device if key in (
        "vendor_id",
        "product_id",
        "serial_number",
        "manufacturer_string",
        "product_string",
        "usage_page",
        "usage",
        "interface_number",
        "path",
    )}


def json_default(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    raise TypeError(type(value).__name__)


def enumerate_mouse() -> List[Dict[str, Any]]:
    return [
        device_dictionary(device)
        for device in hid.enumerate()
        if device["vendor_id"] == LOGITECH_VENDOR_ID
        and device["product_id"] == M585_M590_PRODUCT_ID
    ]


def select_vendor_collection(devices: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    matches = [
        device
        for device in devices
        if device["vendor_id"] == LOGITECH_VENDOR_ID
        and device["product_id"] == M585_M590_PRODUCT_ID
        and device["usage_page"] == LOGITECH_VENDOR_USAGE_PAGE
        and device["usage"] == LOGITECH_VENDOR_USAGE
    ]
    if len(matches) != 1:
        raise HidppError(f"expected exactly one 046d:b01b FF43:0202 collection, found {len(matches)}")
    return matches[0]


def use_non_exclusive_darwin_open() -> bool:
    try:
        library = ctypes.CDLL(hid.__file__)
        set_exclusive = library.hid_darwin_set_open_exclusive
        set_exclusive.argtypes = [ctypes.c_int]
        set_exclusive.restype = None
        set_exclusive(0)
        return True
    except (OSError, AttributeError) as error:
        print(json.dumps({"non_exclusive_open": {"enabled": False, "error": str(error)}}))
        return False


def check_hid_listen_access() -> Dict[str, Any]:
    request_type_names = {0: "post-event", 1: "listen-event"}
    access_names = {0: "granted", 1: "denied", 2: "unknown"}
    try:
        iokit = ctypes.CDLL("/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDCheckAccess.argtypes = [ctypes.c_int]
        iokit.IOHIDCheckAccess.restype = ctypes.c_int
        result = iokit.IOHIDCheckAccess(1)
        return {
            "function": "IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)",
            "raw_result": result,
            "result": access_names.get(result, f"unknown:{result}"),
            "request_type": request_type_names[1],
        }
    except (OSError, AttributeError) as error:
        return {"function": "IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)", "error": str(error)}


def make_request(feature_index: int, function: int, params: bytes = b"") -> bytes:
    if len(params) > 16:
        raise ValueError("HID++ payload is limited to 16 bytes")
    header = bytes((
        HIDPP_LONG_REPORT_ID,
        BLUETOOTH_DEVICE_NUMBER,
        feature_index,
        function | SOFTWARE_ID,
    ))
    return header + params + bytes(HIDPP_PACKET_SIZE - len(header) - len(params))


def classify_response(response: bytes, request: bytes) -> str:
    if len(response) != HIDPP_PACKET_SIZE:
        return "wrong-length"
    if response[0] != HIDPP_LONG_REPORT_ID:
        return "wrong-report-id"
    if response[1] not in (BLUETOOTH_DEVICE_NUMBER, 0x00):
        return "wrong-device-number"
    if response[2] == 0xFF and response[3:5] == request[2:4]:
        return "hidpp-error"
    if response[2:4] == request[2:4]:
        return "response"
    return "unrelated"


class HidapiTransport:
    def __init__(self, device_info: Dict[str, Any]):
        self.device_info = device_info
        self.device: Optional[hid.device] = None

    def open(self) -> None:
        assert self.device is None
        self.device = hid.device()
        self.device.open_path(self.device_info["path"])

    def close(self) -> None:
        if self.device is not None:
            self.device.close()
            self.device = None

    def query(self, request: bytes, timeout_seconds: float = 2.0) -> bytes:
        if self.device is None:
            raise HidppError("HID transport is not open")
        written = self.device.write(request)
        if written != len(request):
            raise HidppError(f"short write: sent {written} of {len(request)} bytes")

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            response = self.device.read(HIDPP_PACKET_SIZE, timeout_ms=100)
            if not response:
                continue
            response_bytes = bytes(response)
            kind = classify_response(response_bytes, request)
            if kind == "response":
                return response_bytes
            if kind == "hidpp-error":
                raise HidppError(f"device returned HID++ error 0x{response_bytes[5]:02X}")
        raise HidppTimeout("timed out while waiting for a matching HID++ response")


def query_root_feature_index(transport: HidapiTransport, feature_id: int) -> Tuple[int, bytes]:
    if not 0x0001 <= feature_id <= 0xFFFF:
        raise ValueError("HID++ feature ID must fit 16 bits")
    request = make_request(ROOT_FEATURE_INDEX, ROOT_GET_FEATURE_FUNCTION, bytes((feature_id >> 8, feature_id & 0xFF)))
    response = transport.query(request)
    feature_index = response[4]
    if not 0x01 <= feature_index <= 0xEF:
        raise HidppError(f"feature 0x{feature_id:04X} is unsupported or has invalid index 0x{feature_index:02X}")
    return feature_index, response


def query_root_change_host_index(transport: HidapiTransport) -> Tuple[int, bytes]:
    return query_root_feature_index(transport, CHANGE_HOST_FEATURE_ID)


def query_change_host_status(transport: HidapiTransport, feature_index: int) -> Tuple[Dict[str, int], bytes]:
    request = make_request(feature_index, CHANGE_HOST_GET_STATUS_FUNCTION)
    response = transport.query(request)
    host_count = response[4]
    current_host = response[5]
    if not 1 <= host_count <= 3 or current_host >= host_count:
        raise HidppError(
            f"invalid CHANGE_HOST status: host_count={host_count}, current_host={current_host}"
        )
    return {"host_count": host_count, "current_host_index": current_host}, response


def query_hosts_info_state(transport: HidapiTransport, feature_index: int) -> Tuple[Dict[str, int], bytes]:
    request = make_request(feature_index, HOSTS_INFO_GET_INFO_FUNCTION)
    response = transport.query(request)
    capability_flags = response[4]
    host_count = response[6]
    current_host = response[7]
    if not 1 <= host_count <= 3 or current_host >= host_count:
        raise HidppError(f"invalid HOSTS_INFO state: host_count={host_count}, current_host={current_host}")
    if not capability_flags & 0x01:
        raise HidppError("device does not expose the read-host-name capability")
    return {
        "capability_flags": capability_flags,
        "host_count": host_count,
        "current_host_index": current_host,
    }, response


def query_host_descriptor(transport: HidapiTransport, feature_index: int, host_index: int) -> Tuple[Dict[str, int], bytes]:
    if not 0 <= host_index < 3:
        raise HidppError(f"host index out of range: {host_index}")
    request = make_request(feature_index, HOSTS_INFO_GET_DESCRIPTOR_FUNCTION, bytes((host_index,)))
    response = transport.query(request)
    if response[4] != host_index:
        raise HidppError(
            f"host descriptor slot mismatch: requested {host_index}, received {response[4]}"
        )
    status = response[5]
    name_length = response[8]
    maximum_length = response[9]
    if name_length > MAX_HOST_NAME_LENGTH or maximum_length > MAX_HOST_NAME_LENGTH or name_length > maximum_length:
        raise HidppError(
            f"invalid host descriptor for slot {host_index}: name_length={name_length}, maximum_length={maximum_length}"
        )
    return {
        "paired": bool(status),
        "status_raw": status,
        "name_length": name_length,
        "maximum_length": maximum_length,
    }, response


def query_host_name_piece(
    transport: HidapiTransport,
    feature_index: int,
    host_index: int,
    offset: int,
    remaining: int,
) -> Tuple[bytes, bytes]:
    if not 0 <= host_index < 3 or offset < 0 or remaining <= 0 or offset + remaining > MAX_HOST_NAME_LENGTH:
        raise HidppError(f"invalid host-name read: host={host_index}, offset={offset}, remaining={remaining}")
    request = make_request(feature_index, HOSTS_INFO_GET_NAME_FUNCTION, bytes((host_index, offset)))
    response = transport.query(request)
    if response[4] != host_index or response[5] != offset:
        raise HidppError(
            f"host-name response context mismatch: requested host={host_index}, offset={offset}, "
            f"received host={response[4]}, offset={response[5]}"
        )
    expected_size = min(14, remaining)
    name_piece = response[6 : 6 + expected_size]
    if len(name_piece) != expected_size:
        raise HidppError(f"short host-name response: expected {expected_size} data bytes, received {len(name_piece)}")
    return name_piece, response


def read_host_name(transport: HidapiTransport, feature_index: int, host_index: int) -> Tuple[Dict[str, object], List[Dict[str, str]]]:
    descriptor, descriptor_response = query_host_descriptor(transport, feature_index, host_index)
    evidence = [{
        "function": HOSTS_INFO_GET_DESCRIPTOR_FUNCTION,
        "request_hex": make_request(feature_index, HOSTS_INFO_GET_DESCRIPTOR_FUNCTION, bytes((host_index,))).hex(),
        "response_hex": descriptor_response.hex(),
        "decoded": {"host_index": host_index, **descriptor},
    }]
    name_bytes = bytearray()
    expected_length = int(descriptor["name_length"])
    while len(name_bytes) < expected_length:
        remaining = expected_length - len(name_bytes)
        offset = len(name_bytes)
        piece, response = query_host_name_piece(
            transport,
            feature_index,
            host_index,
            len(name_bytes),
            remaining,
        )
        evidence.append({
            "function": HOSTS_INFO_GET_NAME_FUNCTION,
            "request_hex": make_request(
                feature_index,
                HOSTS_INFO_GET_NAME_FUNCTION,
                bytes((host_index, len(name_bytes))),
            ).hex(),
            "response_hex": response.hex(),
            "decoded": {"host_index": host_index, "offset": offset},
        })
        name_bytes.extend(piece)
    raw_name = bytes(name_bytes).split(b"\x00", 1)[0]
    try:
        name = raw_name.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HidppError(f"host {host_index} name is not valid UTF-8") from error
    return {"host_index": host_index, **descriptor, "name": name}, evidence


def run_readonly_query(devices: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    vendor_collection = select_vendor_collection(devices)
    non_exclusive = use_non_exclusive_darwin_open()
    access = check_hid_listen_access()
    result: Dict[str, Any] = {
        "selected_collection": vendor_collection,
        "non_exclusive_open": {"enabled": non_exclusive},
        "hid_listen_access": access,
        "queries": [],
    }
    if access.get("raw_result") != 0:
        result["blocked_before_open"] = "IOHIDCheckAccess(listen-event) is not granted"
        return result
    if not non_exclusive:
        raise HidppError("failed to select hidapi Darwin non-exclusive open mode; refusing to open exclusively")

    transport = HidapiTransport(vendor_collection)
    try:
        transport.open()
        feature_index, root_response = query_root_change_host_index(transport)
        result["queries"].append({
            "name": "root-get-change-host",
            "feature_id": CHANGE_HOST_FEATURE_ID,
            "function": ROOT_GET_FEATURE_FUNCTION,
            "request_hex": make_request(ROOT_FEATURE_INDEX, ROOT_GET_FEATURE_FUNCTION, bytes((0x18, 0x14))).hex(),
            "response_hex": root_response.hex(),
            "feature_index": feature_index,
        })
        status, status_response = query_change_host_status(transport, feature_index)
        result["queries"].append({
            "name": "change-host-get-status",
            "feature_id": CHANGE_HOST_FEATURE_ID,
            "function": CHANGE_HOST_GET_STATUS_FUNCTION,
            "request_hex": make_request(feature_index, CHANGE_HOST_GET_STATUS_FUNCTION).hex(),
            "response_hex": status_response.hex(),
            "decoded": status,
        })
        result["change_host_status"] = status
    finally:
        transport.close()
    return result


def read_hosts_info_with_transport(transport: HidapiTransport) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "queries": [],
        "hosts": [],
    }
    feature_index, root_response = query_root_feature_index(transport, HOSTS_INFO_FEATURE_ID)
    result["queries"].append({
        "name": "root-get-hosts-info",
        "feature_id": HOSTS_INFO_FEATURE_ID,
        "function": ROOT_GET_FEATURE_FUNCTION,
        "request_hex": make_request(
            ROOT_FEATURE_INDEX,
            ROOT_GET_FEATURE_FUNCTION,
            bytes((HOSTS_INFO_FEATURE_ID >> 8, HOSTS_INFO_FEATURE_ID & 0xFF)),
        ).hex(),
        "response_hex": root_response.hex(),
        "feature_index": feature_index,
    })
    state, state_response = query_hosts_info_state(transport, feature_index)
    result["queries"].append({
        "name": "hosts-info-get-state",
        "feature_id": HOSTS_INFO_FEATURE_ID,
        "function": HOSTS_INFO_GET_INFO_FUNCTION,
        "request_hex": make_request(feature_index, HOSTS_INFO_GET_INFO_FUNCTION).hex(),
        "response_hex": state_response.hex(),
        "decoded": state,
    })
    for host_index in range(state["host_count"]):
        host, evidence = read_host_name(transport, feature_index, host_index)
        result["hosts"].append(host)
        result["queries"].extend(evidence)
    return result


def run_hosts_info_query(devices: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    vendor_collection = select_vendor_collection(devices)
    non_exclusive = use_non_exclusive_darwin_open()
    access = check_hid_listen_access()
    result: Dict[str, Any] = {
        "selected_collection": vendor_collection,
        "non_exclusive_open": {"enabled": non_exclusive},
        "hid_listen_access": access,
    }
    if access.get("raw_result") != 0:
        result["blocked_before_open"] = "IOHIDCheckAccess(listen-event) is not granted"
        return result
    if not non_exclusive:
        raise HidppError("failed to select hidapi Darwin non-exclusive open mode; refusing to open exclusively")

    transport = HidapiTransport(vendor_collection)
    try:
        transport.open()
        result.update(read_hosts_info_with_transport(transport))
    finally:
        transport.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", action="store_true", help="make only Root GetFeature and CHANGE_HOST function 0x00 queries")
    parser.add_argument("--check-access-only", action="store_true", help="report IOHIDCheckAccess without opening HID")
    parser.add_argument("--hosts-info", action="store_true", help="make only explicit HOSTS_INFO 0x1815 read-only queries")
    args = parser.parse_args()

    output: Dict[str, Any] = {}
    if args.check_access_only:
        output["hid_listen_access"] = check_hid_listen_access()
    else:
        devices = enumerate_mouse()
        output["devices"] = devices
        if args.query and args.hosts_info:
            raise SystemExit("choose exactly one read-only mode: --query or --hosts-info")
        if args.query:
            if not devices:
                raise SystemExit("M585/M590 is not connected")
            output.update(run_readonly_query(devices))
        elif args.hosts_info:
            if not devices:
                raise SystemExit("M585/M590 is not connected")
            output.update(run_hosts_info_query(devices))
    print(json.dumps(output, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
