# WorldGen to MuJoCo export (design sketch)

Status: draft for review, nothing implemented. Facts below were checked
against the source on 2026-10-20; items still unverified are marked.
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
`Randomize()`, calls `Regenerate()` from `BeginPlay`, and broadcasts
`OnWorldGenerated(const FRammsWorldManifest&)` when done.

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

**When it runs.** URLab compiles at `BeginPlay`, while the generator also
calls `Regenerate()` from `BeginPlay`, and the order between the two is not
defined. Recompiling mid-PIE is supported: `AAMjManager::CompileModel`
reruns every contributor's `AuthorSceneSpec`, installs the new model
transactionally (a failed compile keeps the old one), and migrates robot
qpos, qvel, ctrl and mocap state. So the contributor binds `OnWorldGenerated`
and requests a recompile, which covers both PIE start and runtime
regeneration. Cost: two compiles at PIE start, unless the first compile is
deferred until generation finishes.

## Zero-code baseline to try first

URLab already ships `AMjHeightfieldActor`, which raycasts the level's complex
collision inside a box and builds a world-body heightfield geom, cached to
disk. Dropping one over a MainStreet block should let a MuJoCo robot feel
curbs, ramps and steps today, with edges limited to the grid resolution and
no vertical faces (walls become steep slopes). Worth trying before Phase 1 to
get a reference run and see whether exact parts are needed for the curb work.

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

- MainStreet's actual contents. The `PRE_MainStreet` preset sets entrance
  step and ramp chances, and the streets graph builds curbs and curb ramps,
  but the saved `.umap` was not inspected.
- Whether `BeginPlay` regeneration is skipped for saved levels, and whether
  PCG-spawned pieces are transient.
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
4. Defer URLab's first compile until generation finishes (needs a hook in
   URLab), or accept two compiles at PIE start?
