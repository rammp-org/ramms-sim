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
