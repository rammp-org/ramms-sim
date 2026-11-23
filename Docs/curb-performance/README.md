# Curb crossing performance

This folder holds the curb crossings' history, one JSON record per crossing, so a robot can be tracked over time and compared with another robot measured the same way. The runner (`Scripts/curb_runner/run_curb.py`) records every run it makes. `Scripts/curb_runner/history.py` adds, exports and charts the records:

```
python -I Scripts/curb_runner/history.py list --history Docs/curb-performance/gen1_history.jsonl
python -I Scripts/curb_runner/history.py csv  --history Docs/curb-performance/gen1_history.jsonl
python -I Scripts/curb_runner/history.py plot --history Docs/curb-performance/gen1_history.jsonl
```

The CSV and the charts are generated into `Saved/CurbHistory/`, which is not in git. A robot whose history is kept privately keeps it in its own plugin. A `plot` given several `--history` files charts the robots together.

| File | Robot |
|---|---|
| `gen1_history.jsonl` | RAMMP Gen1 (`rammp_gen1`) |

The `public-curb-history` pre-commit hook (`Scripts/check_public_history.py`) keeps every line here public. It rejects a privately kept robot's record, a private repository's code state, the optional private plugin's name, and absolute paths.

## A record (schema 3)

| Group | What |
|---|---|
| identity | `schema`, `robot` (the history's robot name), `robot_id` (what `ramms.Robot` started), `scenario` (a `curb_terrain` id), `dir` (`up`, `down`), `start` (`standing`), `descent_start` (`top`: the descent started on the sidewalk), `rep`, `ran_at` (UTC), `label` |
| `run` | `dir` (relative to the project), `started`, `argv` (with paths made relative), `editors` |
| `code` | `ran_on`: for each public repository, its commit, branch and `dirty` (tracked files differ, up to 20 named), plus when the editor's plugin binaries were `built`. A record made later from a run folder without its `history_run.json` has `at_record` instead (the checkout at recording). |
| `settings` | `standard` (the robot's standard settings, below), `max_fps` (the frame-rate cap), `frame_ms` / `frame_max_ms` / `frame_p99_ms` (the trace's median, worst and p99 frame), `physics_step_ms` (from the rider IMU's rate), `maps` (`public`), `ask_sim_s`, `steady` (at rest when asked), `late_s`, `clock` (what the trace was timed by: `physics`), `locked_frame_s` (URLab's frame lock, null when off; see `Scripts/curb_runner/README.md`), `plan_in_step` (true when `Ramms.Curb.PlanInStep` was on for the session, which the runner sets with a fixed frame lock: a plan is waited for where it is asked, so a locked crossing repeats exactly; null otherwise, and absent from records made before it, so fixed-lock records with and without it are separate series), `cvars`, `robot` (its setup: for RAMMP Gen1 `style` 1 Blended, `stance`, `stick`, `start_offset_cm`, `start`) |
| `outcome` | `phase` (`DONE`, `FAULTED`, `ABORTED`, `REFUSED`, `TIMEOUT`), `pass`, `met` (null when not scored), `expect`, `failed` (the checks), `status`, `why` |
| `shared` | `measures.py`'s figures, the same for every robot. `version`, `across`, and `wheels` (`counted`, `raised`). `events` (simulated s): `t_ask`, `t_begin`, `t_edge`, `t0`, `t_last_down`, `t_done`, `t_rest`, `t_end`, `last_down_wheel`, `down` per wheel. `times`: `edge_to_last_down_s`, `edge_to_done_s`, `edge_to_rest_s`, `edge_to_end_s`, `ask_to_edge_s`, `planning_after_edge_s`. `speed`: `v_min_cm_s`, `stops`, `stopped_s`, `mean_cm_s`, plus the same to Done. `attitude`: seat and chassis inclination, tilt rate, the seat's inclination at `t0` and its largest turn from there up to Done (`t0_seat_incl_deg`, `seat_excursion_to_done_deg`), the seat against the chassis at the ask (`ask_seat_off_chassis_deg`), the attitude at Done and at rest, and its change beyond the surfaces. `path`: `drift_cm`, `yaw_change_deg`. `landing`: `min_r`. `resolution_s` |
| `rider` | the rider's acceleration from the physics IMU (m/s², two 50 ms low-passes): `peak_` and `rms_` of `fore_aft`, `vertical` and `total`, `samples`, `clock_offset_s`. Null when the IMU lost samples. |
| `controller` | the robot's controller's own figures (its own definitions: kept beside the shared ones, never compared across robots), `step_found`, `lifts_back` |

The measures' exact definitions are in `Scripts/curb_runner/measures.py` and `Scripts/curb_runner/README.md`. The headline is `shared.times.edge_to_last_down_s`: from the leading wheel at the edge, or from when the controller began if that was later, to the last counted wheel down on the far surface. Planning, and any stall at rest before the edge, are never counted. Compare records only with the same `shared.version`, `scenario`, `dir`, `start` and `descent_start`.

## RAMMP Gen1's standard settings

A record has `settings.standard` true when all of these hold:
- the runner's 16 fps cap, with the trace's median frame within 10% of 62.5 ms, and no frame lock;
- the Blended style;
- the outdoor stance: front arm −14° (front omni wheels up), elevators 9°;
- the stick held at 1;
- a climb started 20 cm ahead of the map's PlayerStart, or a descent from the sidewalk start;
- asked for at rest at 5 s;
- no console variables of its own.

From the map's PlayerStart itself, the front hubs are about 153 cm from the edge, just past the controller's 150 cm scan, so it refuses: hence the 20 cm offset.

RAMMP Gen1's physics step is 2 ms (its MJCF). Its controller, like the runner, acts once per editor frame, so the frame rate is part of the setup. Its maps:
- **pass**: S0 (6 in) and S4 (4 in), up and down;
- **refusal expected, climbing**: S8 (taller than its 17 cm limit), and A15, A30, A30N and R_A40 (off square); their descents are explore;
- **explore**: the other maps, run and recorded but not scored.

## Against the real robot

The real RAMMP Gen1 was filmed crossing a 15 cm (6 in) curb, front at the edge to rear down. It took about 15 s up and 10 s down, and about 17 s and 13 s to stopped; the video climb includes a pause. On S0 (15.24 cm) the simulated `edge_to_last_down_s` comes to about 15 s up and 13 s down, and `edge_to_rest_s` about 18.5 s and 17.5 s. The climb matches. The descent is about a third slower than the video. The offline MuJoCo reference (`mujoco/rammp_gen1/curb_sequence.py --sequence blended`) shows the same gap, about 13 s, so it is in the model of the robot, not in how the crossing is measured.
