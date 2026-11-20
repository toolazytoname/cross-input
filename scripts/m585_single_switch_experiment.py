#!/usr/bin/env python3
"""Prepare one explicitly authorized M585/M590 Mac-to-Windows switch attempt."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from m585_readonly_probe import (
    CHANGE_HOST_FEATURE_ID,
    CHANGE_HOST_GET_STATUS_FUNCTION,
    HidapiTransport,
    HidppError,
    HOSTS_INFO_FEATURE_ID,
    LOGITECH_VENDOR_ID,
    LOGITECH_VENDOR_USAGE,
    LOGITECH_VENDOR_USAGE_PAGE,
    M585_M590_PRODUCT_ID,
    ROOT_GET_FEATURE_FUNCTION,
    check_hid_listen_access,
    enumerate_mouse,
    json_default,
    make_request,
    query_change_host_status,
    query_root_feature_index,
    query_hosts_info_state,
    read_host_name,
    use_non_exclusive_darwin_open,
)

EXPECTED_SERIAL = os.environ.get("M585_SERIAL", "7A09C04B5120EA18")
EXPECTED_CHANGE_HOST_INDEX = 9
EXPECTED_HOSTS_INFO_INDEX = 10
EXPECTED_CURRENT_SLOT = 1
EXPECTED_TARGET_SLOT = 0
EXPECTED_CURRENT_NAME = os.environ.get("M585_MAC_HOST_NAME", "lazy的Mac Mini")
EXPECTED_TARGET_NAME = os.environ.get("M585_WINDOWS_HOST_NAME", "LAZY-WINDOWS")
DEFAULT_GUARD_PATH = Path("evidence/mouse/m585-mac-to-windows-single-attempt-guard.json")
DEFAULT_LOG_PATH = Path("logs/2026-11-19-m585-single-switch-experiment.json")


class OneShotHidapiTransport(HidapiTransport):
    def submit_no_reply(self, request: bytes) -> int:
        if self.device is None:
            raise HidppError("HID transport is not open")
        written = self.device.write(request)
        if written != len(request):
            raise HidppError(f"short write: submitted {written} of {len(request)} bytes")
        return written


def select_expected_collection(devices: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    serial_matches = [device for device in devices if device.get("serial_number") == EXPECTED_SERIAL]
    if not serial_matches:
        raise HidppError(f"M585/M590 serial {EXPECTED_SERIAL} is not present")
    matches = [
        device
        for device in serial_matches
        if device.get("vendor_id") == LOGITECH_VENDOR_ID
        and device.get("product_id") == M585_M590_PRODUCT_ID
        and device.get("usage_page") == LOGITECH_VENDOR_USAGE_PAGE
        and device.get("usage") == LOGITECH_VENDOR_USAGE
    ]
    if len(matches) != 1:
        raise HidppError(
            f"expected exactly one vendor collection for serial {EXPECTED_SERIAL}, found {len(matches)}"
        )
    return matches[0]


def perform_strict_preflight(transport: Any) -> Dict[str, Any]:
    queries: List[Dict[str, Any]] = []

    change_request = make_request(
        0,
        ROOT_GET_FEATURE_FUNCTION,
        bytes((CHANGE_HOST_FEATURE_ID >> 8, CHANGE_HOST_FEATURE_ID & 0xFF)),
    )
    change_index, change_root_response = query_root_feature_index(
        transport, CHANGE_HOST_FEATURE_ID
    )
    if change_index != EXPECTED_CHANGE_HOST_INDEX:
        raise HidppError(
            f"CHANGE_HOST feature index changed: expected {EXPECTED_CHANGE_HOST_INDEX}, got {change_index}"
        )
    queries.append({
        "name": "root-get-change-host",
        "request_hex": change_request.hex(),
        "response_hex": change_root_response.hex(),
        "feature_index": change_index,
    })

    status_request = make_request(change_index, CHANGE_HOST_GET_STATUS_FUNCTION)
    status, status_response = query_change_host_status(transport, change_index)
    if status != {"host_count": 2, "current_host_index": EXPECTED_CURRENT_SLOT}:
        raise HidppError(f"CHANGE_HOST state mismatch: {status}")
    queries.append({
        "name": "change-host-get-status",
        "request_hex": status_request.hex(),
        "response_hex": status_response.hex(),
        "decoded": status,
    })

    hosts_request = make_request(
        0,
        ROOT_GET_FEATURE_FUNCTION,
        bytes((HOSTS_INFO_FEATURE_ID >> 8, HOSTS_INFO_FEATURE_ID & 0xFF)),
    )
    hosts_index, hosts_root_response = query_root_feature_index(
        transport, HOSTS_INFO_FEATURE_ID
    )
    if hosts_index != EXPECTED_HOSTS_INFO_INDEX:
        raise HidppError(
            f"HOSTS_INFO feature index changed: expected {EXPECTED_HOSTS_INFO_INDEX}, got {hosts_index}"
        )
    queries.append({
        "name": "root-get-hosts-info",
        "request_hex": hosts_request.hex(),
        "response_hex": hosts_root_response.hex(),
        "feature_index": hosts_index,
    })

    state_request = make_request(hosts_index, 0x00)
    state, state_response = query_hosts_info_state(transport, hosts_index)
    if state["host_count"] != 2 or state["current_host_index"] != EXPECTED_CURRENT_SLOT:
        raise HidppError(f"HOSTS_INFO state mismatch: {state}")
    queries.append({
        "name": "hosts-info-get-state",
        "request_hex": state_request.hex(),
        "response_hex": state_response.hex(),
        "decoded": state,
    })

    target_host, target_evidence = read_host_name(transport, hosts_index, EXPECTED_TARGET_SLOT)
    current_host, current_evidence = read_host_name(transport, hosts_index, EXPECTED_CURRENT_SLOT)
    queries.extend(target_evidence)
    queries.extend(current_evidence)

    if not target_host["paired"]:
        raise HidppError("target slot 0 is not marked paired/available by HOSTS_INFO")
    if target_host["name"] != EXPECTED_TARGET_NAME:
        raise HidppError(
            f"target slot name mismatch: expected {EXPECTED_TARGET_NAME!r}, got {target_host['name']!r}"
        )
    if not current_host["paired"]:
        raise HidppError("current slot 1 is not marked paired/available by HOSTS_INFO")
    if current_host["name"] != EXPECTED_CURRENT_NAME:
        raise HidppError(
            f"current slot name mismatch: expected {EXPECTED_CURRENT_NAME!r}, got {current_host['name']!r}"
        )

    return {
        "change_host_feature_index": change_index,
        "hosts_info_feature_index": hosts_index,
        "change_host_status": status,
        "hosts_info_state": state,
        "hosts": [target_host, current_host],
        "queries": queries,
    }


def create_attempt_guard(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as error:
        raise HidppError(f"single-attempt guard already exists: {path}") from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as guard_file:
        json.dump({
            "created_at": datetime.now(timezone.utc).isoformat(),
            "serial": EXPECTED_SERIAL,
            "target_slot": EXPECTED_TARGET_SLOT,
            "target_name": EXPECTED_TARGET_NAME,
            "policy": "one submit attempt; no retry; no automatic return switch",
        }, guard_file, ensure_ascii=False, indent=2)
        guard_file.write("\n")


def write_attempt_log(path: Path, result: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )


def run_experiment(
    devices: Sequence[Dict[str, Any]],
    *,
    apply: bool,
    authorization_confirmed: bool,
    physical_rollback_ready: bool,
    guard_path: Path,
    log_path: Path,
    transport_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    selected = select_expected_collection(devices)
    result: Dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "selected_collection": selected,
        "expected_serial": EXPECTED_SERIAL,
        "expected_current_slot": EXPECTED_CURRENT_SLOT,
        "expected_current_name": EXPECTED_CURRENT_NAME,
        "expected_target_slot": EXPECTED_TARGET_SLOT,
        "expected_target_name": EXPECTED_TARGET_NAME,
    }

    if apply:
        if not authorization_confirmed or not physical_rollback_ready:
            result["blocked_before_any_hid_io"] = True
            return result
        if guard_path.exists():
            result["blocked_before_any_hid_io"] = True
            result["guard_path"] = str(guard_path)
            return result

    factory = transport_factory or (lambda device: OneShotHidapiTransport(device))
    if transport_factory is None:
        non_exclusive = use_non_exclusive_darwin_open()
        access = check_hid_listen_access()
        result["non_exclusive_open"] = {"enabled": non_exclusive}
        result["hid_listen_access"] = access
        if access.get("raw_result") != 0:
            result["blocked_before_open"] = "IOHIDCheckAccess(listen-event) is not granted"
            return result
        if not non_exclusive:
            raise HidppError("refusing to use an exclusive Darwin HID open")

    transport = factory(selected)
    try:
        transport.open()
        preflight = perform_strict_preflight(transport)
        result.update(preflight)
        if not apply:
            result["would_submit"] = make_request(
                EXPECTED_CHANGE_HOST_INDEX,
                0x10,
                bytes((EXPECTED_TARGET_SLOT,)),
            ).hex()
            return result

        create_attempt_guard(guard_path)
        result["guard_path"] = str(guard_path)
        switch_request = make_request(
            EXPECTED_CHANGE_HOST_INDEX,
            0x10,
            bytes((EXPECTED_TARGET_SLOT,)),
        )
        result["switch_request_hex"] = switch_request.hex()
        result["switch_submit_attempted"] = True
        try:
            submitted_bytes = transport.submit_no_reply(switch_request)
        except Exception as error:
            result["switch_submit_error"] = {
                "error_type": type(error).__name__,
                "detail": str(error),
            }
            result["switch_report_submit"] = {
                "attempt_count": 1,
                "bytes_submitted": None,
                "no_reply_expected": True,
                "meaning": "submission reached the HID transport call but its return status was ambiguous; device departure and target-host input require external evidence",
                "retry": False,
                "automatic_return_switch": False,
                "error_type": type(error).__name__,
                "detail": str(error),
            }
            return result
        result["switch_report_submit"] = {
            "attempt_count": 1,
            "bytes_submitted": submitted_bytes,
            "no_reply_expected": True,
            "meaning": "report submitted to the HID transport; target-host input requires user observation",
            "retry": False,
            "automatic_return_switch": False,
        }
        return result
    finally:
        if hasattr(transport, "close"):
            transport.close()
        write_attempt_log(log_path, result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strict one-shot M585/M590 Mac-to-Windows experiment; does nothing unless --dry-run or --apply is selected"
    )
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument("--dry-run", action="store_true", help="perform read-only preflight only")
    mode.add_argument("--apply", action="store_true", help="preflight then submit at most one switch report")
    parser.add_argument("--expected-target-name")
    parser.add_argument("--confirm-single-send", action="store_true")
    parser.add_argument("--user-ready-rollback", action="store_true")
    parser.add_argument("--guard-path", type=Path, default=DEFAULT_GUARD_PATH)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.dry_run and not args.apply:
        print(json.dumps({
            "mode": "plan-only",
            "hid_io_performed": False,
            "required_for_readonly_preflight": "--dry-run",
            "required_for_apply": [
                "--apply",
                f"--expected-target-name {EXPECTED_TARGET_NAME}",
                "--confirm-single-send",
                "--user-ready-rollback",
            ],
        }, ensure_ascii=False, indent=2))
        return
    if args.apply and (
        args.expected_target_name is None
        or args.expected_target_name != EXPECTED_TARGET_NAME
        or not args.confirm_single_send
        or not args.user_ready_rollback
    ):
        raise SystemExit(
            "apply requires the exact target name, --confirm-single-send, and --user-ready-rollback"
        )

    result = run_experiment(
        enumerate_mouse(),
        apply=args.apply,
        authorization_confirmed=args.confirm_single_send,
        physical_rollback_ready=args.user_ready_rollback,
        guard_path=args.guard_path,
        log_path=args.log_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))


if __name__ == "__main__":
    main()
