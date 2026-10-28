# SimReady door PIE test

The Kinova Gen3 + 2F-85 opening and closing an articulated SimReady appliance under MuJoCo (URLab) inside
Unreal, driven through the project's own `RammsMjEndEffectorController`. It replays, in the engine, a door
opening that `mujoco/articulation_test.py` planned and checked in standalone MuJoCo.

```
door_map.py   the level builder: an unsaved scratch level with AMjManager, the Gen3 (fixed base) and the
              appliance Blueprint placed as in the plan (runs inside the editor)
door_op.py    the PIE run: follows the plan's hand targets and grip on the sim clock, records the door
              joint every tick, takes HighResShots, ends PIE (runs inside the editor)
```

## Run

1. Convert and import the appliance (RammsWorldGen README, "Articulated SimReady assets in MuJoCo"): for
   example `/Game/SimReady/MuJoCo/sr_fc_refrigerator`.
2. Plan and check it offline, which writes the plan (`<out>.json`):
   ```
   python mujoco/articulation_test.py --model D:/simready/mjcf/sr_fc_refrigerator/sr_fc_refrigerator.xml \
       --joint door_1 --handle col_handle_002 --grip-z 1.08 --depth -0.01 --yaw-follow 0.5 \
       --open 80 --app-pos 1.168 0.053 0 --video 0 --out D:/runs/fridge_door
   ```
3. In the editor's Python console (PIE stopped, no unsaved changes to a real map; an unsaved `/Temp`
   scratch level is replaced):
   ```python
   import unreal; D = unreal.Paths.project_dir() + "Scripts/pie_tests/simready_door/"
   DM_PLAN = r"D:/runs/fridge_door.json"; DM_APP = "/Game/SimReady/MuJoCo/sr_fc_refrigerator"
   exec(open(D + "door_map.py").read())
   DO_PLAN = DM_PLAN; DO_JOINT = "door_1"; DO_SHOTS = [5.0, 8.6, 11.8, 15.0, 20.8]
   DO_OUT = r"D:/runs/fridge_door_ue.json"
   exec(open(D + "door_op.py").read())
   ```
   `DM_CAM` (MuJoCo lookat x y z, distance, azimuth, elevation, as `articulation_test.py --cam`) sets the
   view. The optional settings (`DM_CAM`, `DM_GEN3`, `DM_OUT`, `DO_SPEED`, `DO_MOVIE`, `DO_FPS`, `DO_RES`) are
   consumed when read, since the editor's Python globals outlive a console entry. `door_op.py` runs from a slate tick, so the console returns at once; PIE ends by itself when the
   plan does, and `DO_OUT` holds `rows` of `[sim_s, joint (rad or m), planned joint, grip 0..255, yaw]`
   with the offline log beside them. Screenshots go to `Saved/Screenshots`.
4. To record a video, add `DO_MOVIE = True` (and `DO_SPEED = 15`): a 960x540 HighResShot every 1/15 sim
   second, the simulation paused until each is written, then for example
   `ffmpeg -framerate 15 -i Saved/Screenshots/WindowsEditor/HighresScreenshot%05d.png -vf fps=30 -pix_fmt yuv420p door.mp4`.
   The unfocused editor renders a few frames a second and its screenshot requests lag, so neither
   `r.DumpingMovie` nor shots taken without pausing line up with the simulation.

## How the plan maps into Unreal

`articulation_test.py` runs `RammsMjEndEffectorController`'s own IK law by default (`--controller ue`: damping
0.08, gain 0.5, no per-step clamp, targets held between 50 Hz editor ticks), so the plan is checked against
the controller that will run it. Replayed offline with that law, a plan reproduces the PIE result to the
degree; with `ik_test.py`'s stiffer law (`--controller offline`) it can pass offline and fail in PIE.

- URLab mirrors Y between MuJoCo and Unreal (MuJoCo `(x, y, z)` m is Unreal `(100x, -100y, 100z)` cm, a
  MuJoCo yaw `a` an Unreal yaw `-a`), so the builder places the Gen3 at `(0, 0, 100 base_z)` and the
  appliance at the plan's position mirrored.
- The controller (`bTrackBaseFrame`) takes targets in the arm's base frame, so the op subtracts the base
  height; orientation goes in as per-tick base-frame deltas through `MoveTargetBy` (which pre-multiplies
  `qz * qy * qx`), mirrored in the op so the commanded orientation does not drift.
- The builder sets gravity compensation on the Gen3's bodies (the real arm's controller provides it; the
  plan assumes it) and the manager's solver options to the Gen3 MJCF's (elliptic cone, `impratio` 10,
  implicitfast; the manager's defaults are pyramidal and 1). A plan that starts with the joint moved
  (`--start`) gets it set through `UMjJointRuntime.SetPosition`.
- The appliance is welded to the world at its actor; the floor, pedestal and counter are visual only.
- `GameModeBase` keeps the project's default pawn and crowd out; its `DefaultPawn` is destroyed and the
  view is the `door_cam` camera.

## Results (2026-10-28)

ForgeCAD `refrigerator`, left door, grasped by its bar handle (plan: open to 80 degrees, close holding it):

| | opened to | final |
| --- | --- | --- |
| MuJoCo 3.17, `--controller ue` | 77.4 deg | 0.74 deg |
| Unreal PIE (URLab) | 78.4 deg | 0.74 deg |

The two traces follow the commanded angle within a few degrees all the way.

ForgeCAD `refrigerator`, freezer drawer, grasped by its handle (plan: pull out 0.22 m, push back in):

| | pulled to | final |
| --- | --- | --- |
| MuJoCo 3.17, `--controller ue` | 0.217 m | 0.0000 m |
| Unreal PIE (URLab) | 0.217 m | 0.0003 m |

ForgeCAD `microwave_oven` on a 0.85 m counter, door ajar at 25 degrees, its free edge straddled by the
half-closed fingers (`--grip 135`; plan: open to 85, bring back to 12, let go, push it shut):

| | opened to | brought back to | final |
| --- | --- | --- | --- |
| MuJoCo 3.17, `--controller ue` | 89.3 deg | 20.1 deg | 1.3 deg |
| Unreal PIE (URLab) | 89.3 deg | about 20 deg | 1.25 deg |

The door runs a few degrees past the open target and stops about 20 degrees short on the way back (the
inner finger meets the cabinet's front at that angle); the push closes the rest. A pinch of the 28 mm edge
(full grip) passes with `--controller offline` but not under the controller's softer tracking: the edge
twists out of the 2F-85's pads, in PIE and in the offline replay alike (opened to 90, back to 25, final
about 66 degrees). On its way to the push point the hand first moves straight out from the door's outer
face, so it does not clip the free edge.

## Limits

- The replay is open loop with respect to the door: the hand follows where the door should be. If the
  grasp slips, the rest of the plan (a push to close, say) is wrong for where the door is.
- Only the arm's base frame at `(0, 0, base_z)` with no rotation is handled (as the builder places it).
