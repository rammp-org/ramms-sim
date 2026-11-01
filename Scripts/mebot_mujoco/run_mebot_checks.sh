#!/bin/bash
# PIE checks of the MeBot MuJoCo pawn on Map_MebotCurb_URL: it stands, drives, turns, every lift
# moves to its commanded position in its own units, the gamepad drives it through the chair's
# input map, and the arm on its seat answers arm.* / gripper.* while the base still drives. Needs a running editor (Scripts/editor_remote_exec.py). PYTHON overrides the interpreter.
# Exit status: nonzero if any check failed (PIE is still ended).
S=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$S/../.." && pwd); cd "$ROOT" || exit 1
PY=${PYTHON:-python3}
FAIL=0
op(){ if ! "$PY" Scripts/editor_remote_exec.py --code "unreal._ramms_mebot_op='$*'" >/dev/null 2>&1; then
          echo "!! could not set the op '$*'"; FAIL=1; return 1; fi
      "$PY" Scripts/editor_remote_exec.py --file "$S/mebot_op.py" 2>&1 | grep -E "\[mebot\]|Error\]" | sed 's/^\[Info\] //; s/^\[Error\] //'
      local st=${PIPESTATUS[0]}; if [ "$st" -ne 0 ]; then echo "!! $* failed"; FAIL=1; fi; return "$st"; }
cleanup(){ op end; sleep 3; }
trap cleanup EXIT   # early exits; the normal end runs cleanup itself, so its result counts

op begin || exit 1
sleep 25
echo "--- standing ---"
op state
op expect_level 3

echo "--- drive: half stick forward 2 s, then a half-right turn ---"
op mark; op set drive.forward 0.5; sleep 2; op release drive.forward; sleep 1.5
op expect_moved x 40 250
op expect_yaw -5 5
op mark; op set drive.turn 0.5; sleep 1.5; op release drive.turn; sleep 1.5
op expect_yaw 10 120
op expect_moved x -20 20

echo "--- lifts: each to a target in its own units (deg / cm), at its actuator's speed ---"
op set lift.dw_main_plate_l 10; op set lift.dw_main_plate_r 10; sleep 7
op expect_motor translator_l 9 11
op expect_motor translator_r 9 11
op set lift.dw_main_plate_l 0; op set lift.dw_main_plate_r 0; sleep 7
op expect_motor translator_l -1 1
op set lift.motor_swing_arm_l 10; op set lift.motor_swing_arm_r 10; sleep 3
op expect_motor elevator_l 0.10 0.19
op set lift.motor_swing_arm_l 0; op set lift.motor_swing_arm_r 0; sleep 3
op set lift.front_caster_swing_arm -15; sleep 4
op expect_motor front_arm -0.30 -0.20
op set lift.front_caster_swing_arm 0; sleep 4
op set lift.rear_caster_swing_arm 15; sleep 3
op expect_motor rear_lift 0.18 0.28
op set lift.rear_caster_swing_arm 0; sleep 3
op state
op expect_level 3

echo "--- gamepad: left stick drives, right stick Y raises the elevators, the triggers move the translators ---"
op mark; op pad Gamepad_LeftY 0.6; sleep 2; op pad_release; sleep 1.5
op expect_moved x 40 250
op pad Gamepad_RightY 0.5; sleep 1; op pad_release; sleep 3
op expect_motor elevator_l 0.08 0.30
op pad Gamepad_RightTriggerAxis 1.0; sleep 1; op pad_release; sleep 6
op expect_motor translator_l 4 20
op state

# arm.up moves the gripper along its own up (the teleop's local frame), which the stowed arm holds sideways: the
# check is that it moves. Then the base still drives (backwards: the curb is ahead) with the arm's IK running.
echo "--- arm (in the MJCF, on the seat): arm.up moves the gripper, gripper.close closes it; the base keeps its commands ---"
op mark_body arm_bracelet_link; op set arm.up 1; sleep 1.5; op release arm.up; sleep 1
op expect_body_moved arm_bracelet_link 5 60
op trigger gripper.close; sleep 1.5
op expect_control gripper.closed 0.9 1.1
op mark; op set drive.forward -0.5; sleep 2; op release drive.forward; sleep 1.5
op expect_moved x -250 -40

trap - EXIT
cleanup
if [ "$FAIL" -ne 0 ]; then echo "MEBOT CHECKS FAILED"; else echo "all MeBot checks passed"; fi
exit "$FAIL"
