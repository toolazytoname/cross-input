#!/usr/bin/env python3
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "windows_hid_protocol_probe.ps1"
HELPER = ROOT / "scripts" / "run_windows_hid_protocol_probe.sh"
LAUNCHER = ROOT / "scripts" / "windows_m585_edge_launcher.cmd"
BOOTSTRAP = ROOT / "scripts" / "windows_m585_edge_bootstrap.ps1"
TASK_CONTROLLER = ROOT / "scripts" / "windows_m585_edge_task_controller.ps1"
SSH_TASK_STARTER = ROOT / "scripts" / "start_windows_m585_edge_from_ssh.sh"
DEPLOYER = ROOT / "scripts" / "deploy_windows_m585_edge_launcher.sh"


class WindowsHidProtocolProbeStaticTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.lower = self.text.lower()
        self.helper = HELPER.read_text(encoding="utf-8")

    def test_default_mode_is_metadata_only(self):
        self.assertIn('output.Mode = "metadata-only"', self.text)
        self.assertIn("output.HidOutputReportSent = false", self.text)
        self.assertIn("CreateFileW(item.DevicePath, 0,", self.text)
        self.assertIn("HidOutputReportSent = $false", self.helper)
        self.assertIn("CreateMetadataOutput($candidates)", self.text)

    def test_cli_surface_has_only_narrow_protocol_entries(self):
        self.assertIn("[switch]$MouseReadOnly", self.text)
        self.assertIn("[switch]$K94ViaVersion", self.text)
        for forbidden in ("[string]$Frame", "[byte[]]$Report", "0xAA D0"):
            self.assertNotIn(forbidden, self.text)

    def test_interactive_foreground_modes_are_builtin(self):
        for switch in ("$WindowsEdgeWatch", "$WindowsEdgeDryRun", "$WindowsReturnHotKey", "$WindowsPeerHealth"):
            self.assertIn("[switch]" + switch, self.text)
        self.assertIn("$IsWindowsEdgeMode = @($WindowsEdgeModes).Count -eq 1", self.text)
        self.assertIn("[WindowsHidProtocolProbe]::RunWindowsReturnHotKey()", self.text)
        self.assertIn("[WindowsHidProtocolProbe]::RunWindowsEdgeWatch([bool]$WindowsEdgeDryRun)", self.text)

    def test_peer_health_is_readonly_versioned_and_fresh(self):
        for required in (
            "RunWindowsPeerHealth()",
            "CreatePeerHealth()",
            "controller = \"windows-peer-health-v1\"",
            "controller_ready = false",
            "return_ready",
            "bool ready = desktopAvailable",
            "bool returnReady = desktopAvailable && mousePresent && slotEvidenceVerified && currentSlot == 0",
            "watcher-health-file-unavailable",
            "generated_at_utc",
            "expires_at_utc",
            "AddSeconds(15)",
            "M585_EDGE_WINDOWS_HEALTH_PATH",
            "WriteHealthFile(",
            'state == "AWAITING_WINDOWS_DEVICE" || state == "READY_WINDOWS" || state == "TARGET_UNAVAILABLE" || state == "DEVICE_DEPARTED" || state == "SESSION_UNAVAILABLE"',
            'state == "AWAITING_WINDOWS_DEVICE" || state == "READY_WINDOWS" || state == "SWITCHING_TO_MAC" || state == "DEVICE_DEPARTED" || state == "TARGET_UNAVAILABLE"',
            "hid_output_report_sent = false",
        ):
            self.assertIn(required, self.text)
        self.assertIn("peer-health", self.helper)
        self.assertIn("[WindowsHidProtocolProbe]::RunWindowsPeerHealth()", self.helper)
        self.assertIn("M585_EDGE_WINDOWS_HEALTH_PATH", self.helper)

    def test_single_watch_has_return_and_stop_hotkeys(self):
        for required in (
            "WM_HOTKEY_RETURN_ID = 1",
            "WM_HOTKEY_STOP_ID = 2",
            "0x4D",
            "0x58",
            "PeekMessageW(out message",
            "controller-stopped",
            "hotkey-ctrl-alt-shift-x",
        ):
            self.assertIn(required, self.text)

    def test_visible_temp_launcher_does_not_install_or_elevate(self):
        launcher = LAUNCHER.read_text(encoding="utf-8")
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        deployer = DEPLOYER.read_text(encoding="utf-8")
        task_controller = TASK_CONTROLLER.read_text(encoding="utf-8")
        ssh_task_starter = SSH_TASK_STARTER.read_text(encoding="utf-8")
        self.assertIn("M585_EDGE_MAC_HOST=192.168.1.4", launcher)
        self.assertIn("M585_EDGE_MAC_HEALTH_PORT=8787", launcher)
        self.assertIn("LAUNCHER_MODE=watch", launcher)
        self.assertIn('if /I "%~1"=="dry-run" set "LAUNCHER_MODE=dry-run"', launcher)
        self.assertIn("Ctrl+Alt+Shift+M", launcher)
        self.assertIn("Ctrl+Alt+Shift+X", launcher)
        self.assertIn("does not elevate or install anything", launcher)
        self.assertNotIn("Tee-Object", launcher)
        self.assertIn("windows_m585_edge_bootstrap.ps1", launcher)
        self.assertIn('type NUL > "%LOGFILE%"', launcher)
        self.assertIn("pause", launcher)
        self.assertIn("bootstrap-starting", bootstrap)
        self.assertIn("New-Object System.Diagnostics.ProcessStartInfo", bootstrap)
        self.assertIn("1> $stdoutPath 2> $stderrPath", bootstrap)
        self.assertIn("[void]$child.Start()", bootstrap)
        self.assertIn("Read-NewChildOutput -Stream $stdoutStream", bootstrap)
        self.assertIn("$exitCode = $child.ExitCode", bootstrap)
        self.assertNotIn("& $probe @parameters 2>&1", bootstrap)
        self.assertIn("bootstrap-error", bootstrap)
        self.assertIn("bootstrap-stopped", bootstrap)
        self.assertIn("[System.IO.File]::AppendAllText($logFile", bootstrap)
        self.assertIn("exit $exitCode", bootstrap)
        self.assertIn("AppData/Local/Temp/MiniOpsM585Edge", deployer)
        self.assertIn("windows_m585_edge_bootstrap.ps1", deployer)
        self.assertIn("windows_m585_edge_task_controller.ps1", deployer)
        self.assertIn("No service or scheduled task was created", deployer)

    def test_interactive_ssh_task_helper_is_explicit_and_reversible(self):
        task_controller = TASK_CONTROLLER.read_text(encoding="utf-8")
        ssh_task_starter = SSH_TASK_STARTER.read_text(encoding="utf-8")
        for required in (
            "MiniOpsM585EdgeWatch",
            "New-ScheduledTaskPrincipal",
            "-LogonType Interactive",
            "New-ScheduledTaskAction",
            "-WindowStyle Normal",
            "-MultipleInstances IgnoreNew",
            '"stop"',
            '"remove"',
        ):
            self.assertIn(required, task_controller)
        for required in (
            "register-start|status|stop|remove",
            "dry-run|watch",
            "BatchMode=yes",
            "StrictHostKeyChecking=yes",
            "windows_m585_edge_task_controller.ps1",
        ):
            self.assertIn(required, ssh_task_starter)
        self.assertNotIn("mouse-switch-mac-once", ssh_task_starter)

    def test_watch_writes_start_and_error_health_before_first_output(self):
        for required in (
            'Write-WatchHealthJson -State "CONTROLLER_STARTING"',
            'Write-WatchHealthJson -State "ERROR_ADD_TYPE"',
            'Write-WatchHealthJson -State "ERROR_RUNTIME"',
            "exit 2",
            "exit 3",
            "Move-Item -LiteralPath $temporary -Destination $WatchHealthPath -Force",
        ):
            self.assertIn(required, self.text)
        self.assertIn("WriteHealthFile(state, dryRun, InputDesktopAccessible()", self.text)

    def test_native_overlapped_uses_explicit_native_memory(self):
        self.assertNotIn("WAIT_INFINITE", self.text)
        self.assertNotRegex(self.text, r"GetOverlappedResult\([^)]*,\s*true\)")
        self.assertIn("Marshal.AllocHGlobal(nativeLength)", self.text)
        self.assertIn("Marshal.AllocHGlobal(Marshal.SizeOf(typeof(OVERLAPPED)))", self.text)
        self.assertIn("Marshal.StructureToPtr(new OVERLAPPED()", self.text)
        self.assertIn("WriteFileNative(SafeFileHandle handle, IntPtr buffer", self.text)
        self.assertIn("ReadFileNative(SafeFileHandle handle, IntPtr buffer", self.text)
        self.assertIn("IntPtr overlapped)", self.text)
        self.assertNotIn("byte[] buffer, uint numberOfBytesToWrite", self.text)
        self.assertNotIn("ref OVERLAPPED overlapped", self.text)

    def test_each_pending_operation_owns_a_manual_reset_event(self):
        self.assertIn("public SafeWaitHandle EventHandle;", self.text)
        self.assertIn("CreateEventExW(IntPtr.Zero, null, 0x00000001", self.text)
        self.assertIn("new SafeWaitHandle(nativeEventHandle, true)", self.text)
        self.assertIn("Marshal.OffsetOf(typeof(OVERLAPPED), \"hEvent\")", self.text)
        self.assertIn("operation.EventHandle.DangerousAddRef(ref eventRef)", self.text)

    def test_cancel_uses_exact_pending_pointer_and_handles_1168(self):
        self.assertIn("CancelIoEx(operation.Overlapped)", self.text)
        self.assertIn("EntryPoint = \"CancelIoEx\"", self.text)
        self.assertIn("ERROR_NOT_FOUND = 1168", self.text)
        self.assertIn("completion.CancelNativeError == ERROR_NOT_FOUND", self.text)
        self.assertIn("CancelCompletionWaitMilliseconds = 1000", self.text)

    def test_unconfirmed_operation_is_retained_never_freed(self):
        self.assertIn("UnresolvedPendingOperations.Add(operation)", self.text)
        self.assertIn("UnresolvedPendingOperationCount", self.text)
        self.assertIn("if (operation.Retained)", self.text)
        self.assertIn('"Cannot free an unresolved pending operation"', self.text)
        self.assertIn("unconfirmed-cancel-never-freed", self.text)
        self.assertIn("\"write-unresolved\"", self.text)

    def test_read_buffer_is_copied_before_confirmed_free(self):
        self.assertLess(
            self.text.index("input = CopyConfirmedBuffer(readOperation, nativeInputLength)"),
            self.text.index("FreeConfirmedPendingOperation(readOperation)"),
        )
        self.assertIn("Marshal.Copy(operation.Buffer, copy, 0, length)", self.text)

    def test_full_native_error_and_timing_evidence_is_recorded(self):
        for direction in ("Write", "Read"):
            for stage in ("InitialNativeError", "WaitNativeError", "CancelNativeError", "GetOverlappedNativeError", "FinalNativeError"):
                self.assertIn(f"public int {direction}{stage}", self.text)
            self.assertIn(f"public long {direction}ElapsedMilliseconds", self.text)
            self.assertIn(f"public long {direction}CancelWaitMilliseconds", self.text)
        self.assertIn("result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds", self.text)

    def test_input_and_output_caps_are_used_separately(self):
        self.assertIn("selected.InputReportByteLength, selected.OutputReportByteLength", self.text)
        self.assertIn("CreatePendingOperation(device, null, nativeInputLength)", self.text)
        self.assertIn("CreatePendingOperation(device, protocolFrame, nativeOutputLength)", self.text)
        self.assertIn("controlled-transport-success-distinct-caps", self.text)

    def test_hidpp_swid_and_actual_function_whitelist(self):
        self.assertIn("HidppSoftwareId = 0x01", self.text)
        for required in ("rootChange[3] == 0x01", "descriptor[3] == 0x11", "name[3] == 0x31"):
            self.assertIn(required, self.text)
        self.assertIn("BuildHidppRequest(0x09, 0x10", self.text)
        self.assertIn("BuildChangeHostSwitchToMacRequest(0x09)", self.text)
        self.assertIn("frame[4] = 0x01", self.text)
        self.assertIn("Requested HID++ feature/function is outside the read-only whitelist", self.text)
        self.assertIn("hidpp-swid-and-function-whitelist", self.text)

    def test_hidpp_matching_and_protocol_errors_are_strict(self):
        self.assertIn("response[3] == request[3] && request[3] != 0", self.text)
        self.assertIn("wrongSwid[3] = 0x21", self.text)
        self.assertIn('"hidpp-error"', self.text)
        self.assertIn("GetHidppErrorCode(input)", self.text)
        self.assertIn("hidpp-strict-response-and-error", self.text)

    def test_hosts_info_capability_quantity_slot_and_lengths_are_gated(self):
        self.assertIn("(capabilityFlags & 0x01) == 0", self.text)
        self.assertIn("hostCount != expectedCount", self.text)
        self.assertIn("currentHost != expectedCurrent", self.text)
        self.assertIn("descriptorResult.Response[4] != slot", self.text)
        self.assertIn("MaximumHostNameLength = 32", self.text)
        self.assertIn("nameLength > maximumLength", self.text)
        self.assertIn("mouse-readonly-capability-and-name-gates", self.text)

    def test_windows_to_mac_switch_is_fixed_and_preflighted(self):
        self.assertIn("RunMouseSwitchToMac", self.text)
        self.assertIn('output.Mode = "M585-switch-to-mac-once"', self.text)
        self.assertIn("ProbeOutput output = RunMouseReadonly(candidates, channel, device, selected);", self.text)
        self.assertIn("BuildChangeHostSwitchToMacRequest(0x0A)", self.text)
        self.assertIn('"switch-submitted-no-reply"', self.text)
        self.assertIn("mouse-switch-to-mac-once-after-preflight", self.text)

    def test_windows_edge_geometry_uses_live_virtual_screen(self):
        self.assertIn("GetSystemMetrics(76) + GetSystemMetrics(78)", self.text)
        self.assertIn("atRightEdge = cursor.X >= virtualRight - EdgeThresholdPixels", self.text)
        self.assertNotIn("cursor.X >= 1920", self.text)
        self.assertNotIn("cursor.X >= 3840", self.text)

    def test_windows_edge_requires_dwell_cooldown_and_no_interaction(self):
        for required in (
            "DwellMilliseconds = 400",
            "CooldownMilliseconds = 2500",
            "AnyButtonOrModifierPressed()",
            "if (!atRightEdge)",
            "rearmRequiresLeaveEdge = true",
            "bool dwellSatisfied = !rearmRequiresLeaveEdge",
            "dwellSatisfied",
            "cooldownSatisfied",
        ):
            self.assertIn(required, self.text)

    def test_windows_edge_peer_and_slot_are_fail_closed(self):
        self.assertIn("MacPeerHealth()", self.text)
        self.assertIn("MacPeerReady(peer)", self.text)
        self.assertIn("\"\\\"ready\\\":true\"", self.text)
        self.assertIn("\"\\\"return_target_ready\\\":true\"", self.text)
        self.assertIn("ConfirmWindowsDeviceReady()", self.text)
        self.assertIn("SlotEvidence(output)", self.text)
        self.assertIn("\\\"current_slot_evidence\\\":", self.text)
        self.assertIn("\\\"target\\\":", self.text)
        self.assertIn("\\\"recovery\\\":\\\"easy-switch-or-mouse-switch-mac-once\\\"", self.text)
        self.assertIn("windows-slot-0-mac-slot-1-confirmed", self.text)
        self.assertIn("TARGET_UNAVAILABLE", self.text)
        self.assertIn("RECOVERY_REQUIRED", self.text)

    def test_windows_session_and_manual_return_are_explicit(self):
        self.assertIn("InputDesktopAccessible()", self.text)
        self.assertIn("SESSION_UNAVAILABLE", self.text)
        self.assertIn("RegisterHotKey", self.text)
        self.assertIn("Ctrl+Alt+Shift+M", self.text)
        self.assertIn("RunWindowsReturnHotKey()", self.text)

    def test_k94_request_and_selection_are_exact(self):
        self.assertIn("frame[0] = 0x00", self.text)
        self.assertIn("frame[1] = 0x01", self.text)
        self.assertIn("requestZeroTail", self.text)
        self.assertIn('instanceId.Contains("&MI_01\\\\")', self.text)
        self.assertIn("candidate.InputReportByteLength == 33 && candidate.OutputReportByteLength == 33", self.text)
        self.assertIn("k94-mi01-and-caps-selected", self.text)
        self.assertIn("k94-receiver-path-uses-verified-request", self.text)

    def test_k94_reply_prefixes_and_independent_fixture(self):
        for required in (
            "response[0] == 0x01",
            "response[0] == 0x00 && response[1] == 0x01",
            "response[0] == 0xAA && response[1] == 0x01",
            "response[0] == 0xAA && response.Length > 2 && response[2] == 0x01",
            "response[1] == 0xAA && response.Length > 2 && response[2] == 0x01",
        ):
            self.assertIn(required, self.text)
        self.assertIn("MakeK94Reply()", self.text)
        self.assertIn("k94Echo", self.text)
        self.assertIn("k94-independent-fixture-matches", self.text)

    def test_offline_tests_replace_placeholder_assertions(self):
        for forbidden in ('name = "default-no-requests", passed = true', "ExchangeResult timeout = new ExchangeResult()", 'name = "legal-hidpp-response", passed = ClassifyHidppResponse'):
            self.assertNotIn(forbidden, self.text)
        for required in (
            "controlled-transport-success-distinct-caps",
            "short-read-rejected",
            "pending-write-cancel-bounded",
            "cancel-not-found-completed-race",
            "unconfirmed-cancel-never-freed",
            "mouse-switch-to-mac-once-after-preflight",
        ):
            self.assertIn(required, self.text)

    def test_ssh_helper_has_fixed_entries_and_streams_stdin(self):
        for mode in ("metadata-only", "mouse-readonly", "mouse-switch-mac-once", "mouse-edge-watch", "mouse-edge-dry-run", "mouse-return-hotkey", "peer-health", "k94-via-version", "test-only"):
            self.assertIn(mode, self.helper)
        self.assertIn('python3 - "$probe_script" "$temporary_script" "$mode"', self.helper)
        self.assertIn('powershell -NoProfile -NonInteractive -Command -', self.helper)
        self.assertIn('< "$temporary_script"', self.helper)
        self.assertIn("BatchMode=yes", self.helper)
        self.assertIn("StrictHostKeyChecking=yes", self.helper)
        self.assertNotIn("--frame", self.helper)


if __name__ == "__main__":
    unittest.main()
