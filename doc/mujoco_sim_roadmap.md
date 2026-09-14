# MuJoCo simulation roadmap

Status: **draft for review** (2026-09-11). Companion to
`newton_learnings_to_urlab_plan.md` (a separate draft, not yet in the repo, which
records the Chaos-deprioritized decision and archives the Chaos-specific
learnings). This doc is the forward plan under a **MuJoCo-only focus** on
URLab v0.6.0-beta: the re-scoped no-regret work, plus three integration threads
the effort now targets — driving bases in MuJoCo, seating a person in the
simulated chair + crowd interop, and Python scene-generation automation.

Threads 2 and 3 below are filled from investigations still in progress at the
time of this draft; thread 1 and the phases are complete.

---

## Phases 1–2, re-scoped to MuJoCo (no-regret, in scope now)

Dropped the Chaos-rig framing; kept what serves MuJoCo simulation:

**Phase 1 — backend-neutral data hygiene + runbook.**
- Port `bake_inertials.py` (bakes MuJoCo-computed `<inertial>` into every MJCF
  body — identity for MuJoCo, but makes masses explicit/portable) and the
  OBJ-from-GLB restore (dodges the `.gitignore *.obj` landmine), wiring them
  into `mujoco/` compose scripts. Verify URLab-beta ingests `<inertial>` onto
  `MjBody` on import.
