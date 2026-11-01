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
- **front_arm / rear_arm**: hinges; each arm carries a pair of omni wheels. Positive puts the wheels down and raises that end.
- **front_omni_* / rear_omni_***: omni wheels. Each is a hub plus two staggered rows of passive barrel rollers, measured from the visual meshes:
  - front: 2 × 12 rollers;
  - rear: 2 × 18 rollers, with treads 2.5 cm outboard of the physics asset's hulls.

  Each roller's profile follows the wheel's circle, so the wheel rolls round. In `mebot_powered_front` the front hubs have torque motors (positive forward); otherwise they turn freely.

The lift joints are driven directly by position actuators. The linear actuators and their links are passive, light bodies that follow those joints through loop closures, the physics asset's user constraints. They move the meshes as the robot moves and carry no load. The rear actuator and suspension arm stay fixed to the chassis, because nothing in the Unreal asset connects them to the rear arm. The robot's geoms collide only with the world.

- **Geom groups:** 2 visual meshes; 3 collision geoms (boxes, the drive wheels' cylinders, the rollers).
- **Custom numerics:** `drive_wheel_radius`, `front_omni_radius` and `rear_omni_radius`.

**Placeholders:** masses, actuator gains, forces and speeds in `PARAMS` stand in until they are measured on the robot. The joint ranges are the Unreal physics asset's limits.

## The curb crossing

`curb_sequence.py` keeps the chassis level and riding just under curb height, raised for a climb and lowered for a descent, so the frame clears the edge. Each pair of supports (front omni wheels, drive wheels, rear omni wheels) is lifted over the edge and set down in turn. Each touchdown lowers from the wheels' measured height until the pair carries load.

The rule: the rear omni wheels are not lifted until both drive wheels are on the far level, translated aft and each carrying 10% of the weight, with the centre of mass ahead of their axle. With a rider on the seat, the centre of mass sits behind the drive axle; lifting the rear omni wheels any earlier tips the robot back.

- **standard:** with the drive wheels up, the translators carry them forward over the edge. Once set down, they are translated aft while braked, which pulls the chassis forward over them.
- **powered_front:** with the drive wheels up, the front omni wheels pull the robot forward while the translators bring the drive wheels aft, so the wheels land already aft. Up and down each take about 30% less time than the standard sequence with these placeholder speeds.

With the physics asset's joint limits, the arms reach about 15 cm up or down from the chassis. That makes 17 cm about the most the sequence can cross: the standard descent already runs out of rear-arm reach there.
