#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
remote_dir='%TEMP%\MiniOpsM585Edge'
ssh_alias="${M585_SSH_ALIAS:-lazy-windows-ts}"
operation="${1:-status}"
mode="${2:-dry-run}"

case "$operation" in
  register-start|start|status|stop|remove)
    ;;
  *)
    echo "usage: $0 [register-start|start|status|stop|remove] [dry-run|watch|pointer-test]" >&2
    exit 2
    ;;
esac

case "$mode" in
  dry-run|watch|pointer-test)
    ;;
  *)
    echo "mode must be dry-run, watch or pointer-test" >&2
    exit 2
    ;;
esac

if [ "$operation" = "register-start" ]; then
  ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$ssh_alias" \
    -o ConnectTimeout=5 \
    "cmd /c if not exist $remote_dir mkdir $remote_dir"
  scp -q -o BatchMode=yes -o StrictHostKeyChecking=yes \
    -o ConnectTimeout=5 \
    "$script_dir/windows_hid_protocol_probe.ps1" \
    "$script_dir/windows_m585_edge_bootstrap.ps1" \
    "$script_dir/windows_m585_edge_task_controller.ps1" \
    "$script_dir/windows_pointer_probe.ps1" \
    "$script_dir/windows_input_service.ps1" \
    "$script_dir/text_clipboard_sync.py" \
    "$script_dir/windows_auxiliary_task_controller.ps1" \
    "$ssh_alias:$remote_dir/"
  ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$ssh_alias" \
    -o ConnectTimeout=5 \
    powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \
    "$remote_dir/windows_m585_edge_task_controller.ps1" -Operation register -Mode "$mode"
  ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$ssh_alias" \
    -o ConnectTimeout=5 \
    powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \
    "$remote_dir/windows_m585_edge_task_controller.ps1" -Operation start -Mode "$mode"
fi

controller_operation="$operation"
if [ "$operation" = "register-start" ]; then
  controller_operation="status"
fi

ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$ssh_alias" \
  -o ConnectTimeout=5 \
  powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \
  "$remote_dir/windows_m585_edge_task_controller.ps1" -Operation "$controller_operation" -Mode "$mode"
