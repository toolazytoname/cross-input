# Cross Input

Experimental, hardware-channel mouse switching between a Mac mini and a Windows PC using a Logitech M585/M590, with research into KEMOVE K94 keyboard control.

The mouse does not use Logitech Flow or software mouse forwarding. The local controllers read the mouse's HID++ state and send its documented `CHANGE_HOST` command to move the existing Bluetooth pairing between hosts.

## Current status

- **Mouse, both directions:** verified on hardware. Mac slot 1 to Windows slot 0 and back.
- **Automatic screen-edge switching:** one supervised automatic Mac to Windows to Mac round trip completed, with JSONL evidence.
- **Stability:** disconnect recovery, duplicate suppression, dwell, cooldown, and re-arm-after-leaving-edge have offline tests. A 50-round-trip soak test and sleep/network recovery acceptance remain to be completed. `scripts/supervised_roundtrip.py` drives both edges and records per-round evidence; it has not completed a live run.
- **Text clipboard:** bounded UTF-8 synchronization includes authentication, sequence tracking, replay detection, duplicate suppression, and delivery retries. The Windows Unicode adapter has passed a local Windows read/write test, and Mac-to-Windows payload application was observed. Two-host bidirectional acceptance is still pending.
- **KEMOVE K94:** official firmware builds reproducibly. The unflashed VIA protocol patch compiles, but a control channel that is simultaneously reachable and capable of invoking a BLE transition is still unproven. No firmware was flashed.
- **Keyboard following and GUI:** an experimental software-forwarding implementation and a local control window are present. Windows key injection and the complete start/stop path have not passed runtime acceptance.

Deskflow is a separate rollback path. The edge controllers must not run at the same time as Deskflow's edge handling.

## Repository layout

- `scripts/`: Mac and Windows probes, one-shot mouse tools, and supervised edge controllers.
- `docs/`: implementation status, protocol notes, architecture, and acceptance criteria.
- `evidence/`: selected hardware responses, test results, and research evidence.
- `tests/`: offline tests for the Mac controller/probe and Windows protocol implementation.

The upstream KEMOVE QMK source and compiled firmware artifacts are not bundled. See the official repository at https://github.com/KEMOVE-Official/KEMOVE-QMK-Firmware. The small K94 patch is included for review, with its own recovery warnings.

## Mouse protocol and safety

The M585/M590 exposes a vendor collection with VID/PID `046d:b01b`, usage page `0xff43`, usage `0x0202`, and a 20-byte HID++ long report. On this installation, `CHANGE_HOST 0x1814` is feature index 9 and `HOSTS_INFO 0x1815` is feature index 10. `HOSTS_INFO` identifies the paired host names.

Before switching, the tools verify the device, feature indices, host count, current slot, pairing state, and host names. A write is attempted once, without retrying or assuming the target accepted input. Report submission is only a transport result, not proof of cursor usability.

Read-only and dry-run modes are available. Automatic switching also requires a fresh peer-health response, a stable current slot, and an interactive desktop. Recovery remains available through the mouse's physical Easy-Switch button and the explicit one-shot commands.

## Requirements

- macOS with Python 3 and `hidapi` (`python3 -m pip install hidapi`) for Mac HID tools.
- Windows PowerShell 5.1 with the built-in .NET C# compiler.
- An already paired M585/M590 on both computers.
- A configured SSH alias for the Windows computer, if using the remote task controller.

Set `M585_SSH_ALIAS` and `M585_EDGE_MAC_HOST` for your installation. Windows temporary files default to `$env:TEMP` when available.

The mouse tools also accept `M585_PYTHON`, `M585_SERIAL`, `M585_MAC_HOST_NAME`, and `M585_WINDOWS_HOST_NAME` to match a different installation.

## Checks and dry runs

```sh
python3 scripts/m585_readonly_probe.py --query
python3 scripts/m585_edge_controller.py --check-environment --check-peer
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The Windows script's default mode performs metadata enumeration only. Its test mode uses controlled transports, not physical switching.

```sh
scripts/run_windows_hid_protocol_probe.sh metadata-only
scripts/run_windows_hid_protocol_probe.sh test-only
```

## Supervised edge test

Pause Deskflow's edge handling before starting the two controllers. The Windows controller must run in the logged-in user's interactive session. A normal SSH session cannot host the hotkeys, so the supplied reversible task helper uses an Interactive principal.

```sh
scripts/start_windows_m585_edge_from_ssh.sh register-start dry-run
python3 scripts/m585_edge_controller.py --dry-run
```

Inspect the logs and health responses first. Then use `watch` mode for a supervised hardware test. Windows hotkeys are `Ctrl+Alt+Shift+M` to return to Mac and `Ctrl+Alt+Shift+X` to stop the controller. Stop the Mac controller with `Ctrl+C`.

```sh
scripts/start_windows_m585_edge_from_ssh.sh register-start watch
python3 scripts/m585_edge_controller.py --watch
```

Restore Deskflow after testing and remove the temporary Windows task when finished.

```sh
scripts/start_windows_m585_edge_from_ssh.sh remove
```

## Text clipboard

Create an identical random secret on both computers, stored outside the repository. The two processes bind a specific private IPv4 address and exchange authenticated UTF-8 clipboard text over TCP port 8791. Use a user-selected private port and allow it only on the trusted private network.

```sh
python3 scripts/text_clipboard_sync.py --host mac --listen <mac-private-ip> --peer <windows-private-ip> --secret-file <mac-secret-path>
python3 scripts/text_clipboard_sync.py --host windows --listen <windows-private-ip> --peer <mac-private-ip> --secret-file <windows-secret-path>
```

The protocol limits text to 256 KiB. It logs only metadata, retries an unacknowledged clipboard change with a fresh sequence, and suppresses duplicate application and clipboard loops. It has not completed a Windows or two-host runtime test. Images and files remain outside this protocol.

## Current limitations

The controller has not passed its full acceptance matrix. It does not claim UAC or Windows login-screen support. Bluetooth disconnects, Wi-Fi changes, Windows sleep, and stale peer health require explicit recovery behavior. Do not deploy it as an unattended daily service yet.

The keyboard forwarder and unified control window are experimental. The Windows clipboard service now uses the shared Python implementation and direct Win32 clipboard access, with local read/write evidence, but has not completed bidirectional two-host validation. The acceptance matrix and explicit boundaries are in `docs/completion-goal.md`.

The K94 factory BLE handler requires BLE source mode, while the observed raw VIA interface was found in USB mode. A VIA response from the 2.4 GHz receiver also needs a same-shape online positive control before its responder and control capabilities can be identified.

## License

MIT for this project's original source and documentation. KEMOVE's QMK code and related upstream materials retain their original licenses.
