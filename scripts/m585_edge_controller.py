#!/usr/bin/env python3
"""Supervised Mac-side edge controller for the M585/M590 hardware channel."""

import argparse
import socket
import ctypes
import fcntl
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LOG_PATH = Path("logs/m585-edge-events.jsonl")
DEFAULT_LOCK_PATH = Path("logs/m585-edge-controller.lock")
MAC_SWITCH_ENTRY = SCRIPT_DIR / "m585_switch_to_windows_once.sh"
WINDOWS_HEALTH_ENTRY = SCRIPT_DIR / "run_windows_hid_protocol_probe.sh"
MAC_READONLY_PROBE = SCRIPT_DIR / "m585_readonly_probe.py"


@dataclass(frozen=True)
class EdgeConfig:
    threshold_px: int = 8
    dwell_ms: int = 400
    cooldown_ms: int = 2500
    poll_interval_seconds: float = 0.05
    state_poll_seconds: float = 1.0
    switch_stability_ms: int = 5000
    return_confirmations_required: int = 2
    query_failure_limit: int = 3
    peer_check_timeout_seconds: float = 8.0


@dataclass(frozen=True)
class EdgeSample:
    timestamp_ms: int
    x: float
    y: float
    event_type: int
    button_pressed: bool
    modifier_pressed: bool


@dataclass
class AttemptRecord:
    attempt_id: str
    reason: str
    origin_state: str
    target: str
    current_slot_evidence: Optional[Dict[str, Any]]
    peer_health: Optional[Dict[str, Any]]
    submit_evidence: Optional[Dict[str, Any]]
    submitted_at: Optional[str]
    result: str
    recovery: str


class EdgeArbiter:
    """Debounce edge events without using Deskflow or network state as truth."""

    def __init__(self, config: EdgeConfig, clock_ms: Callable[[], int]):
        self.config = config
        self.clock_ms = clock_ms
        self.state = "READY_MAC"
        self._dwell_started_at: Optional[int] = None
        self._last_submit_completed_ms: Optional[int] = None
        self._submit_completed_at: Optional[int] = None
        self._recovery_entered_at: Optional[int] = None
        self._rearm_requires_leave_edge = False

    def observe(self, sample: EdgeSample, edge_x: float) -> Dict[str, Any]:
        at_edge = sample.x <= edge_x + self.config.threshold_px
        interaction = sample.button_pressed or sample.modifier_pressed
        now = self.clock_ms()
        if self._rearm_requires_leave_edge:
            if at_edge:
                return {"trigger": False, "reason": "rearm-requires-leave-edge", "dwell_ms": 0}
            self._rearm_requires_leave_edge = False
        if not at_edge or interaction or sample.event_type != 5:
            self._dwell_started_at = None
            return {"trigger": False, "reason": "not-at-edge" if not at_edge else "interaction-or-drag"}

        if self._dwell_started_at is None:
            self._dwell_started_at = now
        dwell_ms = now - self._dwell_started_at
        if dwell_ms < self.config.dwell_ms:
            return {"trigger": False, "reason": "dwelling", "dwell_ms": dwell_ms}

        if self.state != "READY_MAC":
            return {"trigger": False, "reason": "state-" + self.state, "dwell_ms": dwell_ms}
        if self._last_submit_completed_ms is not None and now - self._last_submit_completed_ms < self.config.cooldown_ms:
            return {"trigger": False, "reason": "cooldown", "dwell_ms": dwell_ms}

        self.begin_attempt()
        return {"trigger": True, "reason": "left-edge-dwell", "dwell_ms": dwell_ms}

    def begin_attempt(self) -> None:
        self.state = "SWITCHING_TO_WINDOWS"
        self._dwell_started_at = None
        self._rearm_requires_leave_edge = True

    @property
    def submit_completed_at(self) -> Optional[int]:
        return self._submit_completed_at

    @property
    def rearm_requires_leave_edge(self) -> bool:
        return self._rearm_requires_leave_edge

    @property
    def recovery_entered_at(self) -> Optional[int]:
        return self._recovery_entered_at

    def mark_submit_completed(self) -> None:
        self._last_submit_completed_ms = self.clock_ms()
        self._submit_completed_at = self._last_submit_completed_ms
        self.state = "SWITCHING_TO_WINDOWS"

    def mark_submit_failed(self) -> None:
        self._last_submit_completed_ms = self.clock_ms()
        self._submit_completed_at = self._last_submit_completed_ms
        self.state = "RECOVERY_REQUIRED"

    def mark_target_unavailable(self) -> None:
        self.state = "TARGET_UNAVAILABLE"
        self._dwell_started_at = None

    def note_mouse_absent(self, external: bool = False) -> None:
        if self.state == "READY_MAC":
            self.state = "MOUSE_ABSENT_EXTERNAL"
        elif self.state == "SWITCHING_TO_WINDOWS":
            self.state = "MOUSE_ABSENT_AFTER_SWITCH"
        self._dwell_started_at = None
        self._rearm_requires_leave_edge = True

    def mark_return_ready(self) -> None:
        self.state = "READY_MAC"
        self._dwell_started_at = None
        self._recovery_entered_at = None
        self._rearm_requires_leave_edge = True

    def mark_return_target_ready(self) -> None:
        self.state = "READY_MAC_RETURN_TARGET"
        self._dwell_started_at = None
        self._rearm_requires_leave_edge = True

    def mark_recovery_required(self, at_ms: Optional[int] = None) -> None:
        if self.state == "RECOVERY_REQUIRED":
            return
        self.state = "RECOVERY_REQUIRED"
        self._dwell_started_at = None
        self._recovery_entered_at = self.clock_ms() if at_ms is None else at_ms

    def confirm_mac_slot(self, current_slot: int) -> bool:
        if current_slot == 1:
            if self.state == "READY_MAC":
                return True
            if self.state in ("MOUSE_ABSENT_EXTERNAL", "MOUSE_ABSENT_AFTER_SWITCH", "READY_MAC_RETURN_TARGET"):
                self.mark_return_ready()
                return True
            return False
        self.mark_recovery_required()
        return False


class AttemptLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record: AttemptRecord) -> None:
        line = json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
                log_file.flush()
                os.fsync(log_file.fileno())


class ControllerStatus:
    def __init__(self):
        self._lock = threading.Lock()
        self._values = {
            "schema": 1,
            "host": "mac",
            "state": "STARTING",
            "mouse_current_slot": None,
            "ready": False,
            "controller_running": False,
            "mouse_present": None,
            "poll_outcome": None,
            "return_confirmations": 0,
            "return_target_ready": False,
            "query_failure_count": 0,
            "recovery_started_at": None,
            "started_at": utc_now(),
            "last_slot_evidence": None,
            "last_peer_health": None,
        }

    def update(self, **values):
        with self._lock:
            if values.get("ready"):
                running = values.get("controller_running", self._values.get("controller_running", False))
                state = values.get("state", self._values.get("state"))
                slot = values.get("mouse_current_slot", self._values.get("mouse_current_slot"))
                values["ready"] = bool(running and state in ("READY_MAC", "READY_MAC_RETURN_TARGET"))
            self._values.update(values)

    def snapshot(self):
        with self._lock:
            return dict(self._values)


class HealthServer:
    """One-line JSON health endpoint used by the Windows peer before a return hop."""

    def __init__(self, bind_address: str, port: int, status: ControllerStatus):
        self.bind_address = bind_address
        self.port = port
        self.status = status
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server.bind((bind_address, port))
            self.server.listen(4)
        except BaseException:
            self.server.close()
            raise
        self.server.settimeout(1.0)
        self.stop_event = threading.Event()

    def serve(self):
        while not self.stop_event.is_set():
            try:
                connection, peer = self.server.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(2.0)
                try:
                    connection.recv(1024)
                    payload = json.dumps(self.status.snapshot(), ensure_ascii=False, separators=(",", ":"))
                    connection.sendall(payload.encode("utf-8") + b"\n")
                except OSError:
                    continue

    def stop(self):
        self.stop_event.set()
        try:
            self.server.close()
        except OSError:
            pass


class ControllerLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.handle.close()
            self.handle = None
            raise RuntimeError("another M585 Mac edge controller is already running") from error
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()) + "\n")
        self.handle.flush()
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.handle is not None:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()


