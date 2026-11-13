#!/bin/bash
# PIE: the RAMMP Gen1 curb controller climbs Map_RammpGen1Curb_URL's 15 cm platform and descends its far edge, each
# started with curb.negotiate within 1.5 m of the edge, from a stance it must end in again. STANCE=outdoor (the
# default: front arm -14 deg, the front omni wheels up; elevators 9 deg, for ground clearance) or reference (every
# lift at 0, every wheel down). STYLE=rolling (the default: it rolls through each crossing, as the real robot does)
# or stepped (it stops for each step), set on curb.style. Needs a running editor (Scripts/editor_remote_exec.py);
# PYTHON overrides the interpreter. Exit status: nonzero unless both crossings finish back in the stance (PIE is
# still ended).
S=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$S/../.." && pwd); cd "$ROOT" || exit 1
PY=${PYTHON:-}
if [ -z "$PY" ]; then
    for c in python3 python "/c/Program Files/Epic Games/UE_5.8/Engine/Binaries/ThirdParty/Python3/Win64/python.exe"; do
        if "$c" -c "import sys" >/dev/null 2>&1; then PY=$c; break; fi
    done
fi
[ -n "$PY" ] || { echo "!! no Python found: set PYTHON"; exit 1; }
FAIL=0
op(){ if ! "$PY" Scripts/editor_remote_exec.py --code "unreal._ramms_rammp_gen1_op='$*'" >/dev/null 2>&1; then
          echo "!! could not set the op '$*'"; FAIL=1; return 1; fi
      "$PY" Scripts/editor_remote_exec.py --file "$S/rammp_gen1_op.py" 2>&1 | grep -E "\[rammp_gen1\]|Error\]" | sed 's/^\[Info\] //; s/^\[Error\] //'
      local st=${PIPESTATUS[0]}; if [ "$st" -ne 0 ]; then echo "!! $* failed"; FAIL=1; fi; return "$st"; }
cleanup(){ op end; sleep 3; }
trap cleanup EXIT   # early exits; the normal end runs cleanup itself, so its result counts

# A poll captured in $(...) runs op in a subshell, where its FAIL=1 is lost: poll() latches FAIL here and prints
# what the failed poll said.
poll(){ if ! R=$(op "$@"); then echo "$R"; echo "!! the poll '$*' failed"; FAIL=1; return 1; fi; }
# Drive forward until the chassis passes x (cm): one poll per call, so the simulation runs between them.
drive_to(){ for i in $(seq 1 200); do poll drive_to "$1" 0.4 || { op release drive.forward; return 1; }
                case "$R" in *arrived*) echo "$R"; return 0;; esac; sleep 0.15; done
            op release drive.forward; echo "!! did not reach x $1"; FAIL=1; return 1; }
# Start a crossing and wait for it to end; it must end Done with the expected outcome. It goes only while the rider's
# stick is held forward: held through it, let go as it ends. While it runs the arm is held: a command to it is refused.
cross(){ op trigger curb.negotiate || return 1
         op hold_stick 0.6 crossing
         sleep 3; op expect_refused arm.up 1
         for i in $(seq 1 60); do sleep 5; poll curb || { op release_stick; return 1; }
             case "$R" in *DONE*|*ABORTED*|*IDLE*) echo "$R"; op release_stick; case "$R" in *DONE*"$1"*) return 0;; esac; echo "!! the crossing did not finish: $1"; FAIL=1; return 1;; esac
         done; op release_stick; echo "!! the crossing timed out"; FAIL=1; return 1; }

# The stance: the front arm's and the elevators' angles (deg). A crossing must end with every lift back where it was
# before it (half a degree, half a centimetre).
case "${STANCE:-outdoor}" in
    outdoor) FRONT=-14; ELEV=9;;
    reference) FRONT=0; ELEV=0;;
    *) echo "!! STANCE is outdoor or reference, not $STANCE"; exit 1;;
esac
case "${STYLE:-rolling}" in
    rolling) STYLE_V=1;;
    stepped) STYLE_V=0;;
    *) echo "!! STYLE is rolling or stepped, not $STYLE"; exit 1;;
esac
rad(){ awk -v d="$1" -v t="$2" 'BEGIN { r = d * 3.14159265 / 180; t = t * 3.14159265 / 180; printf "%.4f %.4f", r - t, r + t }'; }
back(){ op expect_lifts_back 0.5 0.5; }

op begin || exit 1
sleep 25
echo "--- crossings: ${STYLE:-rolling} ---"
op set curb.style "$STYLE_V"; op expect_control curb.style $((STYLE_V)).0 $((STYLE_V)).0
echo "--- the stance: ${STANCE:-outdoor} (front arm $FRONT deg, elevators $ELEV deg) ---"
op set lift.front_caster_swing_arm "$FRONT"; op set lift.motor_swing_arm_l "$ELEV"; op set lift.motor_swing_arm_r "$ELEV"; sleep 4
# Loaded, the lifts sit up to about 2 deg short of their commands (the elevators reach 7.3 deg of 9).
op expect_motor front_arm $(rad "$FRONT" 2.5); op expect_motor elevator_l $(rad "$ELEV" 2.5); op expect_motor elevator_r $(rad "$ELEV" 2.5)
echo "--- climb: the 15 cm platform's near face is at x 300; the arm out, for the crossing to stow ---"
op set arm.up 1; sleep 1; op release arm.up; sleep 1; op expect_control arm.stowed -0.1 0.1
drive_to 150 && sleep 2 && op mark_lifts && cross "crossed up 15.0" && back; op stats
op expect_control arm.stowed 0.9 1.1
echo "--- descent: its far edge is at x 600 ---"
drive_to 450 && sleep 2 && op mark_lifts && cross "crossed down 15.0" && back; op stats
op state

trap - EXIT
cleanup
if [ "$FAIL" -ne 0 ]; then echo "RAMMP GEN1 CURB CHECKS FAILED"; else echo "all RAMMP Gen1 curb checks passed"; fi
exit "$FAIL"