- Fold the headless-acceptance runbook truths into `main`'s docs: spectator-only
  game mode, Python-writes-a-result-file, `-ExecCmds`-applies-after-first-tick,
  and the URLab import landmines (SC provider blocks scripted import, purge
  `Intermediate/CachedAssetRegistry*.bin` after `.uasset` deletion, save physes
  materials on creation, no delete-then-reimport in one session, no import in
  Play mode, don't kill `UnrealEditor-Cmd` before the post-log `save_asset`).
- ~~Re-check whether URLab-beta still drops `armature`/`frictionloss` on
  import~~ **(checked 2026-09-11):** beta's ProtoSpec schema carries
  `Armature`/`Frictionloss` on `MjJoint` and `<inertial>` (`UMjInertial`) as
  generated elements with stock-parity import, so the pre-beta drop is fixed and
  the old `fixup_mebot_import.py` workaround is obsolete. `bake_inertials` is
  therefore optional-but-useful (explicit/portable masses), not required to
  avoid a drop.

**Phase 2 — measurement + unified command surface** (useful even MuJoCo-only):
a `Ramms.Probe`/`Validate`-style headless health/acceptance check reading joint
state + a unified drive/joint command entry. Under MuJoCo-only this largely
overlaps the URLab bridge + simulate widget, so scope it to what those don't
already give us (a scriptable RAMMS-side acceptance metric). Revisit priority
after thread 1, which needs the command surface anyway.

---

## Thread 1 — architecture: a shared robot base component (2026-09-12)

Converged design (supersedes the per-controller drive seam in
rammp-org/ramms-core#21 + ramms-mujoco-support#2, which are reworked into this):

**`URammsRobotBaseComponent`** — one per robot actor, the shared substrate every
actuation/drive subsystem consumes:
- Loads the robot's **motor registry** data table and resolves the physics
  **backend once** (Chaos vs MuJoCo, via the drive-backend registry — now
  generalized to `IRammsActuationBackend`).
- Pure **router + query surface**, no semantics: `SetCommand(MotorId, value)` /
  `GetValue` / `GetVelocity` / `GetType` by ID, and **geometry queries** derived
  from the resolved model — `GetMotorPosition(id)`, `GetMotorAxis(id)`, and
  helpers like motor-to-motor separation (skid-steer track width) and motor
  angles (holonomic). Backend implements the reads; the component computes
  derived facts.

**Motor registry table** (`FRammsMotorSpec` row) — intrinsic facts only, **no
role**: `Id` (canonical, defaults to the MuJoCo actuator name) + optional
`ChaosName` override; `Type` { Torque, Position, Velocity }; optional control
config (range/limits). Roles were dropped deliberately — the same mechanism
(a 5-bar linkage in x-z) serves different purposes (drive-motor positioning per
side vs. seat elevation), so "what it's for" is expressed by *which controller
drives which motor IDs*, not a coerced enum.

**Controllers are thin ID-list consumers** — no per-controller backend wiring or
name plumbing:
- Differential drive: `LeftMotorIds`/`RightMotorIds`, commands torque + queries
  track width from the two drive motors' separation.
- Holonomic (future): its wheel motor IDs + positions/angles from the base.
- 5-bar linkage (drive-positioning, seat): commands its motors by ID through the
  base, but takes its **own separate kinematic data table** (link lengths, pivot
  geometry) — the base motor registry deliberately doesn't model geometry.

**Backend selection** is per-actor on the base component (`EDrivePhysicsBackend`
Auto/Chaos/Mujoco); optional-with-fallback so existing Chaos BPs without a table
keep working. Chaos actuation backend lives in RammsCore; MuJoCo backend in
RammsMujocoSupport, registered via the registry (no RammsCore→URLab dep).

**Build order:** (1) RammsCore foundation — motor spec + `IRammsActuationBackend`
+ base component + Chaos actuation backend; (2) MuJoCo actuation backend
(RammsMujocoSupport); (3) rework the differential drive controller into a
consumer; (4) the Mebot/5-bar linkage consumer + its kinematic table; (5)
holonomic controller.

### Status (2026-09-11)

- **(1) DONE** — rammp-org/ramms-core#22. `FRammsMotorSpec` (FTableRowBase),
  `IRammsActuationBackend`, `RammsActuationBackends` registry,
  `URammsRobotBaseComponent` (loads the motor table, resolves the backend once,
  routes `SetMotorCommand`/`GetMotorValue`/`GetMotorVelocity` + geometry
  `GetMotorTransform`/`GetMotorSeparation` by Id; backend-null-safe), and the
  native `FRammsChaosActuationBackend` (torque about the wheel bone's local Y).
  Backend resolution: Mujoco (registry) / Chaos (native) / Auto (MuJoCo then
  Chaos fallback). Clean `RammsEditor` Mac compile+link.
- **(2) DONE** — ramms-mujoco-support#3. `FRammsMujocoActuationBackend`
  (articulation resolve, UI control source, Id→actuator, staged control clamped
  to `ctrlrange`, `GetLength`/`GetVelocity`/node transform) registered via the
  registry at module startup. Clean compile+link with #22 in place.
- **(3) DONE** — rammp-org/ramms-core#22. The differential-drive controller
  routes wheel physics I/O through a sibling `URammsRobotBaseComponent` by motor
  Id (velocity read, torque command, braking), backward-compatible via the
  existing wheel-bone fallback when no base component is present. Public API
  unchanged (RammsAccess recompiles clean). See design notes below. Needs PIE/RC
  validation on both backends (Chaos chair + MeBot-MuJoCo).
- **(4) DONE** — rammp-org/ramms-core#22. `FRamms5BarLinkageSpec` (separate
  kinematic table row: pivots, link lengths, angle mapping, elbow branch),
  `URamms5BarKinematics` (stateless IK/FK), and `URamms5BarLinkageController`
  (one per linkage; commands its two proximal Position motors by Id through the
  base component). Geometry defaults measured from lift_drive_linkage_ue.xml
  (left centre leg = the true 5-bar: hip_a + hip_b -> shared wheel-mount
  endpoint). IK/FK verified numerically (exact roundtrip; FK at the reference
  config lands the endpoint on the wheel centre). Geometry defaults want PIE
  validation on the live articulation.
- **Self-review (2026-09-12)** — fixes on both PRs. Notable: the 5-bar IK elbow
  branch was inverted (the first roundtrip test couldn't see it — FK∘IK is
  identity on the mirrored crossed-knee pose too; the right test is
  IK(FK(q)) == q on *feasible* q, now exact); the MuJoCo backend's
  "first articulation in the level" fallback would have hijacked an unrelated
  robot under `Backend=Auto` (now owner/attached-child only); MuJoCo motor
  transforms now resolve the driven joint's body (actuator nodes sit at the
  model root, so track-width separation was ~0). Base component: lazy backend
  resolution (BeginPlay-order-safe), per-motor `Direction` sign in the
  registry, unregistered-Id warning; diff-drive falls back to the direct Chaos
  path when the base has no backend.
- **Review round 2 (2026-09-12)** — addressed on both PRs (registry load
  order + duplicate Ids, straight-knee FK boundary, brake law parity, lateral
  track width, joint-based MuJoCo reads with slide→cm, honest transform
  failure). One item is **outside these PRs**: URLab's
  `AMjArticulation::ApplyControls` returns right after an enabled
  `UMjArticulationController`'s `ComputeAndApply`, so on a composed base+arm
  articulation with the end-effector controller enabled, staged wheel/hip
  commands are never copied into `d->ctrl`. The backend now warns; the real
  fix is a reorder in URLab (apply staged owned-actuator controls, then let the
  controller overwrite the actuators it owns) — a fork/local-patch change to
  propose upstream. Until then: keep base and arm as separate articulations, or
  disable the arm controller while driving.
- **Live PIE validation (2026-09-12, via Python remote execution)** — assets:
  `Content/Robots/Data/DT_Mebot_ChaosMotors`, `DT_LiftDriveLinkage_Motors`,
  `DT_LiftDriveLinkage_5Bar`; `BP_Mebot_Ramms` gained a `RobotBase`
  (Chaos, `VehicleMesh`, left→`drive_wheel_r` / right→`drive_wheel_l` as the
  BP was authored); new `BP_LiftDriveLinkage_Ramms` (child of the imported
  articulation) with `RobotBase` (MuJoCo) + diff-drive on the centre wheels +
  left/right centre 5-bar controllers.
  - Chaos chair: drives through the base component exactly as before
    (motor-curve-limited ~2 N·m at 100 RPM, full 7 N·m at stall); measured
    lateral motor separation 60.9 cm vs authored 60.
  - MuJoCo base: staged == applied == actuator force, wheels spin up along the
    motor curve, base translates; measured separation 54.9 vs 54.8.
  - 5-bar: the joint-sign convention was inverted (fixed: Sign = −1 for a +Y
    hinge); "retract above the reference pose" is correctly refused (hip_b's
    range floor is 0 — the reference pose IS fully retracted); "extend to
    10 cm" raises the body ~1:1 with leg extension and lifts the front wheel.
    The hip position servo (kp 2500) shows steady-state offset under the
    ~110 N·m body load — expected for a P servo, tune kp/kv in the MJCF if
    tighter tracking is wanted.
  - Test gotchas (see the memory note / `Scripts/pie_tests/base_component/`):
    Map_BaseTest_URL's MuJoCo scene starts **paused** (`AMjManager.set_paused
    (False)`); the chair's `RammsAccessInputComponent` re-zeroes external drive
    input each tick; never `set_editor_property` on live PIE components.
- **Docs + media** — `doc/base_component_controls.md` details which assets carry
  which controllers and every control surface (Blueprint/C++, player input incl.
  Pixel Streaming, Python remote execution, Remote Control HTTP, URLab bridge
  coexistence). Captures from the validation runs are not versioned; the
  scripted PIE checks in `Scripts/pie_tests/base_component/` reproduce them.
- **Player pawns (2026-09-12)** — `URammsKeyboardTeleopComponent` (RammsCore,
  on PR #22): polls keys → diff-drive input, 5-bar endpoint height, and
  data-driven key→position-motor groups. `BP_LiftDriveLinkage_Ramms` and
  `BP_LiftDriveHolonomic_Ramms` are auto-possessed pawns with a follow camera;
  validated by keyboard through the editor and the Pixel Streaming page
  (`doc/base_component_controls.md` §2b).
  Fixed on the way: `ARammsPlayerController::OnPossess` crashed (CastChecked)
  on any non-chair pawn.
- **Test-drive map (2026-09-12)** — `ARammsMujocoTestGameMode`
  (RammsMujocoSupport, on PR #3): pre-spawns `DefaultPawnClass` in `InitGame`
  so the pawn is in the compiled MuJoCo scene, unpauses the engine after
  begin-play, hides the widget; plain `PlayerController`.
  `BP_LiftDriveTestGameMode` (holonomic by default) is `Map_BaseTest_URL`'s
  GameMode Override with a PlayerStart; the raw placed articulations were
  removed. Press Play and drive.
- **Pawn cameras (2026-09-13)** — `URammsRobotCameraComponent` (RammsCore, on
  PR #22): Tab cycles the pawn's cameras (follow / top-down / URLab possess),
  right- or left-drag orbits the active spring arm, wheel zooms, Home resets;
  `Orbit()/Zoom()/NextCamera()/ActivateCamera()` for UI/Blueprint/Python.
  Verified in PIE over Pixel Streaming (Tab/wheel/Home), via the API
  (orbit/zoom) and with a real mouse drag on the PIE viewport. Gotcha found on
  the way: the PIE viewport keeps the press that starts a drag (PlayerInput
  never sees the button, only the movement), so the component reads Slate's
  pressed buttons / cursor as the fallback. Also: URLab's `PossessCamera`
  hangs off `Bodies[0]` = the static `worldbody` in these scenes, so it never
  follows the robot — the pawns list `CameraNames = [FollowCamera, TopCamera]`
  and the component orders authored cameras before runtime-added ones.
- **Chair lift/linkage motors on the base (2026-09-14)** — the Chaos backend
  drives Position motors as physics-asset constraint drives (DOF inferred from
  the constraint; rad / cm), `DT_Mebot_ChaosMotors` registers the elevators,
  translators and caster arms, and `UMebotControllerComponent` routes through
  the base (`bUseRobotBase`) — so both chair controllers are base consumers
  now. Found on the way: the holonomic base's centre-wheel hinges are −Y, so
  its table carries `Direction = −1` (forward was inverted); the diff-drive's
  joystick mixing had the steering sign inverted (the chair BP hid it by
  swapping its wheel bones) — fixed in the library, chair un-swapped, turn
  direction asserted by both PIE runners.
- **(5) NEXT** — holonomic drive controller.

Note on the linkage mechanism (lift_drive_linkage_ue.xml): each side has front
and rear legs (crank position actuator + coupler + arm closed by a `<connect>`)
and a **centre 5-bar** — `hip_a` + `hip_b` position actuators drive two 2-link
chains meeting at the centre-wheel mount (`connect left_center_lower_a/_b`),
positioning that wheel in x-z. The front/rear legs are single-DOF crank linkages
(one position actuator each) — a follow-up if a crank-linkage consumer is wanted;
the 5-bar controller covers the two-actuator parallel case.

### (3) Differential-drive rework — design + open items

Route the controller's physics leaves (`ApplyWheelTorque`, `UpdateWheelState`,
`ApplyBrakes`, `GetBoneBodyInstance`, odometry read) through a sibling
`URammsRobotBaseComponent` instead of touching `FBodyInstance` directly. The
backend-neutral public API (input, arbitration, `GetOdometry`, wheel-state
getters, `SetControlMode`) is preserved verbatim.

Decisions to make it non-breaking + honest:
- **Content migration.** Reading wheel state / applying torque moves to the base
  component, so the MeBot chair BP must gain a `URammsRobotBaseComponent` + a
  motor DataTable (rows `left_motor`/`right_motor`, Type=Torque, ChaosName =
  the wheel bones). Keep the controller's `Left/RightWheelBoneName` as the
  *fallback* when no base component is present, so existing Chaos BPs keep
  driving until migrated (backward-compatible), and add `Left/RightMotorId`
  (default `left_motor`/`right_motor`) used when a base component is found.
- **Slip/traction.** Lateral-slip resistance + load-dependent traction read
  wheel lateral velocity / contact, which the generic motor interface does not
  expose. They default **off** (`bEnableSlipModeling=false`), so the
  base-component path keeps resistive-torque + braking (both need only angular
  velocity, which is exposed) and treats the lateral-slip extras as no-ops with
  a note. Revisit only if a robot needs them under MuJoCo (MuJoCo resolves
  contact itself).
- **Validation** needs a running editor: PIE/RC drive of the Chaos chair
  (no regression) and a MeBot-MuJoCo BP (new path), as done for teleop.

---

## Thread 1 (original) — Drive RAMMS bases in MuJoCo simulation

**Goal:** the existing base-drive components drive a URLab MuJoCo-simulated MeBot,
with their Python/Remote-Control API surface unchanged. Today they drive Chaos.

### The clean seam
`URammsDifferentialDriveController` already separates concerns perfectly: the
**public API + input model + arbitration are backend-neutral** and only five
private leaves touch physics. Preserve verbatim:
- `SetDriveInput(FVector2D)` / `SetExternalDriveInput(FVector2D)` (X=turn,
  Y=fwd, ±1, deadzone 0.05; external wins for `ExternalInputHoldSeconds`≈0.3s),
  `IsExternalDriveActive`, `GetOdometry`/`ResetOdometry`,
  `GetLeft/RightWheelState`, `SetControlMode` (Torque|Velocity),
  `SetSlipModelingEnabled` — the whole HTTP-RC/BP contract (`RammsAccess` and
  `control_mebot.py`-style callers keep working unchanged).
- Physics-touching leaves to make backend-swappable: `ApplyWheelTorque`,
  `UpdateWheelState`, `UpdateOdometry`, `ApplyBrakes`, `GetBoneBodyInstance`
  (today: skeletal wheel-bone `FBodyInstance::AddTorqueInRadians` + odometry
  from bone rotation).

### How URLab drives a base today (and the gap)
`AMjArticulation` is an `APawn` exposing actuators **by name**
(`SetActuatorControl(name,val)`, `GetActuatorNames/Range`), staged into
`d->ctrl` per step via internal (UI) vs network (ZMQ) slots selected by
`ControlSource`. `UMjTwistController` **captures** WASD/gamepad into a twist and
broadcasts it in the state IR — but **nothing in UE converts twist → wheel
`ctrl`**; that control law currently lives in an external Python/ROS client.
The MeBot MJCFs today put `base_link` on a `<freejoint>` with **torque
`<motor>`** wheel actuators (holonomic 6-wheel / 6-wheel linkage), **no
`<velocity>` actuators and no simple left/right diff-drive pair.**

### Plan
- **Phase 0 (MJCF, needs user decision):** give the MeBot a driveable diff-drive
  base — left/right hinge wheels + `<velocity>` actuators (natural target for
  `VelocityControl`; MuJoCo does the wheel PID). Cross-process/URDF-naming
  change → **ask** (see open questions).
- **Phase 1 (refactor, no behavior change):** route the five physics leaves
  through an internal drive-backend seam; default `ChaosSkeletalBackend` wraps
  today's code exactly. Gate: clean `RammsEditor` UBT compile.
- **Phase 2 (`MujocoDriveBackend`):** reuse the existing
  `JoystickToDifferentialDrive` output (keep diff-drive kinematics UE-side so
  the input model/params keep meaning), map left/right cm/s → wheel rad/s →
  `SetActuatorControl`; feedback via `UMjActuatorRuntime::GetVelocity/GetForce`.
- **Phase 3 (wiring):** the MuJoCo base is a separate pawn (`AMjArticulation`),
  so resolve it + actuator names at `BeginPlay` (mirroring today's
  `SkeletalMeshComponentName` lookup); pick backend by enum or auto-detect.
- **Phase 4:** parity test — arbitration, deadzone, RC calls identical on both
  backends; `RammsAccess` unchanged.

Secondary: `UMebotControllerComponent` (lift/linkage joint-position RC surface)
maps cleanly onto the MJCFs' existing `<position>` actuators — the easier second
target, scope TBD.

### Resolved model (2026-09-12, from the user + MJCF inspection)

- **Wheels are torque `<motor>` actuators** (`ctrlrange="-30 30"`), NOT velocity
  — verified in both `lift_drive_holonomic` and `lift_drive_linkage`
  (`Saved/URLab/ImportPrep/.../*_ue.xml`). The `<position>` actuators are the
  crank/hip lift joints. So the controller's **TorqueControl mode maps directly
  to the motor actuators — no MJCF/wire-contract change needed for v1.**
  (VelocityControl-in-MuJoCo is deferred: add `<velocity>` actuators later, or
  run a velocity loop in the backend.)
- **The base reconfigures between drive modes via its lift linkages:**
  - **Differential / skid-steer** (both bases): front/rear omniwheels lifted off
    the ground; drive torque comes from the **center wheels**
    (`left_center_wheel` / `right_center_wheel`, present in both variants), which
    have the highest traction. So the differential backend drives the **center
    wheels**, matching the controller's one-actuator-per-side model.
  - **Holonomic** (`lift_drive_holonomic` only): center wheels lifted, front/rear
    linkages lowered; the 4 omni wheels give holonomic (x, y, yaw) motion. The
    `lift_drive_linkage` base cannot drive holonomically in any configuration.
  - Entering a mode is a **base-configuration** step (the crank/hip `<position>`
    actuators, i.e. `UMebotControllerComponent`'s domain) done before driving.
- **Two controllers, therefore:** the existing differential controller (this
  thread) for skid-steer via the center wheels, and a **new holonomic drive
  controller** for the holonomic base in holonomic mode (drives the 4 omni
  wheels from an (vx, vy, yaw) command). Planned as a follow-on.

### Layering: how a MuJoCo backend plugs in without RammsCore→URLab dependency

RammsCore must not depend on URLab (that's RammsMujocoSupport's job). So:
`IRammsDriveBackend` stays in RammsCore; the **MuJoCo backend lives in
RammsMujocoSupport** (which already depends on URLab) and is injected via a
**backend-factory registry** in RammsCore. RammsMujocoSupport registers its
factory at module startup; the controller gains an `EDrivePhysicsBackend`
UPROPERTY (Chaos / Mujoco / Auto) and in BeginPlay asks the registry for a
MuJoCo backend when requested, falling back to Chaos if none is registered or
its Initialize fails (no articulation resolved).

### Remaining decisions (non-blocking for the torque v1)
- Control-slot ownership (UE internal slot vs honor `ControlSource` for ZMQ/ROS).
- Odometry under MuJoCo: keep UE wheel-integrated vs read the base `freejoint`.
- Whether `UMebotControllerComponent` (lift/linkage position actuators, and the
  mode-switching it implies) is folded in now or later.

---

## Thread 2 — Person seated in the MuJoCo/Newton chair + crowd interop

**Where things stand today**
- The seat system lives in **RammsCrowd**, not RammsCore: `URammsSeatComponent`
  (`Plugins/RammsCrowd/.../RammsSeatComponent.{h,cpp}`) + the graph-less
  `URammsSeatedPoseAnimInstance`. It is **purely kinematic / rendering-only** —
  it spawns an occupant (City Sample `BP_CrowdCharacter` by default), attaches
  it to the seat transform with `KeepWorldTransform`, **disables all physics +
  collision** ("decoration riding another physics body"), and applies a static
  seated pose via per-bone local rotation offsets. It is wired only to the
  **Chaos** MeBot (`BP_Mebot_Ramms`), not the MuJoCo pawn.
- The MuJoCo chair (`lift_drive_holonomic`) models **only the mobility base** —
  `base_link` on a freejoint + suspension/wheels/lift + the attached Gen3 arm.
  **No seat body, no occupant, no rider mass/inertia** anywhere in the MJCF.
- Crowd is **UE Mass-Entity based** (ZoneGraph + StateTree + MassCrowd), agents
  posed by a blendspace `URammsCrowdAnimComponent` (no AnimBP). Crucially, a
  **robot/vehicle→Mass avatar bridge already exists** (`URammsPlayerAvatarTrait`
  /`Translator`, explicitly built for "a physics-driven skeletal mesh with no
  capsule") so crowds already can avoid/look at the wheelchair.
- `RammsHumanPhysics` is an **empty placeholder plugin** (README + LICENSE only)
  scaffolded for exactly a simulated human body.

**(A) Seating a person in the sim chair — options, physics vs rendering**
- **A(i) Kinematic occupant riding the sim chair** *(recommended first step).*
  Reuse `URammsSeatComponent` as-is but make it follow the `UMjBody` transform
  for `base_link` (or a seat-frame body) instead of a static actor root — the
  same read `URammsMjSkeletalPoseDriver` already does. Full-quality render,
  cheap, proven; but the rider contributes **zero** mass to the sim (wrong
  tipping/motor-load/sag). Mitigation: bake a rider inertial-only body into the
  base MJCF so dynamics see the load while the mesh stays kinematic.
- **A(ii) Simulated articulated occupant** welded into the chair MJCF; render via
  a skeletal-pose driver on those bodies. Correct mass/CoG/sway/perturbation —
  the honest option for stability/comfort/safety studies — but real work to
  build a stable seated MJCF human + rigged-mesh mapping (the `RammsHumanPhysics`
  gap), and it edits the shared MJCF (ask-first).
- **A(iii) Hybrid** *(pragmatic target):* simulate rider **mass/inertia** (an
  inertial body or coarse 1–3-DOF lean joint welded to the seat) for honest
  loading + gross sway, **render** a kinematic posed mesh locked to it, plus
  optional hand/foot IK onto armrests/joystick/footplates (the upgrade already
  noted in RammsCrowd `CUSTOMIZATION.md`).

**(B) Crowd interop**
- **B1 — chair as an obstacle the crowd flows around** *(nearly free — bridge
  exists):* wire the MuJoCo MeBot pawn with `URammsPlayerAvatarTrait` (+ nav
  obstacle / look-at traits + stimulus source). One concern: feed the avatar
  entity from the `base_link` `UMjBody` transform if the AActor root doesn't
  itself track the sim.
- **B2 — a crowd member boards/rides a chair** *(new work):* a StateTree "board"
  task hands the agent's skeletal actor from crowd locomotion (stop the
  blendspace anim, remove it from `RammsCrowdActorSyncProcessor`) to the seat
  system (attach to the chair's seat body, swap to the seated pose instance),
  suppress it from ZoneGraph while riding; reverse on "alight." Needs a new
  "seat an existing actor" path on the seat component (today it always
  spawns/destroys its own occupant).

**Open questions for the user**
1. **Which engine owns the wheelchair base** going forward — MuJoCo
   (`lift_drive_holonomic`) or Newton (`RammsNewtonPhysics`)? Decides where a
   simulated occupant lives. *(Shared with Thread 1.)*
2. **How physically honest must the rider be** — visual only (A(i)),
   mass/inertia loading (A(iii)), or fully articulated (A(ii))? Biggest scope
   driver.
3. **Is `RammsHumanPhysics` the home** for a simulated human body, or weld the
   occupant into the base MJCF?
4. **Is editing the shared `lift_drive_holonomic` MJCF acceptable** (seat frame /
   rider inertial / occupant tree)? *(ask-first per CLAUDE.md)*
5. **Crowd goal:** B1 (obstacles), B2 (boarding riders), or both?
6. **Does `BP_Mebot_Mujoco`'s actor root track the sim base**, or only the
   `UMjBody`? Determines whether the avatar bridge + a component-attached seat
   work as-is. *(Shared with Thread 1.)*
7. **Should the seat move** from RammsCrowd into RammsCore / RammsHumanPhysics
   (it's currently crowd-only and Chaos-only)?

---

## Thread 3 — Python scene-generation / conversion automation

**What already exists (a strong base to build on)**
- **Quick-convert:** `UMjQuickConvertComponent` turns a UE static-mesh actor
  into an MJCF `<body>` (freejoint / `mocap` / `Static`), CoACD or convex hulls,
  per-geom friction/solref/solimp, content-hashed OBJ export, two-way runtime
  coupling. Gaps in source: **authors no mass/inertial** (MuJoCo auto-computes
  from volume), per-actor + editor-only + **synchronous CoACD**.
- **Automatic scene assembly:** `UMjPhysicsEngine::GatherSceneContributors()`
  iterates all actors implementing `IMjSceneContributor` and compiles them in —
  so *dropping actors + attaching quick-convert is sufficient*, no manual wiring.
- **Composition:** `UMjAttach`/`UMjModelAsset` (in-editor) and the offline
  `mujoco/compose_*.py` `MjSpec.attach(prefix=,site=)` idiom (→ `import_xml`).
- **Automation surface, three layers:** (1) UE Python remote-exec (:6766) + RC
  HTTP (:30010) reach all `BlueprintCallable` API; (2) the **URLab ZMQ bridge**
  whose `meta` op ships the whole op table — runtime ops (`step`/`reset`/
  `set_qpos`/`set_mocap_pose`/`get_contacts`/`set_twist`/…) **and editor ops**
  (`create_level`/`ensure_manager`/`spawn_actor`/**`spawn_grid`**/**`add_quick_convert`**/
  `set_actor_transform`/`get_actor_bounds`/`begin_pie`/`snapshot`/…); (3) clients
  `ramms-tools` + `urlab_bridge` (typed client + `gymnasium.Env`). An end-to-end
  build→convert→step→sense loop is already possible over the bridge alone.

