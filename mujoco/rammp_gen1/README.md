# RAMMP Gen1 MJCF

MuJoCo models of the RAMMP Gen1 base, built from its Unreal assets (the public ramms-assets skeletal mesh and physics asset), and the reference sequence for its curb controller.

| File | What it is |
|---|---|
| `extract_ue_rammp_gen1.py` | Editor script: dumps the bones, physics bodies, constraints and the seat socket to `source/rammp_gen1_ue.json` (read-only, nothing is saved) |
| `extract_ue_rammp_gen1_meshes.py` | Editor script: splits the skeletal mesh into per-bone, per-material visual meshes (`meshes/`, listed in `source/rammp_gen1_meshes.json`) |
| `source/` | Those dumps, checked in so the models build without the editor |
| `build_rammp_gen1_mjcf.py` | Writes the models and scenes from the dumps, each with the Gen3 arm (`../gen3_2f85/gen3_2f85_fixed.xml`) on its seat; every placeholder value is in `PARAMS` at the top. The seat and the arm splice come from `../rammp_seat_arm.py`, which RAMMP Gen2's model uses too |
| `rammp_gen1.xml`, `rammp_gen1_scene.xml` | The robot, and the robot on a floor facing a 15 cm curb (generated) |
| `rammp_gen1_powered_front.xml`, `rammp_gen1_powered_front_scene.xml` | The same with hub motors on the front omni wheels (generated) |
| `meshes/omni_*_roller.stl` | The omni wheels' rollers (generated) |
| `check_rammp_gen1.py` | Headless checks of both models: each stands on all six wheels, every motor moves the way the model says, and the linkages stay closed |
| `curb_sequence.py` | The curb crossing, up or down, for either model: a scripted stop-and-step sequence, optionally rendered to a clip |
| `export_curb_config.py` | Writes `curb_config_<variant>.json` for the Unreal curb controller: each support's height table (as `curb_sequence.py` builds it), the wheel radii, the frame's clearance, the lift speeds, and the mass model for the rear-lift rule |

```bash
python Scripts/editor_remote_exec.py --file mujoco/rammp_gen1/extract_ue_rammp_gen1.py          # only when the Unreal asset changes
python Scripts/editor_remote_exec.py --file mujoco/rammp_gen1/extract_ue_rammp_gen1_meshes.py   # likewise
python mujoco/rammp_gen1/build_rammp_gen1_mjcf.py [--rider-kg 75] [--no-arm]
python mujoco/rammp_gen1/check_rammp_gen1.py
python mujoco/rammp_gen1/curb_sequence.py --variant powered_front --dir up [--height 0.15] [--stance -14 9 0] [--clip climb.mp4]
python mujoco/rammp_gen1/export_curb_config.py [--variant powered_front]   # after the model changes; then Scripts/rammp_gen1_mujoco/make_rammp_gen1_pawn.py
python -m mujoco.viewer --mjcf=mujoco/rammp_gen1/rammp_gen1_scene.xml
```

The builder and the checks need `mujoco` and `numpy`; `--clip` also needs `imageio-ffmpeg` and `Pillow`.

## The model

- **chassis**: a free body with the frame and the caster-arm mounts (80 kg).
- **seat**: welded to the chassis on the `seat_base` socket, with the `seat` and `arm_mount` sites. It carries the seat's own mass (40 kg, with its rails and mounts) and a rider mass 25 cm above the socket (75 kg; `--rider-kg 0` leaves it empty). The Unreal pawn hangs the seat's meshes, its seated occupant and its sensors on this body.
- **arm_\***: the Kinova Gen3 + Robotiq 2F-85, spliced in on the arm mount, where `BP_RammpGen1_Ramms` carries it (16 cm ahead of the socket and 26.5 cm to its right), with its names prefixed `arm_`. It is held stowed in the Gen3's Retract position (`PARAMS["arm_stow"]`, the numeric `arm_stow`): folded upright beside the rider, behind the front omni wheels. Like the robot's own geoms, it collides only with the world. `--no-arm` leaves it off.
- **translator_l / _r**: slides along X; each carries its drive wheel's plate. Positive moves the drive wheel forward.
- **elevator_l / _r**: hinges at the swing-arm pivot; they set each drive wheel's height. Positive puts the wheel down and raises the chassis.
- **drive_wheel_l / _r**: torque motors, with a geared motor's inertia at the wheel (armature 0.1 kg·m²). Positive drives forward.
- **front_arm / rear_arm**: hinges; each arm carries a pair of omni wheels. Positive puts the wheels down and raises that end. The front arm is driven directly. The rear arm is sprung and not driven itself.
- **rear_lift**: the rear suspension arm, which the rear actuator turns. It pushes the rear arm down through the aux link, the damper's pivot and the damper. Positive puts the rear wheels down.
- **rear_spring**: the damper's rod, a preloaded spring-damper (`PARAMS["rear_spring"]`: 1 MN/m, 30 kN·s/m, 600 N preload). It sits on its top-out stop until the rear wheels take load, then gives about 1 mm in the outdoor stance. It used to be 200 kN/m and 5 kN·s/m, softer and springier than the robot's: that sagged 6 mm and rang for about four half-swings at 1.5 Hz (2.4° of pitch) after braking from 1 m/s, where this swings 0.4°.
- **front_omni_* / rear_omni_***: omni wheels. Each is a hub plus two staggered rows of passive barrel rollers, measured from the visual meshes:
  - front: 2 × 12 rollers;
  - rear: 2 × 18 rollers, with treads 2.5 cm outboard of the physics asset's hulls.

  Each roller's profile follows the wheel's circle, so the wheel rolls round. In `rammp_gen1_powered_front` the front hubs have torque motors (positive forward); otherwise they turn freely.

