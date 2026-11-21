#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <new-attempt-id>" >&2
  exit 2
fi

attempt_id=$1
case "$attempt_id" in
  ''|.*|*/*|*\\*|*' '*)
    echo "attempt id must be a non-empty path-safe token" >&2
    exit 2
    ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python="${M585_PYTHON:-$script_dir/../../research/mouse/venv/bin/python}"
guard="$script_dir/../evidence/mouse/m585-mac-to-windows-$attempt_id-guard.json"
log="$script_dir/../logs/m585-mac-to-windows-$attempt_id.json"

exec "$python" "$script_dir/m585_single_switch_experiment.py" \
  --apply \
  --expected-target-name "${M585_WINDOWS_HOST_NAME:-LAZY-WINDOWS}" \
  --confirm-single-send \
  --user-ready-rollback \
  --guard-path "$guard" \
  --log-path "$log"
