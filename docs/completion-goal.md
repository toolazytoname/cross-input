# Completion goal

Deliver a usable, reversible two-computer input system for this Mac mini and the 3090 Windows PC.

## Required outcomes

1. The M585/M590 changes Bluetooth hosts in both directions. Edge and hot-key switching use one transition state machine with duplicate suppression and an explicit recovery state.
2. The K94 remains paired to the Mac. While Windows is the active screen, its keystrokes are forwarded to the Windows interactive desktop. Modifier state, key release, disconnect, and focus return are handled. This is the keyboard-following route while the K94 firmware channel remains unproven.
3. UTF-8 clipboard text synchronizes with authentication, size limits, duplicate detection, loop suppression, and retry after an uncertain response. Images and files use LocalSend.
4. Both computers expose the active host, peer health, recent failure, and controller running state. A visible control offers Stop and Restore Deskflow. A single Stop also disables automatic edge switching and keyboard forwarding.
5. The default path does not require a terminal. Stopping the experimental system restores the existing Deskflow path without changing pairing, WOL, SSH, RDP, or the Windows network profile.

## Acceptance

- Three supervised hardware round trips first, then a 50-round-trip soak with one command per requested direction.
- No automatic reverse hop from the same physical movement. Dragging and held modifiers do not cause switching.
- Keystrokes reach only the active computer. Release and focus return cannot leave a modifier held on Windows.
- Chinese, English, newline, and large allowed text synchronize in both directions. Clipboard content is absent from logs.
- Sleep, peer loss, and network changes produce a recoverable status without unattended switching.
- Windows UAC and the login screen are reported unavailable unless separately verified.
- Tests and runtime evidence are committed to the public repository with each working increment.

## Firmware boundary

The unflashed K94 patch is retained for research. Firmware flashing requires a revision-matched image, official bootloader and recovery method, and a reversible procedure. Lack of those materials does not block the software keyboard-forwarding route.
