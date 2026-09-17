#!/bin/bash
# MuJoCo PIE drive + 5-bar test on Map_BaseTest_URL with BP_LiftDriveLinkage_Ramms.
# Exit status: nonzero if any editor command failed (the teardown/restore still run).
S=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$S/../../.." && pwd); cd "$ROOT" || exit 1
FAIL=0
# Run one script in the editor; keep the Python exit status (the filters only shape the output).
f(){ python3 Scripts/editor_remote_exec.py --file "$1" 2>&1 | grep -E "\[setup\]|\[run\]|\[st\]|\[drv\]|\[lift\]|\[t3\]|\[pie\]|\[restore\]|\[turn\]|\[cs\]|\[ci\]|\[hud\]|Traceback|Error|^ERROR" | sed 's/.*LogPython: //' | grep -v "manager AMjManager_1 props"
     local st=${PIPESTATUS[0]}; if [ "$st" -ne 0 ]; then echo "!! $(basename "$1") failed (exit $st)"; FAIL=1; fi; return "$st"; }
# Set an operation variable in the editor, then run its check script. The
# assignment's exit status matters: editor_remote_exec.py returns nonzero when
# the editor command fails, and a silently failed assignment would leave the
# previous op in place, so the next script would re-run that one and the runner
# could report PASS without ever exercising the operation asked for.
setop(){ local var="$1"; shift
     if ! python3 Scripts/editor_remote_exec.py --code "unreal._ramms_${var}='$*'" >/dev/null 2>&1; then
         echo "!! could not set _ramms_${var}='$*'"; FAIL=1; return 1; fi; }
op(){ local var="$1" script="$2"; shift 2; setop "$var" "$@" || return 1; f "$script"; }
cs(){ op cs_op "$S/control_surface_check.py" "$@"; }
cleanup(){ f "$S/mj_teardown.py"; sleep 5; f "$S/mj_restore.py"; }
trap cleanup EXIT

f "$S/mj_setup.py" || exit 1
sleep 20
f "$S/mj_run.py"; sleep 2
echo "--- drive ---"; f "$S/mj_drive.py"; sleep 1; f "$S/mj_state.py"; sleep 3; f "$S/mj_state.py"
echo "--- turn: X=+1 must turn right ---"
op turn_op "$S/mj_turn.py" start; sleep 3
op turn_op "$S/mj_turn.py" check; sleep 1
echo "--- linkage height: bottom of the reachable range (extend centre wheels) ---"
op lift_z "$S/mj_lift.py" lo; sleep 3; f "$S/mj_t3.py"; f "$S/mj_state.py"
echo "--- linkage height: top of the reachable range (retract) ---"
op lift_z "$S/mj_lift.py" hi; sleep 3; f "$S/mj_t3.py"; f "$S/mj_state.py"
echo "--- control surface: raw motors, camera actions ---"
cs describe
cs trigger camera.next
cs registry
echo "--- Enhanced Input -> surface (injected actions): W, Q, N, P, Backspace ---"
ci(){ op ci_op "$S/control_input_check.py" "$@"; }
ci status; ci urlab
# 6 s hold: a value assertion costs one remote-exec round trip (0.5-2 s under
# editor load), so a shorter hold can lapse before the check and read 0.
ci inject IA_Ramms_Drive 0 1 0 6.0; sleep 0.3; ci expect drive.forward 0.99 1.01; sleep 6; ci expect drive.forward -0.01 0.01; f "$S/mj_state.py"
ci inject IA_Ramms_LinkageHeight -1 0 0 1.0; sleep 2.5; ci expect linkage.LeftCenterLinkage.height 2 8; ci expect linkage.RightCenterLinkage.height 2 8
ci camera; ci inject IA_Ramms_CameraNext 1 0 0 0.2; sleep 0.5; ci camera; ci camera_changed
ci inject IA_Ramms_SimPause 1 0 0 0.2; sleep 0.6; ci expect sim.running -0.1 0.1
ci inject IA_Ramms_SimPause 1 0 0 0.2; sleep 0.6; ci expect sim.running 0.9 1.1
ci inject IA_Ramms_SimReset 1 0 0 0.2; sleep 1.5; f "$S/mj_state.py"
echo "--- control HUD (ramms-ui panel + joystick, auto-spawned) ---"
hud(){ op hud_op "$S/hud_check.py" "$@"; }
hud status
hud joystick 0 -1; ci expect drive.forward 0.99 1.01; sleep 1.5; f "$S/mj_state.py"; hud joystick_release; ci expect drive.forward -0.01 0.01; sleep 0.5
hud action sim.pause; sleep 0.5; ci expect sim.running -0.1 0.1; hud action sim.pause; sleep 0.5; ci expect sim.running 0.9 1.1
echo "--- sim controls: pause, resume, reset ---"
cs trigger sim.pause; sleep 1; ci expect sim.running -0.1 0.1
cs set sim.running 1; sleep 1; ci expect sim.running 0.9 1.1
cs trigger sim.reset; sleep 2; f "$S/mj_state.py"
trap - EXIT; cleanup
[ "$FAIL" -eq 0 ] && echo "=== run_mj_full: PASS" || echo "=== run_mj_full: FAIL"
exit "$FAIL"
