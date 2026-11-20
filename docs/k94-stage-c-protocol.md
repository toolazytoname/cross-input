# K94 offline stage C protocol and patch audit

Date: 2026-11-19 America/Los_Angeles. This document describes an offline, unflashed experiment. No bootloader was entered, no firmware was flashed, no protected firmware was read, and no channel-switch command was sent to hardware.

## 1. Baseline and artifacts

The official clone remains untouched at:

- Commit: `c04f415f5934d6e48a76e7100a2c541116941b90`
- Tree: `6450072e8ffe5a648c94427ca286b1e18f980e3e`

The patch was developed in a separate local clone of the official firmware. The official factory reference binary in that working clone was restored after QMK copied its build output over the root filename.

Artifacts:

| Artifact | Size | SHA-256 |
| --- | ---: | --- |
| Unified patch | 10,451 bytes | `1bdd2c85591c8be1696d9a3e3b78e82a92a322893b146ef767c8590c6ccd0cef` |
| Built BIN | 80,548 bytes | `fb45c9c74bf5ca89d7d11351c392e4d0c38dc7201db1129fe869beca6dc9100c` |
| Built ELF | 1,158,380 bytes | `69862d51267961043b580985d3b3fd1f620258e5198f34eb033947759e8c3ce6` |
| Built HEX | 226,598 bytes | `2136743268f27f9b7ee9d79b44e91dcf3b276d90989a3536b7d594cce3d72063` |
| Link map | 1,017,373 bytes | `7422ea6e646c1cd579c499bed7414e9ed0e39920a3302a3ddee3f30b7d75c143` |

Patch location: [evidence/k94/stage-c/k94-stage-c.patch](../evidence/k94/stage-c/k94-stage-c.patch). `git -C research/k94/KEMOVE-QMK-Firmware apply --check <patch>` passes.

Build commands:

~~~sh
PATH="$PWD/research/k94/qmk-venv/bin:$PWD/research/k94/toolchain-pkg/bin:$PATH" \
  qmk clean -a
PATH="$PWD/research/k94/qmk-venv/bin:$PWD/research/k94/toolchain-pkg/bin:$PATH" \
  ALLOW_WARNINGS=yes make 8r101_k94:via
~~~

`qmk clean -a` again prints its known `None (None)` userspace cleanup error after deleting `.build`; the subsequent full build succeeds. The only repeated compiler warning is the FS026 vendor header-guard warning already present in the baseline build.

Final ELF size:

~~~text
text   data     bss     dec
78598   1948   14432   94978
~~~

## 2. Command-space audit

QMK standard top-level VIA command IDs in this source include `0x01` through `0x2C`, plus this KEMOVE fork's `0xAA` and `0xBB`. Creating another top-level ID would be unsafe.

The patch therefore uses the standard VIA custom-value transport:

- `0x07`: VIA custom set value.
- `0x08`: VIA custom get value.
- Channel `0x00`: VIA custom channel.
- Value ID `0xB1`: experimental K94 private value.
- Protocol version `0x01`.

The checked K94 VIA JSON and KEMOVE Web Hub use the RGB Matrix channel/value IDs (`channel 3`, values 1 through 4 in the menus). No use of custom channel `0` or value `0xB1` was found in those materials. VIA does not provide a globally registered private value-ID allocator, so cross-tool collision remains unknown. The version byte, exact length, and zero-tail checks make an accidental collision fail closed; this remains an experimental value rather than a KEMOVE-official allocation.

## 3. Wire format

All packets are exactly 32 bytes.

### Status request

~~~text
08 00 B1 01 00 00 00 00 [24 zero bytes]
~~~

`data[0]` is VIA command `0x08`, `data[1]` is channel 0, `data[2]` is value `0xB1`, and `data[3]` is protocol version 1.

### Switch request

~~~text
07 00 B1 01 TT RR 00 00 [24 zero bytes]
~~~

- `TT`: target BLE slot, only 1, 2, or 3.
- `RR`: nonzero request ID chosen by the host.

USB/2.4G targets and pairing commands are intentionally absent.

### Response

~~~text
07/08 00 B1 01 RS RR SS BB PP PR LT LR LC RW RC RCN [16 zero bytes]
~~~

