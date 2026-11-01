#!/bin/bash
# PIE: the MeBot curb controller climbs Map_MebotCurb_URL's 15 cm platform and descends its far edge, each
# started with curb.negotiate within 1.5 m of the edge. Needs a running editor (Scripts/editor_remote_exec.py);
# PYTHON overrides the interpreter. Exit status: nonzero unless both crossings finish (PIE is still ended).
S=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$S/../.." && pwd); cd "$ROOT" || exit 1
PY=${PYTHON:-python3}
FAIL=0
op(){ if ! "$PY" Scripts/editor_remote_exec.py --code "unreal._ramms_mebot_op='$*'" >/dev/null 2>&1; then
          echo "!! could not set the op '$*'"; FAIL=1; return 1; fi
      "$PY" Scripts/editor_remote_exec.py --file "$S/mebot_op.py" 2>&1 | grep -E "\[mebot\]|Error\]" | sed 's/^\[Info\] //; s/^\[Error\] //'
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
# Start a crossing and wait for it to end; it must end Done with the expected outcome. While it runs the arm is held:
# a command to it is refused.
cross(){ op trigger curb.negotiate || return 1
         sleep 3; op expect_refused arm.up 1
         for i in $(seq 1 60); do sleep 5; poll curb || return 1
             case "$R" in *DONE*|*ABORTED*|*IDLE*) echo "$R"; case "$R" in *DONE*"$1"*) return 0;; esac; echo "!! the crossing did not finish: $1"; FAIL=1; return 1;; esac
         done; echo "!! the crossing timed out"; FAIL=1; return 1; }

op begin || exit 1
sleep 25
echo "--- climb: the 15 cm platform's near face is at x 300; the arm out, for the crossing to stow ---"
op set arm.up 1; sleep 1; op release arm.up; sleep 1; op expect_control arm.stowed -0.1 0.1
drive_to 150 && sleep 2 && cross "crossed up 15.0"
op expect_control arm.stowed 0.9 1.1
echo "--- descent: its far edge is at x 600 ---"
drive_to 450 && sleep 2 && cross "crossed down 15.0"
op state

trap - EXIT
cleanup
if [ "$FAIL" -ne 0 ]; then echo "MEBOT CURB CHECKS FAILED"; else echo "all MeBot curb checks passed"; fi
exit "$FAIL"
