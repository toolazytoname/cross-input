#!/usr/bin/env python3
"""Bounded hardware round-trip acceptance with auditable per-hop evidence."""

import argparse
import ctypes
import json
import socket
import subprocess
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def health():
    with socket.create_connection(("127.0.0.1", 8787), 2) as connection:
        connection.settimeout(2)
        connection.sendall(b"\n")
        return json.loads(connection.recv(8192))


def windows_desktop_ready(environment):
    command = "Add-Type -AssemblyName System.Windows.Forms; if([Environment]::UserInteractive){'interactive'}else{exit 1}"
    return subprocess.run(["ssh", "-o", "ConnectTimeout=5", environment["M585_SSH_ALIAS"], "powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, timeout=10)


def mac_attempts():
    path = ROOT / "logs/m585-edge-events.jsonl"
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text().splitlines() if "attempt_id" in line]


def windows_events(environment):
    result = subprocess.run(["ssh", "-o", "ConnectTimeout=5", environment["M585_SSH_ALIAS"], "powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-Content ($env:TEMP + '\\MiniOpsM585Edge\\logs\\m585-edge-watch.jsonl') -Tail 30"], capture_output=True, text=True, timeout=10)
    return [line for line in result.stdout.splitlines() if '"event"' in line]


def event_identity(line):
    try:
        return json.loads(line).get("attempt_id")
    except (ValueError, TypeError):
        return None


def windows_health(environment):
    result = subprocess.run([str(ROOT / "scripts/run_windows_hid_protocol_probe.sh"), "peer-health"], env=environment, capture_output=True, text=True, timeout=15)
    data = json.loads(result.stdout)
    return data[0] if isinstance(data, list) else data


def move_windows_pointer(environment, x, y):
    result = subprocess.run([str(ROOT / "scripts/start_windows_m585_edge_from_ssh.sh"), "start", "pointer-test"], env=environment, capture_output=True, timeout=12)
    if result.returncode:
        raise RuntimeError("Windows pointer injection failed")


def drain_pointer_events(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(min(0.2, deadline - time.monotonic()))


def post_pointer(x, y):
    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
    cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    cg.CGEventCreate.argtypes = [ctypes.c_void_p]
    cg.CGEventCreate.restype = ctypes.c_void_p
    source = cg.CGEventCreate(None)
    event = cg.CGEventCreateMouseEvent(source, 5, CGPoint(x, y), 0)
    cg.CGEventPost(0, event)


def wait_for(predicate, seconds):
    deadline = time.monotonic() + seconds
    latest = None
    while time.monotonic() < deadline:
        latest = predicate()
        if latest[0]: return latest[1]
        time.sleep(0.5)
    raise TimeoutError(json.dumps(latest[1]))


def run(rounds, output):
    import os
    environment = {**os.environ, "M585_SSH_ALIAS": os.environ.get("M585_SSH_ALIAS", "Administrator@192.168.1.8")}
    records = []
    if rounds < 1 or rounds > 50:
        raise ValueError("rounds must be between 1 and 50")
    started = time.monotonic()
    for index in range(rounds):
        mac_event_ids_before = {item.get("attempt_id") for item in mac_attempts()}
        windows_event_ids_before = {event_identity(line) for line in windows_events(environment)}
        mac_before = len(mac_attempts())
        windows_before = len(windows_events(environment))
        attempt = "acceptance-" + uuid.uuid4().hex
        wait_for(lambda: ((h := health()).get("state") == "READY_MAC" and h.get("mouse_current_slot") == 1, h), 25)
        desktop = windows_desktop_ready(environment)
        if desktop.returncode:
            raise RuntimeError("Windows desktop is not available for supervised acceptance")
        if b"interactive" not in desktop.stdout:
            raise RuntimeError("Windows session is not interactive")
        post_pointer(100, 450)
        time.sleep(0.25)
        post_pointer(0, 450)
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            post_pointer(0, 450)
            time.sleep(0.05)
        windows = wait_for(lambda: ((h := windows_health(environment)).get("return_ready") is True, h), 25)
        records.append({"round": index + 1, "attempt": attempt, "to_windows": windows})
        move_windows_pointer(environment, 100000, 450)
        returned = wait_for(lambda: ((h := health()).get("state") == "READY_MAC" and h.get("mouse_current_slot") == 1, h), 30)
        new_mac_attempts = [item for item in records[-1]["mac_attempts"] if item.get("attempt_id") not in mac_event_ids_before]
        records[-1]["mac_attempts"] = new_mac_attempts
        records[-1]["to_mac"] = returned
        records[-1]["seconds"] = round(time.monotonic() - started, 3)
        records[-1]["mac_state"] = returned
        records[-1]["mac_attempts"] = [item for item in mac_attempts()[mac_before:] if item.get("attempt_id") not in mac_event_ids_before]
        records[-1]["windows_events"] = windows_events(environment)[windows_before:]
        if sum(1 for item in records[-1]["mac_attempts"] if item.get("result") == "submitted") != 1:
            raise RuntimeError("Round did not produce exactly one Mac-to-Windows submission")
        if not any('"switch-submitted"' in line and '"target":"MAC_SLOT_1"' in line and event_identity(line) not in windows_event_ids_before for line in records[-1]["windows_events"]):
            raise RuntimeError("Mac slot returned without an auditable Windows-to-Mac submission")
        output.write(json.dumps(records[-1], ensure_ascii=False) + "\n")
        output.flush()
        time.sleep(6)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("a") as stream:
        run(args.rounds, stream)
