#!/usr/bin/env python3
"""One reversible entry for mouse, keyboard and clipboard controllers."""

import argparse
import json
import os
import signal
import socket
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("CROSS_INPUT_RUNTIME", str(Path.home() / ".config/miniops/cross-input-runtime")))
MAC_PLIST = Path.home() / "Library/LaunchAgents/org.deskflow.deskflow.server.plist"
DOMAIN = f"gui/{os.getuid()}"
PYTHON = os.environ.get("M585_PYTHON", str(ROOT / "research/mouse/venv/bin/python"))
SERVICES = {
    "mouse": [PYTHON, str(ROOT / "scripts/m585_edge_controller.py"), "--watch"],
    "keyboard": [PYTHON, str(ROOT / "scripts/mac_keyboard_forwarder.py"), "--host", os.environ.get("M585_WINDOWS_IP", "192.168.1.8"), "--secret-file", os.environ.get("M585_KEYBOARD_SECRET", str(Path.home() / ".config/miniops/cross-input-keyboard.secret"))],
    "clipboard": [sys.executable, str(ROOT / "scripts/text_clipboard_sync.py"), "--host", "mac", "--listen", os.environ.get("M585_MAC_IP", "192.168.1.4"), "--peer", os.environ.get("M585_WINDOWS_IP", "192.168.1.8"), "--secret-file", os.environ.get("M585_CLIPBOARD_SECRET", str(Path.home() / ".config/miniops/cross-input-clipboard.secret"))],
}
REMOTE_SERVICES = {
    "keyboard": "keyboard",
    "clipboard": "clipboard",
}


def emit(event, **data):
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def pid_path(name):
    return RUNTIME / (name + ".pid")


def running(name):
    try:
        raw = pid_path(name).read_text()
        record = json.loads(raw)
        if isinstance(record, int):
            return None
        pid = int(record["pid"])
        started_at = datetime.fromisoformat(record["started_at"]).timestamp()
        os.kill(pid, 0)
        process_info = subprocess.run(["ps", "-p", str(pid), "-o", "lstart=,command="], capture_output=True, text=True)
        if process_info.returncode or record["command"][1] not in process_info.stdout:
            return None
        if time.time() + 2 < started_at:
            return None
        return pid
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        pid_path(name).unlink(missing_ok=True)
        return None


def record_process(name, process):
    pid_path(name).write_text(json.dumps({"pid": process.pid, "started_at": datetime.now(timezone.utc).isoformat(), "command": process.args}))


def terminate_processes():
    for name in SERVICES:
        pid = running(name)
        if pid:
            try: os.kill(pid, signal.SIGTERM)
            except ProcessLookupError: pass
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(running(name) for name in SERVICES):
        time.sleep(0.05)
    for name in SERVICES:
        pid = running(name)
        if pid:
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass
        pid_path(name).unlink(missing_ok=True)


