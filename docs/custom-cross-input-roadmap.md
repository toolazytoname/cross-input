# Custom cross-screen input roadmap

Date: 2026-11-20 America/Los_Angeles.

## Goal

Replace the daily Logitech Flow and Deskflow path with a small, explicit cross-screen input system for the Mac mini and the 3090 Windows PC. The delivered capability is hardware mouse switching through the M585/M590 CHANGE_HOST feature, including one supervised automatic Mac departure and subsequent return. Three-round and fifty-round stability acceptance remain pending. Minimal UTF-8 clipboard synchronization is implemented and offline-validated. Keyboard following and the status GUI remain pending.

The target topology is one local controller on each computer. Each controller owns only the HID device currently connected to that computer, exchanges compact state over the existing LAN/Tailscale path, and exposes a single requested-screen state. A switch is allowed only after the controller re-reads device identity, current slot, host count, capability flags, paired status, and both host names. The controllers must never infer successful user input from a report submission alone.

## Current status

| Component | Status | Boundary |
| --- | --- | --- |
| Bidirectional M585/M590 hardware switching | Delivered and independently reviewed | Manual one-shot commands; no automatic service |
| Automatic edge switching | One supervised automatic round trip observed; stability acceptance pending | Mac attempt ebcc1b440bda44cc95c73aa0eb30416f submitted 20/20 bytes. Windows reached READY_WINDOWS and later lost the device. Mac returned to slot 1. The copied Windows log does not contain the return switch-submitted event, so the return path is not yet independently auditable |
| Keyboard following | Blocked pending K94 | No firmware flash and no unverified K94 command |
| Clipboard and files | Minimal UTF-8 text sync implemented offline; live two-host test blocked | 256 KiB limit, HMAC-SHA256, persistent host sequence, nonce replay cache, duplicate fingerprint cache, loop suppression, rate limit, timeouts, and metadata-only events. Mac pbpaste/pbcopy passed. Windows and cross-host tests wait for 3090 connectivity. LocalSend remains responsible for images and files |
| GUI and resident services | Not started | CLI only; Deskflow remains installed and running |

A reversible Windows Interactive task and the Mac foreground watch were used for supervised testing. Neither is a login service. Deskflow was paused only during the authorized test and restored afterward.

## Verified capability

- M585/M590 serial 7A09C04B5120EA18, vendor collection 046D:B01B / FF43:0202.
- Slot 0 is LAZY-WINDOWS; slot 1 is lazy的Mac Mini.
- CHANGE_HOST feature index is 9 and HOSTS_INFO feature index is 10.
- Mac slot 1 to Windows slot 0: one 20-byte report was submitted, no retry, and the user previously observed the Windows cursor respond.
- Windows slot 0 to Mac slot 1: after full Windows preflight, one 20-byte report was submitted with native final error 0 and no retry. The mouse returned to Mac and Mac read back current slot 1.
- Automatic Mac attempt ebcc1b440bda44cc95c73aa0eb30416f submitted one 20-byte report at 12:48:30 UTC. Windows reached READY_WINDOWS at 12:48:33 and reported the mouse departed at 12:48:41. Mac returned to READY_MAC around 12:48:42. The retained Windows log lacks the return switch-submitted event and cannot independently prove which return entry issued the reverse hop.

This proves the bidirectional physical control channel. Offline edge-controller checks do not by themselves prove supervised runtime behavior, a stable resident service, keyboard following, or clipboard transfer.

## Tools