**Gaps for procedural cluttered scenes**
- Only single `spawn_actor` + regular `spawn_grid`; **no seeded random scatter,
  collision-free/surface-relative placement, or asset-catalog** abstraction.
- `add_quick_convert` is per-actor/editor-only/sync-CoACD; **no batch convert**,
  **no authored mass/inertia**, one friction triple (no per-material contacts).
- Robot + props spawn as **separate participants**; no build-time `<attach>` RPC
  (fusion is offline-python-only today).
- **`reset` takes no seed**; no episode/scenario abstraction, DR driver, or
  built-in data path. **Determinism must be client-side**: seed the RNG, resolve
  all placements/params, issue spawn/convert/transform ops *before* `begin_pie`
  (the Direct-step + fixed-timestep recipe from `PARALLEL_SIM_PLAN.md` is
  deterministic but doesn't own the seed).

**Proposed `ramms-scene` toolkit (in `ramms-tools`, over the bridge editor ops)**
- **Phase 0 — scaffolding + asset catalog.** Declarative scene spec (YAML): robot
  BP, catalog entries (home/grocery/outdoor), regions, density, physics
  overrides, seed. Import prop meshes as static-mesh BPs, tag which need complex
  collision. `ramms-scene build <spec>` → `create_level`→`ensure_manager`→
  `spawn_*`→`save_level`.
- **Phase 1 — seeded scatter + placement.** Client-side seeded RNG; collision-free
  AABB rejection sampling via `get_actor_bounds`; surface-relative placement
  (items on a shelf/table top face); persist seed + resolved placements.
- **Phase 2 — convert-at-scale + physics authoring.** Batch/`convert_tagged`
  (amortize CoACD + round-trips); port **`bake_inertials`** so bodies carry
  explicit mass (post-process the MJCF, or add mass/density to quick-convert —
  a plugin-API change); surface `contype/conaffinity` + per-object mass/friction.
- **Phase 3 — robot composition.** Multi-participant already works; for a fused
  base+arm+gripper use the offline `compose_*.py`→`import_xml` path (or add a
  runtime `<attach>` op if runtime re-composition is needed).
- **Phase 4 — episode driver + domain randomization.** `reset(seed)` → DR (swap
  catalog variants, jitter poses/masses/friction/lighting) → `begin_pie` →
  Direct-step control (`set_twist` nav + actuator ctrl for the arm +
  `get_contacts` grasp success) → obs (RGB/depth/ToF/sonar). Recommend adding a
  `seed` field to the `reset` RPC (cross-process contract change — ask-first).
- **Phase 5 — data path + scale.** Wire into the Parallel-Sim plan: offline shard
  writer or online `URLabVectorEnv`, multi-instance via the native port scheme.

**Open questions for the user**
1. **Asset catalog source** — dojo pipeline (Blender→UCX→MJCF) for articulated
   furniture (cabinets/fridges with openable parts), plus a static-prop library
   for groceries? CoACD vs authored primitives for small items?
2. **Robot composition mode** — one fused `BP_<robot>` (offline `MjSpec.attach`)
   enough, or need runtime re-composition (swap grippers/payloads)?
3. **Seeding ownership** — extend `reset` with a `seed` field (wire-contract
   change) or keep all randomization client-side?
4. **Mass authoring** — post-process MJCF with `bake_inertials`, or add a
   `mass`/`density` UPROPERTY to `UMjQuickConvertComponent` (plugin-API change)?
5. **Toolkit home** — confirm `ramms-tools` (`ramms_tools.scene`).
6. **Authoring flow** — author in a headless (offscreen) editor → save level →
   run cooked for training, matching the two-mode split in the Parallel-Sim plan?

---

## Cross-cutting decisions — RESOLVED (2026-09-11)

1. **Base engine: MuJoCo and Newton share ONE MJCF configuration.** No
   per-engine model fork; the same MeBot MJCF drives either stepper. (Simplifies
   Threads 1 & 2 — one model to author and maintain.)
2. **Editing the shared MJCF is OK — but the composition target is
   UE/Blueprint, not a monolith.** Compose **base + seat + arm + rider** in
   Unreal via the component tree / `<attach>` (`UMjModelAsset` + `UMjAttach`),
   each subsystem its own MJCF/model, spliced visuals drawn by
   `URammsMjCompiledGeomRenderer`. So keep each piece a standalone, importable,
   independently-testable model; add seat frames / mount bodies rather than
   fusing everything into one base MJCF. This is the "idiomatic UE, easy
   composition/animation" goal made concrete.
3. **Rider fidelity is phased:** (i) **visual-only** kinematic occupant now →
   (ii) **mass-loading** inertial body next → (iii) **articulated** rider later
   (the `RammsHumanPhysics` home). Thread 2 executes in that order.
4. **Wire-contract changes are acceptable** (e.g. `<velocity>` wheel actuators,
   a `seed` field on `reset`, a quick-convert mass property) — **discuss each at
   the point of change**, but they are not blocked.

**Implications for the plans:**
- Thread 1: author the diff-drive wheels + `<velocity>` actuators in the shared
  MeBot MJCF (serves both engines); the UE controller's diff-drive kinematics
  stay UE-side.
- Thread 2: the seat becomes a **composable UE element** attached to the base's
  seat frame; rider rides the seat body's transform (visual phase), then gains a
  composed inertial body (mass phase). Chair-as-crowd-obstacle (B1) proceeds in
  parallel.
- Thread 3: the `<attach>`-in-UE composition path is now the primary robot-build
  mechanism (not offline-only monolithic MJCFs), so the scene toolkit composes
  by placing/attaching models in the component tree.

## Suggested near-term sequence (low-risk, high-leverage first)

1. **Phase-1 no-regret ports** (§ "Phases 1–2"): `bake_inertials` + OBJ-restore
   into `mujoco/`, the headless runbook truths, re-check armature/frictionloss.
   Backend-neutral, unblocks correct masses for every thread.
2. **Thread 1 Phase 1** (drive-backend seam refactor, no behavior change) — safe,
   sets up MuJoCo base driving.
3. **Thread 2 B1** (chair-as-crowd-obstacle) + **A(i)** (kinematic occupant on the
   MuJoCo pawn) — mostly reuse existing systems; high demo value, low risk.
4. **Thread 3 Phase 0–1** (scene-spec + seeded scatter) — the automation spine.

Deeper items (MuJoCo diff-drive MJCF, simulated occupant, batch-convert + mass
authoring, episode/DR driver) follow once the cross-cutting decisions land.
