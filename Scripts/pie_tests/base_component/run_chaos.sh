#!/bin/bash
# Chaos PIE drive test on Map_Demo: the chair drives through the base component.
# Exit status: nonzero if any editor command failed (PIE is still ended).
S=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$S/../../.." && pwd); cd "$ROOT" || exit 1
FAIL=0
# Run one script in the editor; keep the Python exit status (the filters only shape the output).
f(){ python3 Scripts/editor_remote_exec.py --file "$1" 2>&1 | grep -E "\[t1\]|\[s\]|\[pie\]|\[stop\]|\[pos\]|\[mc\]|\[turn\]|\[cs\]|\[arm\]|\[ci\]|\[hud\]|\[access\]|Traceback|Error|^ERROR" | sed 's/.*LogPython: //'
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
cleanup(){ f "$S/pie_end.py"; sleep 4; }
trap cleanup EXIT

LOG="$HOME/Library/Logs/Unreal Engine/RammsEditor/Ramms.log"; MARK=$(wc -l < "$LOG" 2>/dev/null | tr -d ' '); MARK=${MARK:-0}
f "$S/pie_begin_demo.py" || exit 1
sleep 14
f "$S/chaos_t1.py"
for i in 1 2 3 4 5 6; do f "$S/chaos_sample.py"; sleep 0.5; done
f "$S/chaos_stop.py"; sleep 2; f "$S/chaos_sample.py"
echo "--- turn: X=+1 must turn right ---"
op turn_op "$S/chaos_turn.py" start; sleep 2
op turn_op "$S/chaos_turn.py" check; sleep 2
echo "--- constraint position motors (elevators / translators / caster arms) ---"
f "$S/chaos_pos_cmd.py"; sleep 3; f "$S/chaos_pos_read.py"; sleep 2
echo "--- control surface: lift axes, arbitration ---"
cs describe
cs set lift.motor_swing_arm_l 20; sleep 3
cs read lift.motor_swing_arm_l
cs release lift.motor_swing_arm_l
cs arbitration
echo "--- arm / gripper through the surface ---"
cs registry
op arm_op "$S/chaos_arm.py" start; sleep 1.5
op arm_op "$S/chaos_arm.py" check
op arm_op "$S/chaos_arm.py" gripper; sleep 2
op arm_op "$S/chaos_arm.py" gripper_check
op arm_op "$S/chaos_arm.py" resync
echo "--- Enhanced Input -> surface (injected actions) ---"
ci(){ op ci_op "$S/control_input_check.py" "$@"; }
ci status
ci inject IA_Ramms_MotorGroupA 1 0 0 1.0; sleep 1.5; ci expect lift.motor_swing_arm_l 15 45; ci expect lift.motor_swing_arm_r 15 45
ci inject IA_Ramms_GripperOpen 1 0 0 0.2; sleep 0.5; ci expect gripper.closed -0.1 0.1
ci inject IA_Ramms_GripperClose 1 0 0 0.2; sleep 0.5; ci expect gripper.closed 0.9 1.1
# Nothing is commanded here, so the injected Z is the only thing that can move
# the arm: the binding under test decides the result. The holds and the intent
# stream below are sized at ~3x the worst observed remote-exec round trip
# (0.5-2 s under editor load) so a value assertion always lands inside them.
op arm_op "$S/chaos_arm.py" mark
ci inject IA_Ramms_ArmMove 0 0 1 6.0; ci expect arm.up 0.99 1.01; sleep 6; ci expect arm.up -0.01 0.01
op arm_op "$S/chaos_arm.py" check_z
echo "--- control HUD (ramms-ui panel + joystick, auto-spawned) ---"
hud(){ op hud_op "$S/hud_check.py" "$@"; }
hud status
hud row lift.motor_swing_arm_r 20; sleep 2.5; cs read lift.motor_swing_arm_r
hud action gripper.open; sleep 0.5; ci expect gripper.closed -0.1 0.1
echo "--- RammsAccess (UDP intents) -> surface, Source = Autonomy ---"
acc(){ op access_op "$S/access_check.py" "$@"; }
# 8 s of stream: two assertions below, each a remote-exec round trip, and the
# watchdog releases 250 ms after the last packet — a shorter stream ends
# mid-check and the value assertion reads the released 0.
python3 "$S/access_send.py" --drive 0 1 --seconds 8.0 --hz 30 & SENDER=$!; sleep 0.7; acc expect_owner drive.forward Autonomy; ci expect drive.forward 0.99 1.01; f "$S/chaos_sample.py"
wait "$SENDER" || { echo "!! access_send.py (drive stream) failed"; FAIL=1; }; sleep 0.8; ci expect drive.forward -0.01 0.01; f "$S/chaos_sample.py"
python3 "$S/access_send.py" --event gripper_close --seconds 0.2 --hz 10 || { echo "!! access_send.py (event) failed"; FAIL=1; }; sleep 1; ci expect gripper.closed 0.9 1.1
echo "--- MebotController API through the base ---"
op mc_op "$S/chaos_mc_api.py" cmd; sleep 3
op mc_op "$S/chaos_mc_api.py" read; sleep 2
trap - EXIT; cleanup
echo "=== editor log ==="; tail -n +"$MARK" "$LOG" 2>/dev/null | grep -E "DiffDrive\]|RammsRobotBaseComponent|RammsChaosActuationBackend|LogPython: Error" | sed 's/^\[[0-9.:-]*\]\[ *[0-9]*\]//' | head -12
[ "$FAIL" -eq 0 ] && echo "=== run_chaos: PASS" || echo "=== run_chaos: FAIL"
exit "$FAIL"
