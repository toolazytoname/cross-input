#!/usr/bin/env python3
"""Verify peer loss and sleep recovery without automatic wake or blind input switching."""

import argparse
import json
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def probe(alias):
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", alias, "hostname"], capture_output=True, text=True, timeout=8)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--alias", default="Administrator@192.168.1.8")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wait-offline", type=int, default=90)
    parser.add_argument("--wait-online", type=int, default=90)
    parser.add_argument("--request-sleep", action="store_true")
    args = parser.parse_args()
    if args.request_sleep and not probe(args.alias):
        raise SystemExit("Windows must be online before sleep testing")
    if args.request_sleep:
        subprocess.run(["ssh", args.alias, "cmd", "/c", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"], capture_output=True, timeout=8)
    started = time.monotonic()
    offline = False
    while time.monotonic() - started < args.wait_offline:
        if not probe(args.alias):
            offline = True
            break
        time.sleep(1)
    while offline and time.monotonic() - started < args.wait_online:
        if probe(args.alias):
            args.output.write_text(json.dumps({"event": "sleep-recovered", "seconds": round(time.monotonic() - started, 3), "at": datetime.now(timezone.utc).isoformat()}) + "\n")
            return
        time.sleep(1)
    raise SystemExit("Windows did not complete the observed sleep/recovery cycle")


if __name__ == "__main__":
    main()
