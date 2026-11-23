# Curb runner

Runs a robot's curb crossings on the public curb maps (`Content/Maps/Curb`, see `Scripts/curb_maps/README.md`). Every robot is measured by the same code, so robots can be compared. Each crossing is recorded in its robot's history.

```
python -I Scripts/curb_runner/run_curb.py --list
python -I Scripts/curb_runner/run_curb.py --robot rammp_gen1                      # its standard maps, up and down
python -I Scripts/curb_runner/run_curb.py --robot rammp_gen1 --scenarios S0 --dirs up --repeat 5 --no-history
```

The runner needs an editor of this project running. It reaches the editor through `Scripts/editor_remote_exec.py`. If the editor was started on another remote-execution port, set `RAMMS_EDITOR_REMOTE_PORT` to that port. Results go to `--out` (by default `Saved/CurbHistory/runs/<time>-<robot>`):
- `results.json`, one row per crossing;
- `summary.md`;
- each crossing's `<scenario>_<dir>.trace.json`;
- the code state the run ran on.

The run is then recorded in the robot's history, unless you pass `--no-history`. See `Docs/curb-performance/README.md` and `history.py`.

## A crossing

Each crossing is one PIE session. Its timing runs inside the editor's own tick, from `runner_op.py`'s session, so a remote call never delays it.

1. **The start.**
   - **A climb** starts on the near road, at the map's PlayerStart moved the robot's `start_offset_cm` ahead along its heading.
   - **A descent** starts on the sidewalk, at `curb_terrain`'s top start, facing the far curb.
   - The PlayerStart is moved only in the editor's copy of the level, never saved, and put back afterwards.
   - The robot is chosen through `ramms.Robot`, and the runner checks that PIE started it.
   - The frame rate is capped at the robot's standard (16 fps for RAMMP Gen1). Each robot keeps its own physics step, which is recorded.
2. **Setup.** At 1 s of simulated time, the robot is put in its standard setup by its adapter's `prepare`.
3. **The ask.** Once the robot is at rest, the crossing is asked for on the frame nearest 5 s. At rest means the chassis stays within 0.25 cm and 0.1° for 0.5 s, and no powered wheel turns faster than 0.5 rad/s. If it is not at rest, the runner waits at most 5 s more, then asks anyway and flags the crossing as unsteady.
4. **The stick.** The rider's stick is held forward on every frame the crossing is under way. It is let go on the first frame after the crossing ends, so the drive mode the robot hands back to never drives on.
5. **The trace.** One sample is taken every frame, from 1 s before the ask until 2 s after the end, or 0.5 s after a refusal (`measures.py` documents the format). Every physics step's IMU sample of the rider's body is kept too.

A session gives up when PIE has not started the robot its adapter knows within 5 s of simulated time, or when PIE started another robot. A crossing is aborted 90 s of simulated time after the robot appeared, or after 900 s of wall time.

Every time is the physics' own clock (the adapter's `sim_time`, `settings.clock`), so a frame the physics did not advance is not a sample.

## Frame-locked runs (`--locked-frame-s`)

By default MuJoCo runs on its own, paced to the wall clock, and a controller reads whatever state it last published. How much physics happens between two of a controller's ticks then depends on the frame rate, and so do the figures. `--locked-frame-s S` sets URLab's `urlab.LockedFrameSeconds` for the session. MuJoCo then steps exactly `round(S / timestep)` steps per frame, between the frame's actor ticks, so every tick reads the state at the end of one whole batch and the figures no longer depend on the frame rate. The simulation then runs at `S` times the frame rate. `S` becomes the controllers' rate: 0.0625 is the same as RAMMP Gen1's standard 16 fps.

