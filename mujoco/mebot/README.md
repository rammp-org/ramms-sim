# MeBot MJCF

MuJoCo models of the MeBot base, built from its Unreal assets (the public ramms-assets skeletal mesh and physics asset), and the reference sequence for its curb controller.

| File | What it is |
|---|---|
| `extract_ue_mebot.py` | Editor script: dumps the bones, physics bodies, constraints and the seat socket to `source/mebot_ue.json` (read-only, nothing is saved) |
| `extract_ue_mebot_meshes.py` | Editor script: splits the skeletal mesh into per-bone, per-material visual meshes (`meshes/`, listed in `source/mebot_meshes.json`) |
| `source/` | Those dumps, checked in so the models build without the editor |
| `build_mebot_mjcf.py` | Writes the models and scenes from the dumps; every placeholder value is in `PARAMS` at the top |
| `mebot.xml`, `mebot_scene.xml` | The robot, and the robot on a floor facing a 15 cm curb (generated) |
| `mebot_powered_front.xml`, `mebot_powered_front_scene.xml` | The same with hub motors on the front omni wheels (generated) |
| `meshes/omni_*_roller.stl` | The omni wheels' rollers (generated) |
| `check_mebot.py` | Headless checks of both models: each stands on all six wheels, every motor moves the way the model says, and the linkages stay closed |
| `curb_sequence.py` | The curb crossing, up or down, for either model: a scripted stop-and-step sequence, optionally rendered to a clip |

```bash
python Scripts/editor_remote_exec.py --file mujoco/mebot/extract_ue_mebot.py          # only when the Unreal asset changes
python Scripts/editor_remote_exec.py --file mujoco/mebot/extract_ue_mebot_meshes.py   # likewise
python mujoco/mebot/build_mebot_mjcf.py [--rider-kg 75]
python mujoco/mebot/check_mebot.py
python mujoco/mebot/curb_sequence.py --variant powered_front --dir up [--height 0.15] [--clip climb.mp4]
python -m mujoco.viewer --mjcf=mujoco/mebot/mebot_scene.xml
```

The builder and the checks need `mujoco` and `numpy`; `--clip` also needs `imageio-ffmpeg` and `Pillow`.

## The model

- **chassis**: a free body with the frame, the seat site and a rider mass on the seat (`--rider-kg 0` leaves it empty).
- **translator_l / _r**: slides along X; each carries its drive wheel's plate. Positive moves the drive wheel forward.
- **elevator_l / _r**: hinges at the swing-arm pivot; they set each drive wheel's height. Positive puts the wheel down and raises the chassis.
- **drive_wheel_l / _r**: torque motors. Positive drives forward.
- **front_arm / rear_arm**: hinges; each arm carries a pair of omni wheels. Positive puts the wheels down and raises that end. The front arm is driven directly. The rear arm is sprung and not driven itself.
- **rear_lift**: the rear suspension arm, which the rear actuator turns. It pushes the rear arm down through the aux link, the damper's pivot and the damper. Positive puts the rear wheels down.
- **rear_spring**: the damper's rod, a preloaded spring-damper (`PARAMS["rear_spring"]`). It sits on its top-out stop until the rear wheels take load.
- **front_omni_* / rear_omni_***: omni wheels. Each is a hub plus two staggered rows of passive barrel rollers, measured from the visual meshes:
  - front: 2 × 12 rollers;
  - rear: 2 × 18 rollers, with treads 2.5 cm outboard of the physics asset's hulls.

  Each roller's profile follows the wheel's circle, so the wheel rolls round. In `mebot_powered_front` the front hubs have torque motors (positive forward); otherwise they turn freely.

The lift joints are driven directly by position actuators; the rear one sits at the suspension arm. The linear actuators and their links are light bodies that follow those joints through loop closures, the physics asset's user constraints, so the meshes move as the robot moves. Apart from the rear chain, they carry no load. The robot's geoms collide only with the world.

**The rear's reach:** it puts its wheels 14–15 cm down but lifts them only about 4.7 cm, because the rear arm turns roughly 0.5–0.9° per degree of suspension arm. The lift is also stopped short of where the rear actuator passes dead centre, near −40° of suspension arm. On the robot, the actuator's real stroke and mounts set this limit.

- **Geom groups:** 2 visual meshes; 3 collision geoms (boxes, the drive wheels' cylinders, the rollers).
- **Custom numerics:**
  - the wheel radii: `drive_wheel_radius`, `front_omni_radius`, `rear_omni_radius`;
  - the lift speeds for whatever commands the position actuators: `elevator_speed_deg_s`, `caster_arm_speed_deg_s`, `rear_lift_speed_deg_s`, `translator_speed_cm_s`.
- **Keyframe `home`:** the reference pose, with every lift at 0. The Unreal pawn is put in it at spawn, which also stands the robot on the ground.
- **Rider:** its marker is transparent, because URLab draws any alpha above 0 opaque. MuJoCo clips tint it back in.

**Placeholders:** masses, actuator gains, forces and speeds, and the rear spring's rate, preload, damping and travel in `PARAMS` stand in until they are measured on the robot. The joint ranges are the Unreal physics asset's limits.

## The curb crossing

`curb_sequence.py` keeps the chassis level and riding just under curb height, raised for a climb and lowered for a descent, so the frame clears the edge. The height is picked from every support's reach. Each pair of supports (front omni wheels, drive wheels, rear omni wheels) is lifted over the edge and set down in turn. Each touchdown lowers from the wheels' measured height until the pair carries load. While the sprung rear is down, its lift is trimmed against the chassis's pitch.

The rule: the rear omni wheels are not lifted until both drive wheels are on the far level, translated aft and each carrying 10% of the weight, with the centre of mass ahead of their axle. With a rider on the seat, the centre of mass sits behind the drive axle; lifting the rear omni wheels any earlier tips the robot back.

- **standard:** with the drive wheels up, the translators carry them forward over the edge. Once set down, they are translated aft while braked, which pulls the chassis forward over them.
- **powered_front:** with the drive wheels up, the front omni wheels pull the robot forward while the translators bring the drive wheels aft, so the wheels land already aft. Up and down each take about 30% less time than the standard sequence with these placeholder speeds.

With these limits it crosses 8 to 15 cm both ways.
- **16 cm:** it climbs, but on the descent the front omni wheels can't reach the road.
- **17 cm:** no crossing height works, because the rear lifts its wheels only about 4.7 cm.
- **Pitch on climbs:** it reaches 3–4° nose-up. While the drive wheels are forward, the rear carries the most load and sags at full reach, beyond what the trim can correct.
