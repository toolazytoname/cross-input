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
$script = Join-Path $root $(if ($Service -eq 'keyboard') { 'windows_input_service.ps1' } else { 'text_clipboard_sync.py' })
$arguments = if ($Service -eq 'keyboard') { '-NoProfile -STA -ExecutionPolicy Bypass -File "' + $script + '" ' } else { '' }
if ($Service -eq 'keyboard') {
    $arguments += '-SecretFile "' + $secret + '" -ListenAddress ' + $WindowsAddress + ' -LogDirectory "' + (Join-Path $root 'logs') + '"'
} else {
    $script = Join-Path $root 'text_clipboard_sync.py'
    $arguments = '"' + $script + '" --host windows --listen ' + $WindowsAddress + ' --peer ' + $MacAddress + ' --secret-file "' + $secret + '" --sequence-file "' + (Join-Path $root 'clipboard-live.sequence') + '"'
}
if ($Service -eq 'keyboard') { $arguments += ' 1>"' + (Join-Path $root ($Service + '.stdout.log')) + '" 2>"' + (Join-Path $root ($Service + '.stderr.log')) + '"' }

switch ($Operation) {
    'register' {
        $executable = 'cmd.exe'
        $actionArguments = if ($Service -eq 'keyboard') { '/c powershell.exe ' + $arguments } else { '/c ""' + $Python + '" ' + $arguments + ' 1>"' + (Join-Path $root 'clipboard.stdout.log') + '" 2>"' + (Join-Path $root 'clipboard.stderr.log') + '""' }
        $action = New-ScheduledTaskAction -Execute $executable -Argument $actionArguments -WorkingDirectory $root
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
