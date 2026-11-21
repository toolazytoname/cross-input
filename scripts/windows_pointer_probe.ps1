param(
    [Parameter(Mandatory = $true)][int]$X,
    [Parameter(Mandatory = $true)][int]$Y,
    [switch]$ReportOnly
)
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class MiniOpsPointer { [DllImport("user32.dll", SetLastError=true)] public static extern bool SetCursorPos(int x, int y); [DllImport("user32.dll")] public static extern int GetSystemMetrics(int index); }'
$X = if ($ReportOnly) { 0 } else { [MiniOpsPointer]::GetSystemMetrics(76) + [MiniOpsPointer]::GetSystemMetrics(78) }
if (-not [MiniOpsPointer]::SetCursorPos($X, $Y)) { throw 'SetCursorPos failed' }
@{ moved = $true; x = $X; y = $Y; virtual_right = $X } | ConvertTo-Json -Compress
