# Level-assist performance history

One JSON record per course run, one line each, in a robot's own file. `gen1_level_history.jsonl` here is RAMMP Gen1's and is public: every line must pass `Scripts/check_public_history.py` (no private robot, no private repository's state, no absolute path). A robot kept in a private plugin registers a file of its own through its profile (`level` `history_file`), and that file is never this folder's.

`Scripts/curb_runner/run_level.py` records each run as it ends. `Scripts/curb_runner/history.py add-level RUN` records a run folder again. `Scripts/curb_runner/level_report.py --history FILE` makes a page of the latest pair per case.

## A record (group `level`, schema 1)

| field | what |
|---|---|
| `group`, `schema` | `"level"`, 1 |
| `robot`, `robot_id` | the history's robot name and the robot definition's id |
| `course`, `dir`, `start`, `variant` | the course (`Scripts/level_maps`), `fwd` or `rev`, the named start, and what happens on the way (`course.py`) |
| `level` | `on` or `off`: the assist |
| `pref`, `stick`, `hold` | the rider's preferred tilt (pitch, roll, degrees), the stick's value, whether the heading hold was on |
| `rep`, `ran_at`, `label` | the repeat, when it ran, the run's label |
| `run` | `id`, `dir` (relative to the project), `started`, `argv`, `editors` |
| `code` | each public repository's commit and whether its tracked files differed; when the editor's binaries were built |
| `settings` | `standard`, `max_fps`, the frame times, `locked_frame_s`, `clock`, `steady` (at the gate), `gate_s`, `go_s`, `level_ready`, `mode`, `robot` (its setup) |
| `outcome` | `end` (`end line`, `end time`, `left the lane`, `timeout`), `expect`, `met`, `failed`, `not_measured`, `checks` (each with its value and limit), `why` |
| `figures` | `level_measures.figures`: `overall`, `segments`, `transitions`, `parked`, `return_level` (`figures.version`) |
| `pair` | on an assist-on record: its figures against the assist-off run of the same case (`rejection`, `speed_kept`, ...) |
| `rider` | the rider's acceleration with its lateral part, when the run kept the IMU (`--imu`) |

Records are keyed by course, dir, start, variant, pref, stick, hold, level, rep and the run's id. Recording a run folder again replaces its earlier records.

## What the figures mean

Attitudes are pitch (nose up) and roll (right side up) in degrees. The rider is the seat less its mount's offset from the chassis.

- **Error**: an attitude less the preference. With the assist on it should be zero. The assist-off run is scored against the same preference.
- **Off the ground**: an attitude less the ground's own under the standing wheels. With the assist off it is zero.
- **A segment**: a stretch where every standing wheel is on one plane. Its `rider_residual_deg` is the mean error over its last 1.5 s.
- **A transition**: each seam (from the first wheel reaching it) and each event (assist on or off, a preference change, a mode switch, a stop, a go). It gives the peak error, the time outside 1°, the fastest tilt over 0.3 s, and the time to settle within 0.5° for good. The stop at the end of the run (`stop at the end`: the stick let go at speed) is a transition too; `return_level` (how the rider comes back after the last seam onto the flat) ends where the stick is let go, so the stop does not count against it.
- **Standing** (`parked`): `drift_cm` is the farthest the reference point moved from where it stood at go, every switch on the way included; `hold_drift_cm` is the creep alone, from settled to the next event; `settled_after_s` is when the rider was within 0.5° for 1 s; `quiet_after_s` is when the commands last changed; `cmd_changes_after_settle` counts command changes later than 3 s after settled (hunting).
- **Rejection**: the rider's error RMS with the assist on over the same with it off.
- **Steering effort**: the `drive.turn` the hold held to keep the run on its path. Where the hold carries the drive's stick dead zone it is never under that dead zone, so compare an on run with its off run and not with zero. A run with the hold off (`--hold off`) shows the yaw and the drift the robot has by itself.
