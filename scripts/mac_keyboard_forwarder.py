#!/usr/bin/env python3
"""Capture K94 keys only while Windows owns the mouse channel."""

import argparse
import ctypes
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keyboard_protocol import KeySender


MAC_TO_KEY = {
    12: "q", 13: "w", 14: "e", 15: "r", 17: "t", 16: "y", 32: "u", 34: "i", 31: "o", 35: "p",
    0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x", 8: "c", 9: "v", 11: "b",
    45: "n", 46: "m", 38: "j", 40: "k", 37: "l", 33: "leftbracket", 30: "rightbracket",
    42: "backslash", 41: "semicolon", 39: "quote", 43: "comma", 47: "period", 44: "slash", 50: "grave",
    27: "minus", 24: "equal", 18: "1", 19: "2", 20: "3", 21: "4", 23: "5", 22: "6", 26: "7", 28: "8", 25: "9", 29: "0",
    36: "return", 48: "tab", 53: "escape", 51: "backspace", 117: "delete", 49: "space",
    123: "left", 124: "right", 126: "up", 125: "down", 115: "home", 119: "end", 116: "pageup", 121: "pagedown",
    57: "capslock", 122: "f1", 120: "f2", 99: "f3", 118: "f4", 96: "f5", 97: "f6", 98: "f7", 100: "f8", 101: "f9", 109: "f10", 103: "f11", 111: "f12",
}


class KeyboardState:
    def __init__(self, health_url: str):
        self.health_url = health_url
        self.remote = False
        self.last_check = 0.0
        self.last_error = None

    def update(self, now: float) -> bool:
        if now - self.last_check < 0.2:
            return self.remote
        self.last_check = now
        try:
            with socket.create_connection(("127.0.0.1", 8787), 0.3) as connection:
                connection.settimeout(0.3)
                connection.sendall(b"\n")
                health = json.loads(connection.recv(8192))
            self.remote = health.get("state") == "READY_MAC_RETURN_TARGET" and health.get("mouse_present") is False and health.get("return_target_ready") is True
            self.last_error = None
        except (OSError, ValueError):
            self.remote = False
            self.last_error = "peer-unavailable"
        return self.remote

    def release_if_returned(self) -> bool:
        if self.remote and not self.update(time.monotonic()):
            self.remote = False
            self.last_check = 0
            return True
        return False


class MacKeyTap:
    def __init__(self, sender: KeySender, state: KeyboardState):
        self.sender = sender
        self.state = state
        self.down = set()
        self.remote_keys_down = False
        self.cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        self.cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        self.callback_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
        self.cg.CGEventTapCreate.restype = ctypes.c_void_p
        self.cg.CGEventTapCreate.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_void_p]
        self.cg.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.cg.CGEventGetIntegerValueField.restype = ctypes.c_int64
        self.cg.CGEventGetFlags.argtypes = [ctypes.c_void_p]
        self.cg.CGEventGetFlags.restype = ctypes.c_uint64
        self.cf.CFMachPortCreateRunLoopSource.restype = ctypes.c_void_p
        self.cf.CFMachPortCreateRunLoopSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        self.cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        self.cf.CFRunLoopGetCurrent.argtypes = []
        self.cf.CFRunLoopAddSource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.cf.CFRunLoopAddTimer.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.cf.CFRunLoopTimerCreate.restype = ctypes.c_void_p
        self.cf.CFRunLoopTimerCreate.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_void_p]
        self.cf.CFAbsoluteTimeGetCurrent.restype = ctypes.c_double
        self.cf.CFAbsoluteTimeGetCurrent.argtypes = []
        self.cf.CFRunLoopRun.argtypes = []

    def release_all(self):
        if self.down or self.remote_keys_down:
            try: self.sender.send("release_all")
            except OSError: pass
            self.down.clear()
            self.remote_keys_down = False

    def forward(self, key, pressed, flags=0):
        """Send only while Windows is active; never consume on transport failure."""
        if not self.state.update(time.monotonic()):
            self.release_all()
            return False
        try:
            self.sender.send("key", key, pressed, flags)
            self.remote_keys_down = True
            if pressed:
                self.down.add(key)
            else:
                self.down.discard(key)
            return True
        except OSError:
            self.release_all()
            self.state.remote = False
            self.state.last_check = 0
            return False

    def callback(self, proxy, event_type, event, refcon):
        if event_type in (0xFFFFFFFE, 0xFFFFFFFF):
            return event
        code = self.cg.CGEventGetIntegerValueField(event, 9)
        flags = self.cg.CGEventGetFlags(event)
        if event_type in (12, 0xFFFFFFFE, 0xFFFFFFFF):
            if self.state.release_if_returned():
                self.release_all()
            return event
        if flags & 0x00000010:
            return event
        key = MAC_TO_KEY.get(code)
        is_modifier = code in (54, 55, 56, 58, 59, 60, 61, 62)
        if is_modifier:
            key = {54: "command", 55: "command", 56: "shift", 58: "option", 59: "control", 60: "shift", 61: "option", 62: "control"}[code]
            pressed = bool(flags & {54: 0x100000, 55: 0x100000, 56: 0x20000, 58: 0x80000, 59: 0x40000, 60: 0x20000, 61: 0x80000, 62: 0x40000}[code])
        else:
            pressed = event_type in (10, 12)
        if not key:
            self.release_all()
            return event
        return None if self.forward(key, pressed, flags & 0x00FF0000) else event

    def run(self):
        callback = self.callback_type(self.callback)
        mask = sum(1 << event for event in (10, 11, 12))
        tap = self.cg.CGEventTapCreate(1, 0, 0, mask, callback, None)
        if not tap:
            raise RuntimeError("Accessibility permission is required for keyboard forwarding")
        source = self.cf.CFMachPortCreateRunLoopSource(None, tap, 0)
        self.cg.CGEventTapEnable.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.cg.CGEventTapEnable(tap, True)
        timer_callback = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(lambda timer, info: self.release_all() if self.state.release_if_returned() else None)
        timer = self.cf.CFRunLoopTimerCreate(None, self.cf.CFAbsoluteTimeGetCurrent() + 0.2, 0.2, 0, 0, timer_callback, None)
        self.cf.CFRunLoopAddTimer(self.cf.CFRunLoopGetCurrent(), timer, ctypes.c_void_p.in_dll(self.cf, "kCFRunLoopCommonModes"))
        self.cf.CFRunLoopAddSource(self.cf.CFRunLoopGetCurrent(), source, ctypes.c_void_p.in_dll(self.cf, "kCFRunLoopCommonModes"))
        print(json.dumps({"event": "keyboard-forwarder-started", "keys_logged": False}), flush=True)
        try:
            self.cf.CFRunLoopRun()
        finally:
            self.cg.CGEventTapEnable(tap, False)
            self.release_all()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.1.8")
    parser.add_argument("--port", type=int, default=8792)
    parser.add_argument("--secret-file", type=Path, required=True)
    args = parser.parse_args()
    tap = MacKeyTap(KeySender(args.host, args.port, args.secret_file), KeyboardState("local"))
    def stop(signum, frame):
        tap.release_all()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    tap.run()


if __name__ == "__main__":
    main()
