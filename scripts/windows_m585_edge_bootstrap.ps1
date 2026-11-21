param(
    [ValidateSet("watch", "dry-run", "pointer-test")]
    [string]$Mode = "watch"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$probe = Join-Path $root "windows_hid_protocol_probe.ps1"
$logDirectory = Join-Path $root "logs"
$logFile = Join-Path $logDirectory "m585-edge-watch.jsonl"
$env:M585_EDGE_MAC_HOST = if ($env:M585_EDGE_MAC_HOST) { $env:M585_EDGE_MAC_HOST } else { "mac-host.local" }
$env:M585_EDGE_MAC_HEALTH_PORT = if ($env:M585_EDGE_MAC_HEALTH_PORT) { $env:M585_EDGE_MAC_HEALTH_PORT } else { "8787" }
$env:M585_EDGE_WINDOWS_HEALTH_PATH = Join-Path $root "windows-health.json"

function Write-BootstrapEvent {
    param(
        [Parameter(Mandatory = $true)][string]$Event,
        [Parameter(Mandatory = $true)][string]$Result,
        [int]$ExitCode = 0
    )
    $eventObject = [pscustomobject]@{
        schema = 1
        host = "windows"
        event = $Event
        mode = $Mode
        generated_at_utc = [DateTime]::UtcNow.ToString("o")
        result = $Result
        exit_code = $ExitCode
        log_file = $logFile
        deskflow_unchanged = $true
    }
    function Escape-JsonString([string]$Value) {
        return $Value.Replace('\', '\\').Replace('"', '\"').Replace([string][char]13, '\r').Replace([string][char]10, '\n')
    }
    $json = '{"schema":1,"host":"windows","event":"' + (Escape-JsonString $Event) + '","mode":"' + $Mode + '","generated_at_utc":"' + $eventObject.generated_at_utc + '","result":"' + (Escape-JsonString $Result) + '","exit_code":' + $ExitCode + ',"log_file":"' + (Escape-JsonString $logFile) + '","deskflow_unchanged":true}'
    [System.IO.File]::AppendAllText($logFile, $json + [Environment]::NewLine, [System.Text.Encoding]::UTF8)
    [Console]::Out.WriteLine($json)
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $logFile)) { New-Item -ItemType File -Path $logFile -Force | Out-Null }
Write-BootstrapEvent -Event "bootstrap-starting" -Result "probe-output-will-be-logged"

$probeSwitch = "-WindowsEdgeWatch"
if ($Mode -eq "dry-run") { $probeSwitch = "-WindowsEdgeDryRun" }
function Read-NewChildOutput {
    param(
        [Parameter(Mandatory = $true)][System.IO.Stream]$Stream,
        [Parameter(Mandatory = $true)][bool]$IsError
    )
    if ($Stream.Length -le $Stream.Position) { return }
    $bytes = New-Object byte[] ($Stream.Length - $Stream.Position)
    $read = $Stream.Read($bytes, 0, $bytes.Length)
    if ($read -le 0) { return }
    if ($read -lt $bytes.Length) {
        $trimmed = New-Object byte[] $read
        [Array]::Copy($bytes, $trimmed, $read)
        $bytes = $trimmed
    }
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    [System.IO.File]::AppendAllText($logFile, $text, [System.Text.Encoding]::UTF8)
    if ($IsError) { [Console]::Error.Write($text) } else { [Console]::Out.Write($text) }
}

$exitCode = 0
if ($Mode -eq 'pointer-test') {
    & (Join-Path $root 'windows_pointer_probe.ps1') -X 400 -Y 450
    Start-Sleep -Milliseconds 500
    & (Join-Path $root 'windows_pointer_probe.ps1') -X 100000 -Y 450
    Start-Sleep -Milliseconds 1000
    & (Join-Path $root 'windows_pointer_probe.ps1') -X 100000 -Y 450
    exit $LASTEXITCODE
}
try {
    $stdoutPath = Join-Path $logDirectory ("probe-stdout-" + [Guid]::NewGuid().ToString("N") + ".log")
    $stderrPath = Join-Path $logDirectory ("probe-stderr-" + [Guid]::NewGuid().ToString("N") + ".log")
    $argumentText = "/c powershell.exe -NoProfile -ExecutionPolicy Bypass -File $probe $probeSwitch 1> $stdoutPath 2> $stderrPath"
    $childStartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $childStartInfo.FileName = "cmd.exe"
    $childStartInfo.Arguments = $argumentText
    $childStartInfo.WorkingDirectory = $root
    $childStartInfo.UseShellExecute = $false
    $childStartInfo.CreateNoWindow = $false
    $child = New-Object System.Diagnostics.Process
    $child.StartInfo = $childStartInfo
    [void]$child.Start()

    for ($waitAttempt = 0; $waitAttempt -lt 100 -and -not ((Test-Path -LiteralPath $stdoutPath) -and (Test-Path -LiteralPath $stderrPath)); $waitAttempt++) {
        Start-Sleep -Milliseconds 10
    }
    if (-not ((Test-Path -LiteralPath $stdoutPath) -and (Test-Path -LiteralPath $stderrPath))) {
        throw "Child output files were not created"
    }
    $stdoutStream = [System.IO.File]::Open($stdoutPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    $stderrStream = [System.IO.File]::Open($stderrPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        while (-not $child.HasExited) {
            Read-NewChildOutput -Stream $stdoutStream -IsError $false
            Read-NewChildOutput -Stream $stderrStream -IsError $true
            Start-Sleep -Milliseconds 200
        }
        $child.Refresh()
        $child.WaitForExit()
        $child.Refresh()
        Read-NewChildOutput -Stream $stdoutStream -IsError $false
        Read-NewChildOutput -Stream $stderrStream -IsError $true
        $exitCode = $child.ExitCode
    } finally {
        $stdoutStream.Dispose()
        $stderrStream.Dispose()
        Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    }
} catch {
    $exitCode = 4
    $message = $_.Exception.Message
    Write-BootstrapEvent -Event "bootstrap-error" -Result $message -ExitCode $exitCode
    Write-Error $_
} finally {
    Write-BootstrapEvent -Event "bootstrap-stopped" -Result "controller-process-returned" -ExitCode $exitCode
}

exit $exitCode
