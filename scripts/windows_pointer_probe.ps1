param(
    [Parameter(Mandatory = $true)][int]$X,
    [Parameter(Mandatory = $true)][int]$Y
)
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class MiniOpsPointer { [DllImport("user32.dll", SetLastError=true)] public static extern bool SetCursorPos(int x, int y); }'
if (-not [MiniOpsPointer]::SetCursorPos($X, $Y)) { throw 'SetCursorPos failed' }
@{ moved = $true; x = $X; y = $Y } | ConvertTo-Json -Compress