class MacEventTap:
    """Listen-only CGEventTap; it never alters or consumes input events."""

    MOUSE_MOVED = 5
    LEFT_MOUSE_DRAGGED = 6
    RIGHT_MOUSE_DRAGGED = 7
    OTHER_MOUSE_DRAGGED = 8
    MOUSE_BUTTON_MASK = 0x000000FF
    MODIFIER_MASK = (
        0x00010000 | 0x00020000 | 0x00040000 | 0x00080000 |
        0x00100000 | 0x00200000 | 0x00400000 | 0x00800000
    )
    K_CG_EVENT_SOURCE_STATE_COMBINED_SESSION_STATE = 0

    def __init__(self, samples: "queue.Queue[EdgeSample]"):
        self.samples = samples
        self.on_running: Optional[Callable[[], None]] = None
        self.core_graphics = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        self.core_graphics.CGGetActiveDisplayList.restype = ctypes.c_int32
        self.core_graphics.CGGetActiveDisplayList.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        self.application_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        self.core_foundation = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        self.core_graphics.CGEventTapCreate.restype = ctypes.c_void_p
        self.core_graphics.CGEventTapCreate.argtypes = [
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.core_graphics.CFMachPortInvalidate.argtypes = [ctypes.c_void_p]
        self.core_graphics.CFMachPortInvalidate.restype = None
        self.core_graphics.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.core_graphics.CGEventTapEnable.restype = ctypes.c_bool
        self.core_foundation.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
        self.core_foundation.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        self.core_foundation.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        self.core_foundation.CFRunLoopGetCurrent.argtypes = []
        self.core_foundation.CFRunLoopAddSource.restype = None
        self.core_foundation.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.core_foundation.CFRunLoopRun.restype = None
        self.core_foundation.CFRunLoopRun.argtypes = []
        self.core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        self.core_foundation.CFMachPortInvalidate.restype = None
        self.core_foundation.CFMachPortInvalidate.argtypes = [ctypes.c_void_p]
        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        self.core_graphics.CGEventGetLocation.restype = CGPoint
        self.core_graphics.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        self.core_graphics.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.core_graphics.CGEventGetIntegerValueField.restype = ctypes.c_int64
        self.core_graphics.CGEventGetDoubleValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.core_graphics.CGEventGetDoubleValueField.restype = ctypes.c_double

    def accessibility_trusted(self) -> bool:
        self.application_services.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(self.application_services.AXIsProcessTrusted())

    def event_tap_available(self) -> bool:
        event_mask = (1 << self.MOUSE_MOVED) | (1 << self.LEFT_MOUSE_DRAGGED) | (1 << self.RIGHT_MOUSE_DRAGGED) | (1 << self.OTHER_MOUSE_DRAGGED)
        callback_type = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        callback = callback_type(self._callback)
        tap = self.core_graphics.CGEventTapCreate(1, 0, 1, event_mask, callback, None)
        if not tap:
            return False
        self.core_foundation.CFMachPortInvalidate(tap)
        return True

    def run(self) -> None:
        if not self.accessibility_trusted():
            raise RuntimeError("Accessibility is not granted to this process; use System Settings to grant it")

        event_types = {self.MOUSE_MOVED, self.LEFT_MOUSE_DRAGGED, self.RIGHT_MOUSE_DRAGGED, self.OTHER_MOUSE_DRAGGED}
        event_mask = 0
        for event_type in event_types:
            event_mask |= 1 << event_type

        callback_type = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        callback = callback_type(self._callback)
        tap = self.core_graphics.CGEventTapCreate(
            ctypes.c_uint(1),  # kCGSessionEventTap
            ctypes.c_uint(0),  # kCGHeadInsertEventTap
            ctypes.c_uint(1),  # kCGEventTapOptionListenOnly
            ctypes.c_uint32(event_mask),
            callback,
            None,
        )
        if not tap:
            raise RuntimeError("CGEventTapCreate failed; Accessibility/Input Monitoring may be missing")
        self.core_graphics.CFMachPortInvalidate.argtypes = [ctypes.c_void_p]
        self.core_graphics.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.core_graphics.CGEventTapEnable(tap, True)
        try:
            run_loop_source = self.core_foundation.CFMachPortCreateRunLoopSource(None, tap, 0)
            common_modes = ctypes.c_void_p.in_dll(self.core_foundation, "kCFRunLoopCommonModes")
            self.core_foundation.CFRunLoopAddSource(
                self.core_foundation.CFRunLoopGetCurrent(),
                run_loop_source,
                common_modes,
            )
            if self.on_running is not None:
                self.on_running()
            self.core_foundation.CFRunLoopRun()
        finally:
            self.core_graphics.CGEventTapEnable(tap, False)
            self.core_foundation.CFMachPortInvalidate(tap)

    def _callback(self, proxy, event_type, event, refcon):
        now_ms = int(time.monotonic() * 1000)
        point = self._event_location(event)
        flags = self._event_flags(event)
        self.samples.put(EdgeSample(
            timestamp_ms=now_ms,
            x=point[0],
            y=point[1],
            event_type=int(event_type),
            button_pressed=int(event_type) != self.MOUSE_MOVED or self._event_buttons(event, int(event_type), flags),
            modifier_pressed=bool(flags & self.MODIFIER_MASK),
        ))
        return event

    def _event_location(self, event):
        point = self.core_graphics.CGEventGetLocation(event)
        return float(point.x), float(point.y)

    def _event_buttons(self, event, event_type: int, flags: int) -> bool:
        # The drag event type already identifies a held button.  For other mouse
        # events, pressure is the public per-event button field and the low flag
        # bits contain the combined mouse-button state.
        if event_type in (self.LEFT_MOUSE_DRAGGED, self.RIGHT_MOUSE_DRAGGED, self.OTHER_MOUSE_DRAGGED):
            return True
        pressure = self.core_graphics.CGEventGetDoubleValueField(event, 2)
        return pressure > 0.0 or bool(flags & self.MOUSE_BUTTON_MASK)

    def _event_flags(self, event) -> int:
        self.core_graphics.CGEventGetFlags.argtypes = [ctypes.c_void_p]
        self.core_graphics.CGEventGetFlags.restype = ctypes.c_uint64
        return int(self.core_graphics.CGEventGetFlags(event))


class DisplayEnumerator:
    def __init__(self):
        self.core_graphics = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )

    def frames(self) -> List[Dict[str, Any]]:
        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        class CGRect(ctypes.Structure):
            _fields_ = [("origin", CGPoint), ("width", ctypes.c_double), ("height", ctypes.c_double)]

        displays = (ctypes.c_uint32 * 16)()
        count = ctypes.c_uint32()
        result = self.core_graphics.CGGetActiveDisplayList(16, displays, ctypes.byref(count))
        if result != 0:
            raise RuntimeError("CGGetActiveDisplayList failed: " + str(result))
        output = []
        self.core_graphics.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        self.core_graphics.CGDisplayBounds.restype = CGRect
        for index in range(count.value):
            frame = self.core_graphics.CGDisplayBounds(displays[index])
            output.append({
                "index": index + 1,
                "display_id": int(displays[index]),
                "x": frame.origin.x,
                "y": frame.origin.y,
                "width": frame.width,
                "height": frame.height,
            })
        return output


