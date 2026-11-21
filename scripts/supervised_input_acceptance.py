#!/usr/bin/env python3
"""Use a visible Windows editor and benign clipboard probes for live acceptance."""

import argparse
import base64
import ctypes
import hashlib
import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KEYBOARD_TEXT = "CrossInput Abc 123"
MODIFIER_TEXT = "Z"
CLIPBOARD_PROBES = (
    "Cross Input 中文 English",
    "first line\nsecond line\t123",
    "x" * (256 * 1024),
)


class CGEvent(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class MacKeyInjector:
    def __init__(self):
        self.cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        self.cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        self.cg.CGEventCreate.restype = ctypes.c_void_p
        self.cg.CGEventCreate.argtypes = [ctypes.c_void_p]
        self.cg.CGEventPost.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        self.cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.keycodes = {"return": 36, "leftshift": 56, "rightshift": 60}
        self.keycodes.update({character: code for character, code in zip("abcdefghijklmnopqrstuvwxyz", (0, 11, 8, 2, 14, 3, 5, 4, 34, 38, 40, 37, 46, 45, 31, 35, 12, 15, 1, 17, 32, 9, 13, 7, 16, 6))})
        self.keycodes.update({character: code for character, code in zip("1234567890", (18, 19, 20, 21, 23, 22, 26, 28, 25, 29))})
        self.keycodes["space"] = 49

    def key(self, name, pressed, flags=0):
        source = self.cg.CGEventCreate(None)
        event = self.cg.CGEventCreateKeyboardEvent(source, self.keycodes[name], pressed)
        self.cg.CGEventSetFlags(event, flags)
        self.cg.CGEventPost(0, event)
        self.cf.CFRelease(event)
        self.cf.CFRelease(source)

    def text(self, text):
        for character in text:
            name = "space" if character == " " else character.lower()
            flags = 0x20000 if character.isupper() else 0
            if flags:
                self.key("leftshift", True, flags)
            self.key(name, True, flags)
            self.key(name, False, flags)
            if flags:
                self.key("leftshift", False)


class LiveAcceptance:
    def __init__(self, alias, evidence):
        self.alias = alias
        self.evidence = evidence
        self.environment = {**__import__("os").environ, "M585_SSH_ALIAS": alias}
        self.remote = r"%TEMP%\MiniOpsM585Edge"

    def run(self, command, timeout=15, check=True):
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=self.environment)
        if check and result.returncode:
            raise RuntimeError("command failed: " + result.stderr[-500:])
        return result

    def powershell(self, script, timeout=15):
        return self.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", self.alias, "powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)

    def windows_clipboard(self, text=None):
        command = "from text_clipboard_sync import WindowsClipboard; import base64; print(base64.b64encode(WindowsClipboard().get().encode()).decode())" if text is None else "from text_clipboard_sync import WindowsClipboard; import sys; WindowsClipboard().set(sys.stdin.buffer.read().decode())"
        process = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", self.alias, "cmd", "/c", "cd /d %TEMP%\\MiniOpsM585Edge && D:\\Apps\\Python\\cpython-3.12.15-windows-x86_64-none\\python.exe -c \"" + command + "\""], input=None if text is None else text.encode(), capture_output=True, timeout=15)
        if process.returncode:
            raise RuntimeError("Windows clipboard adapter failed")
        if text is None:
            return base64.b64decode(process.stdout.strip()).decode("utf-8")

    def windows_health(self):
        result = self.run([str(ROOT / "scripts/run_windows_hid_protocol_probe.sh"), "peer-health"], timeout=20)
        payload = json.loads(result.stdout)
        return payload[0] if isinstance(payload, list) else payload

    def mac_health(self):
        with socket.create_connection(("127.0.0.1", 8787), 2) as connection:
            connection.sendall(b"\n")
            connection.settimeout(2)
            return json.loads(connection.recv(8192))

    def wait(self, predicate, seconds=30):
        deadline = time.monotonic() + seconds
        latest = None
        while time.monotonic() < deadline:
            latest = predicate()
            if latest:
                return latest
            time.sleep(0.25)
        raise TimeoutError("live acceptance condition not reached: " + repr(latest)[:500])

    def prepare(self):
        if self.mac_health().get("state") != "READY_MAC":
            raise RuntimeError("Mac mouse controller is not ready")
        self.run([str(ROOT / "scripts/start_windows_m585_edge_from_ssh.sh"), "status"], timeout=20)

    def go_windows(self):
        self.post_mac_pointer(100, 450)
        time.sleep(0.15)
        self.post_mac_pointer(0, 450)
        return self.wait(lambda: self.windows_health().get("return_ready") is True)

    def go_mac(self):
        self.run([str(ROOT / "scripts/start_windows_m585_edge_from_ssh.sh"), "register-start", "pointer-test"], timeout=25)
        time.sleep(2.5)
        return self.wait(lambda: self.mac_health().get("state") == "READY_MAC" and self.mac_health().get("mouse_current_slot") == 1)

    def post_mac_pointer(self, x, y):
        cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGEvent, ctypes.c_uint32]
        cg.CGEventPost.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        event = cg.CGEventCreateMouseEvent(None, 5, CGEvent(x, y), 0)
        cg.CGEventPost(0, event)
        cf.CFRelease(event)

    def keyboard(self):
        self.go_windows()
        self.powershell("Remove-Item -LiteralPath ($env:TEMP + '\\MiniOpsM585Edge\\keyboard-acceptance.ready') -Force -ErrorAction SilentlyContinue")
        self.powershell("Start-ScheduledTask -TaskName MiniOpsKeyboardAcceptance")
        self.wait(lambda: self.powershell("Test-Path -LiteralPath ($env:TEMP + '\\MiniOpsM585Edge\\keyboard-acceptance.ready')").stdout.strip().lower() == "true")
        time.sleep(0.5)
        injector = MacKeyInjector()
        injector.text(KEYBOARD_TEXT)
        injector.key("return", True)
        injector.key("return", False)
        injector.key("leftshift", True)
        injector.key("rightshift", True)
        injector.key("leftshift", False)
        injector.text(MODIFIER_TEXT)
        injector.key("rightshift", False)
        injector.key("return", True)
        injector.key("return", False)
        self.powershell("Stop-ScheduledTask -TaskName MiniOpsKeyboardAcceptance")
        time.sleep(0.5)
        state = self.powershell("(Get-ScheduledTask -TaskName MiniOpsKeyboardAcceptance).State.value__")
        if state.stdout.strip() == "4":
            raise RuntimeError("Windows keyboard target did not close")
        result = self.powershell("[Convert]::ToBase64String([IO.File]::ReadAllBytes($env:TEMP + '\\MiniOpsM585Edge\\keyboard-acceptance.txt'))")
        actual = base64.b64decode(result.stdout.strip()).decode("utf-8")
        expected = KEYBOARD_TEXT + "\r\n" + MODIFIER_TEXT + "\r\n"
        if actual != expected:
            raise RuntimeError("Windows keyboard text differs from the benign probe")
        self.go_mac()
        return {"keyboard_text_sha256": hashlib.sha256(actual.encode()).hexdigest(), "characters": len(actual), "modifier_release_verified": True}

    def register_keyboard_target(self):
        self.run(["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", str(ROOT / "scripts/windows_keyboard_target.ps1"), self.alias + ":" + self.remote + "/"])
        script = "$root=Join-Path $env:TEMP 'MiniOpsM585Edge'; $a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -STA -ExecutionPolicy Bypass -File \"' + (Join-Path $root 'windows_keyboard_target.ps1') + '\" -ResultFile \"' + (Join-Path $root 'keyboard-acceptance.txt') + '\" -ReadyFile \"' + (Join-Path $root 'keyboard-acceptance.ready') + '\"'); $p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive; Register-ScheduledTask -TaskName MiniOpsKeyboardAcceptance -Action $a -Principal $p -Force | Out-Null"
        self.powershell(script)

    def clipboard(self):
        self.register_keyboard_target()
        for name in ("keyboard", "clipboard"):
            self.powershell("& $env:TEMP\\MiniOpsM585Edge\\windows_auxiliary_task_controller.ps1 -Operation start -Service " + name)
        time.sleep(1)
        records = []
        original_mac = subprocess.run(["pbpaste"], capture_output=True, check=True).stdout.decode()
        original_windows = self.windows_clipboard()
        try:
            for text in CLIPBOARD_PROBES:
                for source, destination in (("mac", "windows"), ("windows", "mac")):
                    if source == "mac":
                        subprocess.run(["pbcopy"], input=text.encode(), check=True)
                    else:
                        self.windows_clipboard(text)
                    if destination == "windows":
                        received = lambda: self.windows_clipboard() == text
                    else:
                        received = lambda: subprocess.run(["pbpaste"], capture_output=True, check=True).stdout.decode() == text
                    self.wait(received)
                    records.append({"source": source, "destination": destination, "bytes": len(text.encode()), "sha256": hashlib.sha256(text.encode()).hexdigest()})
            return records
        finally:
            subprocess.run(["pbcopy"], input=original_mac.encode(), check=True)
            self.windows_clipboard(original_windows)
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--alias", default="Administrator@192.168.1.8")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    acceptance = LiveAcceptance(args.alias, args.output)
    try:
        acceptance.prepare()
        acceptance.register_keyboard_target()
        if args.prepare_only:
            return
        records = {"keyboard": acceptance.keyboard(), "clipboard": acceptance.clipboard(), "attempt": uuid.uuid4().hex}
        args.output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
    finally:
        acceptance.powershell("Stop-ScheduledTask -TaskName MiniOpsKeyboardAcceptance -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName MiniOpsKeyboardAcceptance -Confirm:$false -ErrorAction SilentlyContinue", timeout=10)
        subprocess.run([sys.executable, str(ROOT / "scripts/cross_input_control.py"), "stop"], cwd=ROOT, timeout=40)


if __name__ == "__main__":
    main()
