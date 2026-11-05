#!/bin/bash
# PIE: RAMMP Gen1 curb assist on Map_RammpGen1Curb_URL, from the outdoor stance (front arm -14 deg, elevators 9 deg).
# The gamepad's A switches it on (curb.assist); held forward at the 15 cm platform, a crossing starts on its own;
# pulled back before a wheel has lifted, it cancels and the lifts go back; switched off, driving at the curb starts
# nothing; on again and held forward, it climbs -- pausing, nothing moving, while the stick is let go mid-crossing --
# and, held forward again, drives on to the platform's far edge and goes down it, every lift back where it was after
# each crossing.
# Needs a running editor (Scripts/editor_remote_exec.py) and the input maps from make_input_assets.py; PYTHON
# overrides the interpreter. Exit status: nonzero unless every check passes (PIE is still ended).
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
cleanup(){ op release_stick; op end; sleep 3; }
trap cleanup EXIT
poll(){ if ! R=$(op "$@"); then echo "$R"; echo "!! the poll '$*' failed"; FAIL=1; return 1; fi; }
# Wait (up to $2 s) until the curb report matches the glob $1.
wait_curb(){ for i in $(seq 1 $(( $2 * 2 ))); do poll curb || return 1; case "$R" in $1) echo "$R"; return 0;; esac; sleep 0.5; done
             echo "$R"; echo "!! waited $2 s for $1"; FAIL=1; return 1; }
press_a(){ op pad_key Gamepad_FaceButton_Bottom down; sleep 0.3; op pad_key Gamepad_FaceButton_Bottom up; sleep 0.5; }

op begin || exit 1
sleep 25
echo "--- the outdoor stance; curb assist off at spawn ---"
op set lift.front_caster_swing_arm -14; op set lift.motor_swing_arm_l 9; op set lift.motor_swing_arm_r 9; sleep 4
op expect_control curb.assist -0.1 0.1
echo "--- A: curb assist on ---"
press_a; op expect_control curb.assist 0.9 1.1

echo "--- held forward toward the curb (its face at x 300), a crossing starts; held back as it approaches, it cancels ---"
op mark_lifts
op hold_stick 0.4
wait_curb "*APPROACH*" 30
op hold_stick -0.6
wait_curb "*ABORTED*cancelled*" 15
op release_stick; sleep 2
op expect_lifts_back 0.5 0.5

echo "--- A: off; driving forward at the curb starts nothing ---"
press_a; op expect_control curb.assist -0.1 0.1
op hold_stick 0.25; sleep 1; op release_stick; sleep 2
poll curb && case "$R" in *ABORTED*cancelled*) echo "$R";; *) echo "$R"; echo "!! a crossing started with curb assist off"; FAIL=1;; esac

echo "--- A: on; held forward it climbs, and pauses mid-crossing while the stick is let go ---"
press_a; op expect_control curb.assist 0.9 1.1
op mark_lifts
op hold_stick 0.6
if wait_curb "*DRIVE_UP*" 40; then
    op release_stick; sleep 1.5
    poll curb; BEFORE=$(echo "$R" | sed 's/.*curb \([A-Z_]*\).*/\1/')
    op mark_body chassis; sleep 3; op expect_body_moved chassis 0 1
    poll curb; AFTER=$(echo "$R" | sed 's/.*curb \([A-Z_]*\).*/\1/')
    echo "$R"
    if [ "$BEFORE" != "$AFTER" ]; then echo "!! the crossing went on while the stick was let go ($BEFORE -> $AFTER)"; FAIL=1; fi
    op hold_stick 0.6
fi
# Each crossing's lifts checked at rest: let go once it is done (driving on, the loaded translators and rear give a
# little), then held forward again.
wait_curb "*DONE*crossed up 15.0*" 90; op release_stick; sleep 2; op expect_lifts_back 0.5 0.5
echo "--- held forward again, it drives on to the far edge (x 600) and goes down it ---"
op mark_lifts
op hold_stick 0.6
wait_curb "*DONE*crossed down 15.0*" 90; op release_stick; sleep 2; op expect_lifts_back 0.5 0.5
op state

trap - EXIT
cleanup
if [ "$FAIL" -ne 0 ]; then echo "RAMMP GEN1 CURB ASSIST CHECKS FAILED"; else echo "all RAMMP Gen1 curb assist checks passed"; fi
exit "$FAIL"
