# Chaos backend spike

Builds a MuJoCo-described robot or object as Chaos bodies and constraints straight from its MJCF, runs
it in PIE on the same commands as MuJoCo, and compares the two. The findings and the plan are in
`doc/chaos_physics_backend_plan.md`. This is a throwaway spike, not the runtime design.

```
mjcf_chaos_export.py   host: compile the MJCF with MuJoCo; write bodies / collision hulls / joints /
                       actuators / connects / keyframes in Unreal's frame (JSON)
build_chaos_proto.py   editor: hull meshes, a StaticMeshActor per body, a PhysicsConstraintActor per
                       joint and connect, drives, in /Game/ChaosProto/Map_ChaosProto
chaos_pie.py           editor: run a schedule in PIE; joint angles measured from body poses
traj.py                the schedules: arm, grasp (Gen3 + 2F-85), base (keyframed stances + driving),
                       object (push every joint open)
mj_run.py              host: the same schedule in MuJoCo
cmp.py, plot_track.py  host: arm comparison table and figure
```

## Run

Host side. Use any Python with `pip install mujoco scipy matplotlib`, and run it outside the repo root,
whose `mujoco/` folder shadows the package:

```sh
mkdir -p Saved/ChaosSpike && cd Saved/ChaosSpike
S=../../Scripts/chaos_spike; X=../../mujoco/gen3_2f85/gen3_2f85.xml
python3 $S/mjcf_chaos_export.py $X gen3_2f85_chaos.json
python3 $S/mj_run.py $X gen3_2f85_chaos.json arm mj_arm.json
python3 $S/mj_run.py $X gen3_2f85_chaos.json grasp mj_grasp.json box
```

Editor side, in the Python console. Options are `CP_*` globals, and each run consumes them:

```python
import unreal; D = unreal.Paths.project_dir() + "Scripts/chaos_spike/"
CP_JSON = "gen3_2f85_chaos.json"; exec(open(D + "build_chaos_proto.py").read())   # builds and saves the level
CP_JSON = "gen3_2f85_chaos.json"; CP_OUT = "track"; CP_SCHED = "arm"; exec(open(D + "chaos_pie.py").read())
```

Then compare on the host: `python3 $S/cmp.py track.json mj_arm.json`, and
`python3 $S/plot_track.py track.json mj_arm.json tracking.png`.

- **Grasp:** build with the box (`import sys; sys.path.insert(0, D); import traj; CP_BOX = traj.BOX`),
  then run with `CP_SCHED = "grasp"`.
- **Any model with keyframes** (a lift-drive base): export it, run `mj_run.py ... base`, build with
  `CP_BASE_Z = 1.0`, then run with `CP_SCHED = "base"`.
- **Articulated objects:** use `CP_SCHED = "object"`.
- **Drive overrides:** `CP_DRIVE_OVERRIDE = callable(joint, constraint component)` adjusts drives at the
  start of a run. The base needed its servos' max force ×10; see gotcha 5.

The level and meshes under `/Game/ChaosProto` are generated, so don't commit them.
