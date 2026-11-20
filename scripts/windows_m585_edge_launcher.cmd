@echo off
setlocal

set "ROOT=%~dp0"
set "PROBE=%ROOT%windows_hid_protocol_probe.ps1"
set "LOGDIR=%ROOT%logs"
set "LOGFILE=%LOGDIR%\m585-edge-watch.jsonl"
if not defined M585_EDGE_MAC_HOST set "M585_EDGE_MAC_HOST=mac-host.local"
set "M585_EDGE_MAC_HEALTH_PORT=8787"
set "M585_EDGE_WINDOWS_HEALTH_PATH=%ROOT%windows-health.json"
set "LAUNCHER_MODE=watch"

if /I "%~1"=="dry-run" set "LAUNCHER_MODE=dry-run"
if not exist "%PROBE%" (
  echo Missing HID probe: %PROBE%
  pause
  exit /b 2
)

if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo Starting M585 edge controller in this visible window.
echo Return to Mac: Ctrl+Alt+Shift+M    Stop controller: Ctrl+Alt+Shift+X
echo JSONL log: %LOGFILE%
echo This launcher does not elevate or install anything.

if not exist "%LOGFILE%" type NUL > "%LOGFILE%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%windows_m585_edge_bootstrap.ps1" -Mode %LAUNCHER_MODE%
set "EXIT_CODE=%ERRORLEVEL%"
echo Controller exited with code %EXIT_CODE%. Close this window to remove it.
pause
exit /b %EXIT_CODE%