The lift joints are driven directly by position actuators; the rear one sits at the suspension arm. The linear actuators and their links are light bodies that follow those joints through loop closures, the physics asset's user constraints, so the meshes move as the robot moves. Apart from the rear chain, they carry no load. The robot's geoms collide only with the world.

**The rear's reach:** it puts its wheels 14–15 cm down but lifts them only about 4.7 cm, because the rear arm turns roughly 0.5–0.9° per degree of suspension arm. The lift is also stopped short of where the rear actuator passes dead centre, near −40° of suspension arm. On the robot, the actuator's real stroke and mounts set this limit.

- **Geom groups:** 2 visual meshes; 3 collision geoms (boxes, the drive wheels' cylinders, the rollers).
- **Custom numerics:**
  - the wheel radii: `drive_wheel_radius`, `front_omni_radius`, `rear_omni_radius`;
  - the lift speeds for whatever commands the position actuators: `elevator_speed_deg_s`, `caster_arm_speed_deg_s`, `rear_lift_speed_deg_s`, `translator_speed_cm_s`;
  - `arm_stow`: the arm's stowed joint angles (rad, joint_1..7). `build_rammp_gen1_mjcf.hold_arm_stowed` puts it there and holds it, and the Unreal arm IK starts there.
- **Keyframe `home`:** the reference pose, with every lift at 0. The Unreal pawn is put in it at spawn, which also stands the robot on the ground.
- **Rider:** its marker is transparent, because URLab draws any alpha above 0 opaque. MuJoCo clips tint it back in.

**Placeholders:** masses, actuator gains, forces and speeds, and the rear spring's rate, preload, damping and travel in `PARAMS` stand in until they are measured on the robot. The speeds are 18°/s for the elevators, 13 cm/s for the translators, 30°/s for the front caster arm and 26°/s for the rear lift, all estimated from a video of the robot. In it the caster arms go their full throw in 2–4 s, the carriages theirs in 5–7 s, and the drive wheels drop in about 2 s. The first two are taken as 3 s and 6 s over this model's ranges; the last is the elevators' 34–36° lift and set-down on a 15 cm crossing. The lifts' servos are stiff, because the electrohydraulic actuators hold where they are put: a 10° elevator command under the full load reaches 8.3°. The joint ranges are read from the Unreal physics asset's constraints; a range set in `PARAMS` overrides them. With the seat, rider and arm the robot is 246 kg.

## The curb crossing

`curb_sequence.py` keeps the chassis level and riding just under curb height, raised for a climb and lowered for a descent, so the frame clears the edge. The height is picked from every support's reach. Each pair of supports (front omni wheels, drive wheels, rear omni wheels) is lifted over the edge and set down in turn. Each touchdown lowers from the wheels' measured height until the pair carries load. While the sprung rear is down, its lift is trimmed against the chassis's pitch, as fast as the rear lift moves. The trim has to level the chassis while the translators re-centre after a climb; otherwise the rear sags as the drive wheels move forward, and the frame meets the curb.

The rule: the rear omni wheels are not lifted until both drive wheels are on the far level, translated aft and each carrying 10% of the weight, with the centre of mass ahead of their axle. With a rider on the seat, the centre of mass sits behind the drive axle; lifting the rear omni wheels any earlier tips the robot back.

- **standard:** with the drive wheels up, the translators carry them forward over the edge. Once set down, they are translated aft while braked, which pulls the chassis forward over them.
- **powered_front:** with the drive wheels up, the front omni wheels pull the robot forward while the translators bring the drive wheels aft, so the wheels land already aft. Their hubs hold the robot from the start of the drive wheels' lift: braked, the drive wheels grip the road as their arms swing them up and push the chassis back, and once they are off it nothing else stops it rolling. At 15 cm it takes about 38 s up and 43 s down; the standard sequence takes about 43 s up and 46 s down.

On a descent, the chassis is lowered onto the braked drive wheels before the rear omni wheels go down. That swings the drive wheels on their arms and can roll the robot back; if the rear omni wheels come back over the edge, it creeps on until they are past it again. Throughout, the arm is held stowed.

`--stance FRONT ELEVATORS REAR` starts the robot with its lifts at those angles (degrees). The outdoor stance is about `-14 9 0`: the front omni wheels up, the drive wheels down for ground clearance, the robot on its drive and rear wheels. Front omni wheels that start off the ground stay up. The chassis is levelled with them where they are, or higher if the crossing needs it, and they are not set down only to be lifted again at the curb. Every crossing ends with the translators and then every lift back where it started, and the levelling trim goes out with that last move, so the robot is back in its stance at its own pitch.

With these limits it crosses 8 to 15 cm both ways.
- **16 cm:** it climbs, but on the descent the front omni wheels can't reach the road.
- **17 cm:** no crossing height works, because the rear lifts its wheels only about 4.7 cm.
- **15 cm with the powered front:** the frame passes 2–5 mm over the curb top while the drive wheels are brought aft and re-centred; at 12 cm it keeps about 2 cm.
- **Pitch on climbs:** it reaches 2–3° nose-up with the seat, rider and arm (4.5–5° with the softer damper it had). While the drive wheels are forward, the rear carries the most load and sags at full reach, beyond what the trim can correct.