A negative `S` is matched: each batch is the real time its frame took, cap reached or not (at most 1/20 s; a step's remainder is carried). It keeps real time but brings the frame rate back into the figures. In the editor, the Sim group's Frame lock control (Off / Matched / 1/16 s) sets the same variable, and its "Frame lock is" line says exactly what is set. A fixed period set elsewhere shows as the fixed choice, and picking that choice keeps it.

A locked run is recorded with `settings.locked_frame_s` and is never `standard`: it is a series of its own. URLab turns the lock off and sets its variable back to 0 if a batch stops making progress; a run whose lock did not hold to the end is an error, never recorded.

## The shared measures (`measures.py`, `shared.version` 1)

All figures are taken from the trace, against the map's terrain (`curb_terrain`).

**Events:**
- **`t_edge`**: the robot's leading wheel reaches the edge line. That is its hub plus its radius in its rolling plane, along the edge normal, interpolated between samples.
- **`t0 = max(t_edge, t_begin)`**: the crossing's start. `t_begin` is when the controller began to carry out the crossing, after any planning, so planning and a stall at rest are never counted as crossing time.
- **`t_last_down`**: the last counted wheel comes down for good on the surface the crossing ends on.
  - "Down" means its lowest point is within 1 cm of that surface, less the gap the wheel had at rest before the ask, with its hub past the edge.
  - Dips out of "down" shorter than 0.1 s (roller ripple, a bounce) are bridged.
  - A wheel held up at the ask, more than 2 cm over the start surface, is not counted. RAMMP Gen1's raised front omni wheels are an example.
  - Every counted wheel must be down past the edge by 1 s after the end: a wheel still settling as the controller reports Done counts when it gets there, so `t_last_down` can come after `t_done`. If one is not, the crossing did not get across and has no crossing times.
- **`t_done`**: the controller reports Done.
- **`t_rest`**: from `t_last_down` on, the chassis stays within 0.25 cm and 0.1° for 0.5 s.

**Times:** `edge_to_last_down_s` (the headline), `edge_to_done_s`, `edge_to_rest_s`. `ask_to_edge_s` and `planning_after_edge_s` are reported on their own and are never part of a crossing time.

**Other figures:**
- the least forward speed (signed, over exact 0.3 s windows), stops, and the time stopped;
- the seat's and the chassis's most inclination and fastest tilt (over 0.3 s);
- the attitude at Done, and its change from the ask less what the surfaces' slopes explain;
- drift across the starting heading, and the change of heading;
- how far past the edge each wheel came down, in radii;
- the rider's acceleration (`rider`): every physics step's IMU sample of the rider's body, rotated to the world, gravity taken off, two first-order low-passes of 50 ms, then the peak and RMS of its fore/aft, vertical and total parts. The IMU's clock is the physics' own, and it is lined up with the trace's.

A robot's controller also reports its own figures (`controller`). These are kept beside the shared ones, never in their place. They are not compared across robots.

## Scoring (`scoring.py`)

Each robot's profile gives an expectation per map and direction:
- **`pass`**: every check passes.
  - Shared checks:
    - it ended Done and got across;
    - the step its controller found is the map's, within 1.5 cm;
    - its final pitch and roll changed no more than 1.5° beyond what the surfaces explain;
    - every wheel came down at least 0.3 radii past the edge;
    - it stayed upright.
  - The robot's own checks are added (RAMMP Gen1: every lift back where it was).
- **`refuse:<words>`**: the controller refuses the crossing, giving a reason that matches.
- **`explore`**: run and recorded, but not scored.

Tilt and speed are reported, not scored.

## Your robot

A robot is two files:
- **A profile** (`robots/<name>.py`, see `robots/__init__.py`): its robot id, wheels (names and radii), rider body, start offset, standard setup, maps, expectations, standard settings and history file.
- **An editor-side adapter** (`robots/<name>_editor.py`, see `robots/rammp_gen1_editor.py`). It reads the robot's chassis, seat and wheel hubs, and asks for, aborts and follows a crossing through the robot's own controller.

The runner finds profiles here, in any checked-out plugin's `Scripts/curb_runner_robots/`, and in the folders listed in `$RAMMS_CURB_ROBOTS`. The profile's `robot_id` is what `ramms.Robot` is set to: a robot definition's id, or a pawn class path for a robot with no definition (`/Game/MyRobot/BP_MyRobot.BP_MyRobot_C`).

## Tests

```
python -I Scripts/curb_runner/tests/test_measures.py
python -I Scripts/curb_runner/tests/test_history.py
```

These use synthetic traces with known answers. They need no editor, and they write nothing outside a temporary folder.
