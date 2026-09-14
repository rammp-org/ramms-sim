#!/bin/bash
# MuJoCo PIE drive + 5-bar test on Map_BaseTest_URL with BP_LiftDriveLinkage_Ramms.
S=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$S/../../.." && pwd); cd "$ROOT" || exit 1
f(){ python3 Scripts/editor_remote_exec.py --file "$1" 2>&1 | grep -E "\[setup\]|\[run\]|\[st\]|\[drv\]|\[lift\]|\[t3\]|\[pie\]|\[restore\]|Traceback|Error|^ERROR" | sed 's/.*LogPython: //' | grep -v "manager AMjManager_1 props"; }
f $S/mj_setup.py; sleep 20
f $S/mj_run.py; sleep 2
echo "--- drive ---"; f $S/mj_drive.py; sleep 1; f $S/mj_state.py; sleep 3; f $S/mj_state.py
echo "--- lift to 16 (retract centre wheels) ---"; f $S/mj_lift16.py; sleep 3; f $S/mj_t3.py; f $S/mj_state.py
echo "--- lower to 10 (extend centre wheels) ---"; f $S/mj_lift10.py; sleep 3; f $S/mj_t3.py; f $S/mj_state.py
f $S/mj_teardown.py; sleep 5
f $S/mj_restore.py
