param(
    [ValidateSet('register', 'start', 'stop', 'remove', 'status')][string]$Operation = 'status',
    [ValidateSet('keyboard', 'clipboard')][string]$Service = 'keyboard',
    [string]$Python = 'D:\Apps\Python\cpython-3.12.15-windows-x86_64-none\python.exe',
    [string]$MacAddress = '192.168.1.4',
    [string]$WindowsAddress = '192.168.1.8'
)

$ErrorActionPreference = 'Stop'
$root = Join-Path $env:TEMP 'MiniOpsM585Edge'
$taskName = 'MiniOpsCrossInput' + $Service
$secret = Join-Path $root ($Service + '.secret')
$script = Join-Path $root $(if ($Service -eq 'keyboard') { 'windows_input_service.ps1' } else { 'windows_text_clipboard_service.ps1' })
$arguments = '-NoProfile -STA -ExecutionPolicy Bypass -File "' + $script + '" '
if ($Service -eq 'keyboard') {
    $arguments += '-SecretFile "' + $secret + '" -ListenAddress ' + $WindowsAddress + ' -LogDirectory "' + (Join-Path $root 'logs') + '"'
} else {
    $arguments += '-Python "' + $Python + '" -Script "' + (Join-Path $root 'text_clipboard_sync.py') + '" -SecretFile "' + $secret + '" -SequenceFile "' + (Join-Path $root 'clipboard-live.sequence') + '" -ListenAddress ' + $WindowsAddress + ' -PeerAddress ' + $MacAddress + ' -LogDirectory "' + (Join-Path $root 'logs') + '"'
}
$arguments += ' 1>"' + (Join-Path $root ($Service + '.stdout.log')) + '" 2>"' + (Join-Path $root ($Service + '.stderr.log')) + '"'

switch ($Operation) {
    'register' {
        $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c powershell.exe ' + $arguments) -WorkingDirectory $root
        $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
        @{ task = $taskName; registered = $true } | ConvertTo-Json -Compress
    }
    'start' { Start-ScheduledTask -TaskName $taskName; @{ task = $taskName; started = $true } | ConvertTo-Json -Compress }
    'stop' { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue; @{ task = $taskName; stopped = $true } | ConvertTo-Json -Compress }
    'remove' { Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue; @{ task = $taskName; removed = $true } | ConvertTo-Json -Compress }
    'status' {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        @{ task = $taskName; state = if ($task) { [int]$task.State } else { 0 } } | ConvertTo-Json -Compress
    }
}
