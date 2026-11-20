#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
probe_script="$script_dir/windows_hid_protocol_probe.ps1"
mode="${1:-metadata-only}"

case "$mode" in
  metadata-only|mouse-readonly|mouse-switch-mac-once|mouse-edge-watch|mouse-edge-dry-run|mouse-return-hotkey|peer-health|k94-via-version|test-only)
    ;;
  *)
    echo "usage: $0 [metadata-only|mouse-readonly|mouse-switch-mac-once|mouse-edge-watch|mouse-edge-dry-run|mouse-return-hotkey|peer-health|k94-via-version|test-only]" >&2
    exit 2
    ;;
esac

temporary_script=$(mktemp "${TMPDIR:-/tmp}/windows-hid-protocol-probe.XXXXXX")
trap 'rm -f "$temporary_script"' EXIT HUP INT TERM

python3 - "$probe_script" "$temporary_script" "$mode" <<'PY'
import pathlib
import sys

source, destination, mode = sys.argv[1:]
lines = pathlib.Path(source).read_text(encoding="utf-8").splitlines()
mouse = "$true" if mode == "mouse-readonly" else "$false"
k94 = "$true" if mode == "k94-via-version" else "$false"
test = "$true" if mode == "test-only" else "$false"
lines[0] = (
    f'param([switch]$MouseReadOnly = {mouse}, '
    f'[switch]$K94ViaVersion = {k94}, '
    '[switch]$AllCandidates, '
    f'[switch]$TestOnly = {test})'
)
add_type_index = next(index for index, line in enumerate(lines) if line.lstrip().startswith("Add-Type -TypeDefinition"))
exit_two_index = next(index for index in range(add_type_index, len(lines)) if lines[index].strip() == "exit 2")
add_type_index = next(index for index in range(exit_two_index, len(lines)) if lines[index].strip() == "}")
runner_lines = []
if mode == "mouse-readonly":
    runner_lines.extend([
        "$candidates = [WindowsHidProtocolProbe]::Enumerate($false)",
        "$result = [WindowsHidProtocolProbe]::RunMouseReadonly($candidates)",
    ])
elif mode == "mouse-switch-mac-once":
    runner_lines.extend([
        "$candidates = [WindowsHidProtocolProbe]::Enumerate($false)",
        "$result = [WindowsHidProtocolProbe]::RunMouseSwitchToMac($candidates)",
    ])
elif mode == "mouse-edge-watch":
    runner_lines.extend([
        "[WindowsHidProtocolProbe]::RunWindowsEdgeWatch($false)",
    ])
elif mode == "mouse-edge-dry-run":
    runner_lines.extend([
        "[WindowsHidProtocolProbe]::RunWindowsEdgeWatch($true)",
    ])
elif mode == "mouse-return-hotkey":
    runner_lines.extend([
        "[WindowsHidProtocolProbe]::RunWindowsReturnHotKey()",
    ])
elif mode == "peer-health":
    runner_lines.extend([
        "$healthPath = if ($env:M585_EDGE_WINDOWS_HEALTH_PATH) { $env:M585_EDGE_WINDOWS_HEALTH_PATH } else { Join-Path $env:TEMP 'MiniOpsM585Edge/windows-health.json' }",
        "$result = $null",
        "if (Test-Path -LiteralPath $healthPath) {",
        "    $candidate = Get-Content -LiteralPath $healthPath -Raw | ConvertFrom-Json",
        "    $expires = [DateTime]::Parse($candidate.expires_at_utc, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()",
        "    if ($expires -gt [DateTime]::UtcNow) { $result = $candidate }",
        "}",
        "if ($null -eq $result) { $result = [WindowsHidProtocolProbe]::RunWindowsPeerHealth() }",
    ])
elif mode == "k94-via-version":
    runner_lines.extend([
        "$candidates = [WindowsHidProtocolProbe]::Enumerate($false)",
        "$result = [WindowsHidProtocolProbe]::RunK94ViaVersion($candidates)",
    ])
elif mode == "test-only":
    runner_lines.extend([
        "$result = [WindowsHidProtocolProbe]::RunOfflineTests()",
    ])
else:
    runner_lines.extend([
        "$candidates = [WindowsHidProtocolProbe]::Enumerate($false)",
        "$result = [pscustomobject]@{",
        '    Mode = "metadata-only"',
        "    HidOutputReportSent = $false",
        "    Candidates = $candidates",
        "}",
    ])
runner_lines.extend([
    "$json = ConvertTo-Json -InputObject @($result) -Depth 7",
    "[Console]::Out.WriteLine($json)",
    "return",
])
lines[add_type_index + 1:add_type_index + 1] = runner_lines
pathlib.Path(destination).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

ssh \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  "${M585_SSH_ALIAS:?Set M585_SSH_ALIAS to the Windows SSH alias}" \
  powershell -NoProfile -NonInteractive -Command - \
  < "$temporary_script"
