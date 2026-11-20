#!/usr/bin/env python3
"""Enumerate K94 and optionally send only a read-only VIA protocol query."""

import argparse
import json
from typing import Any

import hid

KEMOVE_VENDOR_ID = 0x36B0
QMK_RAW_USAGE_PAGE = 0xFF60
QMK_RAW_USAGE_ID = 0x61
VIA_GET_PROTOCOL_VERSION = 0x01
VIA_PROTOCOL_0_0C = 0x000C


def device_dictionary(device: dict[str, Any]) -> dict[str, Any]:
    return {
        key: device[key]
        for key in (
            "vendor_id",
            "product_id",
            "serial_number",
            "manufacturer_string",
            "product_string",
            "usage_page",
            "usage",
            "interface_number",
            "path",
        )
    }


def json_default(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    raise TypeError(type(value).__name__)


def enumerate_k94() -> list[dict[str, Any]]:
    devices = [device_dictionary(device) for device in hid.enumerate() if device["vendor_id"] == KEMOVE_VENDOR_ID]
    devices.sort(
        key=lambda device: (
            device["product_id"],
            device["usage_page"],
            device["usage"],
            str(device["path"]),
        )
    )
    return devices


def query_via_protocol(device_info: dict[str, Any]) -> dict[str, Any]:
    device = hid.device()
    device.open_path(device_info["path"])
    try:
        request = bytearray(32)
        request[0] = VIA_GET_PROTOCOL_VERSION
        request[1] = 0x00
        frame = bytes([0x00]) + request
        written = device.write(frame)
        response = device.read(32, timeout_ms=1500)
        result = {
            "device": device_info,
            "request_hex": frame.hex(),
            "bytes_written": written,
            "response_hex": bytes(response).hex(),
        }
        if len(response) >= 3 and response[0] == VIA_GET_PROTOCOL_VERSION:
            result["via_protocol"] = f"{response[1]}.{response[2]:02X}"
            result["expected_protocol"] = f"{VIA_PROTOCOL_0_0C >> 8:01X}.{VIA_PROTOCOL_0_0C & 0xFF:02X}"
        return result
    finally:
        device.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--via-probe", action="store_true", help="query VIA protocol only; never switch modes")
    args = parser.parse_args()

    devices = enumerate_k94()
    output = {"devices": devices}
    raw_devices = [
        device
        for device in devices
        if device["usage_page"] == QMK_RAW_USAGE_PAGE and device["usage"] == QMK_RAW_USAGE_ID
    ]
    output["qmk_raw_collections"] = raw_devices

    if args.via_probe:
        if not raw_devices:
            raise SystemExit("No K94 QMK raw HID collection (usagePage 0xFF60, usage 0x61) is currently enumerable")
        output["via_protocol_query"] = query_via_protocol(raw_devices[0])

    print(json.dumps(output, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
