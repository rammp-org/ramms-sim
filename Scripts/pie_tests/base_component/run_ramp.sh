#!/bin/bash
# Chaos PIE stop-on-a-ramp test on Map_RampTest (make_ramp_map.py builds the map):
# the chair drives up, then down, a 1:12 and a 1:8 ramp, is let go on the slope, and must stay put.
# Exit status: nonzero if any editor command failed (PIE is still ended).
S=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$S/../../.." && pwd); cd "$ROOT" || exit 1
FAIL=0
f(){ python3 Scripts/editor_remote_exec.py --file "$1" 2>&1 | grep -E "\[ramp\]|\[pie\]|Traceback|Error|^ERROR" | sed 's/.*LogPython: //'
     local st=${PIPESTATUS[0]}; if [ "$st" -ne 0 ]; then echo "!! $(basename "$1") failed (exit $st)"; FAIL=1; fi; return "$st"; }
setop(){ local var="$1"; shift
     if ! python3 Scripts/editor_remote_exec.py --code "unreal._ramms_${var}='$*'" >/dev/null 2>&1; then
         echo "!! could not set _ramms_${var}='$*'"; FAIL=1; return 1; fi; }
op(){ local var="$1" script="$2"; shift 2; setop "$var" "$@" || return 1; f "$script"; }
cleanup(){ f "$S/pie_end.py"; sleep 4; }
trap cleanup EXIT

f "$S/pie_begin_ramp.py" || exit 1
sleep 12
for lane in A B Ad Bd; do
    echo "--- lane $lane: drive ${lane:1:1}, let go on the slope, hold ---"
    op ramp_op "$S/chaos_ramp.py" go "$lane"
    # 1 s settle after the teleport + up to ~8 s to the release point + 2 s settle + 6 s hold
    sleep 20
    op ramp_op "$S/chaos_ramp.py" check "$lane"
done
trap - EXIT; cleanup
[ "$FAIL" -eq 0 ] && echo "=== run_ramp: PASS" || echo "=== run_ramp: FAIL"
exit "$FAIL"
