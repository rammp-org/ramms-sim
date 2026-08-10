# RAMMP robot static-parts pipeline (arm + gripper + base)

Goal: export the robot as **static meshes + physics constraints** (like the
dojo furniture pipeline) instead of skeletal meshes, with joint dynamics
(motors, springs, masses) authored in Blender and carried through to
UE / USD / MJCF.

## Annotated source files

- `data\cad\kinova\gen3_6dof.blend` — Kinova Gen3 6DOF arm (`base_link` →
  `link_0..link_6`) + 2F-85-style four-bar gripper (`base` + `link_*_l/_r`,
  loop-closure empties `link_2_3_l/_r`).
- `data\cad\mebot\mebot_3_assembled.blend` — RAMMP base (`chassis` subtree)
  plus embedded copies of the arm/gripper (`.001` suffixes handled).
- Pre-annotation backups: `*.pre_annotate.bak.blend` next to each file.

`data\robot_annotate.py` (copy in `Ramms\Scripts\`) stamps the attributes.
It only writes **missing** properties — hand-edited values always survive
re-runs. Re-run after renaming/adding parts:

    blender <file>.blend --python robot_annotate.py -- --save

## Attribute schema (custom properties on the part objects)

Same `dojo_*` family as the furniture pipeline; joints are defined between
an object and its **parent** in the outliner hierarchy, pivot = the
object's origin (all the gen3 links are modeled that way).

| property                | meaning                                                        |
|-------------------------|----------------------------------------------------------------|
| `dojo_joint`            | `revolute` \| `continuous` \| `prismatic` \| `fixed`           |
| `dojo_axis`             | joint axis `[x,y,z]`, asset-root local frame                   |
| `dojo_pivot`            | root-local override; default = object origin                   |
| `dojo_limits`           | `[lo,hi]` degrees (revolute) / meters (prismatic)              |
| `dojo_mass`             | kg — **0.0 means FILL ME** (importer falls back to auto-mass)  |
| `dojo_motor_torque`     | N·m (revolute) / N (prismatic); 0 = passive                    |
| `dojo_motor_velocity`   | deg/s / m/s; 0 = unlimited                                     |
| `dojo_spring_stiffness` | N·m/rad / N/m; 0 = none                                        |
| `dojo_spring_damping`   | N·m·s/rad / N·s/m                                              |
| `dojo_spring_rest`      | spring equilibrium, deg / m                                    |
| `dojo_friction`         | joint dry friction, N·m / N                                    |
| `dojo_mimic`            | name of the driving joint object; this joint follows it        |
| `dojo_mimic_ratio`      | follower = ratio × driver                                      |
| `dojo_connect`          | (loop-closure empties) name of the OTHER body the joint links  |

## What was stamped vs. what needs your numbers

**Arm** — real-ish defaults from Kinova Gen3 specs (verify): J1/J4/J6
continuous about Z, J2 ±128.9°, J3 ±147.8°, J5 ±120.3° about Y; 32 N·m /
50 °/s on J1–J3, 13 N·m / 57 °/s on J4–J6; per-link masses from the Kortex
URDF; `link_6` (vision/interface) fixed.

**Gripper** — drive knuckles `link_0_l/_r` (±46°, 5 N·m); all other finger
joints mimic the drive knuckle (`link_3` at ratio −1); `link_2_3_*`
empties are the four-bar loop closures (`dojo_connect` → `link_2_*`).
Open/close signs per side are guesses — flip `dojo_limits` /
`dojo_mimic_ratio` signs if a finger moves the wrong way.

**Base (the SIMPLIFIED `mebot` subtree — the working model)** — every part
under the `mebot` root is annotated. Axis/limit conventions (all
**guesses**, please review): suspension/linkage pivots revolute about
lateral Y ±30°; caster wheel swivels continuous about Z; drive wheels
continuous about Y with 20 N·m / 720 °/s motors. `*_rod` parts are
telescoping prismatic joints whose axes were **computed from the geometry**
(parent→child origin direction): `motor_elevator_rod_*` and the
`*_caster_motor_rod`s are motorized linear actuators (400 N / 0.05 m/s
placeholder), `*_dampener_rod`s are passive spring sliders (stiffness /
damping 0.0 = FILL ME). All masses in the subtree are `0.0` = FILL ME —
the annotate run prints the outstanding list each time.

The legacy detailed `chassis` subtree is also annotated (coarser guesses);
ignore or delete those props if that copy is retired. Untouched and
needing consolidation before they can articulate: `dw_left/right_assembly*`
(raw CAD with thousands of MeshInstance empties), the standalone
`mount_arm` / `mount_luci` / `mount_rail` / `rammp_seat` /
`front/rear_caster_assembly` roots, and `mebot_3.blend`.

## Next steps (export/import pipeline)

1. Exporter: walk the parent hierarchy (every `dojo_joint` object = one
   rigid part), join child meshes per part, UCX from the authored `UBX_*`
   boxes where present (fall back to island boxes), origin at joint pivot,
   manifest with joints + motor/spring/mass, USD (UsdPhysics drives) and
   MJCF (`<motor>`/`<position>` actuators, `stiffness`/`damping`,
   `<equality>` for mimics and loop closures).
2. UE importer: constraint per joint (angular/linear drives from motor
   props, spring-damper from stiffness/damping), mimic via constraint
   gearing or runtime component, loop closures as extra constraints.

## Exporter (robot_export.py — working)

`data\robot_export.py` (copy in `Ramms\Scripts\`). Run headless per file:

    ROBOT_ROOTS=base_link,base blender cad\kinova\gen3_6dof.blend --python robot_export.py
    ROBOT_ROOTS=mebot          blender cad\mebot\mebot_3_assembled.blend --python robot_export.py

Env: `ROBOT_ROOTS` (comma list), `ROBOT_OUT` (default
`UE_VAULT_EXPORT\rammp_parts`). Output per root: one FBX per rigid part
(origin at the joint pivot, collision meshes embedded), `<root>.mjcf.xml`
(motors, springs, mimic + closure equality constraints), `<root>.usda`
(UsdPhysics joints + drives), merged `rammp_manifest.json`.

Collision resolution per part (first match wins):
1. **Authored**: meshes named `UBX_/UCX_/USP_/UCP_<part object name>`
   anywhere in the scene are passed through (re-based + renamed to UE's
   `UCX_<rendermesh>_NN` convention automatically).
2. **`dojo_collision` prop**: `cylinder | box | boxes | convex | none`.
3. **Auto**: `continuous` joints (wheels) get a cylinder fitted about
   their `dojo_axis` (radius/height measured from the mesh; UE gets a
   24-seg convex, MJCF/USD get a true cylinder primitive); everything
   else gets a single convex hull (UE) + AABB box approx (MJCF/USD).

`fixed` parts merge into their parent rigid body. Verified: all three
roots reassemble correctly from part FBXs + manifest origins.

TODO next: UE importer (constraints with angular/linear drives from
motor/spring props, mimic gearing, closure constraints); OBJ export for
authored convex shapes in MJCF; consolidate dw_* assemblies.

## MJCF validation findings (2026-08-07, mebot root)

The exported `mebot.mjcf.xml` was validated end-to-end in plain MuJoCo and
Newton's SolverMuJoCo via `mujoco/compose_mebot_scene.py` (which produces the
driveable `mujoco/mebot/mebot_scene.xml`). Raw-export gaps the composer
currently papers over — fold these back into the annotation/exporter:

1. **No self-collision filtering**: the dense CAD boxes interpenetrate and
   internal contacts jam the mechanism solid (~800 kN chassis contact force).
   Exporter should emit `contype/conaffinity` classes or `<exclude>` pairs.
2. **The front/rear "caster" wheels are OMNIWHEELS** — single roll axis,
   exactly as exported (no Z swivel; earlier swivel injection was wrong and
   is removed). The rollers' free lateral slip is approximated with low
   sliding friction (0.05) on the wheel geoms plus **`priority="1"`** —
   without priority, MuJoCo takes the elementwise MAX of the two geoms'
   friction and the floor's default 1.0 silently wins, which is why turning
   stalled. Turn-in-place now works (+135 deg/3 s at half torque in plain
   MuJoCo). Simulating the rollers themselves is future work. If joints are
   ever added to the blend, keep **one joint per body**: newton's MJCF
   importer fuses multi-joint bodies into renamed compound joints
   (`*_ang0/_ang1`), breaking name-based state interchange.
2b. **Visual meshes now exported for MJCF/USD** (2026-08-07 exporter
   update): each part's joined render mesh is written part-local to
   `assets/<part>.obj` and referenced as a non-colliding `group="2"`
   `density="0"` mesh geom (menagerie convention; collision primitives are
   `group="3"`). `density="0"` matters — without it the visual shell
   double-counts into the auto-mass (224 kg -> 506 kg).
3. **Placeholder dynamics stall the drive**: at auto-density masses
   (~224 kg total) and the guessed 20 N.m wheel gear, drive torque cannot
   break caster static friction — turning stalls with everything static.
   Composer uses 60 N.m gear + 0.3 caster friction provisionally; real
   masses (`dojo_mass`) and motor specs are still FILL-ME.
4. **Suspension springs are FILL-ME** (`dojo_spring_*`): passive linkage
   hinges collapse to their limits. Composer adds provisional
   stiffness=20000/damping=500 about the exported rest pose.

Validated behavior (plain MuJoCo, 2 ms, implicitfast): settles static,
drives +3.4 m/3 s straight (+/-2 deg wander), differential-turns ~44 deg/3 s.
Under Newton SolverMuJoCo (GPU) the same scene loads and steps finite but
contact response diverges badly (spin-out during commanded straight
driving) — the known upstream Newton contact-set translation issue; the
wheeled base is a clean quantitative repro for that report
(see Plugins/RammsNewtonPhysics/README.md, Known issues).

### Base + arm composition (2026-08-07)

`mujoco/compose_mebot_gen3.py` rigidly mounts the gen3_2f85 (tracking-base
machinery stripped: free base joint, base_target mocap, base_weld) onto the
MeBot chassis at a provisional `arm_mount` site -> `mujoco/mebot/
mebot_gen3_scene.xml` (nq=65, nu=14, ~233 kg). Validated in plain MuJoCo and
Newton SolverMuJoCo (GPU): settles static, arm holds home while driving, no
topple; both engines agree qualitatively on the drills. Open-loop torque
drive veers (~+95 deg/3 s) because the offset arm mass loads the wheels
asymmetrically — expected; a closed-loop diff-drive velocity controller is
the fix. TODO: surveyed mount transform (ARM_MOUNT_POS is a guess), real
masses/motor specs, then a URLab map for the composed model to run it
in-editor under Newton.

### Materials + artifact split (2026-08-07 late)

- **Materials**: the exporter now emits a `<material name="mat_<part>"
  rgba="..."/>` per part (principled BSDF Base Color, fallback viewport
  color) and assigns it to the visual mesh geom. URLab's importer maps MJCF
  materials onto the UE meshes, so part colors flow Blender -> MJCF -> UE
  and into every MuJoCo viewer. Upgrade path: MJCF `<texture>` assets for
  base-color textures (URLab parses textures already), and extending
  URLab's GLB-sidecar convention (currently flexcomp-only:
  `<mesh>.glb` next to the referenced file wins) to regular mesh assets for
  full PBR — upstream PR candidate.
- **Robot vs scene artifacts**: compose now writes BOTH `mebot.xml` /
  `mebot_gen3.xml` (robot only — **import these into UE maps**) and
  `*_scene.xml` (adds a 40x40 m ground plane — standalone CLI/viewer ONLY).
  Importing a *_scene file into a populated level plants the giant
  invisible plane through the whole map: instant contact explosion and
  local-solver instability (observed as QVEL/QACC NaN warnings within
  ~10 ms). A controlled UE test of the robot-only import (clean map,
  AMjManager + robot + Newton solver) is stable under Newton for minutes
  with ~1 mm resting contact jitter.
- **Testing motors / tuning springs in UE**: every imported actuator is an
  `MjActuator` component — `SetControl(float)` (BlueprintCallable) drives
  it directly (drive_wheel_l/r, the elevator/caster rods, arm joints).
  Joint springs/dampers are per-`MjJoint`-component properties
  (`stiffness` / `damping` / `springref`, override-flag pattern) editable
  in the BP Details panel; they land in the compiled model on the next
  sim start. Authoritative values belong in the blend (`dojo_spring_*`,
  `dojo_motor_*`) or the compose-script constants.

### Loop closures + per-material visuals (2026-08-07 night)

- **The mebot blend had NO closure empties authored** — every `*_rod`
  mechanism chain exported as an open branch, so driving a rod moved
  nothing. Geometric detection (rod tips + all near-contact part pairs,
  `< 3 mm` with the next candidate 15+ mm away) yielded 15 unambiguous
  closures; they are now AUTHORED IN THE BLEND as dojo-schema empties
  (`closure_<host>__<other>`, dojo_joint + dojo_connect, backup at
  `mebot_3_assembled.pre_closures.bak.blend`). Validated: caster motor
  rods rotate their linkages ~20 deg; elevator rods articulate the pivot
  linkage (the seat they lift is not part of the mebot subtree yet — see
  the consolidation TODO above).
- **Exporter `<connect>` anchor bug fixed**: anchors were written in the
  root frame; MuJoCo wants body1-local (bodies are translation-only in
  this exporter, so local = pivot − body1 origin). The gripper closures in
  older exports had the same bug.
- **Per-material visual export**: a part joined from CAD solids carries
  several materials; exporting one OBJ per material group (17 shared
  `<material>`s dedup'd by Blender material name, real principled Base
  Colors) instead of one grey shell per part. Manifest `visuals` is now a
  list of {mesh, material, rgba}.
- **Compose springs narrowed**: provisional stiffness now only on
  `*dampener*` joints (blanket springs were absorbing the 400 N rod
  forces); other linkage joints get light damping. The mechanism sags a
  few cm at settle until real `dojo_spring_*`/mass values are authored.
  Rod slide ranges also deserve review (400 N pushes past the +/-0.08 m
  soft limit).

### Texture baking per material group (2026-08-08)

The exporter now BAKES textures for any material group whose principled
inputs are linked (image or procedural): Base Color (DIFFUSE color-only
pass), Roughness, and Normal, at `ROBOT_BAKE_RES` (default 1024, Cycles
CPU, 16 samples). UV-less CAD pieces get a smart-project unwrap first (the
unwrap lands in the exported OBJ). Baked pieces get a UNIQUE MJCF material
with `<texture>` assets + MJCF 3.x `<layer role="rgb|roughness|normal">`
children (NOTE: the legacy `texture=` attribute is mutually exclusive with
layers — layers only); flat materials stay on the shared-rgba path, so a
flat-color export bakes nothing. Constant-metallic is fine unbaked; LINKED
metallic is skipped with a note (no Cycles bake type). `ROBOT_BAKE_FORCE=1`
force-bakes Base Color for smoke-testing. First real catch: `elevator_body`
and `caster_dampener_rod` carry authored normal maps — 7 normal PNGs now
flow into the MJCF/URLab import automatically.

### Closure transmission fixes (2026-08-09)

"Only the first linkage follows the rod" had three stacked causes, all
fixed:

1. **Default-soft `<connect>`s attenuate ~4x per stage** — a chain of
   closures at MuJoCo's default solref/solimp absorbs the motion before it
   reaches the output link. The exporter now emits `solref="0.005 1"
   solimp="0.95 0.99"` on every closure connect AND mimic joint equality.
2. **Surface-point anchors bind a stiff loop** — the detected anchors sat
   on pin SURFACES (single closest-approach points); with stiff
   constraints those pin-radius errors act as elastic locks (~1.4 deg of
   travel). All 15 closure empties were refined in the blend to
   contact-RING centroids (3-13 mm shifts, i.e. onto the pin axes).
3. **The mechanism lifts the robot** — with the loop properly coupled, the
   annotated 400 N rod placeholder stalls under gravity (verified: full
   free sweep in zero-g). Compose now sets a provisional 2.5 kN rod gear
   (`ROD_GEAR`, leadscrew-class) until `dojo_motor_*` gets real specs:
   under gravity the chassis lifts ~1 cm with rods driven.

Anchor-refinement recipe (for future closures): average ALL cross-part
vertex-pair midpoints within 3 mm around the coarse anchor — the contact
ring of a pin-in-bore centers the anchor on the pin axis.

### Stability + load-path round (2026-08-09 eve)

User-reported: rear rod poorly linked; L/R elevators jitter with growing
oscillation until sim reset. Findings/fixes (all CLI-reproduced first):

1. **Five closures were spurious** (plate-contact detections, not pins):
   the four elevator `dampener_(aux_)link <-> pivot` connects and the rear
   `aux_linkage <-> suspension_arm`. Pairwise-connecting three bodies that
   already share a hinge makes an over-constrained triangle whose anchor
   error drives a solver-fight limit cycle (the observed 2.4 rad
   oscillation). Removed from the blend (`prune_closures`).
2. **Undriven mechanisms collapse and bounce on joint soft-limits**
   (68 rad/s sustained). Leadscrew rods are modeled as POSITION SERVOS now
   (`<position>` kp=5e5, forcerange +/-6 kN*, ctrl = target extension in
   metres — natural control API; holds when idle). Motor trunnion hinges
   get damping 50 (kills the motor+rod pendulum mode).
3. **The elevator 4-bar has a free DOF even with rod length held** — in
   hardware the gas dampener holds it; its true attachment is NOT
   derivable from near-contact geometry (both detected candidates were the
   spurious closures above). STAND-IN: rest springs on the elevator pivots
   (k=1000*) and caster swing arms (k=5000*) hold the chassis at ride
   height. Consequence of the stand-in: chassis stays up (rootZ 0.073),
   turning works (+114 deg/3 s), settle is calm (maxqvel 0.2), but the
   elevator cannot LIFT the full chassis load at 6 kN x ~4 cm moment arm —
   real masses + actuator specs + the true dampener attachment (from CAD,
   not geometry) are needed for seat-lift under load.

Newton sanity: final base+arm artifacts load and settle finite on GPU.

### Hardware-informed round (2026-08-09 night, user input)

User confirmed: the linear actuators are MICRO ELECTRO-HYDRAULIC
(high-force class -> rod servos now kp=1e6, forcerange +/-15 kN*), and the
elevator dampener couples to the pivot on the opposite side of the joint
from the motor rod-link. The dampener_link->pivot closures are RE-AUTHORED
in the blend accordingly (each side; NOT aux_link->pivot, which is plate
contact — adding both recreates the over-constrained triangle).

Load-path geometry measured from the export: the dampener acts through a
~1.8 cm arm about the pivot axis (motor rod-link: ~5.1 cm). Holding
~250 N.m of chassis load through 1.8 cm needs ~14 kN of gas-spring
preload; a linear rest-spring stand-in emulates that preload (pivots
k=1000*, front+rear caster swing arms k=5000*) and the closures are
modeled as compliant bushings (solref 0.02) so the load-bearing constraint
fight (limit-cycle source) stays out.

Validated end state (plain MuJoCo): settle calm (maxqvel 0.22), ride
height held (rootZ 0.073), turn-in-place +118 deg/3 s, caster servos
actuate (+0.15 rad); elevator drive under full load remains weak pending
real masses (`dojo_mass`) + measured actuator/gas-spring specs — the
mechanism itself is verified free in zero-g.

## HOW-TO: author loop closures manually in Blender

The closure empties are the source of truth for every `<connect>` equality
in the MJCF (and USD). One empty = one ball-joint constraint between its
HOST part and one OTHER part, at the empty's world position. Everything the
automated passes got wrong came down to two things you can do better by
eye: put the anchor exactly ON the pin axis, and only author closures where
a physical pin/bushing actually exists.

### Authoring one closure

1. Open `cad/mebot/mebot_3_assembled.blend`. Existing closures are the
   sphere-display empties named `closure_<host>__<other>`, parented under
   their host part — select one to see the pattern.
2. Position the 3D cursor on the pin axis of the joint you're closing:
   - Enter Edit Mode on one of the two parts, hover the pin's bore or
     shaft, select its circular edge loop (Alt+Click), then
     `Shift+S -> Cursor to Selected` — the cursor lands on the circle's
     center, i.e. the axis. (This is the step no heuristic does reliably:
     surface-graze midpoints are off by the pin radius, and under stiff
     constraints a few mm of anchor error rigidly binds the loop.)
3. `Add -> Empty -> Sphere` (spawns at the cursor). Name it
   `closure_<host>__<other>` (name is cosmetic but keep the convention).
4. Parent it to the HOST part (select empty, then host, Ctrl+P ->
   Object). Host = the part whose subtree the empty lives in; the
   constraint links host <-> other, so either side can host — pick the
   part it moves with mechanically (e.g. the rod for a rod-tip pin).
5. Add custom properties (Object Properties -> Custom Properties):
   - `dojo_joint` = `fixed`   (string; marks it for the exporter)
   - `dojo_connect` = `<other part's object name>`  (exact name)
6. Save. Re-run the export + compose pipeline (below). The exporter emits
   `<connect body1=host body2=other anchor=(body1-local pin point)>` with
   stiff solver params automatically.

### Rules learned the hard way

- **Anchor ON the pin axis.** Surface-contact points bind stiff loops
  after ~1 deg of travel.
- **Only close real pins.** Parts that merely pass close (plate faces,
  clearance gaps) must NOT get closures. Symptom of a wrong one: a
  sustained oscillation/jitter that grows — three bodies pairwise
  connected (two closures + a shared hinge) form an over-constrained
  triangle and the solver fights itself. One pin = one closure.
- **One joint per body** if you ever add helper joints: newton's MJCF
  importer fuses multi-joint bodies into renamed compound joints and
  breaks the Newton worker's state mapping.
- A closure is a BALL joint (3 DOF removed). For a planar linkage that is
  enough; don't try to stack two closures on the same pin.

### Current closure inventory (2026-08-09)

In the blend now (10): front caster [motor_rod->linkage,
linkage_arm->linkage_aux, linkage_aux_arm->swing_arm], rear caster
[motor_rod->suspension_arm, aux_linkage->motor_dampener_pivot,
dampener_rod->swing_arm], elevator l/r [motor_rod->rod_link,
dampener_rod->dampener_link, dampener_link->pivot (bushing-softened in
compose)]. Removed as spurious: elevator (aux_)link->pivot plate contacts,
rear aux_linkage->suspension_arm. If the front/rear caster chains are
missing links in reality (user observation), the fix is new empties at the
real pins per the steps above — most likely candidates are wherever the
swing arms/wheel carriers pin to the linkage outputs. To delete a wrong
closure just delete its empty; to move an anchor, move the empty (its
world position IS the anchor).

### Regenerate + verify after editing

From `C:\Users\waemf\data` (PowerShell):

    $env:ROBOT_ROOTS="mebot"
    & "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" -b cad\mebot\mebot_3_assembled.blend --python robot_export.py

Then from the repo root:

    Plugins\RammsNewtonPhysics\Scripts\.venv\Scripts\python.exe mujoco\compose_mebot_scene.py
    Plugins\RammsNewtonPhysics\Scripts\.venv\Scripts\python.exe mujoco\compose_mebot_gen3.py

Quick transmission check — drives each rod and prints which chain joints
moved (save as e.g. `mujoco/mebot/check_chains.py` and run with the same
python):

    import os, numpy as np, mujoco
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    m = mujoco.MjModel.from_xml_path("mebot_scene.xml"); d = mujoco.MjData(m)
    act = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i): i for i in range(m.nu)}
    j = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i): i for i in range(m.njnt)}
    jp = lambda n: float(d.qpos[m.jnt_qposadr[j[n]]])
    for _ in range(3000): mujoco.mj_step(m, d)
    watch = [n for n in j if n and ("caster" in n or "elevator" in n or "swing" in n)]
    b = {n: jp(n) for n in watch}
    for rod in ("front_caster_motor_rod", "rear_caster_motor_rod", "motor_elevator_rod_l"):
        for _ in range(1500):
            d.ctrl[:] = 0; d.ctrl[act[rod]] = 0.08
            mujoco.mj_step(m, d)
        print("==", rod)
        for n in sorted(watch):
            dd = jp(n) - b[n]
            if abs(dd) > 0.01: print("   %-34s %+.3f" % (n, dd))
        b = {n: jp(n) for n in watch}

### About the remaining oscillation

The slow residual oscillation is the provisional-physics stack: auto-mass
links (224 kg total, wrong distribution) + stand-in preload springs + the
bushinged dampener closures. It shrinks as real values land, in this
order of impact: `dojo_mass` per part >> gas-spring preload/rate
(`dojo_spring_*` on the dampener joints) >> hydraulic actuator specs
(`dojo_motor_*`). The stand-in springs live in
`mujoco/compose_mebot_scene.py` (marked `*`) and should be deleted once
the real dampener values are authored.
