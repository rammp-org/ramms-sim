# Physics backend unification plan

> ## Hand-off state (2026-08-05) — read this first when picking up
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