def choose_left_edge(frames: List[Dict[str, Any]], display_index: Optional[int] = None) -> float:
    if not frames:
        raise RuntimeError("no active Mac displays were returned")
    if display_index is None:
        return min(frame["x"] for frame in frames)
    matches = [frame for frame in frames if frame["index"] == display_index]
    if len(matches) != 1:
        raise RuntimeError("display index is not unique: " + str(display_index))
    return float(matches[0]["x"])


def run_json_command(command: List[str], timeout: float) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            timeout=timeout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "ok": False,
            "error": type(error).__name__,
            "detail": str(error),
            "stderr_tail": "",
            "stdout_tail": "",
        }
    if completed.returncode != 0:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "stderr_tail": completed.stderr[-500:],
            "stdout_tail": completed.stdout[-500:],
        }
    try:
        return {"ok": True, "data": json.loads(completed.stdout)}
    except json.JSONDecodeError as error:
        return {
            "ok": False,
            "error": "invalid JSON",
            "detail": str(error),
            "stderr_tail": completed.stderr[-500:],
            "stdout_tail": completed.stdout[-500:],
        }


def read_mac_slot(python: str) -> Dict[str, Any]:
    result = run_json_command([
        python,
        str(MAC_READONLY_PROBE),
        "--query",
    ], 8.0)
    if not result.get("ok"):
        diagnostic = (result.get("stderr_tail") or "") + (result.get("stdout_tail") or "")
        absent_markers = (
            "is not present",
            "is not connected",
            "found 0",
        )
        if any(marker in diagnostic for marker in absent_markers):
            result["device_present"] = False
            result["outcome"] = "device-absent"
        else:
            result["device_present"] = None
            result["outcome"] = "query-failed"
        return result
    data = result["data"]
    status = data.get("change_host_status", {})
    return {
        "ok": status == {"host_count": 2, "current_host_index": 1},
        "current_host_index": status.get("current_host_index"),
        "host_count": status.get("host_count"),
        "device_present": True,
        "outcome": "present-slot-1" if status == {"host_count": 2, "current_host_index": 1} else "present-wrong-slot",
    }


def check_windows_peer(timeout: float) -> Dict[str, Any]:
    command = [str(WINDOWS_HEALTH_ENTRY), "peer-health"]
    try:
        completed = subprocess.run(
            command,
            check=False,
            timeout=timeout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "ok": False,
            "error": type(error).__name__,
            "detail": str(error),
            "hid_output_report_sent": False,
        }
    try:
        payload = json.loads(completed.stdout)[0] if completed.stdout else {}
    except (json.JSONDecodeError, IndexError, TypeError):
        payload = {}
    evaluated = evaluate_windows_peer_health(payload)
    return {
        "ok": completed.returncode == 0 and evaluated["ok"],
        "returncode": completed.returncode,
        "response": payload,
        "validation": evaluated,
        "hid_output_report_sent": evaluated.get("hid_output_report_sent"),
    }


