# RammsWorldGen

Seed-driven generation and randomization of pedestrian / wheelchair
environments for RAMMS, built on UE 5.8 PCG: street grids with sidewalks,
curb ramps and crosswalks; building shells with level, stepped and ramped
entrances; street furniture and the hazards that narrow a route; suburban
lots, lawns and parks; and indoor layouts with doors, thresholds and
furniture. Every world comes with a **ground-truth manifest** that says where
the routes are, how wide they really are, and which features break the
accessibility profile — so an episode knows which curb, door or A-frame is
the hard one.

```
preset (params + palette + profile + graph)  ──►  ARammsWorldGenerator (seed)
                                                        │  PCG graph
          Street Network ─► Subdivide Lots ─► Building Massing
                 │                │
                 │                └─► Park Layout ─┐
                 └─► Hazard Placer ◄───────────────┘
                          │
   Primitives (ISM cubes + materials)   Props (Fab meshes)   Pieces (ARammsProcPiece actors)
                          └──────────────── Manifest ──────────────────┘
                                                        │
                                              FRammsWorldManifest (JSON)
```

The five example levels (`Content/Maps/Gen/Map_Gen_*`, built by `Scripts/worldgen/build_levels.py`):

| Downtown (seed 7) | Suburban (seed 11) | Park (seed 3) |
|---|---|---|
| ![](Docs/images/Map_Gen_Downtown.jpg) | ![](Docs/images/Map_Gen_Suburban.jpg) | ![](Docs/images/Map_Gen_Park.jpg) |

| Indoor home (seed 5) | Office (seed 2) |
|---|---|
| ![](Docs/images/Map_Gen_Indoor.jpg) | ![](Docs/images/Map_Gen_Office.jpg) |

## Contents

