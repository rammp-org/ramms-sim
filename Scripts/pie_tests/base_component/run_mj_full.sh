#!/bin/bash
# MuJoCo PIE drive + 5-bar test on Map_BaseTest_URL with BP_LiftDriveLinkage_Ramms.
# Exit status: nonzero if any editor command failed (the teardown/restore still run).
S=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$S/../../.." && pwd); cd "$ROOT" || exit 1
FAIL=0
# Run one script in the editor; keep the Python exit status (the filters only shape the output).
f(){ python3 Scripts/editor_remote_exec.py --file "$1" 2>&1 | grep -E "\[setup\]|\[run\]|\[st\]|\[drv\]|\[lift\]|\[t3\]|\[pie\]|\[restore\]|\[turn\]|\[cs\]|\[ci\]|\[hud\]|Traceback|Error|^ERROR" | sed 's/.*LogPython: //' | grep -v "manager AMjManager_1 props"
     local st=${PIPESTATUS[0]}; if [ "$st" -ne 0 ]; then echo "!! $(basename "$1") failed (exit $st)"; FAIL=1; fi; return "$st"; }
cleanup(){ f "$S/mj_teardown.py"; sleep 5; f "$S/mj_restore.py"; }
trap cleanup EXIT

f "$S/mj_setup.py" || exit 1
sleep 20
f "$S/mj_run.py"; sleep 2
echo "--- drive ---"; f "$S/mj_drive.py"; sleep 1; f "$S/mj_state.py"; sleep 3; f "$S/mj_state.py"
echo "--- turn: X=+1 must turn right ---"
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_turn_op='start'" >/dev/null 2>&1; f "$S/mj_turn.py"; sleep 3
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_turn_op='check'" >/dev/null 2>&1; f "$S/mj_turn.py"; sleep 1
echo "--- linkage height: bottom of the reachable range (extend centre wheels) ---"
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_lift_z='lo'" >/dev/null 2>&1; f "$S/mj_lift.py"; sleep 3; f "$S/mj_t3.py"; f "$S/mj_state.py"
echo "--- linkage height: top of the reachable range (retract) ---"
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_lift_z='hi'" >/dev/null 2>&1; f "$S/mj_lift.py"; sleep 3; f "$S/mj_t3.py"; f "$S/mj_state.py"
echo "--- control surface: raw motors, camera actions ---"
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_cs_op='describe'" >/dev/null 2>&1; f "$S/control_surface_check.py"
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_cs_op='trigger camera.next'" >/dev/null 2>&1; f "$S/control_surface_check.py"
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_cs_op='registry'" >/dev/null 2>&1; f "$S/control_surface_check.py"
echo "--- Enhanced Input -> surface (injected actions): W, Q, N, P, Backspace ---"
ci(){ python3 Scripts/editor_remote_exec.py --code "unreal._ramms_ci_op='$*'" >/dev/null 2>&1; f "$S/control_input_check.py"; }
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
hud(){ python3 Scripts/editor_remote_exec.py --code "unreal._ramms_hud_op='$*'" >/dev/null 2>&1; f "$S/hud_check.py"; }
hud status
hud joystick 0 -1; ci expect drive.forward 0.99 1.01; sleep 1.5; f "$S/mj_state.py"; hud joystick_release; ci expect drive.forward -0.01 0.01; sleep 0.5
hud action sim.pause; sleep 0.5; ci expect sim.running -0.1 0.1; hud action sim.pause; sleep 0.5; ci expect sim.running 0.9 1.1
echo "--- sim controls: pause, resume, reset ---"
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_cs_op='trigger sim.pause'" >/dev/null 2>&1; f "$S/control_surface_check.py"; sleep 1
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_cs_op='read sim.running'" >/dev/null 2>&1; f "$S/control_surface_check.py"
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_cs_op='set sim.running 1'" >/dev/null 2>&1; f "$S/control_surface_check.py"; sleep 1
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_cs_op='read sim.running'" >/dev/null 2>&1; f "$S/control_surface_check.py"
python3 Scripts/editor_remote_exec.py --code "unreal._ramms_cs_op='trigger sim.reset'" >/dev/null 2>&1; f "$S/control_surface_check.py"; sleep 2; f "$S/mj_state.py"
trap - EXIT; cleanup
[ "$FAIL" -eq 0 ] && echo "=== run_mj_full: PASS" || echo "=== run_mj_full: FAIL"
exit "$FAIL"
