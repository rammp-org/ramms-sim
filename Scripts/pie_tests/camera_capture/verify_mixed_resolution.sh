#!/usr/bin/env bash
# Drive the mixed-resolution readback-pool regression test end to end.
#
#   Scripts/pie_tests/camera_capture/verify_mixed_resolution.sh [seconds]
#
# Requires the editor running with remote exec reachable. Places four cameras at
# three distinct colour resolutions, captures for a few seconds, then checks the
# two things that actually matter:
#
#   1. the log carries no "geometry does not hold" -- one hit is a failure, since
#      each one is a DROPPED frame
#   2. every camera wrote the same number of frames -- a camera starved of a
#      correctly shaped readback writes fewer, or none
#
# Bash, not zsh: zsh does not word-split unquoted expansions, and a function body
# that relies on it silently no-ops.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DIR="$ROOT/Scripts/pie_tests/camera_capture"
EXEC="python3 $ROOT/Scripts/editor_remote_exec.py"
SECONDS_TO_RUN="${1:-10}"
OUT="$ROOT/camera_capture_mixedres"

if ! timeout 60 $EXEC --code "unreal.log(1)" >/dev/null 2>&1; then
  echo "FAIL: no editor responded to remote exec"; exit 1
fi

# A fresh output tree, so file counts describe this run only.
rm -rf "$OUT"

$EXEC --code "unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()" >/dev/null 2>&1
sleep 3
$EXEC --file "$DIR/setup_mixed_resolution.py" 2>&1 | grep -E "mixedres\]|Error" || true

# Note the log size first, so the grep below only ever sees THIS run.
# On macOS the editor log is under ~/Library/Logs, not the project's Saved/Logs.
LOG="$HOME/Library/Logs/Unreal Engine/RammsEditor/Ramms.log"
[ -f "$LOG" ] || LOG="$ROOT/Saved/Logs/Ramms.log"
BEFORE=0
[ -f "$LOG" ] && BEFORE=$(wc -l < "$LOG")

$EXEC --code "unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_begin_play()" >/dev/null 2>&1
sleep "$SECONDS_TO_RUN"
$EXEC --code "unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()" >/dev/null 2>&1
sleep 3

FAILED=0

echo "=== geometry errors in this run"
if [ -f "$LOG" ]; then
  HITS=$(tail -n "+$((BEFORE + 1))" "$LOG" | grep -c "geometry does not hold" || true)
  echo "  $HITS"
  [ "$HITS" -gt 0 ] && FAILED=1
  tail -n "+$((BEFORE + 1))" "$LOG" | grep "geometry does not hold" | sort -u | head -5
else
  echo "  log not found at $LOG -- cannot check"; FAILED=1
fi

echo "=== frames per camera"
# Only this test's cameras, and only the LEAF directories. The tree is
# <out>/<actor>/<camera>, so counting both levels double-counts; and the level's
# own robot carries capture cameras that register themselves, whose frame count
# differs simply because they start later. Their presence is useful -- more
# shapes in the same pool -- but they are not what this asserts on.
if [ -d "$OUT" ]; then
  COUNTS=$(find "$OUT" -type d -name 'MixedResCam_*' | while read -r d; do
    n=$(find "$d" -name 'frame_*.exr' | wc -l | tr -d ' ')
    echo "$n $(basename "$d")"
  done | sort -rn)
  echo "$COUNTS" | sed 's/^/  /'
  echo "  (other cameras in the level, for context:)"
  find "$OUT" -type d -not -name 'MixedResCam_*' -mindepth 2 | while read -r d; do
    n=$(find "$d" -name 'frame_*.exr' | wc -l | tr -d ' ')
    [ "$n" -gt 0 ] && echo "    $n $(basename "$d")"
  done
  NUM=$(echo "$COUNTS" | grep -c . || true)
  ZEROS=$(echo "$COUNTS" | awk '$1 == 0' | wc -l | tr -d ' ')
  MAX=$(echo "$COUNTS" | awk 'NR==1 {print $1}')
  MIN=$(echo "$COUNTS" | awk 'END {print $1}')
  SPREAD=$((MAX - MIN))
  echo "  spread: $SPREAD frame(s) (max $MAX, min $MIN)"
  [ "$NUM" -lt 4 ] && { echo "  FAIL: expected 4 cameras with a directory, got $NUM"; FAILED=1; }
  [ "$ZEROS" -gt 0 ] && { echo "  FAIL: $ZEROS camera(s) wrote nothing"; FAILED=1; }
  # A few frames of slack: capture starts and stops asynchronously, so the first
  # and last frames can land for some cameras and not others. The failure this
  # guards against is not a frame or two -- it is a camera starved of a correctly
  # shaped readback, which loses EVERY frame.
  if [ "$SPREAD" -gt 5 ]; then
    echo "  FAIL: frame counts differ by $SPREAD frames across cameras"; FAILED=1
  fi
else
  echo "  no output directory -- nothing captured at all"; FAILED=1
fi

[ "$FAILED" -eq 0 ] && echo "=== PASS" || echo "=== FAIL"
exit "$FAILED"
