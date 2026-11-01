# MeBot on MuJoCo in Unreal

These scripts bring the MeBot MJCF (`mujoco/mebot`, powered-front variant) into Unreal through URLab as a drivable pawn, along with a curb level.

| Script | What it does |
|---|---|
| `import_mebot_mjcf.py` | Imports `mujoco/mebot/mebot_powered_front.xml` as the articulation `/Game/Robots/MeBot/URL/mebot_powered_front`. Its meshes go to `/Game/MuJoCoImports/mebot_powered_front_Assets`. It deletes the pawn and the previous meshes first, then checks that the asset records no machine paths and that every mesh resolves inside `mujoco/mebot`. |
| `make_mebot_pawn.py` | Builds `/Game/Robots/MeBot/BP_MebotPoweredFront_Ramms` on the articulation, plus the motor table `/Game/Robots/Data/DT_MebotPoweredFront_Motors`, read from the MJCF. The curb controller is configured from `mujoco/mebot/curb_config_powered_front.json` (`export_curb_config.py`). |
| `make_mebot_curb_map.py` | Builds `BP_MebotPoweredFrontGameMode` and `/Game/Maps/Map_MebotCurb_URL`: a floor and two platforms, 15 cm and 8 cm high, 3 m ahead of the spawn and 3 m deep. |
| `mebot_op.py` | Drives and reads the pawn in PIE, one operation per call (see its docstring). |
| `run_mebot_checks.sh` | PIE checks: the robot stands, drives, turns, every lift reaches its target in its own units, and the gamepad drives it. |
| `run_mebot_curb.sh` | PIE checks of the curb crossing: the robot climbs the 15 cm platform and descends its far edge. |

Run the three builders in order in a running editor with PIE stopped (`python Scripts/editor_remote_exec.py --file <script>`). Each re-import deletes the pawn, so re-run the two scripts after it.

URLab imports the `.glb` beside each mesh. They are committed. After the meshes change, regenerate them from a Python that has trimesh, numpy, scipy, networkx and Pillow:

```bash
python -I Plugins/unreal-robotics-lab/Scripts/clean_meshes.py mujoco/mebot/mebot_powered_front.xml --out-dir Saved/URLabPrep
```

## The pawn

| Component | |
|---|---|
| `RobotBase` | MuJoCo backend. One motor-table row per MJCF actuator: the drive wheels and the front omni hubs as torque motors, the lifts as position motors. The translators are in cm; ramms-mujoco-support converts cm to the slide's metres. The drive wheels carry speed-loop gains and a brake. |
| `DifferentialDrive` | The drive wheels in velocity control (120 cm/s, 70 deg/s at full stick). Brakes close when it stops. |
| `MebotController` | The lifts, rate-limited at the MJCF's lift speeds (custom numerics). They use the chair's control ids, so `DA_RammsInput_Mebot` and the gamepad layout drive it unchanged: `lift.motor_swing_arm_*` the elevators, `lift.dw_main_plate_*` the translators, `lift.front_caster_swing_arm` the front arm and `lift.rear_caster_swing_arm` the rear lift (the suspension arm, in its own degrees). |
| `ControlSurface`, `ControlInput` | Every control, plus the powered front omni hubs as `motor.front_omni_*`. Nothing drives them in normal driving, so they freewheel. |
| `SimControl` | Puts the robot in the MJCF's `home` key at spawn, which also stands it on the ground under it. |
| `CurbController` | `URammsMebotCurbController` (ramms-core), the curb crossing. It is `mujoco/mebot/curb_sequence.py` in Unreal: `curb.negotiate`, `curb.abort` and `curb.phase`. |
| `DriveModeSelector` | The drive modes: `differential` (first) and `curb`. A crossing selects `curb`, then hands back. |
| `FollowCamera`, `TopCamera` | On the `chassis` body. |

Gamepad, as on the chair:
- **Left stick:** drive.
- **Right stick Y:** elevators.
- **Triggers:** translators.
- **Shoulders:** front arm and rear lift.

Keyboard:
- **W/S, A/D:** drive.
- **Y/H:** elevators.
- **T/B:** translators.
- **Z/X:** front arm and rear lift.

## Crossing a curb

Drive to within 1.5 m of a curb, square to it, then start a crossing:
- **Gamepad:** A starts it; hold B to stop.
- **Keyboard:** Enter starts it; hold End to stop.
- **Remote:** `curb.negotiate` and `curb.abort` through the control surface.

The controller finds the edge and its height with line traces ahead of the front omni wheels. It picks the crossing height from each support's height table, then runs `curb_sequence.py`'s phases:
1. Raise or lower the chassis, level, to the crossing height.
2. Front omni wheels over the edge and down.
3. Drive wheels over and down. With the powered front omni wheels, those pull the robot forward while the translators bring the drive wheels aft.
4. The rule: the rear omni wheels are not lifted until both drive wheels are down on the far level, translated aft, with the centre of mass (from the exported mass model) ahead of their axle. If it fails, the crossing aborts.
5. Rear omni wheels over and down.
6. Translators back to centre while the drive wheels roll, then the driving pose.

A touchdown lowers the wheels by their measured height above the level, to contact and 1 cm past it. The sprung rear's lift is trimmed against the chassis's pitch while its wheels are down. A finished or stopped crossing brakes, then hands back to the differential drive. Steps of 3–17 cm are crossed; others are refused with the reason.

The level's URLab manager runs MuJoCo at the MJCF's 2 ms step, with elliptic friction cones and impratio 10 (the omni rollers creep when braked on pyramidal cones).