def evaluate_windows_peer_health(payload: Dict[str, Any], now: Optional[Any] = None) -> Dict[str, Any]:
    current_time = datetime.now(timezone.utc) if now is None else now
    required_fields = (
        "schema",
        "controller",
        "controller_ready",
        "ready",
        "return_ready",
        "desktop",
        "mouse",
        "generated_at_utc",
        "expires_at_utc",
        "hid_output_report_sent",
    )
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return {"ok": False, "reason": "missing-fields", "missing": missing}
    try:
        generated = _parse_timestamp(payload["generated_at_utc"])
        expires = _parse_timestamp(payload["expires_at_utc"])
    except ValueError as error:
        return {"ok": False, "reason": "invalid-timestamp", "error": str(error)}
    if generated.tzinfo is None or expires.tzinfo is None:
        return {"ok": False, "reason": "naive-timestamp"}
    allowed_clock_skew = timedelta(seconds=2)
    if not generated - allowed_clock_skew <= current_time < expires:
        return {"ok": False, "reason": "expired-or-future", "generated_at_utc": payload["generated_at_utc"], "expires_at_utc": payload["expires_at_utc"]}
    mouse = payload.get("mouse") if isinstance(payload.get("mouse"), dict) else {}
    desktop = payload.get("desktop") if isinstance(payload.get("desktop"), dict) else {}
    checks = {
        "schema": payload.get("schema") == 1,
        "controller": payload.get("controller") == "windows-peer-health-v1",
        "controller_ready": payload.get("controller_ready") is True,
        "desktop": desktop.get("available") is True and desktop.get("state") == "INTERACTIVE_DESKTOP_ACCESSIBLE",
        "no_hid_write": payload.get("hid_output_report_sent") is False,
    }
    return_ready = (
        payload.get("return_ready") is True
        and mouse.get("present") is True
        and mouse.get("current_host_index") == 0
        and mouse.get("slot_evidence_verified") is True
    )
    return {
        "ok": all(checks.values()),
        "return_ready": return_ready,
        "checks": checks,
        "hid_output_report_sent": payload.get("hid_output_report_sent"),
    }


def _parse_timestamp(value: Any) -> datetime:
    text = re.sub(r"\.(\d{6})\d+", r".\g<1>", str(value).replace("Z", "+00:00"))
    return datetime.fromisoformat(text)


def submit_mac_switch(python: str, attempt_id: str) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            [str(MAC_SWITCH_ENTRY), attempt_id],
            check=False,
            timeout=12.0,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "ok": False,
            "error": type(error).__name__,
            "detail": str(error),
        }
    try:
        data = json.loads(completed.stdout) if completed.stdout else {}
    except json.JSONDecodeError:
        data = {}
    submit = data.get("switch_report_submit", {})
    submit_error = data.get("switch_submit_error", {})
    attempt_reached = bool(data.get("switch_submit_attempted") or data.get("switch_request_hex"))
    return {
        "ok": completed.returncode == 0 and submit.get("bytes_submitted") == 20 and submit.get("attempt_count") == 1,
        "attempt_reached": attempt_reached,
        "returncode": completed.returncode,
        "bytes_submitted": submit.get("bytes_submitted"),
        "attempt_count": submit.get("attempt_count"),
        "error_type": submit_error.get("error_type"),
        "detail": submit_error.get("detail"),
        "stderr_tail": completed.stderr[-500:],
    }