- scripts/m585_switch_to_windows_once.sh with a new attempt ID runs the strict Mac preflight and submits one switch to slot 0. The attempt ID creates a distinct guard and log, so a repeated invocation requires a new explicit token.
- scripts/run_windows_hid_protocol_probe.sh mouse-readonly verifies the Windows-side current slot and host map.
- scripts/run_windows_hid_protocol_probe.sh mouse-switch-mac-once repeats the same Windows preflight and submits one switch to slot 1. It exposes no arbitrary HID frame.
- scripts/run_windows_hid_protocol_probe.sh metadata-only remains the safe enumeration entry and sends no HID output report.
- scripts/m585_edge_controller.py --check-environment --check-peer performs read-only Mac display/accessibility/device checks and validates the fresh Windows peer-health response.
- scripts/m585_edge_controller.py --dry-run observes Mac edge decisions and logs them without HID++ output or a peer command.
- scripts/m585_edge_controller.py --watch is the supervised Mac controller entry; it starts a small JSON health endpoint for the Windows return hop.
- scripts/run_windows_hid_protocol_probe.sh mouse-edge-dry-run observes the live Windows virtual-screen edge without HID++ output.
- scripts/run_windows_hid_protocol_probe.sh mouse-edge-watch is the supervised Windows controller entry.
- scripts/run_windows_hid_protocol_probe.sh mouse-return-hotkey registers Ctrl+Alt+Shift+M as an explicit Windows-to-Mac return entry.
- scripts/run_windows_hid_protocol_probe.sh peer-health returns a versioned, expiring read-only JSON health object. It prefers a fresh health file written by the interactive Windows watcher and falls back to a direct read-only probe; it never substitutes test-only results for device or desktop readiness.
- scripts/text_clipboard_sync.py synchronizes bounded UTF-8 text over an authenticated private-LAN TCP channel. It must bind a specific loopback or private IPv4 address and never logs clipboard content.

### Supervised Windows foreground plan

The SSH-launched dry run correctly reports SESSION_UNAVAILABLE because it is not attached to the interactive desktop. A real acceptance run must be launched by the currently logged-in user from a visible PowerShell window; no task or startup entry may be created without separate coordinator review.

Planned foreground preparation, without installing anything:

~~~sh
# From Mac mini, after coordinator review; copies only, never executes:
scripts/deploy_windows_m585_edge_launcher.sh

# The logged-in Windows user then runs this visible TEMP launcher:
C:\Users\Administrator\AppData\Local\Temp\MiniOpsM585Edge\windows_m585_edge_launcher.cmd
# Optional first pass:
C:\Users\Administrator\AppData\Local\Temp\MiniOpsM585Edge\windows_m585_edge_launcher.cmd dry-run
~~~

The launcher opens a visible PowerShell window, sets the Mac endpoint to 192.168.1.4:8787, writes JSONL under the same TEMP directory, and does not elevate or install anything. The single watch process registers Ctrl+Alt+Shift+M as the explicit return-to-Mac action and Ctrl+Alt+Shift+X as the one-key stop; the user may also stop the visible window with Ctrl+C or by closing it.

### Verified SSH-to-interactive-controller launch

The noninteractive SSH process cannot host the hotkeys: RegisterHotKey fails with Windows error 1459 because that context needs an interactive window station. A Scheduled Task principal with LogonType Interactive for the logged-in Administrator was tested instead. A minimal Session 1 probe reported UserInteractive=true, OpenInputDesktop=true, and RegisterHotKey with IntPtr.Zero succeeded. A WinForms message-only window was not needed and failed handle creation, so the delivered watcher keeps the thread message-queue form.

The tested dry-run task action ran the bootstrap in Session 1 (PID 41200 in evidence), Task Scheduler reported State 4/Running, the health file reported desktop.available=true, and the JSONL bootstrap start record existed before controller output. The dry-run correctly kept controller_ready=false; no HID++ output was sent. The temporary MiniOpsM585SupervisedDryRun task was stopped and unregistered after evidence capture.

Coordinator-reviewed commands, using the reversible task name MiniOpsM585EdgeWatch:

~~~sh
scripts/start_windows_m585_edge_from_ssh.sh register-start dry-run
scripts/start_windows_m585_edge_from_ssh.sh status dry-run
scripts/start_windows_m585_edge_from_ssh.sh stop dry-run
scripts/start_windows_m585_edge_from_ssh.sh remove dry-run
~~~

Replace dry-run with watch only after the visible dry-run health/log review and the coordinator's Deskflow pause decision. The helper copies only the three PowerShell files into user TEMP; registration uses an Interactive principal, a two-hour execution limit, and MultipleInstances IgnoreNew. It is not a service or login startup entry. stop requests normal Scheduled Task termination; remove stops and unregisters it.

