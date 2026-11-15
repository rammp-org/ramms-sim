# WorldGen to MuJoCo export (design sketch)

Status: the exact export (Phases 1 to 3) is built, 2026-11-14: see
[What was built](#what-was-built-2026-11-14) and
[Still open](#still-open-after-the-build). The sketch below is kept as it was
reviewed; facts in it were checked against the source on 2026-10-20.
Builds on Thread 3 of
[mujoco_sim_roadmap.md](mujoco_sim_roadmap.md#thread-3--python-scene-generation--conversion-automation),
which should reuse RammsWorldGen for seeded placement instead of a separate
scatter tool.

## Problem

RammsWorldGen levels have Unreal (Chaos) collision only. A robot driven by
MuJoCo through URLab ignores curbs, ramps, steps, walls and props, because
nothing hands that geometry to the MuJoCo spec
([world_generation.md](world_generation.md), "not yet visible to MuJoCo/Newton").
Nothing in RammsWorldGen references URLab today.

## What a generated level contains

| Source | Examples | Collision today |
|---|---|---|
| PCG Static Mesh Spawner (ISM) | primitive cubes (`/Engine/BasicShapes/Cube`), paving, props, facade modules | `BlockAll`. Palette meshes keep their own simple shapes, else complex as simple (triangles); trees get a trunk box (`palettes.py` `_ensure_collision`) |
| PCG foliage spawner | grass, flowers | `NoCollision` (skip) |
| `ARammsProcPiece` actors (a few hundred in dense downtown) | slabs, curbs, curb ramps, steps, ramps, walls, doors, bollards, planters, trees, roofs | GeometryScript dynamic mesh, complex as simple, no simple collision (`RammsProcPiece.cpp` `ApplyCollision`) |

All of it is static: nothing simulates physics, and doors are static leaves
placed already swung open. No physical materials are assigned anywhere, so
friction is the engine default. Ground is a slab plus paving cubes.

Levels are generated in the editor and saved (`Content/Maps/Gen/Map_Gen_*.umap`).
`ARammsWorldGenerator` also has `Regenerate()`, `RegenerateWithSeed(int32)` and
`Randomize()`, and broadcasts `OnWorldGenerated(const FRammsWorldManifest&)`
when done. It regenerates at `BeginPlay` only when `bGenerateOnBeginPlay` is
set (default off, and off in `Map_Gen_MainStreet`).

`Map_Gen_MainStreet` holds 38 curbs, 26 curb ramps and 2 steps as
`ARammsProcPiece` actors, with a 15 cm rise: sidewalks at Z=0, road at Z=-15.

## Why quick-convert does not fit as is

`UMjQuickConvertComponent` reads each `UStaticMeshComponent` on its owner
(trimesh from the body setup, not `AggGeom`) and merges them into one body.
An ISM is read as a single mesh and its instances are ignored. It only emits
mesh geoms, and its OBJ cache is keyed per actor name
(`Saved/URLab/ConvertedMeshes/<ActorName>`), so the same asset placed many
times would be decomposed many times. URLab has no helper that turns
`AggGeom` boxes, spheres or capsules into MuJoCo primitives.

## Proposal

One scene contributor per generated level that emits the whole level as static
geoms on the MuJoCo world body.

**Where it lives.** A component or actor (working name
`UMjWorldGenContributor`) in the `RammsMujocoSupport` plugin, implementing
`IMjSceneContributor`. `GatherSceneContributors` finds any actor or component
implementing the interface, and each contributor spec is attached with its
own prefix via `mjs_attach`. RammsWorldGen stays free of URLab; the MuJoCo
side gains a dependency on RammsWorldGen, as it already depends on RammsCore.
There is no "MuJoCo active" flag today, so a world subsystem in
`RammsMujocoSupport` spawns the contributor when a level has both an
`AAMjManager` and an `ARammsWorldGenerator`.

**What it emits**, per collision source:

1. **`ARammsProcPiece` (Phase 1).** These are what the wheelchair negotiates,
   and every kind is built analytically from `UPROPERTY` sizes, so they can
   report exact parts:

   | Kind | Parts |
   |---|---|
   | Slab, Curb, Column, Planter | 1 box |
   | Step / Stairs | N boxes |
   | Ramp | 4 (rotated slab box, landing, 2 lips) |
   | Wall | boxes around each opening (openings are built, not cut) |
   | Door | 1 to 6 boxes |
   | Bollard | 1 cylinder |
   | Roof | prism hull plus 1 box |
   | CurbRamp | center wedge plus warning-strip box. The side flares have twisted tops and are not exactly convex: approximate with about 2 wedges each (3 to 7 parts total) |
   | Tree, Shrub | approximate (trunk box plus a few blobs) |
   | Mound | not convex: heightfield geom |
   | Patch, Decal | skip |

   Today each `Build*` function writes boxes straight into the mesh through a
   `Box()` helper, so the work is a refactor: builders emit a part list
   (local transform plus box extent, cylinder, or hull vertices), and both
   the mesh and a new `GetCollisionParts(TArray<FRammsConvexPart>&)` accessor
   come from that one list. The accessor is plain data with no URLab types.
2. **ISM instances (Phase 2).** Group by `UStaticMesh`. Per asset, build
   shapes once: `AggGeom` boxes, spheres and capsules become primitive geoms
   (new code, no URLab helper exists), convex elements become mesh assets,
   and triangle-only meshes go through CoACD once, since MuJoCo collides a
   mesh geom as its convex hull. Cache by asset path plus content hash, not by
   actor name. Each instance then emits geoms that reference the shared
   assets with its transform and scale.
3. **Ground.** The slab and paving as boxes from the steps above.
4. **Skipped.** Foliage and anything with `NoCollision`.

**Contacts are cheap.** MuJoCo never tests two geoms that belong to the same
body (it drops pairs with the same weld body, and this filter cannot be
disabled), and every geom on the world body welds to body 0. So static
scenery never collides with itself, with no `contype`/`conaffinity` setup
needed. The broadphase still sorts every geom, so geom count still costs
something (no numeric guidance found; measure it).

**Limiting geom count.** Optional radius around the manifest's
`SuggestedStart` (`FTransform`), or clip to `Bounds` (`FBox`). Log the geom
and mesh-asset counts at compile.

**When it runs.** URLab compiles at `BeginPlay`. For saved levels the
geometry is already there, so that one compile is enough. Runtime
regeneration (`Regenerate()`, or a level with `bGenerateOnBeginPlay` set,
whose order against URLab's compile is not defined) needs a recompile, which
URLab supports mid-PIE: `AAMjManager::CompileModel` reruns every
contributor's `AuthorSceneSpec`, installs the new model transactionally (a
failed compile keeps the old one), and migrates robot qpos, qvel, ctrl and
mocap state. So the contributor binds `OnWorldGenerated` and requests a
recompile.

## Zero-code baseline to try first

URLab already ships `AMjHeightfieldActor`, which raycasts the level's complex
collision inside a box and builds a world-body heightfield geom, cached to
disk. Edges are limited to the grid resolution and there are no vertical
faces (walls become steep slopes), but it needs no new code.

**Tried 2026-10-20, it works.** The test map lives in the optional private
assets plugin, because the only MuJoCo-driven bases are the lift-drives; the
public `BP_RammpGen1_Mujoco` drives its base on Chaos and only the arm is in
MuJoCo. It is a copy of `Map_Gen_MainStreet` with an `AMjManager`, the
lift-drive test game mode, and a
20 m square `AMjHeightfieldActor` at 512 samples (about 4 cm cells, Z span
-40 to +40 cm) centred on the curb ramp at (204, 46). The heightfield sampled
-15 to 0 cm. Driving the lift-drive forward in differential mode from the
road:

- At full input (about 1 m/s) it climbed the ramp: `base_link` rose 14.9 cm
  (the 15 cm rise), pitch went from its resting 4 degrees to 9 on the slope
  (the ramp is 5.7) and back. It later drove off a curb edge and dropped
  15 cm back to the road without trouble.
- At half input it climbed about 40% of the ramp and stalled, with both
  drive wheels at their full commanded torque (9.4 N·m each, about 146 N of
  traction) and nearly stopped. The cause is the robot model, not the
  terrain: see "Why the half-input climb stalls" below.
- Open loop it drifts: it settled with an 8 degree yaw error and wandered
  off the ramp line, so scripted runs need heading control.

**Terrain fidelity.** Tracing the true Unreal surface at 20,000 random
points in the box and comparing it with the heightfield as MuJoCo sees it
(linear between samples): 99.8% of points are within 0.5 cm, and the ramp
profile is within 0.4 cm. The only error is at vertical curb faces, where
the 15 cm step becomes a slope one cell (3.9 cm) wide, about 75 degrees.
A wheel meeting that slope is pushed up, which a real vertical face does not
do, so curb-climbing results on a heightfield will be optimistic.

**Chaos reference.** There is no Chaos lift-drive, so the public RAMMP Gen1
(Chaos base) ran the same ramp with the same open-loop commands. It is a
different robot and goes about twice as fast per unit of input, so compare
at matched speed:

| Run | Road speed | On the ramp |
|---|---|---|
| Lift-drive, MuJoCo, half input | 0.46 m/s | slowed to about 1 cm/s at 40% up, stalled |
| RAMMP Gen1, Chaos, quarter input | 0.41 m/s | slowed to about 0.2 m/s, still climbing (14 of 15 cm) when the run ended |
| Lift-drive, MuJoCo, full input | 1.0 m/s | climbed fully |
| RAMMP Gen1, Chaos, half and full input | 0.94 and 1.8 m/s | climbed fully |

Both rose the full 15 cm and pitched up by roughly the ramp angle (MuJoCo
lift-drive +5.5 degrees, Chaos RAMMP Gen1 +4.8). Both lose speed on the slope at
low command, but only the lift-drive stalls, for the reason below.

**Why the half-input climb stalls.** The differential controller sends open
loop torque (input times `MaxTorque`, 20 N·m here), not a speed target, so
half input is half torque. The base weighs 111.8 kg (MJCF and runtime agree),
so the 10% grade alone needs about 109 N, well inside the 146 N available.
The rest is the omni wheels. Live contact forces from the URLab bridge
(`get_contacts`):

| Snapshot | Rear omni wheels: load, friction force, ratio |
|---|---|
| At rest on flat | 73 N and 50 N, about 0 N |
| Driving on flat at 0.46 m/s | 348 N, 259 N, 0.75 (one wheel) |
| Stalled on the ramp | 80 N and 79 N, 55 N each, 0.69 |

A ratio near the 0.9 friction coefficient means the wheel is sliding, not
rolling. The omni wheel axles sit at 30 and 60 degrees to the direction of
travel, so moving forward needs the rollers to slide along the axle, but the
MJCF has no rollers: each omni wheel is a plain geom with the shared 0.9
friction. In differential mode the rear omni wheels still carry load, so they
act as skids whose drag does not fall with speed. On flat that drag only
costs speed. On the ramp, grade plus skid exceeds half-input traction, and
the base stalls.

Fix options, all in the private lift-drive model: model the rollers (small
jointed roller bodies), give the omni contacts anisotropic friction (low
along the axle) through explicit `<pair>` friction, or keep the omni wheels
off the ground in differential mode. Until then, differential-mode runs of
this model under-report climbing ability, while the heightfield
(above) over-reports curb climbing at vertical faces.

So the heightfield is good enough to drive WorldGen streets under MuJoCo
now. Exact parts (Phase 1) still matter for sharp curb edges, walls and
anything needing vertical faces, and for areas larger than one fine grid.

## Phases

0. **Heightfield baseline** with `AMjHeightfieldActor`, no new code.
1. **ProcPiece parts plus ground.** Refactor the builders to emit part lists,
   add the contributor and subsystem, recompile on `OnWorldGenerated`.
   Target: drive the MainStreet curbs, ramps and steps under MuJoCo.
2. **ISM instances.** Per-asset primitives, hulls and cached CoACD.
3. **Friction.** No physical materials exist, so either assign them in
   RammsWorldGen or set friction per piece kind in the contributor.
4. **Movable props.** Opt-in palette tag for dynamic props, emitted as
   free-joint bodies with mass (ties into Thread 3 Phase 2).

## Verification

- Debug overlay drawing the compiled MuJoCo geoms over UE collision, checked
  in each `Map_Gen_*` level.
- Drive the lift-drive base over the MainStreet curbs under MuJoCo and compare
  with the Chaos run and with the Phase 0 heightfield run.
- Compile time and geom count logged per level, with a budget for Downtown.

## Still unverified

- Whether PCG-spawned pieces are transient.
- Packaged builds: CoACD links into runtime builds, but quick-convert reads
  `TriMeshGeometries`, which needs cooked collision data, and the `Saved/`
  cache path was not tested in a package.
- Performance with thousands of static geoms.

## Open questions

1. Is it acceptable for `RammsMujocoSupport` to depend on `RammsWorldGen`,
   or should the contributor live in its own small module?
2. The part-list refactor and `GetCollisionParts` are changes in the
   RammsWorldGen plugin (its own repo), including a new public API. OK?
3. CurbRamp flares: approximate with wedges, or emit the flares as small
   heightfields for exact shape?
4. For levels with `bGenerateOnBeginPlay` set: defer URLab's first compile
   until generation finishes (needs a hook in URLab), or accept two compiles
   at PIE start?

Answers (2026-11-14): 1, yes: `RammsMujocoSupport` depends on `RammsWorldGen`,
which stays free of URLab. 2, yes, as a backend-neutral shape list
(`RammsCollisionShapes.h`) rather than `GetCollisionParts`. 3, height grids (below).
4 is still open (below).

## What was built (2026-11-14)

The user chose the exact export over the heightfield baseline: MuJoCo sees
generated surfaces, curbs, ramps and props as boxes, convex hulls and height
fields, so millimetre lips and curb faces stay vertical steps.

**Shapes (RammsWorldGen, `RammsCollisionShapes.h`).** `FRammsCollisionShape`
is Box, Convex (points), HeightGrid (regular samples, solid to a base), Sphere
or Capsule, in world space with a surface class. `ARammsProcPiece::
AppendCollisionShapes` gives a piece's; `ARammsWorldGenerator::
GatherCollisionShapes(Out[, Filter])` gives the world's (every piece plus the
generator's static meshes), optionally limited to a box or a radius in plan.
Nothing in RammsWorldGen references URLab.

Instead of a part-list refactor, each piece runs its own builder into a scratch
mesh with a capture open, and every primitive the builder appends reports
itself: one code path for the Chaos mesh and the shapes, so they cannot drift.

| Kind | Shapes |
|---|---|
| Slab, Curb, Column, Planter, Steps, Ramp (slab, landing, lips), Wall (pieces around openings, frames, glass), Door (leaf, handles, threshold), Roof soffit, warning strip | boxes |
| Bollard (16-gon), tree trunk and branches (frustums), tree and shrub canopy blobs (sphere-boxes), gable roof (prism), the ramp of a CurbRamp (planar top) | convex hulls of each part's own vertices |
| CurbRamp flares, Mound and hollow | height grids over the mesh's own vertices |
| GroundPrisms (graded roads, sidewalks, panels, potholes, covers, pavers) | a level rectangle along the piece's axes is a box; another planar convex top the hull of it and its footprint; a top that is not planar and convex the mesh's own fan, one prism per triangle |
| Hump and table | a height grid two samples wide (the profile is constant across) |
| Patch | the hull of the disc and its drop to the ground (same top) |
| Decal | none (no collision) |

The ground kinds describe themselves from the properties their builders read
(not through the capture). A piece's scale is baked into its shapes, mirrored
or not; a height grid that the scale mirrors or turns over, or whose mesh it
does not match, is exported as one prism per upward-facing triangle of the mesh
(exact, never a hole).

**Flush neighbours are one solid.** Separate geoms meeting at a seam give a
body crossing it a contact on the far geom's edge whose normal leans sideways:
`SeamContacts` measured 0.28 of a sphere's contact normal (r 5 cm), 0.19 of a
wheel's (r 10 cm) and all of a roller pad's, 2 mm into two flush exported
pavers, a bump a level surface does not have. So a GroundPrisms piece merges
parts with the same surface whose tops lie in one plane (within 0.1 mm) and
whose union is convex into one box or hull, and `GatherCollisionShapes` merges
flush neighbouring boxes (`RammsCollisionShapes::MergeFlushBoxes`: paving and
road cubes tiling a flat area, slabs side by side; the filter's
`bMergeFlushBoxes`). A real lip, a gap or another surface keeps its solids, and
its step. The Chaos mesh keeps its parts as built.

Canopy blobs are sphere-boxes, whose box projection splits some quads inward
(dents of a few centimetres); their edges are now flipped to fold outward when
built, so each blob's mesh is its own hull and the hull export is exact there too.

**Flares as height grids, not wedges.** A flare's top is the twisted surface
`-H u (1 - v)` sampled on the strip's grid (up to 16 x 12 vertices), so the
Chaos mesh is a triangulated saddle, neither convex nor concave. Exact convex
parts would be one prism per triangle (hundreds per flare); two wedges would
change the surface the robot drives on. A height grid over the same vertices
is exact with one geom per flare. MuJoCo splits each hfield cell along one
diagonal, which in Unreal's (mirrored) frame is (i+1, j)-(i, j+1); the flare
and mound meshes now split their cells the same way
(`RammsCollisionShapes::MatchHeightGridDiagonals` flips mesh edges), so the two
surfaces agree inside the cells too, not only at the samples (a mismatch would
have been up to about 4 mm on a 15 cm flare).

**Static meshes.** Per instance, the mesh's simple collision as Chaos builds
it, through the engine's own scaling rules (`FK*Elem::GetFinalScaled`: a box
keeps its axes and scales its extents, a sphere takes the smallest scale): box,
sphere, capsule and convex elements, cached per asset. A complex-as-simple mesh
is exported as the convex hulls of its cooked triangles' connected parts
(`RammsCollisionShapes::AppendComponentHulls`: a table is its top and four legs,
open between them; a part inside a larger part's bounds joins it; at most 64
per mesh), logged once per asset. A part that is itself concave (an L-shaped
wall, a doorway in one welded mesh) is still solid inside its hull; CoACD was
not used (see below). Anything without physics collision (PCG foliage is
`NoCollision`), pawns, articulated stand-ins, anything tagged `RammsDynamic`
(traffic) and actors MuJoCo already converts (a `UMjQuickConvertComponent`)
are skipped; spline meshes and colliding components that are neither static
meshes nor pieces are not exported, logged once per class.

**Surfaces.** From the segmentation label (`Road` is Asphalt, `Sidewalk`
Concrete, `Curb` Curb, `Lawn` Grass, `Hazard.Mud` Mud ...), else a physical
material's name, else the piece kind, else Default.

**MuJoCo (RammsMujocoSupport, `ARammsMjWorldGenContributor`).** A URLab
`IMjSceneContributor` actor: boxes become `box` geoms, hulls `mesh` geoms over
vertex-only `<mesh>` assets shared by content hash, height grids `hfield` geoms
over shared `<hfield>`s, spheres and capsules primitives; a flat hull becomes
a thin box. Positions, rotations and vertices go through URLab's
`FMjPosition3::FromUnreal`, `FMjQuatRot::FromUnreal` and
`URLabAxisConv::UePositionToMj`. Elements are built as their generated classes
(no per-geom preview meshes), in `<frame>`s and `<asset>` sections of 64 (URLab
re-sorts a parent's children on every link), and registered under one
effective-value scope, so authoring stays linear. Geoms are group 3, priority 0,
default solref and solimp, sliding friction per surface (asphalt, concrete,
curb 1.0; brick 0.8; cobble 0.7; grass, dirt, gravel, wood 0.6; metal 0.5;
foliage 0.5; mud 0.4; glass 0.4; water 0.3). `Default` (most static meshes)
and any surface the table does not list take `DefaultFriction`, 1.0. The hard
surfaces and `Default` are 1.0 because the flat slab they replace was (sliding
friction 1.0), so a robot geom at 0.9 (RAMMP Gen2's `collision` class, its drive
links included) still gets 1.0 there. Robot geoms keep their tuning; an
equal-priority robot geom takes the larger friction, so a softer surface lowers a
contact only as far as the robot geom's own friction (Gen2's 0.9 geoms see 0.9 on
grass, cobble or brick; Gen1's 1.0 geoms and the priority-1 omni rollers see no
change anywhere).

`URammsPhysicsEngineSubsystem` adds one contributor per generator when the
level runs on MuJoCo (Engine MuJoCo, or Auto with an `AAMjManager`, which the
log announces), unless `ARammsPhysicsSettings::bMuJoCoWorldShapes` is off or
the level has an `AMjHeightfieldActor` (`ramms.mj.WorldShapes` 0/1/2
overrides). No generator gets a second contributor, and none gets one when the
level already has a contributor with no `Generator` (it exports every piece).
When an exported world has a shape (`SuppliesGround`, which stops at the first
piece or mesh with one) the flat fallback slab is not added. The contributor
recompiles the scene on `OnWorldGenerated` (`AAMjManager::CompileModel`), reuses
its spec for any other recompile, and drops a queued recompile that another
compile already served; `ramms.mj.RecompileWorldShapes` forces one;
`ramms.mj.WorldShapesRadius` (or `ExportRadius`) limits the export around the
suggested start. `ramms.mj.DrawWorldShapes 1|2` draws the compiled geoms (read
back from `mjModel`) over the level. Counts and times are logged per compile.

**Measured** (PIE on MuJoCo): `Map_Gen_MainStreet` exports 1160 geoms and
compiles in 186 ms; the graded downtown exports 7532 geoms and compiles in
7.3 s. Step cost and the curb-crossing comparison are not measured yet.

**Tests.** `Ramms.WorldGen.CollisionShapes.ProcPieces` (every kind, ground
prisms and humps included, pitched, rolled, scaled and mirrored pieces: union
bounds within 1 mm of the mesh, vertical probes within 2 mm of Chaos's trace,
mirrored pieces bounds only), `Ramms.WorldGen.CollisionShapes.InstancedMeshes`
(scaled, rotated engine shapes against Chaos simple collision; excluded
actors), `Ramms.WorldGen.CollisionShapes.ComponentHulls` (a table exports as
its five parts, open between the legs where Chaos is),
`Ramms.MuJoCo.WorldGenExport.MatchesChaos` (`mj_ray` in the compiled model
against Chaos's trace of every piece, ground kinds included),
`Ramms.MuJoCo.WorldGenExport.NoDoubleExport` (one contributor per generator,
none beside one with no `Generator`, quick-converted actors left out) and
`Ramms.MuJoCo.WorldGenExport.SeamContacts` (a sphere, a wheel-like cylinder and
a roller pad swept 2 mm in across where two pavers meet: flush pavers are one
geom and no normal leans over 0.01; at a 6 mm lip the step remains, the sphere's
normal leaning at least 0.4, the wheel's 0.25, the roller pad's 0.9), and in
RammsWorldGen `Ramms.WorldGen.CollisionShapes.MergeFlushBoxes` (a field of flush
boxes is one box; a lip, a gap, another surface or thickness is not).

## Still open after the build

- Step cost with thousands of world geoms, and the curb-crossing comparison
  against the Chaos run and the Phase 0 heightfield run, are not measured.
  Every recompile (a robot spawned, a structural edit) still pays URLab's full
  compile of the world geoms, about 7 s on the graded downtown, even though the
  authored spec is reused; `ExportRadius` is the lever until that is cheaper.
- Two compiles at PIE start for `bGenerateOnBeginPlay` levels (question 4):
  the first compile has no world yet (and no fallback slab when the saved
  level already had pieces), the recompile on `OnWorldGenerated` brings it in.
- Concave parts of complex-as-simple palette meshes are solid inside their
  hulls; CoACD (cached per asset plus content hash) would make them exact.
- Seams that remain. Flush neighbours within one GroundPrisms piece, and flush
  boxes anywhere, are merged (no sideways normal across them in
  `SeamContacts`). Still separate: flush parts whose union is not convex (an L
  of pavers stays two solids; the merge is greedy, pairwise, so a field can end
  as a few convex pieces rather than one), flush hulls in different pieces
  (sloped facets of neighbouring pieces), and hulls against height fields
  (a flare against its ramp). Where a robot geom crosses one of those, MuJoCo
  can still add a contact on the far geom's edge, a small bump; what it does to
  a crossing is not measured. Chaos's mesh keeps the internal walls between
  prisms (one trimesh of closed prisms); whether Chaos bumps there is not
  measured either.
- Packaged builds: the complex-as-simple hulls read `TriMeshGeometries` (cooked
  collision), untested in a package.
- Movable props (Phase 4) and the Newton backend are not started.
