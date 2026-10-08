#!/usr/bin/env bash
# Sweep the camera-capture benchmark over a set of camera counts.
#
# Each step restarts PIE so the cameras registered are exactly the ones placed,
# and writes bench_result.json which is collected into bench_results.json.
#
#   Scripts/pie_tests/camera_capture/run_bench.sh 1 2 4 8
#
# Requires the editor running with the project's MCP/remote-exec enabled.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DIR="$ROOT/Scripts/pie_tests/camera_capture"
EXEC="python3 $ROOT/Scripts/editor_remote_exec.py"
COUNTS=("$@")
[ ${#COUNTS[@]} -eq 0 ] && COUNTS=(1 2 4 8)

ALL="$DIR/bench_results.json"
echo "[" > "$ALL"
FIRST=1

for N in "${COUNTS[@]}"; do
  echo "=== $N camera(s) ==="
  python3 - "$N" <<'PY'
import json, sys, os
d = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])) if False else ".", "")
p = "Scripts/pie_tests/camera_capture/bench_config.json"
cfg = json.load(open(p))
cfg["camera_count"] = int(sys.argv[1])
json.dump(cfg, open(p, "w"), indent=2)
PY
  $EXEC --code "unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()" >/dev/null 2>&1
  sleep 3
  # No `timeout`: GNU coreutils, absent on macOS, which BENCH.md documents as a
  # supported platform. editor_remote_exec.py bounds itself.
  if ! $EXEC --code "unreal.log(1)" >/dev/null 2>&1; then
    echo "  editor not responding -- aborting the sweep"; break
  fi
  $EXEC --file "$DIR/bench_setup.py" 2>&1 | grep -E "bench-setup\]|Error" || true
  $EXEC --code "unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_begin_play()" >/dev/null 2>&1
  sleep 6
  rm -f "$DIR/bench_result.json"
  $EXEC --file "$DIR/bench_capture.py" 2>&1 | grep -E "bench\]|Error" || true

  for _ in $(seq 1 240); do
    [ -f "$DIR/bench_result.json" ] && break
    sleep 2
  done
  if [ -f "$DIR/bench_result.json" ]; then
    [ $FIRST -eq 0 ] && echo "," >> "$ALL"
    cat "$DIR/bench_result.json" >> "$ALL"
    FIRST=0
    python3 -c "
import json; r=json.load(open('$DIR/bench_result.json'))
print('  %d cam: baseline %.2f ms, capture %.2f ms (+%.2f), serialize %.2f ms (+%.2f)' % (
  r['camera_count'], r['baseline']['mean_ms'], r['capture']['mean_ms'],
  r['capture'].get('over_baseline_ms',0), r['serialize']['mean_ms'],
  r['serialize'].get('over_baseline_ms',0)))"
  else
    echo "  TIMED OUT at $N cameras"
  fi
done
echo "]" >> "$ALL"
$EXEC --code "unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()" >/dev/null 2>&1
echo "results -> $ALL"
