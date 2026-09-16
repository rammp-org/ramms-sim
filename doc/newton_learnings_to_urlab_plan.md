# Porting the physics-integration learnings onto URLab-beta `main`

Status: **draft for review** (2026-09-11). This is the starting artifact for a
review-and-plan cycle, not a committed plan. The learnings come from
`feat/newton-improvements`, where Chaos/Newton/MuJoCo were unified for the
MeBot + Gen3 + 2F-85 robot; `main` has since adopted **URLab v0.6.0-beta**
("the component tree *is* the MJCF model"). The question this doc frames: which
of those hard-won learnings still apply, and how, now that the plumbing
underneath them (PhysicsAsset/SCS import) has been replaced by URLab's
component-tree import + per-geom rendering.

> **Framing fact that governs everything below.** On `feat/newton-improvements`,
> Chaos was bolted onto the *old* URLab importer: a generator produced a
> static-mesh-per-link + `UPhysicsConstraintComponent`-per-joint rig, and the
> backend switch **destroyed every `Mj*` component at BeginPlay** so URLab
> ignored the actor. The *learnings* are about making UE-native Chaos
> constraints reproduce MuJoCo behavior for a closed-loop mobile manipulator —
> that problem only exists on `main` if a non-MuJoCo backend is still wanted.

---

## The two decisions that gated the rest — RESOLVED (2026-09-11)

> **D1 → Chaos DEPRIORITIZED; focus MuJoCo.** URLab-beta's component-tree model
> already serves the original driver (idiomatic UE use without converting actors
> for sim, easier composition/animation). The Chaos-specific learnings (§1.1,
> §1.6, §1.8, §1.3, the rig generator, open problems §3.1–§3.5) are **archived
> here as a decision record**, not ported; Phases 3 & 5 are **shelved**. Revisit
> only if a UE-native backend is later wanted (macOS/no-GPU fallback, anim-only).
>
> **D2 → CONDITIONAL, low priority.** Hand-authored MJCFs import fine; the
> untested path is Blender → dojo plugin → exported MJCF → reimport. If scale
> problems show there, they're most likely an **export-side** fix in
> `ramms-blender-plugin`, not a URLab bug. One-time verify on next dojo reimport.
>
> Phases 1–2 are re-scoped to MuJoCo and in scope now (see §5). The three new
> planning threads the user added — base-control→MuJoCo, seated-person+crowd,
> and Python scene-gen automation — are tracked in a companion roadmap doc.



**D1 — Is a UE-native Chaos backend still wanted on `main` at all?**
URLab-beta MuJoCo is now the primary backend, and a Newton-behind-URLab path
exists. The branch's *own* conclusion (plan §6.20, "knob space exhausted") is
that Chaos closed-loop fidelity for the gripper four-bar and the suspension
fold is a deep, possibly-unwinnable fight. If Chaos is no longer wanted, roughly
half of these learnings (§1.1, §1.6, §1.8, and the whole rig generator) become
an **archived decision record** rather than a port. If it *is* wanted, we should
be clear on *why* (macOS / no-GPU fallback? cheap background props? a
non-MuJoCo reference?), because that reason sets the fidelity bar.

**D2 — Does URLab-beta's per-geom import produce *unit-scale* geoms?**
The headline bug on the branch (§1.1) was a constraint-frame scale-division that
only bites when constraints are built from **scaled imported meshes** (the
gripper carried ~0.001 compensating scales). Under URLab-beta the compiled-geom
renderer builds visuals at native (unit) scale, but whether a *Chaos rig
generator* walking `MjGeom`/`MjBody` components would re-introduce mm-scale
meshes needs verifying against the beta importer. This single fact decides
whether §1.1/§1.6 are **designed out** (best case) or **ported as patches**.

Everything in Phases 1–2 below is worth doing regardless of D1/D2. Phases 3+
are gated on D1 = "yes, keep Chaos."

---

## 1. Learnings inventory (problem → root cause → fix)

Anchors are on `origin/feat/newton-improvements`.

