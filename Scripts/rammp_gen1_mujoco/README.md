# RAMMP Gen1 on MuJoCo in Unreal

These scripts bring the RAMMP Gen1 MJCF (`mujoco/rammp_gen1`, powered-front variant) into Unreal through URLab as a drivable pawn, along with a curb level.

| Script | What it does |
|---|---|
| `import_rammp_gen1_mjcf.py` | Imports `mujoco/rammp_gen1/rammp_gen1_powered_front.xml` as the articulation `/Game/Robots/RammpGen1/URL/rammp_gen1_powered_front`. Its meshes go to `/Game/MuJoCoImports/rammp_gen1_powered_front_Assets`. It deletes the pawn and the previous meshes first, then checks that the asset records no machine paths and that every mesh resolves inside `mujoco/` (the robot's in `mujoco/rammp_gen1`, the arm's in `mujoco/gen3_2f85`). |
| `make_rammp_gen1_pawn.py` | Builds `/Game/Robots/RammpGen1/BP_RammpGen1PoweredFront_Ramms` on the articulation, plus the motor table `/Game/Robots/Data/DT_RammpGen1PoweredFront_Motors`, read from the MJCF. The curb controller is configured from `mujoco/rammp_gen1/curb_config_powered_front.json` (`export_curb_config.py`). The seat's parts, its occupant and the arm's IK and teleop come from `Scripts/rammp_seat_pawn.py`, which RAMMP Gen2's pawn uses too. |
| `make_rammp_gen1_curb_map.py` | Builds `BP_RammpGen1PoweredFrontGameMode` and `/Game/Maps/Map_RammpGen1Curb_URL`: a floor and two platforms, 15 cm and 8 cm high, 3 m ahead of the spawn and 3 m deep. |
| `rammp_gen1_op.py` | Drives and reads the pawn in PIE, one operation per call (see its docstring). |
| `run_rammp_gen1_checks.sh` | PIE checks: the robot stands, drives, turns, every lift reaches its target in its own units, and the gamepad drives it. The arm moves on `arm.up`, the gripper closes on `gripper.close`, and the base still drives with the arm's IK running. |
| `run_rammp_gen1_curb.sh` | PIE checks of the curb crossing: the robot climbs the 15 cm platform and descends its far edge, from the outdoor stance (`STANCE=reference`: every lift at 0), rolling through each crossing (`STYLE=stepped`: stopping for each step), the stick held through each, and must end each one with every lift back where it was. |
| `run_rammp_gen1_assist.sh` | PIE checks of curb assist. Starting from the outdoor stance:<ul><li>A switches it on.</li><li>Holding forward at the curb starts a crossing; pulling back as it approaches cancels it, with the lifts back.</li><li>Switched off, driving at the curb starts nothing.</li><li>Switched on and held forward, it climbs, pausing with nothing moving while the stick is let go, then drives on and goes down the far edge.</li></ul> |

Run the three builders in order in a running editor with PIE stopped (`python Scripts/editor_remote_exec.py --file <script>`). Each re-import deletes the pawn, so re-run the two scripts after it.

URLab imports the `.glb` beside each mesh. They are committed. After the meshes change, regenerate them from a Python that has trimesh, numpy, scipy, networkx and Pillow:

```bash
python -I Plugins/unreal-robotics-lab/Scripts/clean_meshes.py mujoco/rammp_gen1/rammp_gen1_powered_front.xml --out-dir Saved/URLabPrep
```

## The pawn

