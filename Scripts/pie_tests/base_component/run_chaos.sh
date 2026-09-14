#!/bin/bash
S=$(cd "$(dirname "$0")" && pwd); cd /Users/bob/atdev/Ramms
f(){ python3 Scripts/editor_remote_exec.py --file "$1" 2>&1 | grep -E "\[t1\]|\[s\]|\[pie\]|\[stop\]|Traceback|Error|^ERROR" | sed 's/.*LogPython: //'; }
LOG="$HOME/Library/Logs/Unreal Engine/RammsEditor/Ramms.log"; MARK=$(wc -l < "$LOG" | tr -d ' ')
f $S/pie_begin_demo.py; sleep 14
f $S/chaos_t1.py
for i in 1 2 3 4 5 6; do f $S/chaos_sample.py; sleep 0.5; done
f $S/chaos_stop.py; sleep 2; f $S/chaos_sample.py
f $S/pie_end.py; sleep 4
echo "=== editor log ==="; tail -n +$MARK "$LOG" | grep -E "DiffDrive\]|RammsRobotBaseComponent|RammsChaosActuationBackend|LogPython: Error" | sed 's/^\[[0-9.:-]*\]\[ *[0-9]*\]//' | head -12
