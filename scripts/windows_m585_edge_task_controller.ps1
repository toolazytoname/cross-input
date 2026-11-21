param(
    [ValidateSet("register", "start", "status", "stop", "remove")]
    [string]$Operation = "status",
    [ValidateSet("dry-run", "watch", "pointer-test")]
    [string]$Mode = "dry-run"
)

$ErrorActionPreference = "Stop"
$taskName = "MiniOpsM585EdgeWatch"
$root = Join-Path $env:TEMP "MiniOpsM585Edge"
$bootstrap = Join-Path $root "windows_m585_edge_bootstrap.ps1"

function Convert-ToJsonLine {
    param($Value)
    ConvertTo-Json -InputObject $Value -Depth 6 -Compress
}

switch ($Operation) {
    "register" {
        if (-not (Test-Path -LiteralPath $bootstrap)) {
            throw "Missing bootstrap: $bootstrap"
        }
        $actionArguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Normal -File $bootstrap -Mode $Mode"
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArguments -WorkingDirectory $root
        $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive
        $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
        Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null
        Convert-ToJsonLine (@{
            operation = "register"
            task_name = $taskName
            mode = $Mode
            registered = $true
        })
    }
    "start" {
        if ($Mode -eq 'pointer-test') {
            Start-ScheduledTask -TaskName $taskName
            return
        }
        Start-ScheduledTask -TaskName $taskName
        Convert-ToJsonLine (@{ operation = "start"; task_name = $taskName; started = $true })
    }
    "status" {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction SilentlyContinue
        $processes = @(
            Get-CimInstance Win32_Process |
                Where-Object { $_.CommandLine -match "windows_m585_edge_bootstrap\\.ps1" } |
                Select-Object ProcessId,ParentProcessId,SessionId,CommandLine
        )
        Convert-ToJsonLine (@{
            operation = "status"
            task_name = $taskName
            task = $task
            info = $info
            processes = $processes
        })
    }
    "stop" {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Convert-ToJsonLine (@{ operation = "stop"; task_name = $taskName; stop_requested = $true })
    }
    "remove" {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
        Convert-ToJsonLine (@{ operation = "remove"; task_name = $taskName; removed = $true })
    }
}