If a login-task equivalent is later approved, it must use an Interactive principal for the current user rather than S4U, launch the same visible command, write the same JSONL log, and be stopped with Stop-ScheduledTask -TaskName 'MiniOps M585 Edge Watch'. This task has not been created.

## State model

Each controller owns this local state:

1. MAC: mouse is paired and connected to slot 1.
2. SWITCHING_TO_WINDOWS: Mac preflight passed and one slot-0 report was submitted; awaiting Windows-side advertisement plus user-observed input.
3. WINDOWS: Windows preflight reads current slot 0 and the exact host map.
4. SWITCHING_TO_MAC: Windows preflight passed and one slot-1 report was submitted; awaiting Mac-side advertisement plus user-observed input.

A transition must be idempotent and one-shot. A repeated edge event cannot issue a second switch while the previous submission is unobserved. Network or screen state cannot override the device's current slot. Recovery is always available through the M585/M590 Easy-Switch button and the explicit tools above.

The Mac controller uses a process lock and append-only JSONL attempt records. Each automatic attempt has an independent ID, edge reason, origin state, current-slot evidence, peer health, target, submission time, result, and recovery entry. The Windows controller emits equivalent JSONL events. Neither controller logs clipboard content or keyboard text.

Mac readiness is exposed only after a read-only current-slot result of 1. Windows must see that health response before its right-edge or hot-key return hop. Before Mac switches to Windows, it requires a local read-only slot result of 1 and a fresh Windows peer-health response whose interactive controller is ready; TCP state alone is never sufficient.

The corrected Mac post-submit sequence is explicit:

1. READY_MAC requires controller startup, a working listen-only event tap, and a successful read-only slot-1 result. The health endpoint remains not-ready until all three are true.
2. SWITCHING_TO_WINDOWS starts only after the fixed entry completes. Its cooldown is measured from the current monotonic time at submit completion, not from a queued event timestamp.
3. Once a trigger occurs, the controller requires the pointer to leave the edge before any future trigger. A continuous stale edge stream therefore cannot produce a second CHANGE_HOST even after HID preflight or submit calls take several seconds.
4. A successful submit remains SWITCHING_TO_WINDOWS while read-only polling still finds slot 1. It does not become READY_MAC merely because the old device connection has not disappeared yet.
5. A distinct device-absent poll result changes the state to MOUSE_ABSENT_AFTER_SWITCH. Polling continues at low frequency and sends no write.
6. Return to READY_MAC requires the five-second post-submit stability window plus two consecutive read-only slot-1 results after absence. The leave-edge requirement remains active.
7. If slot 1 persists through the stability window without departure, the state becomes RECOVERY_REQUIRED. Query failures are tolerated only up to three consecutive polls before RECOVERY_REQUIRED; duplicate-device and absent-device diagnostics are not treated as the same condition.
8. TARGET_UNAVAILABLE retries the read-only Windows peer at low frequency. Recovery additionally re-reads Mac slot 1 after the peer becomes ready and retains the leave-edge requirement. Submit failure, no-departure, and wrong-slot still require the explicit recovery paths.

Startup/query-failure recovery is separately bounded:

1. Three consecutive ambiguous query failures may enter RECOVERY_REQUIRED.
2. Recovery records its entry time and requires the listen-only event tap to be running.
3. Two consecutive read-only slot-1 results and a five-second stability window return the controller to READY_MAC.
4. A query failure or wrong-slot result resets the consecutive recovery count.
5. Returning to READY_MAC keeps the leave-edge rearm requirement, so a held edge cannot immediately submit a switch.

The Windows watcher applies the same leave-edge rule after a submitted or simulated right-edge transition. Its foreground-only plan below is required because the SSH session cannot access the interactive input desktop and must remain SESSION_UNAVAILABLE.

## Implementation stages

### Stage 1: mouse switching and supervised edge automation