| Component | |
|---|---|
| `RobotBase` | MuJoCo backend. One motor-table row per MJCF actuator: the drive wheels and the front omni hubs as torque motors, the lifts as position motors. The translators are in cm; ramms-mujoco-support converts cm to the slide's metres. The drive wheels carry speed-loop gains and a brake. |
| `DifferentialDrive` | The drive wheels in velocity control (120 cm/s, 70 deg/s at full stick). Brakes close when it stops. Its speed loop's integral reaches the motors' torque less 5 N·m (55 of 60), so a turn in place from rest gets the ~50 N·m it needs to break away. Capped at the motor table's 25 N·m, it stalled at 39. |
| `RammpGen1Controller` | The lifts, rate-limited at the MJCF's lift speeds (custom numerics). They use the chair's control ids, so `DA_RammsInput_RammpGen1` and the gamepad layout drive it unchanged: `lift.motor_swing_arm_*` the elevators, `lift.dw_main_plate_*` the translators, `lift.front_caster_swing_arm` the front arm and `lift.rear_caster_swing_arm` the rear lift (the suspension arm, in its own degrees). |
| `ControlSurface`, `ControlInput` | Every control, plus the powered front omni hubs as `motor.front_omni_*`. Nothing drives them in normal driving, so they freewheel. |
| `SimControl` | Puts the robot in the MJCF's `home` key at spawn, which also stands it on the ground under it. |
| `CurbController` | `URammsRammpGen1CurbController` (ramms-core), the curb crossing. It is `mujoco/rammp_gen1/curb_sequence.py` in Unreal: `curb.negotiate`, `curb.abort`, `curb.status`, `curb.phase`, `curb.assist` and `curb.style` (Rolling, the default, or Stop and step). |
| `DriveModeSelector` | The drive modes: `differential` (first) and `curb`. A crossing selects `curb`, then hands back. Selecting `curb` (the panel, the mode button) starts the crossing ahead; with no curb it can cross in range, it says why (`curb.phase`'s status, the log) and hands straight back. As the initial mode it starts nothing. |
| `FollowCamera`, `TopCamera` | On the `chassis` body. |
| `SeatEyeArm`, `SeatEyeCamera` | The rider's own view, on the `seat` body: `RammsSeat` puts the arm on the occupant's head bone every frame, so the camera is at the eyes of whoever spawned in. The camera cycles to it (`camera.next`) and looks around rather than orbiting (no zoom). |
| On the `seat` body | `BP_RammpGen1_Ramms`'s seat parts, placed where the chair has them on the `seat_base` socket: the seat, its rails, the arm mount, and the LUCI and Gemini camera mounts and cameras (meshes, no collision). `RammsSeat` seats an occupant there, with the chair's settings copied. It is purely visual: the physics has the MJCF's rider mass. |
| `ArmIK`, `ArmTeleop` | The Gen3 arm in the MJCF: `URammsMjEndEffectorController` (ramms-mujoco-support) drives only the arm's joints (from `arm_base_link` to the gripper), starts at the MJCF's `arm_stow` and holds its target in the chassis's frame. `arm.stow` takes it back there joint by joint; `arm.stowed` reads 1 once it is. `URammsMjArmTeleopComponent` puts `arm.*` and `gripper.*` on the control surface, so the chair's arm keys drive it. Both take the standalone arm's (`gen3_2f85_fixed`) settings. URLab writes the base's commands before the IK's, so they no longer silence each other. |

Gamepad, as on the chair:
- **Left stick:** drive.
- **Right stick:** the camera (orbit, or look around in the first-person view).
- **LB + right stick Y:** elevators.
- **LB + right stick X:** front arm and rear lift.
- **Triggers:** translators.

Keyboard:
- **W/S, A/D:** drive.
- **Y/H:** elevators.
- **T/B:** translators.
- **Z/X:** front arm and rear lift.

## Crossing a curb

**Curb assist** (`curb.assist`, Off/On, off at spawn): switch it on, then just drive at the curb.
- **Gamepad:** A switches it on and off; hold B to stop a crossing.
- **Keyboard:** Enter switches it; hold End to stop.
- **Panel:** the Curb group's "Curb assist" row.

With it on, holding the stick forward at a curb the controller can cross starts the crossing once the edge is within 80 cm (`Assist.TriggerDistanceCm`) of the front omni wheels. It won't start one closer than 20 cm (`Assist.MinDistanceCm`); by then you've driven up to the curb. The curb must be within 10° of square (`Config.MaxApproachDeg`; a 10° approach crosses in PIE); the robot does not turn into it for you. A curb it can't cross is left to you, and the status says why. After a crossing it started that didn't finish (stopped, cancelled), it waits for you to let the stick go before it starts another. After one that finished, holding forward drives on to the next curb.

**The stick drives every crossing** (`Stick`, as on RAMMP Gen2): it goes on only while the stick is held forward, at the planned speeds. Let go, or push any other way, and it pauses: the lifts hold where they are and the wheels brake. Push forward again and it goes on. Before any wheel has lifted for the curb or gone over it, pull back and hold: it cancels, puts the lifts back where it found them, and hands back.

To start a crossing by hand, drive to within 1.5 m of a curb, square to it, then use the panel's curb group "Cross the curb ahead", the curb drive mode, or `curb.negotiate` through the control surface (Remote). Then hold the stick forward.

**The status** (`curb.status`, the panel's "Curb status" row, `GetStatusLine()`) says what the crossing is doing and why, in words, coloured by how much it needs you:
- **Crossing up 15.0 cm: Drive to the edge** -- under way (`curb.phase` is the same step).
- **Paused: ...** -- the stick is not held forward.
- **Waiting: the front omni wheels to clear the curb (0.8 cm to go)** -- rolling, held short of the edge for a pair that is not up yet. With nothing moving -- no lift going anywhere that could bring it -- for `Config.WaitSeconds` (5 s), it faults instead of waiting out the phase's minute.
- **Not moving (2 of 3 s): driven at 15 cm/s ...** -- driven, but the chassis is not moving (a wheel against the curb's face, the frame on its edge, the wheels slipping). After `Config.StallSeconds` (3 s) it faults.
- **Faulted: ... Cross the curb ahead to try again.** -- stopped by one of its checks. If no wheel had gone up for the curb, "Cross the curb ahead" (or, with curb assist on, letting go of the stick and pushing forward again) starts it again from where it stands: within 50 cm of where it stopped, it looks for the curb from behind the drive wheels, since the front omni wheels may be over the edge already, and curb assist's reach and least distance do not apply. If a wheel had gone up, the lifts are yours to finish by hand.
- **Stopped**, **Cancelled**, **Done**, **Not crossing: <why a start was refused>**, **Ready**.

A script or autonomy client that starts a crossing must hold `drive.forward` through it, as a rider would (`rammp_gen1_op.py hold_stick 0.6 crossing` does), or set the controller's `Stick.bRequired` false to have it run to the end once begun. Otherwise the crossing waits paused.

The controller finds the edge and its height with line traces ahead of the front omni wheels. An edge is ground that rises or falls steeply (a ramp is not a step), and the far side must stay level for 10 cm past it. A narrow strip, a second step or missing ground refuses the start. It picks the crossing height from each support's height table, then runs `curb_sequence.py`'s phases:
1. Raise or lower the chassis, level, to the crossing height.
2. Front omni wheels over the edge and down. If they start off the ground, as in the outdoor stance (front arm about -14 deg, elevators about 9 deg for ground clearance), they stay up: they are kept where they are, or raised if the crossing needs them higher. They are not set down only to be lifted again at the curb.
3. Drive wheels over and down. With the powered front omni wheels, those pull the robot forward while the translators bring the drive wheels aft.
4. The rule: the rear omni wheels are not lifted until each drive wheel is past the edge and down on the far level, both translated aft, with the centre of mass (from the exported mass model) ahead of their axle. If it fails, the crossing aborts. The mass model has the arm stowed, so a crossing stows it as it starts (`arm.stow`) and holds the `arm.*` controls at rest until it ends: arm commands are refused meanwhile.
5. Rear omni wheels over and down, once both are past the edge. On a descent the chassis is first lowered onto the braked drive wheels, which swings them on their arms and can roll the robot back; if a rear omni wheel comes back over the edge, it creeps on until both are past it again and settled there before setting them down.
6. Translators back where they started while the drive wheels roll, then every lift back where the crossing found it (each one's last command), so the robot ends in the stance it started in.

**Rolling or stop and step** (`curb.style`, the controller's `Style`; the panel's "Curb crossing style" row). The steps above are the order either way. The default, Rolling, is how the real robot's own sequence crosses (videos of it over a 15 cm curb, November 2026), and `curb_sequence.py --sequence blended`.
- It keeps rolling at `Config.CrawlSpeedCmS` (12 cm/s), faster on the approach, and moves each pair as it reaches the edge. If a pair reaches the edge before it is up, the robot is held short of the edge, slowing to a stop, until it is.
- Each touchdown is one move, to contact and the preload.
- The drive wheels freewheel while their arms lift them, so they don't push the chassis back. They go over with the translators where they are, and are drawn aft once down, as it rolls on to the rear's step. If drawing them aft lifts one off the far level, they are set down again once.
- On a descent the drive wheels start down as they roll off the edge, early enough to land past it (`Config.LandMarginCm`).
- The translators re-centre, and the lifts go back to the stance, as it rolls on.
- `curb.phase` is the step begun last, because the pairs overlap.
- It needs the powered front omni wheels; without them a crossing stops and steps.
- Stop and step does each step in turn, settling and finding each touchdown in 5 mm steps.
- A change of style applies from the next crossing.

| PIE, 15 cm, outdoor stance | front at the face/edge → rear down | → stopped |
|---|---|---|
| climb, rolling | 14.4 s | 17.7 s |
| descent, rolling | 12.5 s | 16.1 s |
| the real robot (video) | about 15 s up, 10 s down | about 17 s up, 13 s down |

`STYLE=stepped run_rammp_gen1_curb.sh` runs the checks stopping and stepping.

**Measurements.** The controller's `GetStats()` (`FRammsRammpGen1CurbStats`) measures each crossing on every tick, from its start to its end. It keeps the last crossing's until the next one starts. The summary is logged as the crossing ends, and `rammp_gen1_op.py stats` prints it; `run_rammp_gen1_curb.sh` does after each crossing. The measures are those of `curb_sequence.py`'s:
- **Times:** the whole crossing, from the front omni wheels reaching the edge to the rear omni wheels down, and to the end.
- **Stops:** stops, and the time spent stopped.
- **Chassis:** the largest pitch, roll, inclination and pitch rate.
- **Rider:** acceleration peaks (fore/aft, vertical) and RMS, at `Config.RiderOffsetCm` on `Config.SeatBody`, low-passed at 50 ms.
- **Stability margin:** the config's mass model against the wheels on the ground, each within the touch tolerance of the surface under it; the least, and in which phase.
- **Frame clearance:** the frame's underside over the edge (`Config.Frame*`, the MJCF's chassis boxes); the least, and in which phase.

| PIE, 15 cm, outdoor stance | stops (time stopped) | rider peak / RMS (m/s²) | least margin | frame over the edge |
|---|---|---|---|---|
| climb, rolling | 2 (3.0 s) | 1.35 / 0.19 | 8.7 cm | 1.6 cm |
| climb, stepped | 9 (15.9 s) | 1.29 / 0.21 | 8.6 cm | 2.4 cm |
| descent, rolling | 2 (0.9 s) | 1.04 / 0.18 | 9.1 cm | 2.3 cm |
| descent, stepped | 13 (17.2 s) | 2.33 / 0.26 | 9.1 cm | 2.5 cm |

The rider's acceleration reads higher than in `curb_sequence.py`, as Unreal's drive-wheel brakes stop the wheels harder than the reference's soft hold.

A stop-and-step touchdown lowers the wheels by their measured height above the level, to contact and 1 cm past it. The sprung rear's lift is trimmed against the chassis's pitch while its wheels are down. A finished or stopped crossing brakes, then hands back to the differential drive. If it stops with the drive wheels up, the differential drive would hold nothing on the ground. So it holds the front omni hubs at rest instead, and leaves the lifts to the operator. Once the elevators have the drive wheels down, it hands back. While a crossing runs, `RammpGen1Controller` leaves the lifts alone, then takes them back at their last commands (not where a loaded lift sags to). Steps of 3–17 cm are crossed; others are refused with the reason.

The level's URLab manager runs MuJoCo at the MJCF's 2 ms step, with elliptic friction cones and impratio 10 (the omni rollers creep when braked on pyramidal cones).
