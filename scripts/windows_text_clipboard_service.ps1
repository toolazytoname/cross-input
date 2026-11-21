param(
    [Parameter(Mandatory = $true)][string]$Python,
    [Parameter(Mandatory = $true)][string]$Script,
    [Parameter(Mandatory = $true)][string]$SecretFile,
    [Parameter(Mandatory = $true)][string]$SequenceFile,
    [Parameter(Mandatory = $true)][string]$ListenAddress,
    [Parameter(Mandatory = $true)][string]$PeerAddress,
    [Parameter(Mandatory = $true)][string]$LogDirectory
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $LogDirectory | Out-Null
$logFile = Join-Path $LogDirectory 'clipboard-service.jsonl'
function Write-Event($Name, $Data) {
    $entry = @{ event = $Name; utc = [DateTime]::UtcNow.ToString('o'); data = $Data } | ConvertTo-Json -Compress
    Add-Content -LiteralPath $logFile -Value $entry -Encoding UTF8
}

$reader = $null
$inFlight = $null
try {
    $reader = New-Object System.Diagnostics.Process
    $reader.StartInfo.FileName = $Python
    $reader.StartInfo.Arguments = '"' + $Script + '" --host windows --listen ' + $ListenAddress + ' --peer ' + $PeerAddress + ' --secret-file "' + $SecretFile + '" --sequence-file "' + $SequenceFile + '" --receive-only'
    $reader.StartInfo.UseShellExecute = $false
    $reader.StartInfo.CreateNoWindow = $true
    $readerLog = Join-Path $LogDirectory 'clipboard-receiver.jsonl'
    $reader.StartInfo.FileName = 'cmd.exe'
    $reader.StartInfo.Arguments = '/c ""' + $Python + '" "' + $Script + '" --host windows --listen ' + $ListenAddress + ' --peer ' + $PeerAddress + ' --secret-file "' + $SecretFile + '" --sequence-file "' + $SequenceFile + '" --receive-only 1>>"' + $readerLog + '" 2>&1"'
    $reader.StartInfo.RedirectStandardOutput = $false
    $reader.StartInfo.RedirectStandardError = $false
    $reader.StartInfo.EnvironmentVariables['M585_APPLIED_MARKER'] = Join-Path $LogDirectory 'last-applied.sha256'
    [void]$reader.Start()
    Write-Event 'receiver-started' @{ pid = $reader.Id }

    Add-Type -AssemblyName System.Windows.Forms
    $sha = [Security.Cryptography.SHA256]::Create()
    $lastSentHash = $null
    $appliedLog = Join-Path $LogDirectory 'last-applied.sha256'
    while (-not $reader.HasExited) {
        try {
            $text = [System.Windows.Forms.Clipboard]::GetText([System.Windows.Forms.TextDataFormat]::UnicodeText)
            if (-not [string]::IsNullOrEmpty($text) -and [Text.Encoding]::UTF8.GetByteCount($text) -le 262144) {
                $hash = [Convert]::ToBase64String($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($text)))
                $applied = if (Test-Path $appliedLog) { (Get-Content $appliedLog -Raw).Trim() } else { '' }
                if ($hash -eq $applied) {
                    $lastSentHash = $null
                    Remove-Item $appliedLog -Force
                } elseif ($null -eq $inFlight -and $hash -ne $lastSentHash) {
                    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text))
                    $sendHash = $hash
                    $inFlight = New-Object System.Diagnostics.Process
                    $inFlight.StartInfo.FileName = $Python
                    $inFlight.StartInfo.Arguments = '"' + $Script + '" --send-text "' + $encoded + '" --peer ' + $PeerAddress + ' --secret-file "' + $SecretFile + '" --sequence-file "' + $SequenceFile + '"'
                    $inFlight.StartInfo.UseShellExecute = $false
                    $inFlight.StartInfo.CreateNoWindow = $true
                    $inFlight.StartInfo.RedirectStandardOutput = $true
                    $inFlight.StartInfo.RedirectStandardError = $true
                    [void]$inFlight.Start()
                    Write-Event 'send-started' @{ size = [Text.Encoding]::UTF8.GetByteCount($text) }
                }
            }
        } catch { Write-Event 'clipboard-error' @{ type = $_.Exception.GetType().Name } }
        if ($null -ne $inFlight -and $inFlight.HasExited) {
            $stdout = $inFlight.StandardOutput.ReadToEnd()
            $stderr = $inFlight.StandardError.ReadToEnd()
            if ($inFlight.ExitCode -eq 0) { $lastSentHash = $sendHash }
            Write-Event 'send-finished' @{ code = $inFlight.ExitCode; output = $stdout; error = $stderr }
            $inFlight.Dispose()
            $inFlight = $null
        }
        Start-Sleep -Milliseconds 250
    }
} catch {
    Write-Event 'service-error' @{ type = $_.Exception.GetType().Name; message = $_.Exception.Message }
    exit 1
} finally {
    if ($null -ne $reader -and -not $reader.HasExited) { $reader.Kill() }
    if ($null -ne $inFlight -and -not $inFlight.HasExited) { $inFlight.Kill() }
}