1. **Chaos "pin leak" was a constraint-frame *scale* bug.** Gripper closure pins
   sat torn exactly 4.79 cm from tick 1, immutable, for weeks of mis-diagnosis
   as a "solver leak." Root cause: `UPhysicsConstraintComponent::UpdateConstraintFrames`
   **divides** body-local frame positions by `GetConstraintScale()`; only the
   gripper chain carried ~0.001 asset scales, so its coupler-side frame shrank
   ~1000× and initialized at the coupler origin. Fix
   (`RammsBackendSwitchComponent.cpp:509-520`): re-derive every frame from the
   **owning `MjBody` component transform** and **force the constraint's world
   scale to 1** before the `Term → UpdateConstraintFrames → Init` sequence
   (Init alone does not pick up a moved component).
2. **Closure pins must run without projection.** Projection teleports position
   without touching velocity; over an inconsistent closure network it acts as
   continuous thrust (robot accelerated to 100+ m/s mid-air). Generator emits no
   projection on pins; runtime clears it defensively (`cpp:569-592`). Holds
   0.00–0.03 cm through free-flop and load.
3. **Angular constraint DOFs go inert at ~1e4:1 inertia ratios** *(still open —
   see §3)*. On floored-mass finger links, twist limits and 1e4 twist drives do
   nothing while the *same constraints'* linear locks enforce exactly; fingers
   gravity-fall through a 45.8° window. Suspect: cm²-scale link inertias vs the
   8 kg arm. `Ramms.Debug.ArmInertiaScale` exists to run the experiment to a
   conclusion; it never was.
4. **MuJoCo-computed inertials must be baked into the MJCF** for non-MuJoCo
   consumers. Only the 20 arm bodies carried authored `<inertial>`; MuJoCo
   auto-computes the ~202 kg base, Chaos fell back to crude volume estimates
   ("arm tips the base"). `mujoco/bake_inertials.py` bakes MuJoCo's computed
   inertials into every body (identity for MuJoCo); `compose_mebot_gen3.py` bakes
   on regen.
