#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
remote_dir='%TEMP%\MiniOpsM585Edge'
ssh_alias="${M585_SSH_ALIAS:?Set M585_SSH_ALIAS to the Windows SSH alias}"

ssh \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  "$ssh_alias" \
  cmd /c "if not exist $remote_dir mkdir $remote_dir"

scp \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  "$script_dir/windows_hid_protocol_probe.ps1" \
  "$script_dir/windows_m585_edge_bootstrap.ps1" \
  "$script_dir/windows_m585_edge_task_controller.ps1" \
  "$script_dir/windows_m585_edge_launcher.cmd" \
  "$ssh_alias:$remote_dir/"

printf 'Copied launcher to Windows TEMP: %s\n' "$remote_dir"
printf 'User-run launcher: %s\\windows_m585_edge_launcher.cmd\n' "$remote_dir"
printf 'Optional first run: add the argument dry-run. No service or scheduled task was created.\n'