| Offset | Meaning |
| ---: | --- |
| 4 | Result code |
| 5 | Request ID from the set request |
| 6 | Local `Keyboard_Info.Key_Mode`: 0 BLE, 1 2.4G, 2 USB |
| 7 | Local `Keyboard_Info.Ble_Channel` |
| 8 | Pending target, or zero |
| 9 | Pending request ID, or zero |
| 10 | Last accepted target, or zero |
| 11 | Last accepted request ID, or zero |
| 12 | 1 only after local execution was invoked |
| 13 | Raw `Keyboard_Status.System_Work_Mode` |
| 14 | Raw `Keyboard_Status.System_Work_Channel` |
| 15 | Raw `Keyboard_Status.System_Connect_Status` |

Result codes:

| Code | Meaning |
| ---: | --- |
| `0x00` | Status read succeeded, or a set request was accepted and queued; for set this is not target-host input confirmation |
| `0x01` | Same request ID and target repeated while pending |
| `0x02` | Target already equals local current BLE slot; no transition queued |
| `0x03` | Same request ID/target replay after local press/release in this power cycle; only local callback invocation is claimed |
| `0x10` | Bad length, version, target, request ID, reserved byte, or nonzero tail |
| `0x11` | A different request is pending |
| `0x12` | Same request ID reused with a different target |
| `0x13` | Current source mode is not BLE, so execution is unavailable |
| `0x14` | Persistence cooldown after a prior local press/release commit |

Unknown custom channel/value/command combinations return VIA `0xFF` unhandled. Standard VIA command `0x01` remains handled by QMK core.

## 4. Validation and idempotency

The handler accepts only 32-byte packets, version 1, custom channel 0, value `0xB1`, target 1 through 3, and a nonzero request ID. All reserved bytes and the packet tail must be zero.

While a request is pending:

- Same request ID and target returns duplicate-pending.
- Same request ID with another target returns request-conflict.
- Another request ID returns busy.

After local execution in the same power cycle:

- Same request ID and target returns local-commit replay.
- Same request ID with another target returns request-conflict.
- A new request ID is accepted only after the persistence cooldown.

The response is generated before the delayed execution state runs. A valid request is scheduled for 100 ms later. At execution time the handler checks the source mode again and fails closed if it is no longer BLE.

The state machine then invokes the production callback twice, first with `pressed=true` and immediately afterward with `pressed=false`. The production callback creates a fresh zeroed `keyrecord_t` for each call, sets only the pressed bit, maps target 1/2/3 to `MD_BLE1/2/3`, and calls the keyboard's existing `process_record_user()` for both calls. This deliberately follows the stock transient key path rather than calling `User_process_record_user()` directly.

The built ELF verifies this production boundary:

- [task-disassembly.txt](../evidence/k94/stage-c/task-disassembly.txt) calls the callback once with r1=1 and once with r1=0.
- [execute-request-disassembly.txt](../evidence/k94/stage-c/execute-request-disassembly.txt) stores that argument into the keyrecord pressed field and calls `process_record_user`.
- [vector78-disassembly.txt](../evidence/k94/vector78-disassembly.txt) shows why release is required: if a `Key_Ble_[123]_Status` flag remains set, the interrupt path sends SPI commands 0x05/0x06/0x07 (pairing commands) when it clears the flag.

This is static equivalence to the entry into the stock keyboard callback, not a claim that the wireless module accepted or connected to the target host.

## 5. Critical reachability gate

Static and runtime evidence now establish a mode conflict:

- USB B1 runtime evidence found the QMK raw collection only in wired USB mode, where `Keyboard_Info.Key_Mode == QMK_USB_MODE == 2`.
- The stock `User_process_record_user()` BLE1/BLE2/BLE3 branches require `Keyboard_Info.Key_Mode == QMK_BLE_MODE == 0`; a USB-mode call skips them.
- The physical `Key_Switch_Mode_Scan()` path changes wireless mode and calls `Usb_Disconnect()`, then sends SPI commands and `Save_Flash_Set()`.
- The BLE snapshot has no `0xFF60/0x61` raw collection.

Therefore this patch deliberately returns `SOURCE_BLOCKED` for a set request received while `Key_Mode` is 2.4G or USB. It does not queue the request and does not claim that USB-mode queuing would execute. In particular, a USB-connected K94 cannot use this command to leave wired mode, and the same limitation applies to a hypothetical Windows-side USB return command. The status command remains useful to expose local mode and raw status.