def start():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    secret_dir = Path.home() / ".config/miniops"
    secret_dir.mkdir(parents=True, exist_ok=True)
    for secret_name in ("cross-input-keyboard.secret", "cross-input-clipboard.secret"):
        secret = secret_dir / secret_name
        if not secret.exists():
            secret.write_bytes(secrets.token_bytes(32))
            secret.chmod(0o600)
    subprocess.run(["launchctl", "bootout", DOMAIN + "/org.deskflow.deskflow.server"], capture_output=True)
    windows_alias = os.environ.get("M585_SSH_ALIAS", "Administrator@192.168.1.8")
    windows = subprocess.run([str(ROOT / "scripts/start_windows_m585_edge_from_ssh.sh"), "register-start", "watch"], cwd=ROOT,
                             env={**os.environ, "M585_SSH_ALIAS": windows_alias}, capture_output=True, text=True, timeout=30)
    if windows.returncode:
        subprocess.run(["launchctl", "bootstrap", DOMAIN, str(MAC_PLIST)], capture_output=True)
        raise RuntimeError("Windows controller failed to start; Deskflow restored")
    for name in REMOTE_SERVICES:
        source = secret_dir / ("cross-input-" + name + ".secret")
        destination = windows_alias + ":C:/Users/Administrator/AppData/Local/Temp/MiniOpsM585Edge/" + name + ".secret"
        subprocess.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=5", str(source), destination], check=True, timeout=12)
    for service in REMOTE_SERVICES.values():
        controller = ["ssh", "-o", "ConnectTimeout=5", windows_alias, "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "%TEMP%\\MiniOpsM585Edge\\windows_auxiliary_task_controller.ps1", "-Service", service]
        subprocess.run(controller + ["-Operation", "register"], capture_output=True, check=True, timeout=12)
        remote = subprocess.run(controller + ["-Operation", "start"], capture_output=True, timeout=10)
        if remote.returncode:
            terminate_processes()
            subprocess.run(["launchctl", "bootstrap", DOMAIN, str(MAC_PLIST)], capture_output=True)
            raise RuntimeError(service + " Windows service failed to start; Deskflow restored")
    try:
        for name, command in SERVICES.items():
            if running(name):
                continue
            log = (RUNTIME / (name + ".log")).open("a")
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            record_process(name, process)
            time.sleep(0.4)
            if process.poll() is not None:
                raise RuntimeError(name + " exited at startup; inspect " + str(RUNTIME / (name + ".log")))
            emit("started", service=name, pid=process.pid)
    except Exception:
        terminate_processes()
        subprocess.run(["launchctl", "bootstrap", DOMAIN, str(MAC_PLIST)], capture_output=True)
        raise
    status()


def stop():
    terminate_processes()
    for name in SERVICES:
        emit("stopped", service=name)
    if MAC_PLIST.exists():
        subprocess.run(["launchctl", "bootstrap", DOMAIN, str(MAC_PLIST)], capture_output=True)
    windows_alias = os.environ.get("M585_SSH_ALIAS", "Administrator@192.168.1.8")
    try:
        subprocess.run([str(ROOT / "scripts/start_windows_m585_edge_from_ssh.sh"), "stop"], cwd=ROOT,
                       env={**os.environ, "M585_SSH_ALIAS": windows_alias}, capture_output=True, timeout=10)
        for service in REMOTE_SERVICES.values():
            subprocess.run(["ssh", "-o", "ConnectTimeout=5", windows_alias, "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "%TEMP%\\MiniOpsM585Edge\\windows_auxiliary_task_controller.ps1", "-Operation", "stop", "-Service", service], capture_output=True, timeout=8)
    except (OSError, subprocess.SubprocessError) as error:
        emit("remote-stop-unavailable", reason=type(error).__name__)
    emit("deskflow-restore-requested")


def recover():
    """Force input back to Mac even when the peer is unavailable."""
    terminate_processes()
    script = ROOT / "scripts/run_windows_hid_protocol_probe.sh"
    alias = os.environ.get("M585_SSH_ALIAS", "Administrator@192.168.1.8")
    try:
        result = subprocess.run([str(script), "mouse-switch-mac-once"], cwd=ROOT, env={**os.environ, "M585_SSH_ALIAS": alias}, capture_output=True, text=True, timeout=18)
        if result.returncode:
            emit("recovery-needs-easy-switch", detail="Press the mouse Easy-Switch button to select Mac")
        else:
            emit("recovery-requested")
    except (OSError, subprocess.SubprocessError):
        emit("recovery-needs-easy-switch", detail="Press the mouse Easy-Switch button to select Mac")
    if MAC_PLIST.exists():
        subprocess.run(["launchctl", "bootstrap", DOMAIN, str(MAC_PLIST)], capture_output=True)


def status_window():
    import tkinter
    root = tkinter.Tk()
    root.title("Cross Input")
    root.geometry("360x210")
    root.resizable(False, False)
    label = tkinter.Label(root, font=("Helvetica", 13), justify="left", padx=24, pady=18)
    label.pack(fill="both", expand=True)
    def refresh():
        active = "Unknown"
        try:
            with socket.create_connection(("127.0.0.1", 8787), 0.2) as connection:
                connection.settimeout(0.2)
                connection.sendall(b"\n")
                mouse = json.loads(connection.recv(8192))
            active = "Windows" if mouse.get("return_target_ready") else "Mac"
        except (OSError, ValueError):
            pass
        label["text"] = f"Active computer: {active}\n" + "\n".join(f"{name.title()}: {'Running' if running(name) else 'Stopped'}" for name in SERVICES)
        root.after(1500, refresh)
    def shutdown():
        stop()
        root.destroy()
    refresh()
    controls = tkinter.Frame(root, padx=16, pady=12)
    controls.pack(fill="x")
    tkinter.Button(controls, text="Start", command=start).pack(side="left", expand=True)
    tkinter.Button(controls, text="Stop & Restore Deskflow", command=shutdown).pack(side="right", expand=True)
    tkinter.Button(root, text="Recover mouse to Mac", command=recover).pack(fill="x", padx=16, pady=4)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


def status():
    recent = {}
    for name in SERVICES:
        try:
            recent[name] = (RUNTIME / (name + ".log")).read_text(errors="replace").splitlines()[-1][:600]
        except OSError:
            recent[name] = None
    emit("status", services={name: running(name) for name in SERVICES}, recent_status=recent, runtime=str(RUNTIME))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "stop", "status", "gui", "recover"))
    args = parser.parse_args()
    {"start": start, "stop": stop, "status": status, "gui": status_window, "recover": recover}[args.action]()


if __name__ == "__main__":
    main()