- [How it fits together](#how-it-fits-together)
- [Building](#building)
- [First run](#first-run)
- [Using it](#using-it)
  - [In the editor](#in-the-editor)
  - [From Python](#from-python)
  - [From an AI assistant (MCP)](#from-an-ai-assistant-mcp)
  - [At runtime](#at-runtime)
- [The manifest](#the-manifest)
- [Parameters](#parameters)
- [Extending](#extending)
- [Design notes and limits](#design-notes-and-limits)
- [First-compile checklist](#first-compile-checklist)

## How it fits together

| Layer | What | Where |
|---|---|---|
| **Data assets** | `URammsWorldPreset` (scene kind, params, palette, profile, graph), `URammsWorldPalette` (semantic slots → Fab meshes / materials / actor classes), `URammsAccessibilityProfile` (ADA thresholds + the ranges used to break them on purpose) | `Source/.../Public/RammsWorld*.h`, instances under `/Game/WorldGen/` |
| **Generator** | `ARammsWorldGenerator`: owns the `UPCGComponent`, a seed, a preset; flattens preset + profile + per-instance overrides into `FRammsWorldGenParams`; `Regenerate()` / `Randomize()` / `Cleanup()`; builds the manifest after generation; `PlacePlayerStart()`; `ExportManifest()` | `RammsWorldGenerator.h` |
| **Procedural pieces** | `ARammsProcPiece`: a GeometryScript dynamic mesh whose dimensions decide usability — curb ramps with flares and detectable-warning strips, curbs, steps, ramps with landings and edge protection, walls with door openings, door leaves and thresholds, bollards, planters, low-poly trees and shrubs. Spawned by PCG's Spawn Actor with every property mapped from a same-named point attribute. Complex-as-simple collision. | `RammsProcPiece.h` |
| **PCG nodes (C++)** | `Ramms: Street Network`, `Subdivide Lots`, `Building Massing`, `Park Layout`, `Hazard Placer`, `Indoor Layout`, `Manifest`. Deterministic by seed. They emit *oriented points with attributes*; stock spawners do the placing. | `Public/PCG/*.h` |
| **Graphs** | `PCG_Streets` (downtown, suburban, park) and `PCG_Indoor`, **built from code** by `ramms_worldgen.graphs` so they are reviewable and reproducible. | `/Game/WorldGen/Graphs/` |
| **Python** | Graph builder DSL, palette/preset builders, example-level assembly, MCP toolset | `Content/Python/ramms_worldgen/` |

The one wiring rule: each custom node's overridable properties are named
exactly like the members of `FRammsWorldGenParams`, and the graph feeds a
single **Get Actor Property (Self, `Params`)** attribute set into every
node's **Overrides** pin. Adding a parameter is: add a member to the struct,
add a same-named `PCG_Overridable` property to the node that uses it, done.

Points carry three families of attributes:

- **Spawner inputs**: `Mesh` (soft path) and, for primitives, `Material`
  (slot-0 override). Primitives are `/Engine/BasicShapes/Cube` instances
  scaled to size, which is how roads, sidewalks, floors, building shells,
  windows and crosswalk bars are drawn with the Megascans surface materials.
- **Piece properties**: `KindId`, `SizeX/Y/Z`, `Rise`, `Slope`, `FlareSlope`,
  `StepCount`, `OpeningWidth/Offset/Height`, `LandingSize`, `WarningDepth`,
  `MaterialPath`, `MaterialPath2` — the Spawn Actor node maps each onto
  `ARammsProcPiece` and then calls `Rebuild()`.
- **Manifest**: `ManifestKind`, `ManifestSubtype`, `bCompliant`, `IssueId`,
  `Measure`, `Threshold` — read by the Manifest node for mesh-spawned
  features, and reported by the pieces themselves for actors.

## Building

The plugin is a Runtime module (`RammsWorldGen`) depending on `PCG`,
`GeometryScriptingCore`, `GeometryFramework`, `GeometryCore`, `Json` and
`JsonUtilities`. The `.uplugin` enables `PCG`, `GeometryScripting` and
`PythonScriptPlugin`; the project `.uproject` enables `RammsWorldGen`.

```powershell
$UE = "C:\Program Files\Epic Games\UE_5.8"
& "$UE\Engine\Build\BatchFiles\Build.bat" RammsEditor Win64 Development -Project="$PWD\Ramms.uproject" -WaitMutex
```

Reflection changes (any `UPROPERTY`/`UCLASS` here) need the full build, not
Live Coding — same rule as the rest of the project.

## First run

1. Build and open the editor. The Output Log should show
   `[RammsWorldGen] registered RammsWorldGenToolset with the toolset registry.`
2. Make sure the Fab packs are present (`Content/Fab/MoStreetProps`,
   `Megascans`, `FreeFurniturePack`, `RestaurantScene`, `Stairs_Street`,
   `adoquines_levantados_alcorque`). They are not committed; see the project
   README. Missing packs only leave palette slots empty (procedural stand-ins
   take over), they do not stop generation.
3. Build the assets from code:
   ```
   python Scripts/editor_remote_exec.py --file Scripts/worldgen/build_assets.py
   ```
   or, in the editor's Python console, `import ramms_worldgen.build_all as b; b.build("all")`,
   or ask the assistant for `worldgen_build_assets`. This writes
   `/Game/WorldGen/Palettes/PAL_Default`, `/Game/WorldGen/Profiles/PROF_ADA`,
   `/Game/WorldGen/Presets/PRE_*`, and `/Game/WorldGen/Graphs/PCG_Streets` +
   `PCG_Indoor`. The report lists every palette slot it could not fill.
4. Build the example levels:
   ```
   python Scripts/editor_remote_exec.py --file Scripts/worldgen/build_levels.py
   ```
   Creates `/Game/Maps/Gen/Map_Gen_Downtown`, `Map_Gen_Suburban`,
   `Map_Gen_Park`, `Map_Gen_Indoor`, `Map_Gen_Office`, `Map_Gen_MainStreet` and
   `Map_Gen_Store`, each with lights, a
   ground slab, a `WorldGenerator`, the `BP_MebotGameMode`, and a PlayerStart
   on the widest compliant route. Generation is asynchronous: the level is
   saved when the log says `level ... generated`.

## Using it

### In the editor

Drop a **Ramms World Generator** into any level, set **Preset** and **Seed**,
click **Regenerate**. **Randomize** draws a new seed; **Cleanup** removes
everything it spawned; **Place Player Start** moves the PlayerStart to the
manifest's suggested pose; **Export Manifest** writes the JSON under
`Saved/WorldGen/`. The green box is the site; the generator must sit at ground
level (sidewalk level = its Z). Yaw is ignored — sites are axis-aligned.

Per-instance tweaks go in **Param Overrides** + **Override Keys** (only the
listed members apply, so preset updates still flow through). Everything else
is edited on the preset, the palette, or the profile.

The PCG graphs are ordinary graphs: open `PCG_Streets` to see the wiring, add
stock nodes between ours, or make a copy and point a preset at it. If you
re-run the graph builder your edits to those two assets are overwritten —
copy first.

### From Python

```python
import ramms_worldgen._helpers as H
gen = H.find_generator()                 # the generator in the open level
gen.set_editor_property("seed", 42); gen.regenerate()
# ... wait until not gen.is_generating() ...
m = H.manifest_to_dict(gen)              # routes, features, suggestedStart
bad = [f for f in m["features"] if not f["bCompliant"]]
```

`ramms_worldgen.levels.build_level("downtown", seed=7)` makes a level;
`ramms_worldgen.build_all.build("graphs")` rebuilds just the graphs.
`Scripts/worldgen/regenerate.py` regenerates the open level with a random seed.

### From an AI assistant (MCP)

The in-editor MCP server (see the project README) lists the toolset
`RammsWorldGenToolset`:

| Tool | Purpose |
|---|---|
| `worldgen_status` | Generators in the level: preset, seed, generating?, feature/route/issue counts |
| `worldgen_list_presets` | The presets and what each produces |
| `worldgen_generate` | Regenerate; optionally switch `preset` and `seed` |
| `worldgen_randomize` | New random seed |
| `worldgen_cleanup` | Remove what a generator spawned |
| `worldgen_manifest` | The manifest; filter by `kind` or `only_non_compliant` |
| `worldgen_get_params` / `worldgen_set_param` | Read / override one parameter by name (and regenerate) |
| `worldgen_export_manifest` | Write the manifest JSON |
| `worldgen_place_player_start` | PlayerStart to the suggested start |
| `worldgen_build_assets` | Rebuild palette / presets / graphs from code |
| `worldgen_build_level` | Create an example level (`downtown`, `suburban`, `park`, `indoor`, `office`, `mainstreet`, `store`) |

A typical session: `worldgen_list_presets` → `worldgen_generate(preset="PRE_Downtown", seed=7)`
→ poll `worldgen_status` → `worldgen_manifest(only_non_compliant=true)` →
`begin_pie` (RAMMS toolset) → drive the chair at a hazard.

### From outside the engine (Remote Control / ramms-tools)

`URammsWorldGenBridge` is a function library made for the Remote Control
API: every call takes and returns strings and numbers, generators are
addressed by actor path (or name / label; `""` = the first one), presets and
maps by asset path or short name. The CDO path is
`/Script/RammsWorldGen.Default__RammsWorldGenBridge`.

| Function | Purpose |
|---|---|
| `GetWorldInfo` | JSON: current map, editor vs play world, generator count |
| `FindGenerators` / `ListPresets` / `DescribePresets` / `ListGeneratedMaps` | Discovery |
| `SpawnGenerator(Preset, Seed, Location, Label)` | Spawn a generator pointed at a preset |
| `SetPreset`, `Generate(Path, Seed)`, `Randomize`, `Cleanup`, `IsGenerating`, `PlacePlayerStart` | Lifecycle |
| `GetStatusJson` | Cheap poll: preset, seed, generating?, counts, suggested start |
| `GetManifestJson` / `ExportManifest` | The manifest |
| `GetParamsJson` / `SetParamsJson` / `ClearOverrides` | Parameters as a JSON object of name → number |
| `OpenMap` | Load a map in the editor, or travel to it in a game |

[ramms-tools](https://github.com/rammp-org/ramms-tools) wraps this as
`ramms_tools.worldgen.WorldGen` and the `ramms-worldgen` CLI:

```bash
ramms-worldgen presets
ramms-worldgen generate --preset PRE_Downtown --seed 42 --set HazardDensity=6
ramms-worldgen manifest --issues
ramms-worldgen batch --preset PRE_Park --seeds 1-50 --out data/park
```

```python
from ramms_tools.worldgen import WorldGen
gen = WorldGen().generator()
gen.generate(seed=42)
m = gen.manifest()            # routes, features, issues, suggested start — parsed
```

This is the intended path for episode runners, dataset builders and any
program that is not running inside the editor; the Python module above is
for editor-side tooling and the MCP toolset for assistants.

### At runtime

`ARammsWorldGenerator` is a runtime actor and the nodes are runtime
elements, so a packaged or `-game` sim can regenerate per episode:
`RegenerateWithSeed(N)`, wait for `OnWorldGenerated(Manifest)`, teleport the
pawn to `Manifest.SuggestedStart`. `bGenerateOnBeginPlay` /
`bRandomizeSeedOnBeginPlay` cover the simple case. Generation is asynchronous
(PCG schedules it over frames); `IsGenerating()` is the poll.

The only editor-only parts are the Python builders and the MCP toolset.

## The manifest

`FRammsWorldManifest` (also the JSON): `seed`, `preset`, `sceneKind`,
`bounds`, `suggestedStart`, then

- `routes[]`: `name`, `points[]` (polyline, cm), `nominalWidth`,
  `minClearWidth` (after hazards), `bCompliant`.
- `features[]`: `kind` / `subtype`, `location`, `rotation`, `size`,
  `bCompliant`, `issue`, `measure`, `threshold`.

Kinds and the issues they can carry:

| Kind | Subtypes | Issue |
|---|---|---|
| `CurbRamp` | Standard, TooSteep, NoDetectableWarning | SlopeTooSteep |
| `Crossing` | MissingCurbRamp | MissingCurbRamp |
| `Entrance` | Level, SteppedWithRamp, SteppedSteepRamp, SteppedNoRamp | StepAtEntrance, SlopeTooSteep, DoorTooNarrow, ThresholdTooHigh |
| `Door`, `Threshold` | Standard, Narrow, RaisedThreshold, High/Low | DoorTooNarrow, ThresholdTooHigh |
| `Ramp`, `Step` | Standard, TooSteep / WithRamp, NoRamp | SlopeTooSteep, StepAtEntrance |
| `Hazard` | AFrame, Scooter, BinOut, Cafe, Barrier, Upheaval, or a furniture slot indoors | ClearWidthBelowMinimum, VerticalChangeTooHigh, ObstacleInRoute |
| `Building` / `House` | house footprint | — |
| `Prop`, `Furniture`, `Decor`, `Tree`, `Shrub` | palette slot | ClearWidthBelowMinimum when a prop spills out of the furniture zone |
| `Surface` | Cobbled | SurfaceUneven |
| `Room` | Living, Bedroom, Office, Meeting, Kitchen, Dining, Bathroom, Corridor, Shop, Storage | — |
| `Aisle` | Standard, Narrow (shop floors; measure = aisle width) | ClearWidthBelowMinimum |
| `Path`, `Driveway`, `Vehicle`, `CarPark` | FrontWalk / Concrete / Parked, Driveway, CarPark / SingleRow, DoubleRow, MultiRow | — |
| `CheckoutLane` | Standard, Narrow (store checkouts; measure = lane width) | ClearWidthBelowMinimum |
| `Tree`, `Shrub`, `Prop` (lots) | StreetTree, Canopy / Foundation / Mailbox, StreetLight | — |

`measure` / `threshold` are the number that decided it (slope as rise/run,
widths and heights in cm) and what it was compared to.

## Parameters

All in cm unless noted; defaults are the 2010 ADA numbers where one applies.
`NonCompliance` (0..1) is the single dial: 0 gives a fully accessible world,
and above 0 each feature independently rolls to be generated in one of its
non-compliant forms, always recorded in the manifest. The suburban preset
runs it at 0.2, the office at 0.1.

| Group | Parameters |
|---|---|
| Site | `SiteSizeX/Y`, `NonCompliance`, `Palette` |
| Streets | `BlockSizeMin/Max`, `RoadWidth`, `SidewalkWidth`, `FurnitureZoneWidth`, `PlantingStrip` (1 = the furniture zone is a grass strip), `CurbHeight`, `StreetJitter`, `StreetDropout`, `MidblockCrossingChance`, `CrosswalkWidth`, `ParkFraction`, `ParkingDensity`, `DecalDensity` (cracks, potholes, patches, stains per 100 m) |
| Buildings | `LotWidthMin/Max`, `SetbackMin/Max`, `FloorsMin/Max`, `FloorHeight`, `LotCoverage`, `EntranceStepChance`, `EntranceRampChance`, `WindowSpacing`, `FacadeStyles`, `RearParkingChance` |
| Hazards | `PropDensity`, `HazardDensity` (per 100 m), `TreeSpacing`, `CanopyChance` (big old trees, closer together), `StreetLightSpacing`, `HazardIntrusionChance` |
| Accessibility | `MinClearWidth`, `PreferredClearWidth`, `RampMaxSlope`, `MaxCrossSlope`, `CurbRampFlareSlope`, `DoorClearWidth`, `DoorThresholdMax`, `VerticalChangeMax`, `LandingSize`, `DetectableWarningDepth` |
| Suburban / park | `LawnLots`, `YardTreeChance`, `DrivewayChance`, `DrivewayWidth`, `FrontBoundaryChance`, `PathWidth`, `FoliageDensity`, `GrassDensity` (grass clumps per m^2 on lawns, strips and parks) |
| Indoor | `RoomSizeMin/Max`, `CorridorWidth`, `CorridorChance`, `WallThickness`, `WallHeight`, `DoorWidthMean/Std`, `ThresholdChance`, `FurnitureDensity`, `OfficeFraction`, `RetailFraction` |

## Extending

- **New assets**: add names to `palettes.py` (`MESH_SLOTS`, `MATERIAL_SLOTS`)
  and rebuild the palette, or edit `PAL_Default` by hand. Footprints and
  heights are read from mesh bounds and used for clearances; `LocationOffset`
  puts the mesh's lowest point on the ground. A pack with trees or doors goes
  in the `Tree` / `Shrub` / `DoorActor` slots; the procedural stand-ins stop
  being used as soon as a slot is filled. Furniture and street props are
  normalised to real-world heights per slot (`SLOT_HEIGHTS`); whole houses go
  in the `House` slot and replace the shell on set-back low-rise lots.
- **Ground surfaces**: `surfaces.py` builds world-aligned materials
  (`M_RammsAsphalt`, `M_RammsSidewalk`, `M_RammsConcrete`, `M_RammsGrass`,
  `M_RammsLawn`, `M_RammsPath`, `M_RammsDirt`) from the packs' tileable
  textures. UVs come from world XY at a real tile size, so stretched road
  cubes and huge ground slabs tile correctly; repetition is broken by a second
  sample at another scale (or a variant texture set) blended by a
  low-frequency mask, plus macro brightness variation. Edit `SURFACES` to swap
  textures or tile sizes; the Mat.* slots prefer these materials.
- **Shelving**: `Store.Shelf` entries record their board heights
  (`ShelfHeights`: vertex clusters holding at least 4% of the mesh's vertices,
  plinth and top cap excluded) and face the open side away from the back panel
  (the end of the short axis with the denser vertex band). Shop floors stock
  every board below 175 cm with `Store.Product` meshes that fit under the next
  board.
- **Composite entries**: a palette mesh entry with `Parts` (mesh + relative
  transform + materials) instead of a `Mesh`. `palettes.COMPOSITE_SLOTS`
  captures blueprint houses (Residential Houses - Modular Pack, ~300 child
  actors each) by spawning them once at build time, measuring the union
  bounds and facing them by their front door. These houses have a front and a
  back entrance, so each `EntranceDoor` is scored (the wide front door counts
  for it, a `*_Back` frame against it, nearby porch parts and a front garage
  add a little) and the front is the direction of its porch stairs. The entry
  records `EntranceOffsetY` / `EntranceRise` (front walk and manifest records
  meet the real door; no procedural steps or door are added) and, when a
  garage door is on the front, `GarageDoor` / `GarageWidth` (the driveway runs
  up to it). The massing node spawns the parts as instanced modules
  (`WriteComposite`), so a street of them costs nothing.
- **Facade kits**: `Facade.<style>.GF` / `GFDoor` / `GFCorner` / `Win` /
  `WinTop` / `WinCorner` mesh slots plus the generic `Facade.Top`,
  `Facade.TallTop` (+ `Corner`) and `Facade.WinCorner`, filled by
  `palettes.build_facade_slots` from the AmericanCityPacks module names. Each
  entry records its material slot categories (`MaterialSlots`); the
  `Facade.Mat.<Category>` slots hold the material sets (`Bricks`, `Windows`,
  `Frame`, `Concrete`, `Ornament`, `Shop`, `Metal`, `Roof`...) that Building
  Massing picks from once per building and writes as `Material0..7`
  attributes for the module spawner. Modules have their pivot at the start of
  the run, the facade plane on local Y=0 with the exterior toward +Y, and the
  L1 corner pieces turn the next face toward local −Y. Node settings
  `bFacadeModules` (default on) and `FacadeStyles` (`dt01,dt02,dt03`) choose
  the kits; a lot narrower than 5 m, or a style that cannot tile it, falls
  back to the cube dressing.
- **New preset**: add an entry to `presets.PRESETS` (or duplicate an asset),
  point it at a graph.
- **New parameter**: `FRammsWorldGenParams` member + same-named
  `PCG_Overridable` property on the consuming node.
- **New node**: derive from `URammsPCGSettingsBase` / `FRammsPCGElementBase`,
  emit through `FRammsPointWriter` (`WriteCube`, `WritePaletteMesh`,
  `WritePiece`, `WriteManifest`), add it to `graphs.py`.
- **New piece kind**: add to `ERammsProcPieceKind`, a `Build*` in
  `RammsProcPiece.cpp`, and emit it from a node.

## Streets and yards

- **Curbs and ground**: every surface material projects its texture by the
  dominant normal axis (XY on tops, YZ / XZ on faces), so curb faces, slab
  edges and stand-in building shells tile at real size instead of smearing.
  Curbs use their own finer concrete (`Mat.Curb`); stand-in houses use
  world-aligned brick / siding (`Mat.Facade`, `Mat.FacadeAlt`).
- **Entrances**: steps rise from the street side to the door; a ramp, when
  there is room for one, runs along the facade beside the steps with its
  landing against the top step (it never crosses the sidewalk).
- **Planting strips** (`PlantingStrip`): the furniture zone becomes grass.
  Each house lot dresses the strip in front of it - street trees spaced along
  it, a street light every few lots, grass clumps - around its driveway, whose
  apron continues across the strip and sidewalk to the curb. `CanopyChance`
  turns a block's street into big old trees (`TreeLarge`) closer together.
  Paved streets keep trees in pits, the grate scaled to fit the furniture
  zone; trees are placed by their trunk (measured from the mesh), not the
  canopy's centre.
- **Yards**: foundation shrubs along the house front, flowers by the walk, a
  mailbox at the street end of the walk or driveway, a garage driveway, back
  yard fences, grass clumps (`GrassDensity`) over lawns, parks and strips.
- **Wear**: `Decal` pieces project cracks, potholes, patches, manholes and
  puddles onto roads and cracks / stains onto sidewalks (`DecalDensity`;
  palette `Decal.*` material sets, deferred-decal materials only).

## Indoor furnishing and routes

Walls are finished per room: a 1 cm liner in the room's paint (`Mat.Wall.Paint`,
tinted instances of `M_RammsPaint`), wallpaper (`Mat.Wall.Paper`) or tile below
120 cm (`Mat.Wall.Tile`, bathrooms and some kitchens), cut around doors and
windows, with a skirting board, so the two sides of a shared wall differ.
Floors are picked per room from `Mat.Floor.Wood / Carpet / Tile / Vinyl` and
meet under the wall centre lines (no overlap, no z-fighting). Exterior walls
get windows (frame, sill, mullion and glass in the wall's openings). Doors
are real leaves from `Door.Interior` / `Door.Exterior` (handles included,
turned so the handle is on the free edge), scaled to the opening and standing
open against the casing; casings and frames stand 2 cm proud of the wall so
nothing shares a plane.

A shop floor is laid out like a small supermarket: checkout lanes standing
out from the entrance wall (each lane a `CheckoutLane` record with its
width), baskets and an exit sign by the door, wall freezers along one long
wall, produce tables with crates of fruit and vegetables along the other, a
deli counter across the far end, gondola rows with end-cap displays and a
hanging sign over each aisle, and clutter in the corners.

Rooms are furnished the way a person would arrange them, in groups: a sofa
with its coffee table, armchair and a TV on a stand opposite; a bed with
night tables and lamps; desks in a row along the long wall with a chair at
each; a table in the middle with chairs on every side; a counter of
cupboards in a kitchen; a toilet and bathtub in the bathroom; a picture on
the wall. `OfficeFraction` turns a home (living rooms, bedrooms) into a
workplace (offices, meeting rooms, a break room).

Every piece is a footprint box in its mesh's *facing frame* (the palette
builder detects the front of seating, beds and toilets from where their
upper vertices gather, and stores the footprint and pivot offset in that
frame). A piece is placed only if its box lies inside the room's inner
rectangle, overlaps nothing placed before it, and stays out of every door's
swing and approach strip, so furniture never penetrates a wall, a door or
another piece. The verification pass checks that against the spawned
instances (`collisions` in the report).

Routes are then found through the furnished room on a 10 cm occupancy grid:
a distance transform gives each free cell its clearance, a widest-path
search from each door finds the route with the most room, and the shortest
path at that width is the polyline the manifest carries. Its bottleneck,
doubled, is the route's clear width; the pieces at the pinch point are the
ones reported as `Hazard` / `ObstacleInRoute`. With `NonCompliance` > 0 a
chair, cart or plant is deliberately pulled into an aisle.

## Design notes and limits

- Streets are an axis-aligned jittered grid with pairwise block merges; no
  diagonals or curves yet. Buildings are shells (no interiors); the robot does
  not enter them. Indoor and street worlds are separate presets, not one
  continuous world — a doorway from a street into a generated interior is the
  natural next step (same pieces, a `Doorway` node).
- Flares on curb ramps are rolled slabs, not true warped surfaces; the ramp
  surface itself is exact. Sidewalks are flat (no cross slope); `MaxCrossSlope`
  is carried for the profile but not yet generated.
- Hazard meshes stand in: an info board plays the A-frame, railings play
  barriers, the raised-cobble tree pit plays the heaved slab. Scooters have no
  mesh and use a low planter piece until a pack provides one.
- Trees and shrubs are procedural (a tapered trunk, stub branches and a
  canopy of overlapping spheres in solid foliage / bark materials made by the
  palette builder); a `Tree` / `Shrub` palette slot swaps in real meshes.
  Buildings get the palette's modular facade kits (ground floor with a door
  module, window floors, cornice, corner pieces, one material pick per
  category per building) or, without a kit, storefronts, floor trim,
  cornices, parapets and framed windows; rooftop units come from the
  `RoofUnit` slot; set-back one/two-storey buildings get a house mesh from
  the `House` slot or a gable roof piece. Street parking (`ParkingDensity`)
  puts cars along the curbs. Roads carry a dashed centre line, edge lines and stop
  lines in solid marking materials.
- Generated geometry is Unreal collision. The Chaos backend drives on it
  directly; the MuJoCo / Newton backends only know what URLab has imported, so
  a generated world is not yet visible to them.
- Pieces are one actor each (walls, ramps, doors, trees). A dense downtown
  spawns a few hundred; fine in the editor, and `Collapse` in the Spawn Actor
  node is the lever if it ever matters.
- Pedestrians are not placed by the generator; drop a `RammsCrowdSpawner`
  over the sidewalks as in `Map_CrowdTest`.

## First-compile checklist

The PCG side has been checked against the UE 5.8 engine headers
(`Engine/Plugins/PCG`): pin construction (`EPCGDataType` converts implicitly
to `FPCGDataTypeIdentifier`), the `UPCGBasePointData` write path
(`SetNumPoints` / `AllocateProperties` / value ranges, `EPCGPointNativeProperties::All`),
`FPCGContext::NewPointData_AnyThread`, metadata create/read, `UPCGSplineData::Initialize`,
the component API (`GenerateLocal(bool)`, `CleanupLocal(bool)`,
`GetGeneratedGraphOutput`, `OnPCGGraphGeneratedDelegate`), the settings
virtuals, `PCGE_LOG`, and the graph Input/Output node pin labels (`In` / `Out`,
params pin `Overrides`). `PCGParamData.h` lives at the module root in 5.8,
not under `Data/`, and the includes reflect that.

Not yet checked against headers (engine `GeometryScripting` folder):

| Symptom | Where | Note |
|---|---|---|
| `SetMeshUVsFromBoxProjection` / `AppendSphereBox` / `AppendCylinder` signature | `RammsProcPiece.cpp` | stable since 5.1; float casts are in place |
| `UDynamicMeshComponent::UpdateCollision` / `SetComplexAsSimpleCollisionEnabled` arity | `RammsProcPiece.cpp: ApplyCollision` | |
| C4244 double→float elsewhere | anywhere flagged | add a cast |

Python-side risks fail loudly at build time: `_graph.py` validates every pin
label against the live node and raises with the labels that exist, and the
palette builder reports every slot it could not fill.
