# Physics backend unification plan

> ## Hand-off state (2026-08-18) — read this first when picking up
>
> **The Chaos "pin leak" is root-caused and fixed.** It was never a solver
> convergence problem: `UPhysicsConstraintComponent::UpdateConstraintFrames`
> DIVIDES the computed body-local frame positions by the constraint
> component's scale (`GetConstraintScale`, "used for limits"), and the
> gripper chain carries the imported-asset compensating scales — so the
> coupler-side pin frame shrank ~1000x and every gripper closure initialized
> AT THE COUPLER ORIGIN, permanently torn 4.79 cm. Three runtime/generator
> fixes landed in RammsMujocoSupport (see §6.21 for the full evidence
> chain): (1) `ApplyChaos` re-derives every constraint frame from the
> **MjBody component transform** (unique names, no template-chain drift) and
> **normalizes the constraint's world scale to 1** before
> Term/UpdateConstraintFrames/Init; (2) closure pins run **without
> projection** (measured: with projection the locked pin stays torn 4.8 cm;
> without it it holds 0.00–0.03 cm through free-flop and load); (3) the
> generator **reuses** the `ChaosRig_BackendSwitch` SCS node across
> regenerations (recreating it orphaned placed instances' `Backend=Chaos`
> overrides). Acceptance (new `Ramms.Probe` console command, headless
> `-game` + spectator-only): all 14 closure pins ≤0.03 cm at rest, upZ 1.00,
> zero base drift.
>
> **Open, well-characterized:** on the gripper's floored-mass links the
> ANGULAR constraint DOFs are inert in the live solver — twist limits
> (hard or soft) don't cap and twist drives (1e4, profile-verified on the
> live instance) contribute nothing, while the SAME constraints' linear
> locks and the pins enforce exactly. Fingers gravity-fall to ±81° through
> a 45.8° window. Bisects eliminated: frames (init sep 0.000), scale,
> projection, soft twist limits, soft swing cones, drive params, BP crud
> (reproduced on a clean regen of the pulled BP). Prime suspect: angular
> inertia conditioning (cm²-scale link inertias vs the 8 kg arm, ~1e4:1) —
> `Ramms.Debug.ArmInertiaScale` cvar exists for the experiment. After the
> mechanism holds, the real rest-pose fidelity items are asymmetric limit
> windows (driver [0°,45.8°], coupler [−90°,0°] — MuJoCo rests ON the
> stops) and spring targets honoring `springref` (spring_link preloads at
> +150°, not the spawn pose).
>
> **Workflow this session validated** (all headless, no editor UI):
> rig regen via `UnrealEditor-Cmd -ExecutePythonScript` +
> `unreal.RammsRigLibrary.generate_chaos_rig`; acceptance via `-game` on
> `Map_ChaosSmoke?game=/Script/Engine.GameMode?SpectatorOnly=1` with
> `-ExecCmds="Ramms.Validate ChaosBot, Ramms.Probe ChaosBot 15"` (probe
> report also lands in `Saved/RammsProbe.txt`). Spectator-only matters: the
> default game mode spawns a colliding pawn. Python `unreal.log` output is
> NOT reliably surfaced by headless runs — scripts should write a result
> file (see scratchpad `set_chaosbot_backend.py` pattern). Also fixed:
> `Ramms.Validate` no longer reports MuJoCo-mode instances as stale (their
> rig constraints are destroyed at BeginPlay by design).
>
> **2026-08-18 PM round (user feedback)**: (a) **Masses** — the tipping
> ("arm moves tip the base") was a data gap: only the 20 arm bodies carry
> authored `<inertial>`; MuJoCo auto-computes the base's ~202 kg but Chaos
> fell back to crude volume estimates. New `mujoco/bake_inertials.py`
> bakes MuJoCo's computed inertials into every body of the three
> `mebot_gen3*.xml` files (identity for MuJoCo, verified per-body; base
> now explicit at 202.3 kg vs the user's ~136 kg real-world estimate —
> real per-part `dojo_mass` remains the Blender FILL-ME) and
> `compose_mebot_gen3.py` bakes automatically on future regens.
> **Requires a BP reimport** from the baked `mebot_gen3_ue.xml`
> (scripted: scratchpad `reimport_mebot.py`). (b) **Repo landmine**:
> `.gitignore`'s `*.obj` ("compiled object files") has been eating the
> exporter's mesh OBJs — fresh clones cannot compile the mebot MJCFs with
> plain MuJoCo; `bake_inertials.py` regenerates them from the committed
> `.glb` sidecars (trimesh). (c) **Wheels** — undriven drive wheels rolled
> too freely: zero-command velocity-hold 2e5→8e5 (2e6 was propulsive
> during carriage strokes) + wheel body AngularDamping 0.5→2.0.
> (d) **Fingers — RESOLVED (drivable)**, three stacked fixes:
> unit-scale pre-pass (gripper bodies simulated at component scale 0.001
> — 1000x meshes + compensating scale; the generator now bakes the scale
> into the mesh assets' BuildScale and resets the components to 1), then
> plugin commit dc7ffb4: the symmetric "sign-safe" twist windows let the
> four-bar fall ~46° into its nonphysical open region where the toggle
> singularity + hard pin linear rows overpower every angular row —
> gripper hinges now get their TRUE asymmetric MJCF windows (recorded
> twist centers, UE twist = −MJCF; parent ref frame rotated by the center
> at re-init, drive targets shifted) — plus `ProjectionAngularAlpha=0.25`
> on gripper joints (the UE default is 0.0: "projection on" never
> projected angular error; 1.0 tears the pins, 0.25 gives crisp windows
> AND pins ≤0.04 cm). Validated: rest in-window (drivers −4.1/+21.8°),
> commanded close moves both fingers (`Ramms.Joint ChaosBot
> arm_2f85_split 0.5`: right driver 21.8→12.8°, left follower off its
> stop −50.2→−28.7°), pins 0.007–0.037 cm, upZ 1.00. Remaining fidelity
> item: `springref` preload emulation (spring_link tensions toward +150°)
> so the gravity-side finger doesn't rest on its −50° follower stop.
> **HARNESS GOTCHA (burned a whole bisect campaign): `-ExecCmds` cvars
> apply AFTER the first world tick, i.e. after ApplyChaos** — every
> earlier drives-off / drive-scale / inertia-scale "no effect" result was
> testing nothing. ApplyChaos now parses `-Ramms*` COMMAND-LINE overrides
> for bisects; also the `arm_` name-prefix tests never matched the actual
> `Viz_arm_...` component names (mass floor de-facto 0.15 everywhere —
> kept, flagged in dc7ffb4).
> (e) **Headless MJCF reimport now works**: URLab's import factory pops an
> interactive Python-setup dialog unless
> `Plugins/unreal-robotics-lab/Config/LocalUnrealRoboticsLab.ini` (local,
> untracked) stores `[PythonSettings] PythonPath=` pointing at a python
> with trimesh+numpy+scipy+Pillow — the Newton venv qualifies (scipy and
> Pillow were added to it). Scripted flow: delete BP → AssetImportTask on
> `mebot_gen3_ue.xml` (destination_name=mebot_gen3) → generate_chaos_rig →
> `Scripts/fixup_mebot_import.py` → re-place ChaosBot. Do NOT kill an
> UnrealEditor-Cmd process after its log looks done — the python
> save_asset runs after the last C++ log line (a mid-save kill silently
> discarded one regen).
>
> **2026-08-18 EVE (visual-frame fix + import-pipeline lessons)**: the
> base visuals were rotated out of frame because my GLB→OBJ mesh restore
> skipped the pipeline's axis convention — empirically a **+180° X
> rotation** on the trimesh-loaded GLB lands the round-trip back in the
> body frame (verified per-part against collision AABBs; the −90°X in
> URLab's clean_meshes composes with trimesh's own glTF conventions).
> `bake_inertials.py` now applies it and can also regenerate the GLB
> sidecars in pipeline convention. **The fix was applied SURGICALLY**:
> per-asset in-place `AssetImportTask` reimport of the 60 base static
> meshes from their corrected GLB sources + one rig regen — the BP, map
> and placed actors were never recreated. Validated: meanV 10.6 cm/s,
> pins ≤0.05 cm, drivers in-window, asset bounds match collision truth.
> **Hard-won pipeline lessons**: (1) full BP reimports via the factory
> produced physically-broken content in several attempted flows
> (component scales inconsistent with mesh assets, placement shifts) —
> when a validated BP exists, prefer surgical mesh reimport + regen over
> re-import; (2) deleting an asset then importing the same name IN THE
> SAME editor session fails silently ("Failed to create asset" — the
> deleted object lingers); import in a fresh session; (3) the mesh
> assets are SHARED MUTABLE STATE (generator writes AggGeom + BuildScale
> into them) — a "restore the committed BP" control is only valid if the
> mesh asset folder is restored too; (4) respawning actors from
> broken-class instances reads garbage transforms — two overlapping
> robots produce a violent depenetration explosion (meanV thousands)
> with upZ=1.00 and zero drift, i.e. it looks like "vibration in place";
> keep the MuJoCo-mode twin far from the Chaos instance.
>
> **Newton**: worker-side `set_state` landed earlier (commit 8b87538, e2e
> tests); the UE bridge still deactivates on snapshot restore — wiring it
> is the next Newton item. The 1/10-speed fix (§6.8, DEALER/ROUTER
> pipelining) still needs sign-off. **URLab beta** (v0.6.0-beta, 992 files:
> ProtoSpec components-are-the-model, deletes the XML compile path, MuJoCo
> 3.11.1, breaks existing MjArticulation assets) fixes several things we
> work around (class-inherited gains, geom defaults) but is a deliberate
> multi-day migration — evaluated, not taken.

> ## Hand-off state (2026-08-07 PM) — superseded by the above
>
> **Actuator-driven PIE validation DONE** (RTX 4090): the gen3_2f85
> articulation BP (`/Game/Maps/URL/gen3_2f85` — the grasp map places no arm;
> it normally arrives with the play-time pawn, which simulate never spawns)
> was spawned in-level on `Map_GraspTestURL` and stepped **3+ minutes under
> Newton (nq=64 nu=8 nmocap=1)** with live EE-IK ctrl forwarding, tendon
> gripper actuation, and tracking-base mocap forwarding. Three real bugs
> found and fixed in the worker/bridge (details in the plugin README's Known
> issues): (1) URLab's mj_saveXML re-export re-compacts `solref*`/`solimp*`
> and newton's importer passes partial `solimp` through unpadded →
> divide-by-zero → scene-wide NaN in ≤3 GPU steps — worker now pads all six
> attrs to canonical length (`normalize_sol_shorthand`); (2) SolverMuJoCo's
> re-export appended a mocap body (nmocap 1→2) — worker now scatters
> original-layout mocap through a name-matched index map; (3) mujoco-warp
> sizes constraint buffers from the initial state and overflow is CUDA 700,
> not an error — worker now defaults `nconmax`/`njmax` to worst-case sizes.
> Plus: UE step handler refuses non-finite writeback (graceful deactivate),
> and `RAMMS_NEWTON_DUMP_DIR` dumps every `load_model` payload for CLI
> repro. **A scripted grasp does not hold yet**: free objects slide ~3 mm/s
> at rest under Newton — the known upstream contact-set translation issue
> (Milestone E blocker), now with in-editor measurements. **Next:** worker
> `set_state`; MJCF/USD authoring for the MeBot base toward base+arm
> integration under Newton; gen3_2f85 BP reimport from the fixed
> `gen3_2f85_scene_ue.xml` (asset predates the 08-06 fidelity fixes).
>
> ## Hand-off state (2026-08-07 AM) — superseded by the above
>
> **UE PIE validation DONE on the original dev machine** (which is
> exonerated — the warp crashes were old-mujoco-warp kernel TUs, gone since
> the 3.11 bump; full gate passes there now). Simulate session on
> `Map_GraspTestURL`: Newton bind ~16 s warm (GPU solver, nq=42),
> `ResetSimulation()` → worker resync ~2 s → stepping resumes, clean
> teardown with zero orphaned workers. The session flushed out a real bug,
> now fixed: **worker stdout/stderr pipe backpressure deadlocked
> `load_model`** (trimesh warning spam filled the un-drained pipe; worker
> blocked mid-write). Client now drains the pipe in its recv poll loop +
> READY wait + shutdown; worker quiets trimesh logging. **Next:** plugin
> README pickup checklist — actuator-driven PIE scene, then `set_state`.
>
> ## Hand-off state (2026-08-06) — superseded by the above
>
> **Milestone B worker-side runtime validation is DONE** on a healthy
> machine (Threadripper 9960X / RTX 5090, venv per plugin README): probe,
> both canaries, and the 27-test suite pass; the new `newton_worker parity`
> harness (Milestone B acceptance artifact) shows **~1e-4 qpos parity over
> 4 s** on fixed-base gen3_2f85 with contacts disabled, on both solvers
> (artifacts in `Scripts/parity_artifacts/`). Fixes that fell out: CPU-
> solver readback bug (frozen-state readback), unnamed-joint mapping,
> canary liveness check, kernel warmup inside `load_model` (first step was
> paying minutes of kernel compile against a 2 s step timeout), gen3 MJCF
> corrections in `mujoco/gen3_2f85/` (explicit two-value `solreflimit`,
> explicit `2f85_base_mount` inertial).
>
> **Resolved same day:** the mujoco-warp 3.10.x mesh-CCD kernel crash on
> Blackwell/sm_120 GPUs — `ThirdParty/newton` bumped to **v1.5.0rc2**
> (mujoco / mujoco-warp 3.11), full gate re-verified and parity artifacts
> regenerated under the new pins. **Remaining blocker, upstream-shaped**
> (details in the plugin `Scripts/README.md`): Newton's contact-set
> translation rewrites collision filtering, so contact-regime parity is
> ~0.5 rad — gates Milestone E grasping. **Next:** the plugin README's
> pickup checklist (PIE validation → set_state).
>
> ## Hand-off state (2026-08-05) — superseded by the above
>
> **Where the work lives:** superproject branch `feat/newton-improvements`;
> the `Plugins/RammsNewtonPhysics` submodule carries the rework (commits
> "WIP depend on Unreal Robotics Lab..." + "WIP Adding editor module +
> solver component"). The plugin's own **README.md is the operational
> hand-off doc** — architecture, new-machine setup (venv + canary
> verification), status table, and the ordered pickup checklist. This file
> is the design rationale and decision record.
>
> **Done (compile-clean):** Milestone A (worker + protocol + probe + UE
> client/settings/subsystem, 23-test pytest suite), Milestone B
> implementation (CustomStepHandler bridge), Milestone C core lifecycle
> (reset resync, restore refusal, attach policy, crash fallback), Milestone
> D first cut (Tools ▸ RAMMS Newton menu). Phase 0 done: RammsMujocoPhysics
> submodule removed; RammsHumanPhysics KEPT deliberately (RCareWorld
> placeholder).
>
> **The blocker that shaped everything:** the original dev machine's
> i9-14900K is degraded (Raptor Lake defect) and cannot reliably compile
> warp kernels — random native crashes and silent miscompiles. All
> runtime validation of B/C is therefore pending a healthy machine; the
> code compiles and the design bakes in subprocess isolation + canary +
> liveness checks because of this. **First action on the new machine:**
> plugin README "Setting up on a new machine" — both canaries must pass
> before anything else is meaningful.
>
> **Environment pins:** `ThirdParty/newton` at tag v1.4.0 (editable
> install), mujoco 3.10.0, mujoco-warp 3.10.0.3, warp-lang 1.16.0; venv is
> untracked — recreate per machine. URLab third_party install must be
> built (superproject README). — Chaos / Newton / MuJoCo

Status: proposal (2026-08-04). Covers the review of `Plugins/RammsNewtonPhysics` and
`Plugins/unreal-robotics-lab` (URLab), and the roadmap to (a) bring the Newton
integration up to URLab-grade workflows, and (b) migrate the Chaos robots from
skeletal meshes to Blueprint actors with physics constraints so one authoring and
control pipeline spans all three backends.

---

## 1. Where things stand

### URLab (MuJoCo) — the template, ~73k lines, alpha-labelled but substantially built
- **Authoring**: `AMjArticulation` Blueprints composed of `UMjComponent`s (`MjBody`,
  `MjHingeJoint`, `MjBox`/`MjMeshGeom`, 10 actuator types, ~45 sensor types, tendons,
  equalities, defaults, keyframes). SCS variable name = MuJoCo element name.
  `bOverride_*` + `InlineEditConditionToggle` encodes MJCF default-class inheritance.
- **Scene build**: programmatic `mjSpec` (no MJCF text emission at runtime); per-actor
  child spec + `mjs_attach` with a name prefix for multi-robot namespacing.
- **Runtime**: `AAMjManager` (thin coordinator) + `UMjPhysicsEngine` owning
  `mjModel/mjData` on a dedicated async stepping thread; **render-snapshot pump**
  (`FMjRenderSnapshot`, documented lock order) for physics→game state; **command
  queue** (mocap poses, wrenches) for game→physics; lock-free dual-channel actuator
  control (`InternalValue`/`NetworkValue` atomics).
- **Control**: `UMjArticulationController` (`Bind`/`ComputeAndApply` on the physics
  thread) + shipped PD/passthrough/keyframe controllers; ZMQ + shared-memory bridge
  with Live/Direct/Puppet step modes; `CustomStepHandler` seam replaces `mj_step`.
- **Editor**: MJCF drag-and-drop import factory (Menagerie-validated), CoACD convex
  decomposition (per-geom + right-click Quick Convert), SCS auto-parenting into
  semantic folders, `GetOptions=` dropdowns everywhere, MuJoCo Outliner tab, toolbar
  step-mode pill, `ValidateSpec` on BP compile, 249 automation tests.
- **Codegen**: UE component properties generated from MuJoCo schema snapshots
  (`Scripts/codegen/`), so engine version bumps are one command.

### RammsNewtonPhysics — an advanced scaffold, not yet a physics integration
Critical framing: **"Newton" here is the NVIDIA / Linux Foundation Newton engine**
(`newton-physics/newton`, Python-on-Warp, primary solver = MuJoCo-Warp) — **not**
Newton Dynamics. It has **no C/C++ SDK**; any integration is a bridge to Python.

What exists (~5.5k C++ + 816-line Python worker):
- A URDF-shaped, backend-neutral description schema (`FRammsNewtonRobotDescription`
  / link / joint / material types) — the best part of the plugin.
- `URammsNewtonPhysicsSubsystem` (fixed-step accumulator) → `FRammsNewtonNativeBackend`
  → **synchronous JSON-over-stdio RPC** to `Scripts/ramms_newton_worker.py`
  (ModelBuilder + `SolverXPBD`, joint construction, joint-state readback).
- `URammsNewtonArticulatedRobotComponent`: infers the robot from RammsCore's Chaos
  controllers + physics-asset constraints (gripper config read **via reflection on
  protected UPROPERTYs**); poseable-mesh mirror writeback; USD exporter scripts.

Known defects (fix regardless of strategy):
1. `HandleSimulationStep` / `ApplySolvedJointStates` are stubs — **the articulation
   loop never closes**; the flagship component ships `bAutoRegisterWithSubsystem=false`.
2. The built-in "adapter" is a mock (`SimulatedTimeSeconds += dt`) and
   `RefreshBackendStatus()` sets `bRuntimeReady=true` on every path — a broken
   install silently runs a fake solver.
3. `MaxSubstepsPerTick=1` at 240 Hz drops ~3/4 of steps at 60 fps and accumulates
   unbounded lag; Python mode **blocks the game thread** per step (up to 5 s timeout).
4. Latent unity-build bug: `RammsNewtonNativeBackend.cpp` calls `MakeJsonNumberArray`
   defined in an anonymous namespace of a *different* TU.
5. Any body/joint/gain change sets `scene_dirty` → full `builder.finalize()` rebuild.
6. No editor module, no tests, no log category, `StubOnly`/`HeadersOnly` modes dead.

### RammsMujocoSupport / RammsMujocoPhysics / RammsHumanPhysics
- `RammsMujocoSupport` is the real MuJoCo glue (EE DLS-IK controller on the physics
  thread, mocap-weld base tracking + sub-step smoothing, teleop, skeletal pose
  driver). Depends only on URLab; **zero connection to RammsCore** — it reimplements
  IK and gripper control instead of adapting the Chaos controllers.
- `RammsMujocoPhysics` and `RammsHumanPhysics` are **empty submodules** (README-only).
  RammsMujocoPhysics has stale `Intermediate/` artifacts of a deleted implementation
  that structurally cloned RammsNewtonPhysics (uncommitted local work may be at risk).

### Chaos stack (RammsCore + Content)
- Robots are BP actors carrying a skeletal mesh + PhysicsAsset + controller
  components. No Chaos vehicle for MeBot: `URammsDifferentialDriveController` torques
  wheel *bone bodies*; arm/gripper/Mebot controllers cache raw `FConstraintInstance*`
  and write Chaos angular drives directly — **computation and application are fused**.
- Already backend-neutral: `URammsIKLibrary` (DLS/FABRIK/CCD, pure), diff-drive math
  library, `URammsJointPoseAsset`, `URammsSkeletalPoseComponent` (kinematic pose sink),
  GPU sensors (trace the render TLAS, not physics — only `bUsePhysicsVelocity` on the
  IMU touches Chaos).
- URDF Python scripts only stamp values onto an *existing* PhysicsAsset. The Blender
  pipeline (`Scripts/robot_export.py`, `doc/rammp_robot_pipeline.md`) already exports
  per-part FBX + **MJCF** + USD + manifest; its open TODO is exactly the missing UE
  importer for constraint-component actors.
- **No shared backend interface exists anywhere** (zero UINTERFACEs). Newton scrapes
  the Chaos controllers by reflection; MuJoCo reimplements them; the closest thing to
  a contract is Newton's virtual set (`ApplySolvedJointStates` etc.).

---

## 2. Strategy — two unification seams, not one big abstraction

Verified enabler: the vendored Newton engine natively ingests **MJCF** (and URDF/USD)
via `ModelBuilder.add_mjcf/add_urdf/add_usd`, and ships `SolverMuJoCo` (MuJoCo-Warp)
alongside `SolverXPBD`.

### Seam 1 — MJCF as the canonical robot description (data plane)
One robot definition, three consumers:

```
Blender (dojo_* props) ──robot_export.py──▶  <robot>.mjcf.xml + per-part FBX + manifest
        (or hand-authored / Menagerie MJCF)          │
   ┌───────────────────────────┬─────────────────────┼──────────────────────────┐
   ▼                           ▼                     ▼
 MuJoCo: URLab import       Newton: worker loads   Chaos: NEW importer builds a BP
 factory → MjArticulation   MJCF via add_mjcf      actor (StaticMesh per link +
 BP (works today)           (SolverMuJoCo)         PhysicsConstraint per joint)
```

This is far cheaper than a shared component vocabulary, reuses infrastructure that
already exists (URLab importer, Blender exporter, gen3_2f85 composer), and gives
behavior parity for free where it matters (Newton's MuJoCo-Warp solver ≈ URLab's
MuJoCo, so the grasping contact tuning transfers).

### Seam 2 — a backend-neutral control interface in RammsCore (control plane)
Controllers compute targets; a **driver** applies them. Extracted from the signatures
that already exist (Newton's virtuals + the Kinova/Mebot/Gripper application code):

```cpp
// RammsCore — new
UINTERFACE() class URammsRobotBackend : public UInterface { ... };
class IRammsRobotBackend {
    virtual bool  BindRobot(const FRammsRobotBinding& Desc) = 0;      // names → handles
    virtual void  SetJointTarget(FName Joint, const FRammsJointTarget& T) = 0; // pos/vel/effort + gains
    virtual bool  GetJointState(FName Joint, FRammsJointState& Out) const = 0; // pos/vel/effort
    virtual FTransform GetLinkTransform(FName Link) const = 0;
    virtual void  SetBaseTwist(const FVector2D& VW) { }               // diff-drive convenience
};
```

Implementations: `ChaosConstraintDriver` (code extracted from today's controllers),
`MjArticulationDriver` (adapter over URLab actuators/joints — replaces
RammsMujocoSupport's from-scratch reimplementation), `NewtonBridgeDriver`.
`UKinovaGen3ControllerComponent`, `UGripperControllerComponent`,
`UMebotControllerComponent`, `URammsDifferentialDriveController` become
backend-agnostic consumers. This also **deletes the reflection hack** in
`RammsNewtonArticulatedRobotComponent` (the "pending RammsCore API rework" that
comment refers to is this) and dedupes the two DLS IK implementations and the two
teleop components onto `URammsIKLibrary` + one teleop parameterized by driver.

---

## 3. Roadmap

### Phase 0 — hygiene & honesty (days)
- Newton plugin: fail loudly instead of silently running the mock adapter
  (`bRuntimeReady` only true when the Python worker handshakes; on-screen + log
  warning otherwise). Add `LogRammsNewton` category.
- Fix `MaxSubstepsPerTick` starvation (raise default, clamp accumulated debt, warn on
  drop) and the cross-TU anonymous-namespace bug (move `MakeJsonNumberArray` to a
  shared private header).
- Submodule cleanup decision: delete or repurpose the empty `RammsMujocoPhysics` /
  `RammsHumanPhysics` repos; check whether anyone's local RammsMujocoPhysics work
  (evidenced by stale `Intermediate/`) needs rescuing.

### Phase 1 — Newton runtime rework (2–4 weeks)
Keep the out-of-process Python worker (structural: Newton has no C API), replace the
plumbing with URLab's proven patterns:
- **Transport**: binary framing over **ZMQ** (libzmq is already built in URLab's
  `third_party/install`; msgpack like URLab's bridge) — REQ/REP for control,
  PUB or SHM ring for state. Retire JSON-over-stdio.
- **Threading**: UE-side dedicated pump thread + render-snapshot struct + command
  queue, mirroring `UMjPhysicsEngine`'s producer/consumer design (same lock-order
  discipline). The game thread never blocks on the worker; it consumes the latest
  snapshot and interpolates/extrapolates one frame if the worker is behind.
- **Scene**: robot models load in the worker from **MJCF** (`add_mjcf`); default
  solver **`SolverMuJoCo`**, `SolverXPBD` switchable. Keep the existing UE-primitive
  scraping only for environment/props sync, and batch it (fix `scene_dirty`
  full-rebuild churn by separating pose updates from structural edits).
- **Close the articulation loop**: worker publishes `joint_q/qd` + link transforms →
  UE side applies to the robot actor (pose driver for skeletal visuals now; link
  components after Phase 4). Real drive semantics in the worker (position/velocity/
  effort targets with gains passed through, not the current bang-bang synthesis).
- Handshake carries model hash + solver + step rate; worker pytest suite from day one.

### Phase 2 — workflow & editor parity with URLab (2–3 weeks, overlaps 1)
Goal: authoring/running a Newton robot feels like URLab.
- **Recommended architecture: Newton as an alternate solver behind URLab's data
  model.** Author once as `AMjArticulation` BPs; a backend selector (project setting
  + per-manager override) installs a Newton `CustomStepHandler`-style path: URLab
  compiles the spec as today, the compiled XML + assets ship to the Newton worker,
  actuator `SetControl` values forward to Newton ctrl, and returned `qpos` is written
  back into `mjData` + `mj_forward` (Puppet-mode pattern) so **all** URLab machinery —
  snapshots, sensors, publishers, controllers, debug draw — keeps working unchanged.
  This buys workflow parity by construction instead of by duplication.
  - Fallback if upstream coupling proves too tight: keep RammsNewton's own actor
    path, but then mirror URLab's component naming/UX deliberately.
- Editor tooling (RammsNewtonPhysicsEditor module, new):
  - Toolbar status pill next to URLab's: worker alive / solver / achieved Hz / mode.
  - Details panel: `ValidateRobot` button (dry-run worker load of the MJCF),
    backend-status readout instead of log spelunking.
  - Project Settings polish (auto-locate venv Python, test-connection button).
  - MJCF/USD export actions wired into menus (the existing USD scripts are currently
    console-only); fix the `NewtonActuator` vs legacy `Actuator` USD schema mismatch.

### Phase 3 — the control seam in RammsCore (2–3 weeks)
- Introduce `IRammsRobotBackend` + `FRammsJointTarget/State` (shape above); note this
  is a **public RammsCore API change — review with the team first** (per CLAUDE.md).
- Extract `ChaosConstraintDriver` from the four controllers; controllers keep their
  public BP API but delegate application.
- Rebase `RammsMujocoSupport` on the seam: `MjArticulationDriver`, EE controller
  calls `URammsIKLibrary` (add its physics-thread-friendly DLS variant there), one
  shared teleop component. Restore proper getters on `UGripperControllerComponent`
  and delete Newton's reflection scraping.
- Keep what's proven: the mocap-weld base tracking / smoothing stays MuJoCo-specific
  inside the driver.

### Phase 4 — Chaos migration: skeletal mesh → constraint-component actors (3–5 weeks)
- **Build the missing importer** (editor tooling in RammsCore or a new
  `RammsRobotAuthoring` module): `.mjcf.xml` + manifest → Blueprint actor with one
  `UStaticMeshComponent` per link, one `UPhysicsConstraintComponent` per joint
  (angular/linear drives from motor props, mimic via gearing, loop closures as extra
  constraints), collision from manifest hulls / CoACD. Prior art:
  `UCabinetPhysicsTools::CreateBoxPhysicsAsset`; register a `UFactory` so drag-and-drop
  mirrors URLab's MJCF import (same file, two import flavors).
- Migrate **Gen3 arm first** (validate against the MuJoCo grasping baseline via the
  parity harness below), then **MeBot** (diff-drive controller moves from wheel bone
  bodies to wheel components via the driver seam), then props.
- Sensors: attachment parents change from bones/sockets to link components (straight
  swap); route the IMU's `bUsePhysicsVelocity` through the driver so it doesn't
  silently degrade on non-Chaos backends.
- Retire the URDF→PhysicsAsset Python path once the constraint-actor path is proven
  (keep the exporter).

### Phase 5 — verification, ongoing from Phase 1
- **Cross-backend parity harness**: same MJCF + same ctrl trajectory → compare qpos
  traces (MuJoCo vs Newton headless in Python; Chaos via a scripted PIE run). Gate
  robot-definition changes on it.
- UE automation tests patterned on URLab's suite (import round-trip, binding, step
  server); CI job for the worker pytest suite.
- Table-top grasp/lift test as the standing end-to-end check on every backend.

---

## 4. Decisions (resolved 2026-08-04)
1. **Newton-behind-URLab — as a sibling plugin, not a fork.** See §5.
2. **Newton is for both GPU-parallel fleets and local GPU-accelerated interactive
   sim**, on supported hardware. RAMMS must still load and run the URLab/Chaos sim
   on macOS/Linux (or any machine) where Newton is unavailable — availability is a
   runtime probe, never a load-time requirement. See §5.2.
3. **Breaking API changes are in-scope now** (RAMMS is pre-1.0) — Phase 3 proceeds
   without deprecation shims.
4. **`RammsMujocoPhysics` is confirmed safe to remove** (no work was ever done on
   it) — Phase 0 executes the removal. `RammsHumanPhysics` still pending a call.

---

## 5. Newton-behind-URLab — concrete design

### 5.1 Sibling plugin, not a fork
Rework the existing `RammsNewtonPhysics` submodule in place (rammp-org owns it) as a
plugin with a **plugin dependency on `UnrealRoboticsLab`**, exactly the pattern
`RammsMujocoSupport` already proves out. No fork is needed because every seam the
design requires is already public URLab API (verified in
`Source/URLab/Public/MuJoCo/Core/MjPhysicsEngine.h`):
- `SetCustomStepHandler` / `ClearCustomStepHandler` — replaces `mj_step` (the replay
  system uses the same hook);
- `RegisterPreStepCallback` / `RegisterPostStepCallback`;
- `GetModel()` / `GetData()` / `GetSpec()` raw accessors + public `CallbackMutex`;
- `ActiveAssetPaths` (every VFS mesh/texture from the last compile);
- URLab exposes `<mujoco/mujoco.h>` and links MuJoCo publicly, so the sibling can
  call `mj_saveXMLString` / `mj_forward` itself.

Keep tracking upstream URLab as today. If a seam gap appears, stage it on a
rammp-org fork **branch carrying only that commit** and PR it upstream (Apache-2.0);
known candidates: an `OnModelCompiled` multicast delegate (short-term workaround:
detect `GetModel()` pointer change per tick), and step-handler ownership arbitration
between replay and Newton (short-term: document them as mutually exclusive).

Modules:
- `RammsNewtonPhysics` (Runtime): worker transport + protocol, availability probe,
  `UNewtonSolverBackendComponent` that binds to the manager's `UMjPhysicsEngine`.
- `RammsNewtonPhysicsEditor` (Editor): toolbar pill, settings UX, validation, export
  menu actions.
The current scene-scraping/controller-reflection/JSON-IPC code is retired; the
description types survive only where useful for the Phase 4 Chaos importer.

### 5.2 Availability gating (macOS/Linux/no-GPU must keep working)
The UE plugin has **zero link-time dependency on Newton** — Newton stays
out-of-process Python. The only native dep is a transport lib (libzmq, already built
cross-platform in URLab's `third_party/install`). So the plugin compiles and loads
on every platform; capability is discovered at runtime:
- `Settings → RAMMS Newton`: Python path (auto-locate a pinned venv under
  `Plugins/RammsNewtonPhysics/Scripts/`, uv/lock-file managed, with an
  INSTALLED-stamp drift check patterned on URLab's third-party gate).
- Probe = spawn worker → handshake returns `{newton version, CUDA available,
  solvers, MJCF feature coverage}`. Probe failure ⇒ backend reports Unavailable
  with the reason; nothing else changes.
- Backend selection: `EPhysicsSolverBackend { MuJoCo (default), Newton }` as a
  project-settings default + per-manager override + `-PhysicsBackend=` CLI flag.
  Selecting Newton when unavailable falls back to MuJoCo with an on-screen warning.
  Content never references Newton classes, so maps load cleanly everywhere.

### 5.3 Interactive mode — Newton steps, MuJoCo renders/senses
Per iteration of URLab's existing physics thread, everything runs as stock except
the step itself:
1. URLab as normal: pre-step callbacks → `ApplyControls` writes `d->ctrl` (UI, ZMQ,
   and `UMjArticulationController`s all keep working) → `DrainCommands` applies
   mocap/wrenches.
2. **Our `CustomStepHandler`** instead of `mj_step`: send `{frame k: ctrl[nu],
   mocap_pos/quat, xfrc_applied}` to the worker; worker steps Newton
   (`SolverMuJoCo`, N substeps as configured); reply `{qpos, qvel, act}` is written
   into `mjData`, then `mj_forward(m, d)` recomputes sites/sensors/contacts so all
   derived state is consistent.
3. Post-step callbacks + `PushRenderState` — untouched. Every URLab consumer
   (bodies, ~45 sensor types, publishers, cameras, debug viz, dashboards) works
   unchanged.

Model load: when the model (re)compiles, serialize the **compiled** model via
`mj_saveXMLString` + `ActiveAssetPaths` → `load_model` RPC → worker
`ModelBuilder.add_mjcf`. The worker's handshake capability diff (unsupported MJCF
features, actuator coverage) surfaces in the editor pill.

Transport & budget: SHM ring or ZMQ REQ/REP on localhost; round trip is well under a
2 ms MuJoCo timestep. Synchronous per-step on the physics thread first (the game
thread is never involved); a pipelined one-step-in-flight mode is a later option.

Robustness property worth designing around: **worker death mid-session degrades
gracefully** — `ClearCustomStepHandler()` and URLab resumes stepping locally with
the same `mjModel/mjData`, mid-simulation, with a warning.

Known accepted approximations: contact forces shown by URLab's debug visualizer are
MuJoCo's re-derived ones (from `mj_forward` at Newton's qpos), not Newton's own;
Direct/Puppet RPC step modes are MuJoCo-only initially (Newton backend supports
Live mode first).

### 5.4 GPU-parallel fleets
- The `load_model` artifact (compiled MJCF + assets) doubles as the **scene export
  contract** for headless training — add an editor menu action + RPC op that writes
  it to disk for newton/mujoco/MJX scripts.
- Fleet *viewing* needs almost no new UE code: URLab's **Puppet mode** already
  accepts pushed qpos. Ship `Scripts/ramms_newton_fleet_mirror.py` that runs (or
  attaches to) a Newton multi-env sim and pushes a selected env's qpos to the URLab
  bridge at viz rate; add an editor dropdown to pick the env index.
- Multi-env instancing inside UE (N articulation clones, batched qpos apply) is
  flagged as future work, not in scope.

### 5.5 Milestones for this workstream (replaces the Phase 1/2 sketch in §3)
- **A (~1 wk)**: worker skeleton (`add_mjcf` + `SolverMuJoCo` + step loop), ZMQ/SHM
  transport, protocol, pytest suite; availability probe + settings UI stub.
  - **Status 2026-08-04: worker/protocol/probe/tests delivered**
    (`Scripts/newton_worker/`, see its README). Hard-won findings baked into
    the design: (1) the availability probe MUST include an out-of-process
    canary — imports succeeding does not prove the native toolchain works
    (warp's compiler can hard-crash or silently miscompile; observed on the
    dev machine); (2) liveness must be verified after every model load (a
    miscompiled engine yields a frozen sim); (3) `SolverMuJoCo` re-exports
    the model with renamed elements, so the worker maps state back into the
    ORIGINAL MJCF's layout/names — the UE contract stays clean. Correct
    end-to-end behavior was verified against a plain-MuJoCo baseline when
    the toolchain cooperated; the dev machine currently has an unstable
    warp toolchain (upstream bug report + Linux cross-check pending), which
    the canary/liveness machinery detects and reports rather than crashing.
  - **Status 2026-08-05: Milestone A COMPLETE.** UE side delivered — plugin
    reworked in place onto a `UnrealRoboticsLab` plugin dependency (old
    scene-scraping/JSON-stdio code and the ThirdParty link module deleted;
    stale test content `Map_NewtonTest`/`BP_Newton*`/`BP_Kinova_Gen3_Newton`
    now references missing classes and should be removed or rebuilt).
    New: `FRammsNewtonWorkerClient` (probe subprocess + `serve` spawn with
    READY handshake + ZMQ REQ/REP JSON RPC, timeout/poisoned-socket/dead-
    worker recovery), `URammsNewtonPhysicsSettings` (python path, solver +
    CPU fallback, timeouts, liveness toggle), `URammsNewtonPhysicsSubsystem`
    (engine subsystem, cached sync/async probe + BP delegate),
    `RammsNewtonPhysicsTypes.h` (capabilities/model-info/step-result).
    Compiles clean (UBT, RammsEditor Win64 Development).
- **B (1–2 wk)**: `CustomStepHandler` integration end-to-end on a Menagerie arm;
  qpos-trace parity test (MuJoCo vs Newton, same ctrl trajectory).
  - **Status 2026-08-05: implemented, not yet validated end-to-end.**
    `URammsNewtonSolverComponent` — binds `AAMjManager::GetManager()->
    PhysicsEngine`, detects (re)compiles by `GetModel()` pointer identity
    (no compile delegate exists upstream), serializes the compiled model
    (growing-buffer `mj_saveXMLString` on `m_spec` + `file="…"` basename
    flatten + `ActiveAssetPaths` blobs — mirrors URLab's bridge handshake
    serializer), async worker bind (Start → Hello capability check with
    optional CPU-solver fallback → load_model → nq/nv/nu layout guard →
    optional liveness steps + reset), then `SetCustomStepHandler`: forward
    `d->ctrl`/mocap → worker step → write back qpos/qvel/act → `d->time +=
    timestep` → `mj_forward`. Failure paths: per-step fallback to local
    `mj_step` + game-thread deactivate with on-screen warning; stale-model
    guard in the handler; mocap forwarding self-disables if the solver
    re-export changed nmocap; requires Live step mode (single handler slot
    shared with replay/Direct/Puppet). Validation (Menagerie arm, qpos
    parity trace) blocked on a machine with a working warp toolchain — the
    dev box's i9-14900K instability prevents kernel compilation.
- **C (~1 wk)**: lifecycle — recompile, reset/restore, PIE start/stop, worker-crash
  fallback to local `mj_step`; step-handler arbitration vs replay.
  - **Status 2026-08-05: core lifecycle implemented** (compiles clean;
    runtime validation pending a warp-capable machine, same as B). The step
    handler tracks `d->time` between its own writebacks and detects external
    discontinuities inside the same physics iteration URLab applies them:
    time≈0 ⇒ sim reset — the handler drops to local `mj_step` while Tick
    mirrors the reset in the worker asynchronously (v1 reset = full rebuild)
    and re-arms at the engine's current time (bounded, tiny divergence from
    the locally-stepped frames in between, reconciled by the first
    writeback); any other jump ⇒ snapshot restore — cleanly deactivates
    with a "needs worker set_state" status. Mid-run activation: worker
    starts from the initial model state, so `InstallHandler` reads engine
    time under `CallbackMutex` and either auto-resets the sim
    (`bResetSimOnActivate`, default on) or refuses activation. Already
    covered previously: recompile rebind (model pointer identity),
    worker-crash per-step fallback + game-thread deactivation, PIE
    start/stop (EndPlay uninstalls before teardown; async client retirement
    so a long load can't block EndPlay). Still open in C: proper worker
    `set_state` (unlocks restore + divergence-free reset/attach), and
    explicit arbitration with replay/Direct/Puppet (currently: Live-mode
    gate + mutual-exclusion documentation; displacement of our handler by
    replay is not yet detected).
- **D (1–2 wk)**: editor tooling — toolbar pill (backend / worker alive / solver /
  achieved Hz), backend selector, ValidateRobot (dry-run worker load), export menu.
  - **Status 2026-08-05: first cut implemented** — new `RammsNewtonPhysicsEditor`
    module adds Tools ▸ RAMMS Newton ▸ {Probe Newton Availability (async
    probe → toast with newton/python/CUDA/solvers), Validate Scene Under
    Newton (dry-run worker load of the live compiled model → layout +
    warnings toast; PIE-gated), Export Compiled Scene (MJCF + assets →
    `Saved/NewtonExport/<timestamp>/`, the §5.4 fleet/training artifact;
    PIE-gated)}. `SerializeCompiledModel` promoted to public static on
    `URammsNewtonSolverComponent` for reuse. Remaining in D: the toolbar
    status pill (live worker state / achieved Hz) and a per-manager backend
    selector UX.
- **D (1–2 wk)**: editor tooling — toolbar pill (backend / worker alive / solver /
  achieved Hz), backend selector, ValidateRobot (dry-run worker load), export menu.
- **E (~1 wk)**: fleet mirror script + env-picker; docs; RAMMS robots (gen3_2f85)
  running under Newton with the grasp test.

### 6.5 Full-stack validation pass (2026-08-14, overnight)

MuJoCo/Newton jitter (user report) fixed AT THE MODEL: headless bench showed
rest qvel-RMS 0.099 dominated by (a) near-frictionless caster/drive wheels
rocking and (b) the closure linkage micro-oscillating. compose_mebot_scene.py
now sets wheel damping/frictionloss (casters 5/0.2, drive 2/0.1) and
armature=0.005 on linkage hinges -> qvel-RMS 0.0018 (47x), all joint
amplitudes <5e-5 rad. Newton worker: suite 31/31, parity vs plain MuJoCo on
the retuned base scene PASSED (max qpos divergence ~7e-5). Round-trip
compiles with all 14 actuators.

Chaos arm free-fall fixed: URLab re-export flattens ALL actuators to
<general> (class detection useless) and the gen3 arm actuators carry EMPTY
gainprm/biasprm — their values live on actuator templates nested under
<default class> nodes (parent-chain). Generator now resolves the default
chain and maps position servos (biasprm[1] = -kp) to orientation-hold PD
drives (x1e4 unit conversion). Result: pos_drives 11/13, robot upright
(upz 1.00), arm holds pose (wrist steady at 150 cm), and SetJointCommand
wheel drive produces straight locomotion at the commanded speed
(3 rad/s -> ~55 cm/s over 6.6 m).

Open: verify the armature attr survives URLab BP import for the IN-EDITOR
MuJoCo path (worker path verified via XML directly); Map_Demo BSP contact
still less forgiving than static-mesh floors; L/R mount asymmetry (6.2)
still awaiting the Blender fix.

### 6.6 In-editor armature fixup (2026-08-14)

The URLab importer DROPS the MJCF `armature` and `frictionloss` joint attrs
(templates land with armature=0, frictionloss=0, override flags unset), so
the 6.5 jitter retuning reached the worker (XML path) but not the in-editor
BP. Applied a template fixup on mebot_gen3: armature=0.005 + override on 26
linkage hinges, damping/frictionloss + overrides on the 6 wheel joints; BP
compiled and saved. Live PIE (Newton, unpaused): previously-jittery swing
arms now hold within ~0.0006 rad between samples. Upstream note for URLab:
import `armature`/`frictionloss` like the other codegen attrs — the fixup
script is checked in at Scripts/fixup_mebot_import.py — run it after every
re-import until then.

### 6.7 Feedback batch (2026-08-14, user's Chaos/Newton list)

CHAOS fixes, all validated on the flat map (settle upz 1.00 / arm held /
drove 6 m straight at commanded speed):
- (0) sloppy multi-axis linkages + (4b) gripper limit fall-through: joint
  templates are CLASS-based like the actuators (gripper range/axis/ref/
  stiffness live under <default> nodes) — generator now resolves the
  default chain for joints too. Gripper hinges went from ACM_Free to
  correct 45.8-90 deg windows.
- Activating those limits exposed a mass-ratio explosion: 12-22 g finger
  links coupled to the 8 kg arm through limits+closures back-flipped the
  robot at spawn (bisect: removing the 16 gripper constraints cured it).
  Fixed with constraint projection (bEnableProjection on all rig
  constraints) + a 0.15 kg Chaos-side mass floor.
- Limit windows are SIGN-SAFE now (symmetric around ref covering the full
  range) — AngularRotationOffset sign conventions kicked at spawn;
  proper asymmetric windows are a phase-2 calibration item.
- (2)/(3)+(5) wheels sliding, no actuation, sleep: sleeping bodies ignore
  drive targets and SleepFamily Custom/0 does NOT prevent sleep —
  bNeverSleep now runs a 0.5 s keep-awake tick, and SetJointCommand wakes
  the rig. Runtime drive-PARAM changes never reach the live solver (only
  target updates do), so wheels keep the full-strength always-on velocity
  drive: braked at rest like a real powered wheelchair, casters roll free.
  Manual actuation: console `Ramms.Joint <ActorLabel> <joint> <value>`.
NEWTON:
- (0) rest bounce: wheel anti-rock moved from damping to armature
  (damping=5 on casters sustained ~1 rad/s and made them SKID down ramps).
- (2) linear motors: rod servos kp 60000 / forcerange +-20000 N —
  headless: elevator lifts the 200 kg robot 200 mm.
- (3) casters now roll on ramps (60-70% of travel vs 8%).
- (1) ~20 s reset + 1/10 speed DIAGNOSED: worker GPU-kernel compile takes
  ~19 s, then the solver resets the sim to take over from t=0 (by design,
  log: "Sim advanced during worker load"); the 1/10 speed is the 500 Hz
  model pumped one step per ZMQ round-trip at ~60 fps. Fix = batch N steps
  per tick through the bridge (design item; dt=0.004 was tested headless
  and rejected - 100x jitter).

### 6.8 Design sketch: fixing the Newton bridge 1/10-speed (needs sign-off)

The bridge is strictly synchronous: one 0.002 s model step per ZMQ REQ/REP
round-trip, ~60 round-trips/s from the editor tick -> 0.12x realtime.
Options, in rough preference order:

1. **One-step pipelining** — submit step N without blocking, write back
   step N-1's result (already arrived). Hides the RTT; throughput becomes
   worker-compute-bound (GPU steps the mebot scene far faster than 500 Hz).
   Cost: ZMQ REQ/REP forbids pipelining, so the worker transport moves to
   DEALER/ROUTER (protocol change: tag replies with step ids); writeback is
   one substep stale (2 ms — physically negligible). Touches
   RammsNewtonWorkerClient + newton_worker/transport.py + server.py.
2. **Predictive batching** — first handler call per frame executes
   Step(N_pred) (N_pred = last frame's substep count) and serves the rest
   from cache. No protocol change, but a wrong prediction leaves the worker
   ahead of mjData and trips the resync path — fragile with URLab's
   accumulator.
3. **Accept in-editor slowdown** — document that Newton-in-editor runs
   ~0.1x and rely on headless/worker-native runs for realtime; cheapest,
   no risk.

Recommend (1). Also worth surfacing the worker GPU-compile takeover in the
UI (the planned toolbar status pill) so the ~20 s "reset" reads as
"Newton warming up", not a malfunction.

### 6.9 Unified joint control panel (2026-08-14)

`Ramms.Panel [ActorLabel]` (console) opens a Slate window with one slider
per actuated joint (from the switch component's DriveJoints), routed
through SetJointCommand — the SAME panel drives MuJoCo, Newton, and Chaos
instances. Ranges come from the recorded MJCF ctrlrange (new
DriveCtrlMin/Max arrays on the switch); velocity motors (wheels) get a
+-6 rad/s span. `Ramms.Joint <label> <joint> <value>` remains for
scripted/console use. SetJointCommand's MuJoCo path now writes BOTH
control slots (InternalValue + NetworkValue) so commands work regardless
of the articulation's ControlSource (ZMQ maps silently ate SetControl
before — root cause of "cannot actuate"). Teleop bindings (option C part
2) are next.

### 6.10 Teleop layer (2026-08-14)

The Ramms.Panel window now doubles as a teleop surface (click the panel to
focus it): W/S drive, A/D turn, Space stop (wheels +-3 rad/s), Q/E
elevator rods (both), R/F front caster rod, T/G rear caster rod (rod
targets ramp at 4 cm/s, clamped to +-8 cm). Same SetJointCommand routing,
so identical on all three backends. KNOWN GAP: wheel semantics still
diverge — Chaos interprets wheel commands as rad/s, MuJoCo motor
actuators as torque-fraction clamped to ctrlrange (a 3.0 teleop command
saturates to full torque). Proper unification = interpret wheel commands
as rad/s everywhere and translate to torque via a velocity loop on the
MuJoCo side (phase-2, ties into the IRammsRobotBackend seam).

### 6.11 Chaos panel feedback round 2 (2026-08-14 evening)

- Caster runaway on rod commands: caused by 6.10's wheel material being
  applied to ALL "wheel" bodies — omniwheels need the OPPOSITE (near-zero
  friction). Split: PM_RammsWheel (1.2, Max) on drive wheels only,
  PM_RammsCaster (0.12, Min) on caster wheels. Rod commands no longer
  propel the robot.
- Arm collision vanished: 6.10's piece-asset collision strip hit SHARED
  assets (arm links reuse one mesh as both body carrier and piece).
  Strip now excludes any mesh in the body-carrier set. 51/57 arm-ish
  meshes carry collision again (6 legit visual pieces).
- Gripper fingers motorized: the fingers actuator targets TENDON
  arm_2f85_split; the generator now maps tendon actuators onto their
  Joint wraps (orientation-hold drives on both driver joints, one shared
  drive name, wrap-coef sign via new DriveScale). Panel/console command
  'arm_2f85_split' closes both fingers. Sign/limit calibration pending.
- Command slew-limiting on position drives (5 cm/s / ~57 deg/s): slider
  steps are no longer force impulses.
- ELEVATOR-UNDER-LOAD DEBUGGING (the big one): instrumented lift runs
  showed the chain articulating smoothly (swing arms to -23 deg, low
  forces) and the robot then LAUNCHING (13 m/s) / falling through the
  floor. Root cause: the exporter's +-30 deg linkage ranges are DEFAULTS,
  not real travel — the mechanism sweeps past them and Chaos HARD limits
  vs the stiff closures detonate (MuJoCo's limits are soft, so it never
  showed there). Mebot linkage hinges now run twist-FREE under Chaos
  (closures + geometry bound the motion); arm/gripper keep windows.
  Result: elevator commands are fully stable (no explosion at any tested
  gain). Remaining: loaded lift STALLS (chassis does not rise; unloaded
  articulation works) — task #18, likely needs the real linkage travel /
  lever math or higher-fidelity rod modeling. Also convex wheel cylinders
  went contact-dead under load (cook failure?) — wheels are capsules +
  high-friction material instead.

### 6.12 Round-3 verification (2026-08-14 late)

Controlled-run answers to the round-3 reports:
- "Joints with too many DOF": swing slop measured 0.6 deg max across all
  63 constraints — no off-axis freedom in the current BP. What reads as
  extra DOF is (a) the deliberately twist-FREE mebot linkage hinges
  (6.11) swinging on their REAL axis, and/or (b) a stale placed instance
  (check the output log for the STALE ROBOT INSTANCE error).
- "Gripper has no collision": all gripper body meshes carry collision
  shapes on disk (missing=0). Finger-vs-gripper pass-through is the
  robot-wide self-collision-off scheme (matches the MJCF); fingers DO
  collide with world objects / graspable props.
- "Fingers flop open": real — the closure-loop equilibrium overpowered
  the tendon drives. Finger drive floor raised to 1e6 (100 N*m/rad):
  fingers now hold spawn pose (+-3 deg) and track grip commands
  symmetrically (mirror-aware DriveScale: L/R body frames flip the twist
  sign; wrap coefs alone don't encode it).
- "Robot rolls with no input": parked pose rests on the omniwheels whose
  contact friction is intentionally ~0.12 (lateral slip for turning), so
  the suspension's static push glides the robot at ~0.5 cm/s even with
  caster wheel hinge damping (1e4). Inherent isotropic-friction
  trade-off of the omniwheel approximation — tune PM_RammsCaster's
  friction live in the editor, or it goes away for real when the rollers
  are simulated (long-term goal). Drive wheels not spinning while parked
  is correct: they are raised (parked pose) and velocity-braked.

### 6.13 Ramms.Validate + Map_Demo verification (2026-08-14)

New console command `Ramms.Validate [ActorLabel]`: prints per-robot rig
health (BP class path, rig constraints recorded vs resolved with a STALE
INSTANCE verdict, drive count incl. gripper tendon, collision counts) to
log + screen. Healthy reference: mebot_gen3_C, 77/77, 15 drives (tendon
yes), 148 meshes / 20 shapeless (visual pieces). Re-validated on
Map_Demo's real floor with a fresh spawn: fingers hold, gripper collision
present, 0.5 deg max slop, front-caster rod command stable. Divergent
user reports should start from this command's output.

### 6.14 The real round-3/4 root cause + arm axis fix (2026-08-14)

The persistent "nothing works" divergence: the mebot_gen3 BLUEPRINT WAS
DELETED ON DISK (git: D mebot_gen3.uasset) — consistent with a manual
delete+reimport attempt in the editor, where the import silently FAILS
because the Git source-control plugin cannot 'CheckOut' (same trap that
ate scripted imports). All testing after that point ran against actors
with a broken class. IMPORTANT WORKFLOW NOTE: to reimport the robot,
either use the scripted pipeline (editor closed -> SC provider=None ->
boot to /Engine/Maps/Entry -> import with pinned MujocoImportFactory ->
Generate Chaos Rig -> Scripts/fixup_mebot_import.py) or temporarily set
Editor Preferences > Source Control provider to None first.

Two real fixes landed while diagnosing:
- ARM JOINT AXES: an earlier parent-frame Unrotate transform silently
  corrupted the constraint axis of every rotated body (all arm links) —
  holds looked fine, commanded motion rotated wrong. MJCF axes are in the
  joint's OWNING link frame; used directly now. Validated: shoulder
  command produces a clean X-Z pitch arc. Per-joint sign calibration
  remains (some joints track the negative of the command).
- Tendon (finger) panel range now comes from the wrapped JOINT's travel
  in radians — the actuator ctrlrange is tendon units (0..255 on the
  2f85), which made panel slider drags command hundreds of radians into
  the slew limiter, i.e. "the finger motors do nothing".

BP restored (import + regen + fixup + save); mebot_gen3_scene.uasset
restored from git.

### 6.15 Crash recovery + clevis pins + MJ retune (2026-08-14 night)

- EDITOR STARTUP CRASH (AssetRegistry array out of bounds): caused by
  file-level .uasset deletion while CachedAssetRegistry_0.bin still
  indexed the files. Fix: delete Intermediate/CachedAssetRegistry*.bin
  (pure cache; slow next boot). RULE: asset deletions go through the
  editor, or purge the registry cache after.
- Import gotcha #3: AssetTools refuses imports while the editor is IN A
  PLAY MODE (URLab's bridge auto-start can enter play on boot) — and
  refuses SILENTLY from scripts. End play before importing.
- MJ/Newton (user: springy oscillating elevators, frozen caster
  linkages): headless bench confirmed the 2e4 stand-in springs freeze the
  linkage against its own actuators, and the load-path joints
  (motor_swing_arm damping 5!) ring at 12 rad/s after lifts. Baked:
  load-path damping x10 (trunnions 500, swing arms 50), front swing-arm
  stand-in 5000->1000, pivot preload 1000->200. Bench: ringing RMS
  2.96 -> 0.037, articulation x2.5.
- Chaos closures are now CLEVIS PINS (user insight: ball connects left a
  free spin DOF about the anchor axis): twist free about the link's hinge
  axis, swings limited 5 deg.
- Battery on the new build: grip mirrored -24/+19 deg, rods stable
  (still ~85 cm lateral push through low-friction casters), pins hold
  (1.5 deg). REGRESSION: locomotion sluggish (~4 cm/s vs 45) — softened
  stand-ins / pin swing-limits absorb drive torque; next tuning pass.

### 6.16 Strict per-motor benches + the anchor-units discovery (2026-08-14)

Adopted the user's strict-pass/fail methodology: Scripts/benches/ now has
per-motor isolated tests (articulation of the CORRECT downstream joint,
base translation <= 10 cm, yaw <= 10 deg, post-move ring <= 0.15), chain
tracing, closure bisect and kinematic mobility tools. Run with the Newton
venv python.

MUJOCO/NEWTON: 4/4 PASS (front 0.36 rad, rear 0.42, elevators 0.33/0.35;
<= 1 cm slide; no ring; rest RMS 0.0010). Fix chain: (1) test mapping —
rear articulation is the SUSPENSION ARM (user topology), not swing_arm;
(2) the rear freeze was motor_dampener_pivot name-matching "dampener" and
receiving the 2e4 suspension spring (eq-force probe: 5.1 kN wall);
(3) loaded direction matters (front passes in +stroke); (4) heavy load-
path damping is per-chain: elevator trunnions 500, caster trunnions 50.
Lift height is now only ~10 mm (soft preload stand-ins yield) — real
gas-spring specs from Blender remain the fidelity fix.

CHAOS — the big discovery and the honest state: closure pin ANCHORS are
codegen attribute arrays = native MuJoCo METRES, RIGHT-handed. The rig
read them as cm: every pin collapsed to its body origin -> ZERO lever arm
-> loops cannot transmit torque -> rod force becomes rigid-body shoving
(the user's "slides in circles"), while proximity audits still passed.
With x100 + Y-negation applied the mechanisms TRANSMIT (rear suspension
arm articulated 28 deg, first time ever under Chaos) but the loops sit
pre-stressed at spawn and drift unstably — residual inconsistency,
suspected in the runtime pin frame re-derivation (viz-chain conversion)
or a per-pin sign case. REVERTED to origin-anchors for stability
(TODO(anchor-units) in the generator marks the exact spot): current BP is
fully stable — upright settle, 0.7 deg slop, fingers hold + grip, wheels
drive — but linkage rods stall (zero lever arm), matching prior behavior.
Finishing anchor-units is THE remaining structural Chaos item; with it
done, restore the linkage windows (same commit reverts both).

### 6.17 Anchor units CORRECTED + soft-pin closure design (2026-08-14)

Supersedes the 6.16 anchor diagnosis. Template probe (BP value 7.287 vs
XML 0.07287 m) proves MjEquality.anchor carries the MjUnit="cm" codegen
annotation: the importer ALREADY converts equality anchors to cm — only
the Y handedness flip is missing. Geom sizes / slide ranges have no such
annotation and stay native metres, which is why the x100 rule is right
for them and wrong for anchors. Last session's "x100 transmits torque"
result was running 100x lever arms (pins up to 20 m out) — spectacular
articulation, spectacular instability, all artifact.

New closure design (generator): anchor = (x, -y, z) of the template cm
values; pin twist axis Y-negated; NO projection on pins; linear
LCM_Limited 0.2 cm with SOFT limit (stiffness 5e4, damping 2e3)
emulating MuJoCo solref compliance so mm-scale closure error lives in a
spring, not a solver fight; swing windows 30 deg SOFT (5e3/5e2).
Runtime (switch component): MJCF linkage joint damping never reached
Chaos — linkage/rod/pivot/dampener/swing_arm/suspension bodies (not
wheels, not arm_) now get AngularDamping 10 / LinearDamping 1 at
ApplyChaos to stop the free-linkage windmilling the user reported.

MuJoCo side same session: rear strut restored to authored 20000 (the
"too soft" 300 made the strut absorb the rod stroke — user report);
root cause of the original freeze was ROD SERVO FORCE STARVATION
(kp=6e4 through ~1.1 cm anchor levers), not the strut. Rod servos now
kp=6e5 with dampratio=1 critical kv (fixed kv=6e4 was 100x OVER
critical for the reflected inertia and rocked the whole robot at rest).
compose_mebot_gen3 bakes explicit negative kv into the XML because
MjSpec serializes dampratio as raw positive biasprm[2]=1 (MuJoCo
reinterprets it correctly; URLab's raw-float parser would not).
Strict suite (Scripts/benches/combined_suite.py): 4/4 motors PASS incl.
new rear swing-arm criterion (0.25 rad), rest 0.003, drop + whack PASS.
Elevator lift now ~2-3 cm (was ~1 cm); real gas-spring specs still the
fidelity item.

### 6.18 Chaos closure campaign — landed state (2026-08-14, session 2)

Fix chain, each step verified by the per-motor fresh-PIE bench
(tmp cycle3: one PIE session per stroke — a tipped robot contaminates
every later test; that masking cost several earlier misdiagnoses):

1. Anchors: importer-cm + Y-negation (6.17); placement audit 0 outliers.
2. Slide RANGES are native metres (unannotated): read raw, the rod
   travel limit was +-0.08 CM -> rod welded, 20 kN drive fought its own
   limit, reaction flipped the chassis. x100.
3. Rod command SIGN: UE linear position target moves the child along
   -X of the constraint frame; every Chaos rod test had been running
   the mirror-opposite (loaded) stroke. DriveScale = -1.
4. Pin free play: soft LCM_Limited(0.2) = 2 mm slack per pin; the
   3-pin front loop's fold mode lived entirely inside the slack
   (linkage counter-rotated 20 deg, pins carried single-digit N).
   Pins are now HARD-locked linear; placement verified to 0.01 cm vs
   the MuJoCo model (hinges AND pins), so no spawn stress.
5. Solver convergence: front pins still stretched 0.8-1.3 cm under
   load (both-body anchor projection probe). Per-body iterations 32/4
   + 3 kg mass floor on linkage pieces + body damping 10/1 = the
   stable calibration. Global iteration cvars (30-50) and pin
   projection both made loaded strokes MORE violent (stored loop force
   releases dynamically); joint-level velocity dampers destabilized
   rear strokes. All three reverted with code comments.
6. Rod targets slewed at 3 cm/s (safe at kp 6e5; the old starvation
   was a kp 6e4 artifact) + force cap 8 kN (20 kN vaults the chassis).

Bench state (fresh PIE per stroke): front+ PASS (mechanism moves,
upright), rear- PASS (+23 deg suspension), elev+/- PASS (+-26 deg both
arms, ZERO robot propulsion — solver iterations also fixed the
13 m elevator-slide), wheels PASS. front-/rear+ (chassis-lift
directions) articulate first (rear +28 deg) then TIP the robot
(upz -0.5..-0.7, settles, no fly-off) — remaining calibration item:
MuJoCo reaches force equilibrium quasistatically where Chaos
overshoots once the wheels unload. Candidate next steps: direction-
aware force cap, or accept + require the elevator-first posture the
real robot uses. Front swing arm still under-driven vs MuJoCo
(aux-branch pin leak at the solver level) — front casters lift less
than MuJoCo's 15 deg.

### 6.19 Wheels, rear strut, gripper pose (2026-08-15, session 3)

WHEELS: "duplicate colliders" = URLab's per-geom VisualizerMesh
components each carry a QUERY_ONLY collision element (visible in the
collision view next to our capsule); under Chaos ApplyChaos's non-rig
sweep disables them, so cosmetic only. Slip/free-rolling fixed: wheel
velocity-hold 2e5 -> 2e6 (200 N*m per rad/s — a powered chair brakes
hard at zero command) + AngularDamping 0.5 on wheel bodies. Rest creep
now ~1.7 cm/10 s.

REAR STRUT: still the open item. MuJoCo mode shape: pivot follows aux
at ratio 0.6, strut swings 3-4 deg + compresses 1.4-2.5 cm, swing arm
moves 7-14 deg. Chaos: pivot ratio 0.067 (aux -16.6 -> pivot -1.0),
strut and swing arm dead — the eq11 pin leaks force at the solver level
even after the pivot stand-in spring was cut to 20/50 in the MJCF
(MuJoCo suite still 4/4 after that change; a bell crank needs no
spring). Suspension arm over-rotates (+23 vs MuJoCo +8.6) because the
strut path doesn't resist. Same solver-leak class as the front aux
branch.

GRIPPER (the big win): rest pose now matches MuJoCo (spring_links -1.2
deg, followers +5..9, drivers ~0 — was followers +51 at the window
edge, couplers -15, springs -20). Three stacked causes:
1. The 0.15 kg mass floor breaks spring equilibria tuned for 12-22 g
   links — spring drives now scale by the per-body inflation
   (SpringMassScale) PLUS a 5e4 floor for arm_ bodies (the spring_link
   spring restrains the WHOLE floored chain, ~8x the real mass).
2. Name-resolution hardening: exact-FName match BEFORE suffix-tolerant
   everywhere (gripper viz components share asset-derived names
   "Viz_arm_2f85_follower1..3" across left/right and cross-matched).
3. The "_right_" tendon DriveScale mirror (calibrated in the broken-pin
   era) drove the right four-bar into slack — removed; MuJoCo closes
   both drivers with the same sign, Chaos now does too (close is
   symmetric: both drivers -27, both followers move together).
Remaining finger item: a close over-curls (follower to its -50 window
edge vs MuJoCo -26) — the 100 N*m/rad driver partly tears the leaky
follower-coupler pin instead of dragging the loop; softening drives
lets the loop WALK into contortion at rest (tried 2e5/2e4, reverted).
Designed next step: derive pin frames from the MjBody component
transforms at ApplyChaos init instead of the viz SCS chain (arm viz
meshes are offset from body nodes), then soften drives.

INFRA: the boot crash (AssetRegistry "index 504496128 into 73568") is
RECURRING — the registry cache is corrupted at editor shutdown after
content churn (same index every time). Purging
Intermediate/CachedAssetRegistry*.bin + Saved/AssetRegistryCache fixes
it; the purge is now a standard step in every editor cycle script.

### 6.20 Rear-chain fold: knob space exhausted (2026-08-15, session 3b)

The rear caster rod stroke still topples the robot. Every mitigation
was tried and measured this session:
- Rod force caps 20/8/3/1 kN: at ANY force able to articulate, the
  unresisted rear lifts and the robot topples (1 kN > the rear's ~500 N
  weight share). Lower caps = nothing moves.
- Suspension-arm 15-deg soft window as a strut stand-in: DETONATED
  (limits-vs-loops energy pump; robot launched at v=4300).
- Soft-from-zero pins: Chaos ignores soft params on a radius-0 limited
  linear constraint (1e6 vs 1e9 identical to the decimal) — pins have
  effectively been HARD throughout.
- Virtual strut (direct pivot<->swing-arm axial spring, 2e4/cm,
  bypassing the 3-body chain): NO effect — the leak is UPSTREAM: the
  suspension+aux pair counter-rotate as a near-perfect fold (ratio
  0.885, tip ~stationary), which satisfies a rigid eq11 pin WITHOUT
  moving the pivot. MuJoCo's fold ratio (0.88) leaves a residual that
  drives the pivot at ratio 0.6; Chaos's residual reaches the pivot
  40x weaker. With geometry verified exact to 0.01 cm, the discrepancy
  needs OFFLINE KINEMATIC ANALYSIS (solve the loop positions
  numerically from the verified geometry vs commanded rod extension;
  compare against mjData trajectories) — not more constraint knobs.
Gripper status: rest pose good, symmetric close (correct direction,
panel deduped); spring_link non-participation and follower over-curl
are the same fold phenomenon in the finger four-bar.
Current shipped state: fingers usable, elevators/wheels/drive good,
rear+front rod strokes articulate partially and can topple the robot
if driven hard — user-visible and documented.

### 6.15 Front-caster fly-apart: root cause chain and fix (2026-08-15)

Systematic bisect on the current build (all with the user's place-then-flip
flow, flat map):
- NOT the closure type (ball vs clevis: identical), NOT the swing-arm hold
  (flipped with hold 0 / 1e5 / 2e6 alike; with the hinge broken live it
  still didn't move), NOT self-collision (all RobotSelf/ignore).
- Chain force probe: rod 6 kN -> linkage crank 18 deg -> force decays
  ~40%/pin -> swing arm 0 deg. Chaos's iterative solver leaks force through
  the 4-bar; MuJoCo drives the same stroke to -0.24 rad and then SOFT-
  saturates (the mechanism's range is exhausted at ~-2 cm rod travel: any
  further command is a stall by design). Chaos stalled into a 6 kN hammer.
- Two contributing regressions found+fixed on the way: slide-limit x100
  (rods were free-sliding at +-800 cm; range IS cm on templates) and rod
  servo damping (kv from MJCF dampratio ~591 is MuJoCo's reflected-inertia
  critical value, meaningless vs Chaos kp 6e5 -> ratio 0.003; now k/10).
- FIX: virtual coupler (generic runtime mechanism, generator-emitted):
  follower twist = ratio x leader twist enforced by a strong orientation
  drive on the follower each tick, bypassing the leaky pins — the same idea
  as the rear virtual strut. Front: swing_arm = -0.667 x linkage (ratio
  from MuJoCo joint-space fit, sign flipped for constraint frame handedness).
  Result: full -0.06 retract stable (upz 1.00), swing arm follows to its
  saturation angle (-14 deg, same as MuJoCo's -13.7), front wheels lift
  1 cm, rod force 1.4 kN. Rear rod and elevator commands: stable/upright
  but under-transmitting (loads don't visibly move) — candidates for the
  same coupler treatment with MuJoCo-fitted ratios.
- Stand-in park holds must stay at FULL converted strength (settle fails
  at 0 and at 1/10: robot slides 10 m at spawn).

### 6.16 Rear caster fly-apart (2026-08-15)

Fine-step probe with the chain force tool: rear extend articulates
correctly (suspension arm -4/-6/-8/-10 deg at +0.01/.02/.03/.04, swing arm
following, wheels lifting, upright) with the arm hinge force rising
linearly (1.7 -> 8.4 kN) — the servo stalling the mechanism at its
saturation, exactly what MuJoCo also does at these strokes. The flip only
happens between +0.04 and +0.06: MuJoCo's own rod STALLS at ~2.2 cm (the
linkage physically cannot go further); Chaos slews the target all the way
to 6 cm and the stalled full-force servo's 13 kN reaction tips the robot.
Tried and rejected on the way: rear pivot coupler (moved the pivot, strut
path still leaked, 20 kN), rear end-coupler suspension->swing (slammed the
near-saturated swing arm into its stop, 24 kN), rear rod force cap (no
effect: the reaction is leverage-multiplied), suspension-arm 12 deg soft
limit (100 N*m/rad can't hold it). The bell-crank pivots are now damping-
only (holds there halved the pivot hinge force but weren't the trigger).
FIX: publish the mechanism-realizable travel as the drive range (caster
rods +-4 cm) and clamp SetJointCommand to it — panel sliders, teleop and
scripts can no longer command past what the linkage can do. Validated: all
three rods, both directions, deliberately over-range +-0.08 inputs, robot
upright throughout, rear suspension arm -10/+6 deg (MuJoCo-matched), front
swing arm +-12-14 deg (saturation), clean return to zero.
Note: one opaque editor access-violation crash during rapid end-play/
respawn cycling (not reproduced on relaunch) — treat as harness stress.

### 6.17 Elevator range check (2026-08-15)

MuJoCo realizes nearly the full +-8 cm elevator stroke (rod -7.9/+7.0), so
NO clamp there (unlike the caster rods). MuJoCo full retract lifts the
chassis only 3.7 -> 8.6 cm — the parked robot rests on its BELLY, so the
elevator has ~5 cm of lift available by design; Chaos matches in kind
(stable, upright, full range) with a smaller delta because its chassis
already rests ~3 cm higher (capsule contact vs MuJoCo's belly mesh). The
"elevator doesn't lift" observation is the parked-pose geometry, not the
sim: real lift needs the drive wheels lowered past the belly plane, i.e.
the dojo_ref parked pose or the linkage travel — a model question.

### 6.18 Rest bounce / creep + finger oscillation root causes (2026-08-16)

Measured with VELOCITY probes (position sampling had hidden it):
- Gripper fingers oscillating at rest (driver bodies 73 deg/s): the tendon
  drive at 1e6 on a 0.15 kg link is a ~137 Hz spring the 60 Hz solver
  aliases. dt-limited to 1e4 with heavy damping 5e3 -> spin 55 deg/s and
  falling; fingers park at +-25 deg (the known closure-loop sag). Panel:
  slider knobs are now bound to the shared value (Zero-all moves them),
  and one slider per drive name (tendon registers two entries).
- Base creep 3-10 cm/s at rest with NO input: BISECTED — the base-only BP
  bounces (v_z +-3, pitch 10-13 deg/s) but does NOT creep; the arm/gripper
  converts the bounce into lateral drift on the low-friction casters.
- The bounce is the MODEL: in the authored parked pose the front caster
  wheel centers sit 4.6 cm above the chassis floor plane with a 7.66 cm
  radius (rear: 7.2 cm vs 10.1 cm radius) — the wheels are authored ~3 cm
  INTO the ground. MuJoCo absorbs that in soft contact + strut springs
  (chassis settles LIFTED to 3.7 cm); Chaos's hard contacts see-saw on the
  front swing arm being ground into the floor (measured z=2.7 < chassis
  6.4). Strut-hinge stand-in holds (elevator_dampener/link, rear dampener)
  are now damping-only, correct in itself, but not the bounce driver.
  FIX BELONGS IN BLENDER: raise the casters in the parked dojo_ref pose
  (or lower the chassis) so wheel bottoms are AT the floor plane, then
  re-export. Everything downstream (rest bounce, creep, some of the
  rod-stroke stall margins) follows from that geometry.

Addendum (6.18 check): lifting the casters at runtime (rods +0.03) raises
the front swing arm off the floor (2.7 -> 7.1 cm) and cuts the linear
bounce (v 3 -> ~1 cm/s) but the chassis still PITCHES 26-36 deg/s on its
belly/rear-caster contact — the belly-resting parked pose is itself a
see-saw. Confirms the fix is the parked-pose geometry as a whole (wheels
carrying the robot with the belly clear), not a per-joint tweak.

### 6.19 Rigid struts + real fixes (2026-08-16)

User corrections taken: the parked pose IS correct (wheels below the
chassis floor); the sim was failing to HOLD it, and the arm was absent
from several of my validation runs (base-only BP) — those gripper claims
are void. 6.18's "parked pose is wrong" is RETRACTED: the visual-mesh
bounds probe (tread geometry) misled it; the collision capsules put all
six wheels on the floor with the belly ~4 cm clear, as authored.

Changes (all validated on the full mebot_gen3 WITH the arm, velocity
probes, place-then-flip flow):
- Dampeners modeled as FIXED struts (user decision): compose removes the
  dampener_rod slide joints (a 1e6 spring was dt-unstable in MuJoCo).
  MuJoCo now rests the chassis at 6.65 cm on its wheels (was 3.7 sagging)
  and the elevator lifts +45 mm (was ~5) — confirms the soft struts were
  what let the base sag. Chaos rear virtual strut obsolete (disabled).
- Physical materials WERE NEVER SAVED: LoadObject can't see an in-memory
  package next session, the materials were silently recreated each run and
  every wheel ran on default friction (0.7) for days. Now saved on creation
  (+ synced when values change). Casters 0.35/Average (0.12/Min skated:
  wheels not turning / turning against travel), drive wheels 1.2/Max,
  chassis belly 1.0/Max.
- Finger tendon drive dt-limited (1e6 -> 1e4, damping 5e3): the 137 Hz
  spring aliased into wild rest oscillation. Panel: bound sliders (Zero-all
  moves knobs), one slider per drive name.
- Elevator: coupler rod SLIDE -> TRUNNION (leader value = rod extension
  cm; -2.56 deg/cm from MuJoCo). Without it the rod's 1.8 kN took the easy
  path and pushed the free-rolling carriage sideways (robot rolled 90 cm,
  trunnion 0 deg); couplers on the WHEEL CARRIER were rejected (drove the
  robot off at 45-55 cm/s). Result: chassis lifts 7.3 -> 9.7 cm, trunnion
  -10.6 deg (MuJoCo -17), residual roll ~7 cm/s decaying.
- Rear rod range +-3 cm (saturates earlier with the rigid strut; +0.04
  launched). Drive-wheel brake 2e6 -> 2e5 (hard brake made carriage
  strokes propulsive).
- Slide-leader coupler support (4-arg GetConstrainedComponents).
Process lessons: assert "Result: Succeeded" — a crashed compiler left an
old DLL in place twice and I validated stale binaries; the compiler
crashes intermittently on this machine (cl.exe), just rerun.
Current honest state (flat map, full robot): rest creep 1-3 cm/s (fingers
park at +-25 deg sag), elevator lifts and returns, front rod lifts, rear
rod stable through over-range, gripper command moves both fingers.
Remaining: elevator residual roll, finger sag/curl (needs the MjBody-frame
pin re-derivation the other session noted), per-joint L/R asymmetry from
the two 5 mm Blender mount offsets.

Addendum (6.19): reimported BP re-fixed-up (armature/frictionloss). Newton
worker suite 31/31; parity vs plain MuJoCo on the rigid-strut base PASSES
but with max divergence 0.083 rad (was 7e-5 with soft struts) — the
rigid closure loop is stiffer and the two solvers' contact handling
diverges more. Within tolerance; watch it if the strut model changes again.

### 6.21 The pin leak was a FRAME-SCALE bug, not a solver leak (2026-08-18)

Evidence chain, all measured headlessly with the new `Ramms.Probe` command
(`-game` on Map_ChaosSmoke, spectator-only game mode so no pawn collides):

1. **Symptom quantified**: both gripper follower↔coupler pins sat torn at
   EXACTLY 4.794 cm from the first physics tick, immutable for 12 s, while
   all 12 mebot pins held ≤0.2 cm. Constraint bound, both bodies
   simulating, not broken — enforcement simply absent.
2. **Frames at init**: logging the two ref-frame anchors right after
   `InitComponentConstraint` showed frame1 at the constraint position
   (follower origin — correct, offset 0 is scale-invariant) and frame2 at
   the COUPLER ORIGIN + ~5 mm — i.e. the true 4.79 cm coupler-side offset
   divided by ~1000.
3. **Root cause** (`PhysicsConstraintComponent.cpp:578`):
   `UpdateConstraintFrames` divides `Pos1/Pos2` by
   `GetConstraintScale() = GetComponentScale().GetAbsMin()`. The generated
   constraint nodes inherit the gripper chain's imported-asset
   compensating scales; the mebot chain is unit-scale, which is why only
   gripper pins died. This also retro-explains 6.19's "leaky
   follower-coupler pin" and every soft/hard/projection knob failing.
4. **Fixes** (RammsMujocoSupport): runtime `ApplyChaos` re-derives every
   rig constraint frame from the owning **MjBody component transform**
   (generator now records `ConstraintBodyFrames`/`ConstraintBodyComponents`;
   MjBody names are unique so no shared-asset ambiguity) and **forces the
   constraint's world scale to 1** before `TermComponentConstraint` →
   `UpdateConstraintFrames` → `InitComponentConstraint`. Note
   `InitComponentConstraint` alone does NOT pick up a moved component —
   `UpdateConstraintFrames` must run against the corrected pose.
5. **Projection must be OFF on pins**: with frames fixed, a
   projection-enabled locked pin STILL sat torn 4.79 cm; disabling
   projection made it hold 0.000→0.03 cm (12 s, under free-flop and drive
   load). Generator no longer emits projection on any pin; the runtime
   also clears it defensively for stale rigs.
6. **Regen no longer bricks placed instances**: recreating the
   ChaosRig_BackendSwitch node orphaned per-instance `Backend=Chaos`
   overrides (placed robot silently reverted to MuJoCo → "0 resolved").
   The node is now REUSED (suffix-tolerant) and only its generator-owned
   arrays are reset.
7. **Ramms.Probe** (RammsJointPanel.cpp): samples base
   settle/creep/upright, every drive constraint's twist (or slide
   extension), and every pin's ref-frame separation computed against
   scale-free BODY transforms (component transforms carry the 0.001
   compensating scales and corrupt the metric). Report to log +
   `Saved/RammsProbe.txt`. Gotcha for future tools: `ClearTimer` from
   inside a repeating timer lambda destroys the delegate — and its
   captures — IMMEDIATELY; take strong local copies first.

REMAINING (the honest finger state): with the loop finally closed the
four-bar gravity-falls to ±81° — its ANGULAR limits and drives are inert
in the live solver on these floored-mass links (hard windows, soft
windows, cone hardness, 1e4 drives: no measurable effect; linear locks and
pins on the SAME constraints enforce exactly; drives verified present in
the live profile). Reproduced identically on a clean regen of the pulled
BP — not asset crud. Prime suspect: angular inertia conditioning
(~1e4:1 link-vs-arm inertia ratio); `Ramms.Debug.ArmInertiaScale N` is in
place to test (and `Ramms.Debug.DisableGripperDrives` for drive bisects).
After the mechanism holds: asymmetric windows (driver [0°,45.8°], coupler
[−90°,0°] — MuJoCo rests ON its stops) and springref-aware spring targets
(spring_link preloads toward +150°, not spawn) are the fidelity items.