def _read_mac_slot_locked(python: str, hid_query_lock: threading.Lock) -> Dict[str, Any]:
    with hid_query_lock:
        return read_mac_slot(python)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def apply_mac_slot_poll(
    arbiter: EdgeArbiter,
    status: ControllerStatus,
    slot: Dict[str, Any],
    config: EdgeConfig,
    now_ms: int,
    return_confirmations: int,
    query_failures: int,
) -> Dict[str, Any]:
    previous_state = arbiter.state
    if slot.get("outcome") == "device-absent":
        arbiter.note_mouse_absent(external=arbiter.state == "READY_MAC")
        return_confirmations += 1
        completed_at = arbiter.submit_completed_at
        if (
            arbiter.state == "MOUSE_ABSENT_AFTER_SWITCH"
            and return_confirmations >= config.return_confirmations_required
            and completed_at is not None
            and now_ms - completed_at >= config.switch_stability_ms
        ):
            arbiter.mark_return_target_ready()
        status.update(
            state=arbiter.state,
            ready=False,
            mouse_present=False,
            mouse_current_slot=None,
            poll_outcome="device-absent",
            last_slot_evidence=slot,
            return_confirmations=return_confirmations,
            return_target_ready=arbiter.state == "READY_MAC_RETURN_TARGET",
            recovery_started_at=arbiter.recovery_entered_at,
        )
        return {"state": arbiter.state, "return_confirmations": return_confirmations, "query_failures": 0, "event": "state-changed" if previous_state != arbiter.state else None}

    if not slot.get("ok") and slot.get("device_present") is None:
        query_failures += 1
        recovery = query_failures >= config.query_failure_limit
        if recovery:
            arbiter.mark_recovery_required(at_ms=now_ms)
        status.update(
            state=arbiter.state,
            ready=False,
            mouse_present=None,
            mouse_current_slot=None,
            poll_outcome="query-failed",
            last_slot_evidence=slot,
            return_confirmations=0,
            query_failure_count=query_failures,
            recovery_started_at=arbiter.recovery_entered_at,
        )
        return {"state": arbiter.state, "return_confirmations": 0, "query_failures": query_failures, "event": "state-changed" if previous_state != arbiter.state else None}

    query_failures = 0
    if not slot.get("ok"):
        arbiter.mark_recovery_required(at_ms=now_ms)
        status.update(
            state=arbiter.state,
            ready=False,
            mouse_present=True,
            mouse_current_slot=slot.get("current_host_index"),
            poll_outcome="wrong-slot",
            last_slot_evidence=slot,
            return_confirmations=0,
            recovery_started_at=arbiter.recovery_entered_at,
        )
        return {"state": arbiter.state, "return_confirmations": 0, "query_failures": query_failures, "event": "state-changed" if previous_state != arbiter.state else None}

    if slot.get("current_host_index") != 1:
        arbiter.mark_recovery_required(at_ms=now_ms)
    elif arbiter.state == "READY_MAC":
        pass
    elif arbiter.state == "SWITCHING_TO_WINDOWS":
        completed_at = arbiter.submit_completed_at
        if completed_at is not None and now_ms - completed_at >= config.switch_stability_ms:
            arbiter.mark_recovery_required()
    elif arbiter.state in ("MOUSE_ABSENT_AFTER_SWITCH", "MOUSE_ABSENT_EXTERNAL"):
        return_confirmations += 1
        completed_at = arbiter.submit_completed_at
        required_delay = config.switch_stability_ms if completed_at is not None else config.cooldown_ms
        if (
            return_confirmations >= config.return_confirmations_required
            and (completed_at is None or now_ms - completed_at >= required_delay)
        ):
            arbiter.confirm_mac_slot(1)
        else:
            return_confirmations = min(return_confirmations, config.return_confirmations_required)
    elif arbiter.state == "RECOVERY_REQUIRED":
        if not status.snapshot().get("controller_running"):
            return_confirmations = 0
        else:
            return_confirmations += 1
            recovery_entered_at = arbiter.recovery_entered_at
            stable_for_required_window = (
                recovery_entered_at is None
                or now_ms - recovery_entered_at >= config.switch_stability_ms
            )
            if return_confirmations >= config.return_confirmations_required and stable_for_required_window:
                arbiter.mark_return_ready()
            else:
                return_confirmations = min(return_confirmations, config.return_confirmations_required)
    else:
        return_confirmations = 0

    ready = arbiter.state in ("READY_MAC", "READY_MAC_RETURN_TARGET") and bool(status.snapshot().get("controller_running"))
    status.update(
        state=arbiter.state,
        ready=ready,
        mouse_present=True,
        mouse_current_slot=slot.get("current_host_index"),
        poll_outcome="present-slot-1" if arbiter.state == "READY_MAC" else "present-recovery-candidate",
        last_slot_evidence=slot,
        return_confirmations=return_confirmations,
        query_failure_count=query_failures,
        recovery_started_at=arbiter.recovery_entered_at,
        return_target_ready=arbiter.state == "READY_MAC_RETURN_TARGET",
    )
    return {
        "state": arbiter.state,
        "return_confirmations": return_confirmations,
        "query_failures": query_failures,
        "event": "state-changed" if previous_state != arbiter.state else None,
    }


def poll_mac_state(
    arbiter: EdgeArbiter,
    status: ControllerStatus,
    python: str,
    config: EdgeConfig,
    stop_event: threading.Event,
    hid_query_lock: threading.Lock,
) -> None:
    return_confirmations = 0
    query_failures = 0
    while not stop_event.is_set():
        if not config.state_poll_seconds or stop_event.wait(config.state_poll_seconds):
            break
        with hid_query_lock:
            try:
                slot = read_mac_slot(python)
            except Exception as error:
                slot = {
                    "ok": False,
                    "device_present": None,
                    "outcome": "query-failed",
                    "error": type(error).__name__,
                }
        now_ms = int(time.monotonic() * 1000)
        result = apply_mac_slot_poll(
            arbiter,
            status,
            slot,
            config,
            now_ms,
            return_confirmations,
            query_failures,
        )
        return_confirmations = result["return_confirmations"]
        query_failures = result["query_failures"]
        if result.get("event"):
            print(json.dumps({
                "schema": 1,
                "event": result["event"],
                "utc": utc_now(),
                "state": arbiter.state,
                "poll_outcome": status.snapshot().get("poll_outcome"),
                "hid_write": False,
            }, ensure_ascii=False, separators=(",", ":")), flush=True)