Both one-shot tools and the bidirectional runtime sequence are complete. One supervised automatic round trip has been observed. The edge controllers implement display-boundary detection, interaction suppression, dwell, cooldown, peer health, state logging, locks, and recovery states. Remaining work is a three-round supervised run followed by the fifty-round acceptance below. No permanent service is enabled.

### Stage 1 acceptance gate

Before automatic edge switching can replace the existing input path, all of the following must pass in one approved supervised run:

1. Deskflow is explicitly paused for the supervised run after coordinator review; automatic edge handling and Deskflow edge handling never run concurrently.
2. Fifty complete hardware round trips: Mac slot 1 to Windows slot 0 and back to Mac slot 1.
3. Exactly one CHANGE_HOST submission per requested direction per crossing; no reverse hop caused by the same physical movement.
4. No uncommanded reverse switch within five seconds after an accepted edge transition.
5. Actual Mac cursor movement and click confirmation after return, not just slot state or report submission.
6. Actual Windows cursor movement and click confirmation after arrival, not just slot state or report submission.
7. Drag with a held button, held modifier, and short edge touch do not switch.
8. At least three Windows sleep/resume cycles end in an explicit READY or RECOVERY_REQUIRED state; no automatic WOL.
9. At least one LAN change and one unavailable-peer case end in TARGET_UNAVAILABLE without HID output.
10. Easy-Switch and the existing one-shot CLI remain usable as rollback paths.
11. Attempt logs contain every required field and no clipboard or keyboard text.
12. UAC or the login desktop reports SESSION_UNAVAILABLE or otherwise fails closed; the controller does not claim Secure Desktop support.

### Stage 2: keyboard following

Use mouse screen state as the desired keyboard target. K94 firmware will remain blocked until a same-shape 2.4G positive control identifies the responder and a reversible flashing/recovery procedure exists. Until then, the practical route is to keep K380/K94 on the existing manual or Deskflow-assisted path and not flash anything.

### Stage 3: clipboard and files

The minimal text implementation is present. Each frame carries a host identity, persistent host-local sequence, timestamp, nonce, UTF-8 payload, and HMAC-SHA256. Receivers enforce the timestamp window, sequence, nonce, payload-size limit, duplicate fingerprints, and strict UTF-8. Senders use a response timeout, per-minute rate limit, persistent sequence, and duplicate-for-same-text handling after a lost response. An unacknowledged local change is retried with a fresh sequence, and duplicate-sequence responses identify their payload fingerprint. Events contain sizes, hashes, sequences, and error types only.

Planned live commands, after Windows is reachable and the coordinator reviews the port boundary:

~~~sh
# Mac, after placing the shared 32-plus-byte secret outside the repository:
scripts/text_clipboard_sync.py --host mac --listen 192.168.1.4 --peer 192.168.1.8 \
  --secret-file "$HOME/.config/miniops/cross-input-clipboard.secret"
~~~

~~~powershell
# Windows, with byte-for-byte the same secret outside the repository:
python scripts/text_clipboard_sync.py --host windows --listen 192.168.1.8 --peer 192.168.1.4 `
  --secret-file "$env:USERPROFILE\.miniops\cross-input-clipboard.secret"
~~~

The channel uses TCP 8791 on the private LAN. No firewall rule has been created. The live test must use benign distinct text, record only hashes and sizes, and restore or replace the probe text. Reuse LocalSend for images and files.

### Stage 4: service and GUI

Package each controller as a user-level service with health state, event log, current slot, last transition latency, rollback buttons, and a single emergency command that stops automatic switching. The current implementation includes an optional local Tk status window and reversible `.command` controls, but the start/stop and runtime acceptance have not completed a live Windows run. Network changes and Windows sleep/wake should degrade to manual tool mode rather than guessing device state.

## Non-goals and current boundaries

- No K94 firmware flashing in this stage.
- No K94 custom switch command while its control path and responder are unverified.
- No unbounded clipboard or file replication.
- No automatic switch based only on TCP reachability, Deskflow state, or a timeout.
- No claim of target-host input from a successful HID write alone.
