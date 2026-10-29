# Chaos articulations

Runs URLab articulations on Chaos through ramms-mujoco-support's `URammsChaosArticulationComponent`,
then compares them with MuJoCo. The plan and the spike behind this are in
`doc/chaos_physics_backend_plan.md`.

```
chaos_map.py   editor: a scratch level with articulations and a camera, and no MuJoCo manager
               (/Game/ChaosProto/Map_ChaosArticulation; don't commit it)
chaos_run.py   editor: PIE; switch every articulation to Chaos and run a generic schedule;
               Saved/ChaosArticulation/<run>.json and <run>_summary.txt
robot_run.py   editor: PIE; drive the robot pawn through its control surface (5-bar heights,
               drive.forward, drive.turn) on whichever engine simulates it, and record it;
               Saved/ChaosArticulation/<run>.json and <run>_summary.txt
```

## Run

In the editor's Python console:

```python
import unreal; D = unreal.Paths.project_dir() + "Scripts/pie_tests/chaos_articulation/"
exec(open(D + "chaos_map.py").read())
CA_OUT = "run"; exec(open(D + "chaos_run.py").read())   # CA_FRAMES = True also writes frames
```

**A robot through its controllers.** `robot_run.py` drives the pawn in the open level through
`URammsRobotControlSurfaceComponent`, as a panel or input map would. The robot base component's motors
go to Chaos when its `Backend` is Chaos (or the articulation carries a
`URammsChaosArticulationComponent`), and to MuJoCo otherwise, so the same script measures both. With
`Backend = Chaos` set on the placed pawn, leave `CR_SWITCH` out:

```python
# Chaos: a level with the pawn and no MuJoCo manager; CR_SWITCH adds the component at runtime
CA_MAP = "/Game/ChaosProto/Map_ChaosRobot"
CA_ACTORS = [("/RammsPrivateAssets/Robots/BP_LiftDriveLinkage_Ramms", (0.0, 0.0, 1.0))]
exec(open(D + "chaos_map.py").read())
CR_OUT = "robot_chaos"; CR_SWITCH = ""; exec(open(D + "robot_run.py").read())

# MuJoCo: the base-component test level spawns and starts the pawn
exec(open(unreal.Paths.project_dir() + "Scripts/pie_tests/base_component/mj_setup.py").read())
CR_OUT = "robot_mujoco"; CR_BEGIN = False; CR_WAIT = 8.0; exec(open(D + "robot_run.py").read())
# then mj_restore.py, as run_mj_full.sh does
```

The schedule is 2 s of settling, each 5-bar linkage to the bottom, top and middle of its height range
(3 s, 3 s, 2 s), `drive.forward` 1 for 3 s, a stop, `drive.turn` 1 for 3 s, and a stop. The clock is the
robot's (`GetSimulationTime`, MuJoCo's when MuJoCo steps it), else the game's.

**What gets placed.** `chaos_map.py` always places the Gen3 + 2F-85 (`/Game/Robots/URL/gen3_2f85_fixed`).
It also places the SimReady refrigerator and microwave and the lift-drive linkage base when this
checkout has them. Pass `CA_ACTORS` to choose your own.

**The schedule.** `chaos_run.py` takes each articulation through these steps:

1. It settles for 1 s.
2. It ramps its actuators to each MJCF keyframe's ctrl, 2 s per keyframe.
3. It pushes every joint no actuator moves for 0.5 s: 2 N·m on a hinge, 10 N on a slide.
4. It runs its torque motors at a quarter of their ctrl range for 2.5 s.

**The comparison.** The same schedule run in MuJoCo gives the comparison below. Those runs used
`mujoco` on the host on the same MJCFs, with no floor except where the model has one.

## Videos

Recorded on Chaos at game time, so they play at real-time speed.

| SimReady refrigerator and microwave | Gen3 + 2F-85 |
|---|---|
| ![SimReady fridge and microwave on Chaos](../../../doc/images/chaos_backend/chaos_simready_objects.webp) | ![Gen3 arm on Chaos](../../../doc/images/chaos_backend/chaos_gen3_arm.webp) |
| Each joint is pushed open in turn (fridge doors, freezer drawer, microwave door, turntable, release button), then pushed closed; the joints' damping and the button's spring come from the MJCF | Joint-space move to a reach pose, gripper close and open, then back |

## Results (2026-10-28, Phase 2 defaults)

Each cell is the joint's maximum over the run, then its value at the end. Chaos ran with the
component's defaults: 64 / 8 solver iterations, no joint mass conditioning, the MJCF force ranges as
drive limits. The Phase 1 values (8 / 1 iterations, force limits ×10) are in brackets.

**SimReady refrigerator and microwave**

| joint | Chaos | MuJoCo |
|---|---|---|
| fridge `door_1` / `door_2` (rad) | 2.00 / 2.00, stays (1.75) | 2.10, ends at 2.08 |
| fridge `freezer` / `crisper_1` (m) | 0.115 / 0.123 | 0.125 / 0.114 |
| microwave `door` (rad) | 1.75, ends at 1.74 | 1.79, ends at 1.41 |
| microwave `turntable` / `roller_ring` (rad) | 18.7 / 1.88 | 20.0 / 2.00 |
| microwave `release` button (m) | 0.005, springs back to 0 | 0.010, springs back to 0 |

- Drawers, the turntable and the button agree to within ~10 %.
- MuJoCo's limits are soft, so its doors overshoot the stop and bounce back.

**Gen3 arm, keyframe `home`**

| joint | Chaos | MuJoCo |
|---|---|---|
| `joint_2` (rad) | 0.274 (0.347) | 0.270 |
| `joint_3` (rad) | 3.16 (3.33) | 3.14 |
| `joint_4` (rad) | −2.28 (−2.33) | −2.27 |
| `joint_1` (rad), not commanded | −0.005 to 0.023 (−0.10 to 0.17) | ±0.004 |

- Chaos now reaches the pose with little overshoot; the Phase 1 wobble was the solver, not the gains.
- The gripper's servos track, but its passive linkage settles on a different branch (see the plan).

**Lift-drive linkage base** (private assets)
- **Driving in the `fwd` stance** (this script's schedule): 3.5 m with +1° of yaw, against MuJoCo's
  3.4 m with −10° (7.0 m with −121° in Phase 1). The six-wheel case was the solver: with 8 / 1
  iterations the stance servos sagged, and the wheels shared the load unevenly.
- **Driving in the mid stance** (Phase 1 settings): 4.3 m against 3.5 m, with a heading change of
  −0.1° against +0.5°.
- **Through its controllers** (`robot_run.py`, the linkage pawn):

| | MuJoCo | Chaos |
|---|---|---|
| center linkages to the bottom (−14.9 cm) | −14.9 cm; chassis up 25.3 cm | −14.9 cm; up 25.2 cm |
| to the top (19 cm asked) | stops at 13.7 cm | 15.7–16.3 cm |
| to the middle (2.0 cm) | 2.2 cm; chassis 10.5 cm up | 2.7 cm; 9.6 cm |
| `drive.forward` 1, 3 s | 1.42 m/s, heading +9° | 1.20 m/s, heading +12° |
| stop | coasts (wheels still at 10 rad/s 1 s later) | parked by the brake in 0.3 s |
| `drive.turn` 1, 3 s | 188°/s | 308°/s |
| idle between commands | holds | holds |
| editor frame rate | 56 fps | 100 fps |

  The turn is 1.6× faster and straight driving 15 % slower on Chaos; in both engines the rear wheels
  skid. That is open (see the plan).