def process_samples(
    samples: "queue.Queue[EdgeSample]",
    arbiter: EdgeArbiter,
    edge_x: float,
    log: AttemptLog,
    python: str,
    dry_run: bool,
    config: EdgeConfig,
    peer_check: Callable[[], Dict[str, Any]],
    status: ControllerStatus,
    hid_query_lock: threading.Lock,
) -> None:
    while True:
        sample = samples.get()
        decision = arbiter.observe(sample, edge_x)
        if not decision.get("trigger"):
            continue
        attempt_id = "auto-edge-" + uuid.uuid4().hex
        record = AttemptRecord(
            attempt_id=attempt_id,
            reason="left-edge-dwell",
            origin_state="READY_MAC",
            target="WINDOWS_SLOT_0",
            current_slot_evidence=None,
            peer_health=None,
            submit_evidence=None,
            submitted_at=None,
            result="rejected",
            recovery="manual-easy-switch-or-m585_switch_to_windows_once",
        )
        slot = (
            {"ok": True, "current_host_index": None, "simulated": True, "meaning": "dry-run did not query HID++"}
            if dry_run
            else _read_mac_slot_locked(python, hid_query_lock)
        )
        record.current_slot_evidence = slot
        status.update(last_slot_evidence=slot)
        if not slot.get("ok"):
            if slot.get("device_present") is False:
                record.result = "mouse-absent-before-submit"
                arbiter.note_mouse_absent(external=True)
                status.update(state=arbiter.state, ready=False, mouse_present=False, mouse_current_slot=None)
            else:
                record.result = "recovery-required"
                arbiter.mark_recovery_required()
                status.update(state=arbiter.state, ready=False, mouse_present=slot.get("device_present"))
            log.append(record)
            continue

        peer = {"ok": True, "simulated": True} if dry_run else peer_check()
        record.peer_health = peer
        status.update(last_peer_health=peer)
        if not peer.get("ok"):
            record.result = "target-unavailable"
            arbiter.mark_target_unavailable()
            status.update(state="TARGET_UNAVAILABLE", ready=False)
            log.append(record)
            continue

        if dry_run:
            record.result = "dry-run-would-switch"
            record.submitted_at = utc_now()
            status.update(state="SWITCHING_TO_WINDOWS", mouse_current_slot=None, ready=False)
            log.append(record)
            continue

        submitted = submit_mac_switch(python, attempt_id)
        record.submit_evidence = submitted
        if submitted.get("ok"):
            arbiter.mark_submit_completed()
        elif submitted.get("attempt_reached"):
            arbiter.mark_submit_completed()
        else:
            arbiter.mark_submit_failed()
        record.submitted_at = utc_now()
        record.result = "submitted" if submitted.get("ok") else ("submit-ambiguous" if submitted.get("attempt_reached") else "submit-failed")
        if not submitted.get("ok"):
            if submitted.get("attempt_reached"):
                status.update(
                    state="SWITCHING_TO_WINDOWS",
                    ready=False,
                    mouse_present=True,
                    mouse_current_slot=None,
                    return_confirmations=0,
                    poll_outcome="awaiting-departure-after-ambiguous-submit",
                    last_submit_completed_monotonic_ms=arbiter.submit_completed_at,
                )
            else:
                status.update(state="RECOVERY_REQUIRED", ready=False, mouse_present=True)
        else:
            status.update(
                state="SWITCHING_TO_WINDOWS",
                mouse_present=True,
                mouse_current_slot=None,
                ready=False,
                return_confirmations=0,
                poll_outcome="awaiting-departure",
                last_submit_completed_monotonic_ms=arbiter.submit_completed_at,
            )
        log.append(record)