5. **`.gitignore *.obj` landmine.** The exporter's visual-mesh OBJs are silently
   eaten by the `*.obj` ("compiled object files") pattern, so fresh clones can't
   compile the MJCFs with plain MuJoCo. `bake_inertials.py` regenerates them from
   committed `.glb` sidecars via trimesh — with a **+180°X** round-trip
   convention baked in (composes with URLab clean_meshes' −90°X).
6. **Unit-scale pre-pass for mm-scale gripper bodies.** Gripper bodies imported
   at scale 0.001 — the direct cause of §1's scale division and near-massless
   floor-punching. Fix bakes the scale into mesh-asset `BuildScale` and resets
   components to scale 1.
7. **Wheel velocity-hold / damping tuning.** Undriven drive wheels rolled too
   freely; zero-command velocity-hold drive + wheel AngularDamping 0.5→2.0 ("a
   powered chair brakes hard at zero command"). Omniwheel casters need the
   *opposite* (near-zero friction) — one shared "wheel" material caused caster
   runaway. Values are load-context-dependent (`Ramms.Debug.WheelBrakeScale`).
8. **Virtual couplers to bypass leaky closure loops.** Chaos leaks force through
   multi-pin 4-bar loops (rod moved crank, swing arm never followed). Generator
   emits virtual couplers enforcing `follower = ratio × leader` via a strong
   orientation drive each tick (`TickCouplers`), ratios fitted from MuJoCo.
9. **Clamp drive commands to mechanism-realizable travel.** MuJoCo limits are
   soft; Chaos hard-limits, so commanding past real travel makes the stalled
   full-force servo (13 kN reaction) tip the robot. Exporter's ±30°/±8cm are
   *defaults, not travel*; publish real travel + clamp `SetJointCommand`, plus
   force caps and slew-limiting.
10. **Headless acceptance workflow.** Spectator-only game mode (the default
    spawns a colliding pawn); Python must **write a result file** (`unreal.log`
    isn't reliably surfaced headless). **`-ExecCmds` cvars apply *after* the
    first world tick** (i.e. after the backend applies) — a whole bisect
    campaign tested nothing until overrides were parsed from the *command line*
    instead (`cpp:96-135`).
11. **Landmines** (all UE 5.7 / URLab-import truths, engine-stable): source-control
    provider blocks scripted imports; AssetRegistry cache crash after file-level
    `.uasset` deletion (purge `Intermediate/CachedAssetRegistry*.bin`); physical
    materials silently recreated unless saved on creation; delete-then-import
    same name in one session fails silently; mesh assets are shared mutable
    state; AssetTools refuses imports in Play mode (URLab bridge auto-start can
    enter play on boot); `ClearTimer` inside a repeating-timer lambda frees its
    captures; don't kill `UnrealEditor-Cmd` before the post-log `save_asset`;
    overlapping robots read garbage transforms → depenetration explosion.

## 2. Backend-abstraction architecture (what was built)

- **`URammsBackendSwitchComponent`** — one actor, one MJCF-derived description,
  `ERammsPhysicsBackend { MuJoCo, Chaos }` chosen per instance before BeginPlay.
  A **flat parallel-array snapshot** the generator bakes in (body/constraint
  components, `ConstraintBodyFrames`/`ConstraintBodyComponents` keyed on unique
  MjBody names, `BodyMasses`, drive arrays, coupler arrays). No UINTERFACE.
- **Unified `SetJointCommand(FName, float)`** valid on both backends (wheel
  semantics deliberately diverge in v1). Under MuJoCo writes *both* control
  slots (ZMQ maps ate `SetControl` otherwise).
- **`RammsRigLibrary::GenerateChaosRig(UBlueprint*)`** (Python/BP-callable)
  walks the imported MJCF BP and emits the rig; **reuses** its
  `ChaosRig_BackendSwitch` SCS node across regens (recreating it orphaned
  placed instances' backend overrides).
- **`Ramms.Validate/Probe/Panel/Joint`** console commands — per-robot rig
  health, the acceptance probe (pin separation on **scale-free BODY
  transforms**), a slider-per-joint teleop panel routed through `SetJointCommand`
  so one panel drives all backends.
- **Designed-but-not-built:** an `IRammsRobotBackend` RammsCore UINTERFACE
  (control-plane seam) to delete Newton's reflection-scrape and dedupe the two
  IK / two teleop implementations. Never implemented (breaking public API).

## 3. Open / unresolved problems carried in the hand-off

1. **Inert angular constraint DOFs on floored-mass gripper links** — *the*
   blocking mechanism problem; the inertia-conditioning experiment was never run
   to conclusion.
2. **Asymmetric limit windows** — MuJoCo rests *on* its stops; symmetric windows
   let the four-bar fall past a toggle singularity.
3. **`springref` preload** — MuJoCo's spring_link tensions toward +150°, not the
   spawn pose; Chaos spring drives target the spawn pose.
4. **0.15 kg Chaos mass floor breaks spring equilibria** tuned for 12–22 g links
   (worked around with per-body inflation — a patch on a patch).
5. **Rear-suspension / front-aux closure fold** — declared to need offline
   kinematic analysis (solve loop positions numerically vs mjData), not more
   constraint knobs.
6. **Wheel command-semantics divergence** (rad/s vs torque-fraction) — deferred
   to the control seam.
7. **Rest-bounce / parked pose** — traced to model geometry; a Blender
   `dojo_ref` pose fix. Real per-part `dojo_mass` + gas-spring specs remain
   Blender FILL-MEs.
8. **Newton bridge 1/10-speed** — synchronous one-step-per-round-trip;
   DEALER/ROUTER pipelining partially landed, needs sign-off; worker `set_state`
   wiring is the next Newton item.
9. **URLab dropped `armature`/`frictionloss` on import** (pre-beta) — worked
   around with a fixup script; **re-check whether beta fixed this.**

## 4. What maps onto URLab-beta, and how

The *tuning / solver / harness* learnings (§1.2, §1.3, §1.7–§1.11) are
engine-version-stable and **directly portable**. The *import / scale /
generator* learnings (§1.1, §1.6, and the whole rig generator) must be
**re-seated on the component tree** — mostly to *design the scale bug out*
using `MjBody`-transform frame derivation as the invariant, rather than patch
it. §1.4/§1.5 (inertial baking, OBJ-from-GLB) are backend-neutral and become
*more* valuable under "components are the model." The Newton `CustomStepHandler`
design targeted URLab's public seams and maps conceptually unchanged, **but** it
was written pre-beta — beta "deletes the XML compile path," so the compiled-model
serialization handshake needs re-checking against ProtoSpec.

## 5. Proposed phased plan

**Phase 0 — decide the target shape.** Resolve **D1** and **D2** above. This is
the highest-leverage step; several later phases exist only to serve a "keep
Chaos" answer.

**Phase 1 — backend-neutral, no-regret ports** (valuable regardless of D1):
- Port `bake_inertials.py` + OBJ-from-GLB restore into the compose scripts;
  verify URLab-beta ingests baked `<inertial>` onto `MjBody`.
- Port the harness/runbook truths (§1.10, §1.11) into `main`'s docs/scripts:
  spectator-only headless map, result-file pattern, command-line-override
  bisect parsing, and the SC-provider / registry-cache / play-mode / save-materials
  / mid-save-kill rules.
- Re-check §3.9 (`armature`/`frictionloss` drop) and §1.9 (exporter ranges ≠
  real travel) against beta.

**Phase 2 — port the probe / validate / command surface** (enables all
measurement, useful even MuJoCo-only): `Ramms.Validate/Probe/Panel/Joint`
reading a `main`-side switch component; the unified `SetJointCommand` +
slew/clamp/panel-teleop layer; the scale-free body-transform separation metric
as the acceptance gate.

**Phase 3 — (only if D1 = keep Chaos) re-seat the rig generator on the component
tree.** Rebuild `GenerateChaosRig` to walk URLab-beta `MjComponent`s, **emit
unit-scale meshes** and record `ConstraintBodyFrames` from the start (designing
out §1.1/§1.6). Port the solver-behavioral runtime verbatim: scale-to-1 frame
re-derivation, pins-without-projection, virtual couplers, wheel velocity-hold +
omniwheel material split, mass floor. **Decide the gripper strategy first**
(§3.1): (i) fund the inertia-conditioning experiment to a conclusion, (ii)
accept virtual-coupler kinematic drives for the gripper four-bar too, or (iii)
declare the Chaos gripper cosmetic and keep its dynamics MuJoCo-only.

**Phase 4 — Newton-behind-URLab, re-validated on beta** (largely independent):
re-verify `CustomStepHandler` against beta's ProtoSpec / deleted XML-compile
path; land the DEALER/ROUTER pipelining sign-off and worker `set_state`.
**[ASK]** whether Newton is in scope now.

**Phase 5 — the `IRammsRobotBackend` control seam** (only if multiple backends
coexist long-term; breaking `RAMMSCORE_API`, needs team sign-off per CLAUDE.md).

**Acceptance gate to carry over:** all closure pins ≤0.03 cm at rest, upZ 1.00,
zero base drift, drivers in-window — measured headless via `Ramms.Probe` on a
spectator-only map. The right definition-of-done for any Chaos port.

---

## Key references (`origin/feat/newton-improvements`, RammsMujocoSupport @ `7d01cbca`)

- `doc/physics_backend_unification_plan.md` (§6.21 = pin-leak root cause;
  hand-off header = state at handoff)
- `Plugins/RammsMujocoSupport/.../RammsBackendSwitchComponent.{h,cpp}`
  (`:509-520` scale-to-1, `:569-592` projection-off, `:96-135` CLI bisect
  overrides, `:786` `TickCouplers`)
- `.../RammsMujocoSupportEditor/Private/RammsRigLibrary.h` (generator surface)
- `.../RammsJointPanel.cpp` (`Ramms.Validate/Probe/Panel/Joint`)
- `mujoco/bake_inertials.py`, `compose_mebot_gen3.py`, `compose_mebot_scene.py`
- `doc/dojo_asset_pipeline.md`, `doc/rammp_robot_pipeline.md`
- Engine anchor: `UPhysicsConstraintComponent::UpdateConstraintFrames` /
  `GetConstraintScale` (`PhysicsConstraintComponent.cpp:578`)
