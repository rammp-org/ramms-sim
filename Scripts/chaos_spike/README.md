# Chaos backend spike

Builds the Kinova Gen3 + Robotiq 2F-85 from `mujoco/gen3_2f85/gen3_2f85.xml` as Chaos bodies and
constraints, runs it in PIE on the same joint targets as MuJoCo, and compares. Findings and the plan:
`doc/chaos_physics_backend_plan.md`. This is a throwaway spike, not the runtime design.

```
mjcf_chaos_export.py   host: compile the MJCF with MuJoCo, write bodies / hulls / joints / servos /
                       equalities in Unreal's frame (JSON)
build_chaos_proto.py   editor: hull meshes, a StaticMeshActor per body, a PhysicsConstraintActor per
                       joint and connect, force-mode drives, in /Game/ChaosProto/Map_ChaosProto
chaos_pie.py           editor: PIE run along traj.py, joint angles measured from body poses
traj.py                the target schedules (arm tracking; grasp-and-tip) and the test box
mj_ref.py, mj_grasp.py host: the same schedules in MuJoCo
cmp.py, plot_track.py  host: comparison table and figure
```

## Run

Host (any Python with `pip install mujoco scipy matplotlib`; run outside the repo root, whose `mujoco/`
folder shadows the package):

```sh
mkdir -p Saved/ChaosSpike && cd Saved/ChaosSpike
S=../../Scripts/chaos_spike; X=../../mujoco/gen3_2f85/gen3_2f85.xml
python3 $S/mjcf_chaos_export.py $X gen3_2f85_chaos.json
python3 $S/mj_ref.py $X mj_ref.json && python3 $S/mj_grasp.py $X mj_grasp.json
```

Editor Python console (options are `CP_*` globals, consumed by each run):

```python
import unreal; D = unreal.Paths.project_dir() + "Scripts/chaos_spike/"
exec(open(D + "build_chaos_proto.py").read())                    # builds and saves the level
CP_OUT = "track"; exec(open(D + "chaos_pie.py").read())          # -> Saved/ChaosSpike/track.json
```

For the grasp, rebuild with the box and run the grasp schedule:

```python
import sys; sys.path.insert(0, D); import traj
CP_BOX = traj.BOX; exec(open(D + "build_chaos_proto.py").read())
CP_OUT = "grasp"; CP_TRAJ = "grasp"; exec(open(D + "chaos_pie.py").read())
```

Then, on the host, `python3 $S/cmp.py track.json mj_ref.json` and
`python3 $S/plot_track.py track.json mj_ref.json tracking.png`.

The level and meshes under `/Game/ChaosProto` are generated; don't commit them.