def check_environment(python: str, frames: List[Dict[str, Any]], peer_timeout: float, check_peer: bool) -> Dict[str, Any]:
    tap = MacEventTap(queue.Queue())
    sys.path.insert(0, str(SCRIPT_DIR))
    from m585_readonly_probe import enumerate_mouse
    devices = enumerate_mouse()
    vendor_collections = [
        device for device in devices
        if device.get("vendor_id") == 0x046D
        and device.get("product_id") == 0xB01B
        and device.get("usage_page") == 0xFF43
        and device.get("usage") == 0x0202
    ]
    result = {
        "schema": 1,
        "host": "mac",
        "displays": frames,
        "selected_left_edge": choose_left_edge(frames),
        "accessibility_trusted": tap.accessibility_trusted(),
        "listen_only_event_tap_available": tap.event_tap_available(),
        "mouse_entry_present": MAC_SWITCH_ENTRY.is_file(),
        "readonly_probe_present": MAC_READONLY_PROBE.is_file(),
        "mouse_vendor_collection_count": len(vendor_collections),
        "mouse_serials": sorted({device.get("serial_number") for device in vendor_collections}),
        "deskflow_unchanged": True,
    }
    if check_peer:
        result["windows_peer"] = check_windows_peer(peer_timeout)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch the actual left edge of the Mac display and switch M585/M590 once")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-environment", action="store_true", help="perform read-only environment checks")
    mode.add_argument("--watch", action="store_true", help="run the edge controller in the foreground")
    mode.add_argument("--dry-run", action="store_true", help="detect edges and log decisions without HID or peer commands")
    parser.add_argument("--python", default=str(os.environ.get("M585_PYTHON", "python3")))
    parser.add_argument("--display-index", type=int, help="use a specific display from --check-environment; default is the leftmost frame")
    parser.add_argument("--threshold-px", type=int, default=EdgeConfig.threshold_px)
    parser.add_argument("--dwell-ms", type=int, default=EdgeConfig.dwell_ms)
    parser.add_argument("--cooldown-ms", type=int, default=EdgeConfig.cooldown_ms)
    parser.add_argument("--state-poll-seconds", type=float, default=EdgeConfig.state_poll_seconds)
    parser.add_argument("--switch-stability-ms", type=int, default=EdgeConfig.switch_stability_ms)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--lock-path", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--peer-timeout", type=float, default=EdgeConfig.peer_check_timeout_seconds)
    parser.add_argument("--check-peer", action="store_true", help="include the Windows offline health check in environment output")
    parser.add_argument("--health-bind", default="0.0.0.0")
    parser.add_argument("--health-port", type=int, default=8787)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frames = DisplayEnumerator().frames()
    if args.check_environment:
        print(json.dumps(check_environment(args.python, frames, args.peer_timeout, args.check_peer), ensure_ascii=False, indent=2))
        return

    edge_x = choose_left_edge(frames, args.display_index)
    config = EdgeConfig(
        threshold_px=args.threshold_px,
        dwell_ms=args.dwell_ms,
        cooldown_ms=args.cooldown_ms,
        state_poll_seconds=args.state_poll_seconds,
        switch_stability_ms=args.switch_stability_ms,
        peer_check_timeout_seconds=args.peer_timeout,
    )
    hid_query_lock = threading.Lock()
    stop_event = threading.Event()
    samples: "queue.Queue[EdgeSample]" = queue.Queue()
    arbiter = EdgeArbiter(config, lambda: int(time.monotonic() * 1000))
    log = AttemptLog(args.log_path)
    status = ControllerStatus()
    if args.dry_run:
        status.update(state="READY_MAC", mouse_current_slot=None, ready=False, poll_outcome="dry-run", last_slot_evidence={"simulated": True})
    else:
        startup_slot = read_mac_slot(args.python)
        status.update(last_slot_evidence=startup_slot)
        if startup_slot.get("ok"):
            arbiter.confirm_mac_slot(int(startup_slot["current_host_index"]))
            status.update(state="READY_MAC", mouse_present=True, mouse_current_slot=1, ready=False)
        elif startup_slot.get("device_present") is False:
            arbiter.note_mouse_absent(external=True)
            status.update(state=arbiter.state, mouse_present=False, ready=False)
        else:
            arbiter.mark_recovery_required()
            status.update(state="RECOVERY_REQUIRED", ready=False)
    with ControllerLock(args.lock_path):
        print(json.dumps({
            "schema": 1,
            "event": "controller-started",
            "mode": "dry-run" if args.dry_run else "watch",
            "edge_x": edge_x,
            "config": asdict(config),
            "stop": "Ctrl+C",
            "manual_to_windows": str(MAC_SWITCH_ENTRY) + " <new-attempt-id>",
            "deskflow_unchanged": True,
        }, ensure_ascii=False), flush=True)
        worker = threading.Thread(
            target=process_samples,
            args=(samples, arbiter, edge_x, log, args.python, args.dry_run, config, lambda: check_windows_peer(config.peer_check_timeout_seconds), status, hid_query_lock),
            daemon=True,
        )
        worker.start()
        if not args.dry_run:
            state_poll_thread = threading.Thread(
                target=poll_mac_state,
                args=(arbiter, status, args.python, config, stop_event, hid_query_lock),
                daemon=True,
            )
            state_poll_thread.start()
        try:
            health = HealthServer(args.health_bind, args.health_port, status)
        except OSError as error:
            stop_event.set()
            print(json.dumps({
                "schema": 1,
                "event": "health-bind-failed",
                "bind": args.health_bind,
                "port": args.health_port,
                "error": str(error),
                "ready": False,
            }, ensure_ascii=False), flush=True)
            return
        health_thread = threading.Thread(target=health.serve, daemon=True)
        health_thread.start()
        event_tap = MacEventTap(samples)
        event_tap.on_running = lambda: _mark_controller_running(
            status,
            arbiter,
            args.dry_run,
        )
        try:
            event_tap.run()
        finally:
            stop_event.set()
            health.stop()


def _mark_controller_running(status: ControllerStatus, arbiter: EdgeArbiter, dry_run: bool) -> None:
    snapshot = status.snapshot()
    ready = (
        not dry_run
        and arbiter.state in ("READY_MAC", "READY_MAC_RETURN_TARGET")
        and (
            arbiter.state == "READY_MAC_RETURN_TARGET"
            or (
                snapshot.get("mouse_current_slot") == 1
                and bool(snapshot.get("last_slot_evidence", {}).get("ok"))
            )
        )
    )
    status.update(controller_running=True, ready=ready)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(json.dumps({
            "schema": 1,
            "event": "controller-stopped",
            "reason": "sigint-ctrl-c",
            "ready": False,
        }, ensure_ascii=False), flush=True)
