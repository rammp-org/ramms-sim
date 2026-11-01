# MeBot MJCF

A MuJoCo model of the MeBot base, built from its Unreal assets (the public ramms-assets skeletal mesh and physics asset).

| File | What it is |
|---|---|
| `extract_ue_mebot.py` | Editor script: dumps the bones, physics bodies, constraints and the seat socket to `source/mebot_ue.json` (read-only, nothing is saved) |
| `source/mebot_ue.json` | That dump, checked in so the model builds without the editor |
| `build_mebot_mjcf.py` | Writes `mebot.xml` and `mebot_scene.xml` from the dump; every placeholder value is in `PARAMS` at the top |
| `mebot.xml` | The robot (generated; edit the builder, not this file) |
| `mebot_scene.xml` | The robot on a floor, facing a 15 cm curb (generated) |
| `check_mebot.py` | Headless checks: it stands on all six wheels, and every motor moves the way the model says |

```bash
python Scripts/editor_remote_exec.py --file mujoco/mebot/extract_ue_mebot.py   # only when the Unreal asset changes
python mujoco/mebot/build_mebot_mjcf.py [--rider-kg 75]
python mujoco/mebot/check_mebot.py
python -m mujoco.viewer --mjcf=mujoco/mebot/mebot_scene.xml
```

## The model

- **chassis**: a free body with the frame boxes, the seat site and a rider mass on the seat (`--rider-kg 0` leaves it empty).
- **translator_l / _r**: slides along X; each carries its drive wheel's plate. Positive moves the drive wheel forward.
- **elevator_l / _r**: hinges at the swing-arm pivot; they set each drive wheel's height. Positive puts the wheel down and raises the chassis.
- **drive_wheel_l / _r**: torque motors. Positive drives forward.
- **front_arm / rear_arm**: hinges; each arm carries a pair of passive omni wheels (a hub plus two staggered rows of free rollers). Positive puts the wheels down and raises that end.

The lift joints are driven directly by position actuators. The real linear actuators and their linkages are not modelled, and neither is the rear arm's suspension damper. The robot's geoms collide only with the world.

**Placeholders:** the masses, actuator gains, forces and speeds in `PARAMS` stand in until they are measured on the robot. The joint ranges are the Unreal physics asset's limits. With a rider on the seat, the centre of mass sits behind the drive axle, so lifting the rear omni wheels while they carry weight tips the robot back.
