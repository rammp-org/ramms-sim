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
CFG="$DIR/bench_config.json"
echo "[" > "$ALL"
FIRST=1
FAILED=0

# The sweep EDITS bench_config.json in place. Restore it on the way out --
# including on Ctrl-C -- so the next run starts from the committed defaults
# rather than inheriting whichever mode the last one happened to leave behind.
cp "$CFG" "$CFG.sweep-backup"
trap 'mv -f "$CFG.sweep-backup" "$CFG" 2>/dev/null; echo "[bench] restored $CFG"' EXIT

for N in "${COUNTS[@]}"; do
  echo "=== $N camera(s) ==="
  # Write every field the comparison depends on, not just the count. Setting
  # only camera_count left single_capture and capture_motion at whatever the
  # previous run wrote, so a sweep could silently measure a different mode than
  # the one it reports.
  python3 - "$N" "$CFG" "${SWEEP_SINGLE:-false}" "${SWEEP_MOTION:-true}" <<'PY'
import json, sys
count, path, single, motion = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
cfg = json.load(open(path))
cfg["camera_count"] = int(count)
cfg["single_capture"] = single.lower() == "true"
cfg["capture_motion"] = motion.lower() == "true"
json.dump(cfg, open(path, "w"), indent=2)
print("[bench] config: %d camera(s), single_capture=%s, capture_motion=%s"
      % (cfg["camera_count"], cfg["single_capture"], cfg["capture_motion"]))
PY
  $EXEC --code "unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()" >/dev/null 2>&1
  sleep 3
  # No `timeout`: GNU coreutils, absent on macOS, which BENCH.md documents as a
  # supported platform. editor_remote_exec.py bounds itself.
  if ! $EXEC --code "unreal.log(1)" >/dev/null 2>&1; then
    # Aborting half way through is a failure, not an early finish: without this
    # the sweep breaks out, writes a truncated results file and still exits 0.
    echo "  editor not responding -- aborting the sweep"; FAILED=1; break
  fi
  # Setup failing silently means the next phase measures the wrong camera count
  # and reports it as a result, so its exit status matters.
  if ! $EXEC --file "$DIR/bench_setup.py" 2>&1 | tee /dev/stderr | grep -qE "bench-setup\]"; then
    echo "  setup failed at $N cameras -- skipping this step"; FAILED=1; continue
  fi
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
    # A throttled run measures the editor's frame cap, not the workload, and the
    # numbers look perfectly reasonable -- so say so loudly rather than letting
    # it into the results file unremarked.
    if ! python3 -c "
import json, sys
r = json.load(open('$DIR/bench_result.json'))
print('  %d cam: baseline %.2f ms, capture %.2f ms (+%.2f), serialize %.2f ms (+%.2f)' % (
  r['camera_count'], r['baseline']['mean_ms'], r['capture']['mean_ms'],
  r['capture'].get('over_baseline_ms', 0), r['serialize']['mean_ms'],
  r['serialize'].get('over_baseline_ms', 0)))
if r.get('throttle_suspected'):
    print('  THROTTLED: every phase shares a p95, so this measures the frame cap, not capture')
    sys.exit(1)
"; then FAILED=1; fi
  else
    echo "  TIMED OUT at $N cameras"
    FAILED=1
  fi
done
echo "]" >> "$ALL"
$EXEC --code "unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()" >/dev/null 2>&1
echo "results -> $ALL"
# A partial sweep is not a sweep. Without this a timed-out or throttled step
# printed a line and the script still exited 0, so anything driving it read the
# truncated results file as complete.
if [ "$FAILED" -ne 0 ]; then
  echo "[bench] FAILED: at least one step timed out, failed setup, or was throttled"
  exit 1
fi