This offline patch is not a working Mac-to-Windows K94 channel switch. It is a fail-closed protocol proof and candidate implementation for a future independently verified control path.

## 6. Architecture evidence still missing

| Scenario | Currently known | Missing evidence |
| --- | --- | --- |
| K94 remains wired to Mac | USB raw and standard VIA are reachable | No BLE switch execution because stock BLE handler requires BLE mode |
| K94 is BLE-connected to Mac | Stock BLE handler can run when mode is BLE | No raw HID collection exposed over BLE |
| K94 uses 2.4G receiver | Web Hub maps receiver `36B0:3002` to the bundled K94 24G definition and can use its QMK/VIA path | Physical Windows PnP/interface enumeration and whether a custom command can traverse the receiver while K94 is in 2.4G mode |
| Return from Windows to Mac | Desired right-to-left architecture requires a command origin on Windows or another always-available channel | No Windows raw-control evidence and no post-switch return path |

The absent piece is a control channel that is simultaneously reachable and capable of invoking the stock BLE transition. A wired USB ACK, BLE HID keyboard input, or successful offline compilation does not prove that piece.

## 7. Persistence side effect

Every real BLE slot transition through the stock path invokes `Save_Flash_Set()`. Its disassembly sets `Save_Flash = true` and resets `Save_Flash_3S_Count`; the later keyboard reset path performs the deferred save. Consequently, frequent edge-driven slot changes can cause repeated flash writes and latency.

The patch adds a 3500 ms cooldown after the second local record callback. The timer starts at local callback completion, not at verified flash-write completion; 3500 ms is chosen to exceed the static three-second save countdown, but actual save completion is not exposed or proven. This reduces overlapping transition requests but does not eliminate the long-term wear concern; a production design needs a persistence policy and endurance budget.

## 8. Offline verification matrix

Host state-machine tests: [evidence/k94/stage-c/test_k94_via_switch.c](../evidence/k94/stage-c/test_k94_via_switch.c), output [host-test-output.txt](../evidence/k94/stage-c/host-test-output.txt).

| Case | Expected | Result |
| --- | --- | --- |
| Legal status in BLE source mode | `0x00`, local mode/channel and raw status returned | passed |
| Legal switch request | Queued ACK before execution; callback only at deadline | passed |
| Deadline before 100 ms | No callback | passed |
| Same request/target while pending | Duplicate-pending | passed |
| Same request/different target while pending | Request-conflict | passed |
| Different request while pending | Busy | passed |
| Same completed request/target | Local-commit replay | passed |
| Same completed request/different target | Request-conflict | passed |
| New request before 3500 ms | Persistence cooldown | passed |
| USB source mode | `SOURCE_BLOCKED`, no queue, no callback | passed |
| Production execution boundary | Callback receives target with press=true then press=false | passed |
| Length-zero handler input | No read/write of packet data and no pending state | passed |
| Wrong version/target/request/reserved/tail/short frame | Bad frame or unhandled, no queue | passed |
| Standard VIA protocol command in dispatch mock | Mock dispatch leaves command `0x01` outside the custom override | passed |
| State fields not semantically known | Returned raw, not interpreted | passed |

Firmware build:

- Full clean followed by build succeeded.
- New source compiled without a warning specific to the patch.
- Patch applies cleanly to the official baseline.
- ELF symbols show strong `via_custom_value_command_kb` and QMK core `raw_hid_receive`/`via_custom_value_command` wiring; see [link-symbols.txt](../evidence/k94/stage-c/link-symbols.txt).

No runtime K94 custom command was sent.

The dispatch mock's `0.0C` response proves only that command `0x01` is outside this patch's custom handler. Real standard VIA `0.01` behavior was separately verified on the unflashed USB device during B1 and returned `0.0C`; no modified firmware and no custom command were run on hardware.

## 9. Recovery blockers

The stage C build is not flashable. Still missing are PCB revision identity, a matched FS026 custom bootloader tool and entry procedure, a readback of the current firmware, a revision-matched wireless/LCD recovery package, and a rehearsed official recovery flow. The existing factory BIN is a TTComp-packaged reference artifact and is not proven to match this physical keyboard.
