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


def windows_health(environment):
    result = subprocess.run([str(ROOT / "scripts/run_windows_hid_protocol_probe.sh"), "peer-health"], env=environment, capture_output=True, text=True, timeout=15)
    data = json.loads(result.stdout)
    return data[0] if isinstance(data, list) else data


def move_windows_pointer(environment, x, y):
    result = subprocess.run([str(ROOT / "scripts/start_windows_m585_edge_from_ssh.sh"), "start", "pointer-test"], env=environment, capture_output=True, timeout=12)
    if result.returncode:
        raise RuntimeError("Windows pointer injection failed")


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
    started = time.monotonic()
    for index in range(rounds):
        attempt = "acceptance-" + uuid.uuid4().hex
        wait_for(lambda: ((h := health()).get("state") == "READY_MAC" and h.get("mouse_current_slot") == 1, h), 25)
        post_pointer(100, 450)
        time.sleep(0.3)
        post_pointer(0, 450)
        time.sleep(1)
        post_pointer(0, 450)
        windows = wait_for(lambda: ((h := windows_health(environment)).get("return_ready") is True, h), 25)
        records.append({"round": index + 1, "attempt": attempt, "to_windows": windows})
        move_windows_pointer(environment, 100000, 450)
        returned = wait_for(lambda: ((h := health()).get("state") == "READY_MAC" and h.get("mouse_current_slot") == 1, h), 30)
        records[-1]["to_mac"] = returned
        records[-1]["seconds"] = round(time.monotonic() - started, 3)
        log_path = ROOT / "logs/m585-edge-events.jsonl"
        records[-1]["mac_attempts"] = [json.loads(line) for line in log_path.read_text().splitlines() if "auto-edge" in line][-2:]
        remote_log = subprocess.run(["ssh", "-o", "ConnectTimeout=5", environment["M585_SSH_ALIAS"], "powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-Content ($env:TEMP + '\\MiniOpsM585Edge\\logs\\m585-edge-watch.jsonl') -Tail 30"], capture_output=True, text=True, timeout=10)
        records[-1]["windows_events"] = [line for line in remote_log.stdout.splitlines() if '"event"' in line][-8:]
        if not any('"switch-submitted"' in line and '"target":"MAC_SLOT_1"' in line for line in records[-1]["windows_events"]):
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
