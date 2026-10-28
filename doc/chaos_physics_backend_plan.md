# Chaos as a physics backend for MuJoCo-described robots and objects: feasibility

Status: **feasibility study with a working spike** (2026-10-28). The spike's scripts are in
`Scripts/chaos_spike/` (see its README); nothing in the runtime changed.

The question: can the robots and articulated objects RAMMS describes in MJCF (through URLab) also run on
Chaos, so a user picks the engine that fits their application and their content? Matching MuJoCo exactly
is not the goal. The goal is one robot or object definition that runs on either engine, with RAMMS'
controllers, sensors and UI unchanged, where the Chaos version interacts natively with the user's existing
Chaos content.

## Short answer

**Feasible, with one hard part.** Generating a Chaos robot from the MJCF is mechanical. Free-space arm
motion tracks MuJoCo closely enough for teleop, navigation and data collection. Contact-rich manipulation
is the hard part: the spike's grasp, which MuJoCo holds with under 2 mm of slip, is dropped by Chaos on
every run.

| | Result in the spike (Kinova Gen3 + Robotiq 2F-85, built from `mujoco/gen3_2f85/gen3_2f85.xml`) |
|---|---|
| Building it | 20 Chaos bodies, 15 hinges, 2 loop-closing joints, all from the compiled MJCF, with no hand authoring |
| Arm tracking (2 s moves, MuJoCo's gains copied 1:1) | 0.02–0.08 rad RMS against MuJoCo, 0.01–0.09 rad steady-state offset, about 0.15 s lag on the return |
| Gripper kinematics | opens and closes; the four-bar loops hold (under 0.04 mm of loop error) |
| Gripper at rest | its passive second degree of freedom settles on the opposite stops from MuJoCo's (the pads tilt outward) |
| Grasp and tip a 50 g box | MuJoCo: held, 1.6 mm slip. Chaos: dropped in 3 of 3 runs, one of them with a light coupler spring added |

So the recommendation is to build it in phases (below). Phases 1–3 make bases, arms, articulated
furniture and free-space manipulation selectable per robot. Grasping on Chaos is its own work item, and
until it lands it is labelled as lower fidelity rather than promised.

## What exists today

- **Two robots, two physics paths.** `BP_Mebot_Ramms` runs on Chaos: the chair, arm and gripper are
  skeletal meshes with hand-authored physics assets, and the URDF importer
  (`Plugins/RammsCore/Content/Python/urdf/`) writes limits, masses and inertia into them.
  `BP_Mebot_Mujoco` runs on URLab's MuJoCo. Their link masses are kept equal by hand (`doc/robot_pawn.md`).
- **The actuation seam already exists.** Controllers command motors by id through
  `IRammsActuationBackend` (`RammsActuationBackend.h`). `URammsRobotBaseComponent` picks the
  Chaos-skeletal backend (RammsCore) or the MuJoCo backend (RammsMujocoSupport, through the registry).
  The Chaos backend has three gaps:
  - A torque motor is an acceleration change ×100, not N·m.
  - Velocity motors are ignored.
  - It only knows skeletal physics-asset constraints, not `PhysicsConstraintComponent`s between parts.
- **URLab's model is a component tree.** Each MJCF element is a `UMjNodeComponent`. Compiling it
  produces `mjModel`, with every default resolved and every body's mass, inertia, convex mesh, joint
  axis and actuator gain worked out.
- **URLab already supports other solvers.**
  - `UMjPhysicsEngine::CustomStepHandler` replaces `mj_step`. RammsNewtonPhysics uses it to step Newton
    and write the state back into `mjData`.
  - The `Puppet` step mode takes pushed state rather than stepping.
  - After either one, `mj_forward` keeps URLab's sensors, render pump, recording and bridge consistent.
- **The 2026-09-11 roadmap (`doc/mujoco_sim_roadmap.md`) set Chaos aside for MuJoCo.** This study
  revisits that decision as a user-selectable option, not a replacement.

## What Chaos offers here (UE 5.8, from the engine headers)

- **Rigid bodies with maximal-coordinate joints.** The engine's Chaos has no Featherstone or
  reduced-coordinate articulation solver.
- **Joint settings that help long chains:**
  - per-axis limits, including soft limits
  - linear and angular drives (position and velocity, with a max force), in force or acceleration mode
  - projection, shock propagation and mass conditioning (`ParentInvMassScale`)
  - a linear joint solver (all in `PBDJointConstraintTypes.h`)
- **Project settings:** async physics at a fixed 10 ms step, 16 position and 8 velocity iterations,
  enhanced determinism.
- **Plugins that might be useful later:**
  - Physics Control (1.0, not experimental): targets for bodies and constraints.
  - ImmediatePhysics: a private Chaos simulation you step yourself, as the RigidBody anim node does.
  - Control Rig Physics (beta in 5.8) and Chaos Rigid Asset (experimental).

## Options

| | A. Chaos bodies in the world, built from the compiled model *(recommended)* | B. Chaos stepper behind URLab (like Newton) | C. Offline export to skeletal mesh + physics asset |
|---|---|---|---|
| How | At BeginPlay, a component builds Chaos bodies and constraints from `mjModel` in the world's physics scene and moves URLab's visuals onto them | `CustomStepHandler` steps an ImmediatePhysics simulation at the MJCF timestep and writes `qpos`/`qvel` back | An editor tool writes a skinned mesh and physics asset from the MJCF (an extension of today's URDF importer) |
| Interacts with the user's Chaos content | **Yes**: same scene as their props, ragdolls, vehicles, destruction and Mover characters | No: world objects would have to be mirrored in as kinematic bodies | Yes |
| URLab sensors, bridge, recording | Through puppet-style state push (Phase 3) | For free, as with Newton | No |
| Rate | Project physics rate (100 Hz) | MJCF timestep (500 Hz) | Project physics rate |
| One source of truth | Yes | Yes | No: a generated copy that can drift |
| Fits | "My scene is Chaos" | "MuJoCo semantics, different solver" | "I want an asset I can edit in the Physics Asset Editor" |

**A** is the one that meets Chaos users where they are. **C** is worth keeping as a later export path.
**B** mostly duplicates what Newton already gives URLab.

## Mapping MJCF to Chaos

| MJCF (compiled) | Chaos | Notes |
|---|---|---|
| body with a joint, or free | simulated body | mass from `body_mass` |
| body with no joint | welded to its parent | becomes part of the parent's body, as in MuJoCo |
| `body_inertia` / `ipos` | Chaos inertia from shape × mass | an exact inertia tensor needs C++ (`FBodyInstance`); the spike skipped it |
| geom sphere / capsule / box | sphere / capsule / box element | exact |
| geom mesh | convex element | **MuJoCo collides a mesh as its convex hull, so this matches** (the spike re-hulled with V-HACD at 32 vertices; the builder should pass MuJoCo's hull through) |
| geom cylinder | convex (sided hull) | no Chaos cylinder; wheels become polygons, so prefer the chair's existing sphere wheels |
| geom ellipsoid, hfield, sdf | convex / heightfield / unsupported | |
| hinge / slide / ball | constraint: twist free or limited, the rest locked / one linear axis / swing free | the constraint X axis is the joint axis; signs as in URLab's axis conversion (Y flipped, axis = (−x, y, −z)) |
| asymmetric `range` | limit of half the range plus `AngularRotationOffset` at mid-range | drive targets then subtract mid-range |
| `damping` | angular velocity drive to 0 | |
| `armature` | none | add to the child's inertia if needed |
| `frictionloss` | velocity drive to 0 with a max force | approximate |
| `<position>` / `<general>` servo (kp, kv, forcerange) | twist position + velocity drive, force mode | stiffness = kp·10⁴, damping = kv·10⁴, max = force·10⁴ (N·m to kg·cm²/s²) |
| `<velocity>` | velocity drive | |
| `<motor>` | equal and opposite torques on child and parent at the physics rate | also fixes today's ×100 acceleration hack |
| fixed tendon actuator | per-joint drives with coefficient-scaled gains | the spike does this for the 2F-85 |
| spatial tendons, `joint` equality, `polycoef` | none | compute in the backend each physics step, or drop |
| `connect` equality | point constraint (angular free) | closes loops; held under 0.04 mm in the spike |
| `weld` equality | locked constraint, or a kinematic target for mocap welds | |
| contype / conaffinity / exclude / parent filter | self-collision rules | **required**, see Gotchas |
| friction (sliding) | physical material | MuJoCo takes the max of the pair's frictions (or the geom with higher priority); Chaos averages by default |
| torsional / rolling friction, solref / solimp, margin | none | Chaos contacts are rigid |
| sites, cameras | scene components | |
| sensors | URLab's, from mirrored `qpos`/`qvel` (Phase 3); touch and force from Chaos contacts and constraint forces | |

## The spike

`Scripts/chaos_spike/` builds the Gen3 + 2F-85 in Chaos from the MJCF and runs it against MuJoCo on the
same targets:

1. **`mjcf_chaos_export.py`** (host Python with `mujoco`): compiles the MJCF and writes, in Unreal's frame,
   each body's pose at `qpos0`, its mass, and the convex hull of its collision geoms, plus the joints,
   servo gains, tendon couplings and connect equalities.
2. **`build_chaos_proto.py`** (editor): makes a hull static mesh per body, a `StaticMeshActor` per body
   (welded bodies attached), and a `PhysicsConstraintActor` per joint and per connect, with limits and
   force-mode drives, in `/Game/ChaosProto/Map_ChaosProto`.
3. **`chaos_pie.py`** (editor, PIE): drives the joints through `traj.py`'s schedule and measures each
   joint's angle from the body poses, the same way for both engines.
4. **`mj_ref.py`, `mj_grasp.py`**: the MuJoCo runs. **`cmp.py`, `plot_track.py`**: the comparison.

![Chaos and MuJoCo following the same joint targets](images/chaos_backend/chaos_vs_mujoco_tracking.png)

Arm, 9 s run (out at 1–3 s, hold, back at 7–8.5 s; the gripper closes at 4 s):

| joint | RMS vs MuJoCo | max | at 6 s, Chaos | at 6 s, MuJoCo |
|---|---|---|---|---|
| joint_1 | 0.025 | 0.065 | 0.589 | 0.600 |
| joint_2 | 0.069 | 0.160 | 0.901 | 0.911 |
| joint_3 | 0.022 | 0.054 | 0.018 | 0.000 |
| joint_4 | 0.058 | 0.118 | 1.550 | 1.603 |
| joint_5 | 0.020 | 0.039 | 0.009 | 0.000 |
| joint_6 | 0.084 | 0.168 | 0.515 | 0.600 |
| joint_7 | 0.030 | 0.074 | 0.847 | 0.800 |

(radians)

**Not tuned.** The gains are MuJoCo's, copied 1:1, and Chaos runs at 100 Hz against MuJoCo's 500 Hz.
Angles are read on the game thread, which sees async physics one step late; that probably accounts for
part of the lag. The steady-state offsets (0.05–0.09 rad on joints 4 and 6) are not explained yet.
Likely candidates are joint-solver convergence on a 7-link chain and swing-limit leakage. They are the
first tuning item (drive mode, iterations, substep rate, projection).

**Grasp.** A 3×3×5 cm, 50 g box stands on the gripper base. The gripper closes at 1 s, then joints 2, 4
and 6 tip it over, so gravity pulls the box across the pads.
- MuJoCo holds it (1.6 mm of slip).
- Chaos drops it about 1 s into the tip, on all three runs (one with a light spring added on the coupler).

The likely cause is the 2F-85's underactuated second degree of freedom. In MuJoCo, joint armature,
damping and the soft equality keep it still; in Chaos it sits on the opposite stops. So the pads meet the
box tilted and on their edges.

### Gotchas the spike hit (each one is a rule for the real builder)

1. **Self-collision has to follow MuJoCo's rules.** With every part colliding, the arm came apart before
   the run started; the spike's hulls (V-HACD, at most 32 vertices) are looser than MuJoCo's, so
   non-adjacent links most likely overlapped at `qpos0`. MuJoCo filters
   parent/child pairs and `<exclude>`s and uses contype/conaffinity. The spike makes every part ignore the
   rest (as `bApplySelfCollisionChannel` does for robot pawns). The builder should apply the real MuJoCo
   rules.
2. **A drive target does not wake a sleeping body.** Bodies at rest ignored new targets until they were
   woken each tick. The real backend has to wake bodies on every command, or keep robot bodies out of
   sleep.
3. **Use force mode for physical gains.** Drives default to acceleration mode (`bAccelerationMode`). With
   it off, kp/kv/forcerange carry over as N·m ×10⁴.
4. **Asymmetric limits need the rotation offset, and then targets need correcting.** A limit is
   symmetric about the constraint frame, so the frame is offset to mid-range and every target has mid-range
   subtracted. Without the correction, the gripper's drivers sat at 0.4 rad at "open" and the linkage
   folded into its other branch.
5. **Use a neutral game mode for test levels.** The project's default game mode spawned the MeBot on top
   of the test robot.

## Gaps and risks, most serious first

1. **Grasping and contact-rich manipulation.** Rigid contacts, no torsional friction, friction averaged
   rather than maxed, and small fast parts. Options:
   - author the gripper's passive compliance explicitly
   - offer a fully-actuated (parallel-jaw) gripper variant for Chaos
   - tune contact (margins, iterations, CCD on pads)
   - a clearly-labelled grasp assist (a weld once contact is stable)
   This needs your call; see the questions.
2. **Mass ratios and closed loops.** The pads are 3.5 g, on a 60 kg chair. Maximal-coordinate solvers
   struggle with that. The 2F-85's loops held here, but the arm was on a fixed base, not the moving
   chair. Mass conditioning, projection, and floors on mass and inertia are the levers.
3. **MJCF features with no Chaos equivalent:**
   - joint equalities, `polycoef`, spatial tendons
   - `armature`, `frictionloss`
   - soft contacts (`solref`/`solimp`), `condim` 4/6
   Most can be approximated in the backend's physics-rate callback. Each one is a documented divergence.
4. **Rate and latency.** Chaos runs at the project's 10 ms async step. Raising it costs every simulated
   object in the level. Readings on the game thread lag one step.
5. **URLab features tied to `mjData`** (its sensors, recording/replay, the ZMQ bridge and the gym env)
   work on Chaos only through the state mirror (Phase 3). Contact-derived sensors need Chaos hit events.
6. **Wheels.** MJCF cylinders become convex polygons. The base needs the Chaos chair's existing wheel
   treatment, not a literal conversion.

## Plan

**Phase 1: a Chaos build of a URLab articulation** (C++, in RammsMujocoSupport, since it needs URLab):
- `URammsChaosArticulationComponent` on an `AMjArticulation`, plus a backend choice (MuJoCo / Chaos) on
  the articulation or the robot base.
- On Chaos it compiles the spec (MuJoCo is used only as the compiler) and does not register with
  `AAMjManager`.
- It builds runtime body setups with exact primitives and convex elements from `mjModel`, welds jointless
  bodies, makes an `FConstraintInstance` per joint, and applies MuJoCo's collision filtering.
- It reparents URLab's geom visuals onto the Chaos bodies.
- Acceptance: the spike's tracking numbers or better, from C++, and the arm holds a pose while mounted
  on the moving chair.

**Phase 2: `FRammsChaosArticulationBackend`** (`IRammsActuationBackend`):
- Motor ids resolve to MJCF actuators.
- Servos become drives; `<motor>` becomes physical torque pairs, and velocity PI loops run in an async
  physics callback. This also gives the skeletal Chaos backend a way off its ×100 hack.
- Tendon and coupled actuators are computed per step.
- The same `DT_*Motors` tables drive either engine.

**Phase 3: mirror into URLab:**
- Push `qpos`/`qvel` measured from Chaos into `mjData` each physics step, puppet-style, then run
  kinematics and sensors.
- URLab sensors, recording and the bridge then report the Chaos robot. Touch and force sensors come from
  Chaos contacts and constraint forces.

**Phase 4: articulated objects and a mixed acceptance suite:**
- SimReady furniture (`sr_fc_microwave_oven`, `sr_fc_refrigerator`) on Chaos.
- A `Ramms.Chaos.*` automation suite that turns the spike's comparisons into tests: tracking error,
  loop closure, door swing against MuJoCo.

**Phase 5: manipulation fidelity on Chaos** (gripper compliance, contact tuning, and the grasp policy
decided below).

**Later:** export path C (MJCF to skeletal mesh + physics asset) for users who want editable Chaos
assets. It may also be how `BP_Mebot_Ramms`' hand-authored assets get generated rather than maintained.

## Questions for you

1. **What goes first on Chaos?** The arm on the chair (both MeBots), the SimReady articulated objects, or
   both?
2. **Grasping on Chaos:** acceptable to ship a labelled "grasp assist", or physics only, with lower
   fidelity documented?
3. **Mixed scenes:** is "everything on one engine" enough? Or do you want a MuJoCo robot with Chaos-only
   props? That second case already works one way through quick-convert, but two-way coupling between
   engines is a different project.
4. **Should the generated Chaos robot replace the hand-authored `BP_Mebot_Ramms` once it matches,** or
   should both stay?
