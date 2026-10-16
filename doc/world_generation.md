# World generation and randomization

RAMMS can generate and randomize the environments it drives through —
downtown streets, suburban blocks and parks, and indoor floor plans — from a
preset and a seed, with a ground-truth manifest of routes, hazards and
accessibility violations for every world. The implementation is the
`RammsWorldGen` plugin (`Plugins/RammsWorldGen/README.md` is the full
reference); this page is the workflow.

## What you get

| Preset | Scene | Highlights |
|---|---|---|
| `PRE_Downtown` | dense urban grid | wide sidewalks with a furniture zone, curb ramps and zebra crossings at every intersection, mid-rise shells with level / stepped / ramped entrances, street trees, benches, bins, lights, A-frames, scooters, cafe seating |
| `PRE_Suburban` | residential | long blocks, narrow sidewalks, set-back houses with stepped porches, lawns, a third of the blocks as parks with paths and trees |
| `PRE_Park` | one park block | loop and cross paths, lawn trees and shrubs, benches, a cobbled segment now and then |
| `PRE_Indoor_Home` | a flat | BSP rooms, furniture against walls and around tables, a few narrow doors and raised thresholds |
| `PRE_Indoor_Office` | an office floor | central corridor with rooms off it, wider doors, desks, filing, whiteboards |
| `PRE_MainStreet` | a small-town main street | narrow storefronts from the small-business facade kits, wide sidewalks, cafe seating, kerbside parking |
| `PRE_Indoor_Store` | a grocery / convenience store | gondola aisles (each recorded as an `Aisle` feature, some below the minimum clear width), wall freezers, checkout, stock room |

Example levels: `/Game/Maps/Gen/Map_Gen_Downtown`, `Map_Gen_Suburban`,
`Map_Gen_Park`, `Map_Gen_Indoor`, `Map_Gen_Office`, `Map_Gen_MainStreet`,
`Map_Gen_Store` — each a lit level with a
`WorldGenerator`, the Mebot game mode and a PlayerStart on the first route.

`NonCompliance` is the dial. At 0 every curb has a compliant ramp, every door
is 81 cm or wider, every hazard leaves 91 cm; above it, features roll to be
broken on purpose and the manifest says which: a 1:7 curb ramp, a missing
one, a stoop with no ramp, a 72 cm door, a 4 cm threshold, a heaved slab, an
A-frame leaving 60 cm.

## Workflow

**Once, after building the plugin** (and after claiming the Fab packs):

```
python Scripts/editor_remote_exec.py --file Scripts/worldgen/build_assets.py
python Scripts/editor_remote_exec.py --file Scripts/worldgen/build_levels.py
```

The first writes the palette (mapping semantic slots like `Bench`,
`Hazard.Upheaval`, `Mat.Sidewalk` to the Fab assets it finds), the ADA
profile, the presets and the PCG graphs under `/RammsWorldGen/`. The
second creates the example levels. Both are also MCP tools
(`worldgen_build_assets`, `worldgen_build_level`).

**Every day**: open a `Map_Gen_*` level, select `WorldGenerator`, change the
seed, **Regenerate**. Or run `Scripts/worldgen/regenerate.py`. Or, through
the MCP server, `worldgen_generate(preset="PRE_Downtown", seed=7)` then
`worldgen_manifest(only_non_compliant=true)`.

**For an episode runner**: `RegenerateWithSeed(N)` on the generator, wait for
`OnWorldGenerated`, spawn at `Manifest.SuggestedStart`, read the manifest for
the hazards. Works in packaged and `-game` builds; the nodes and the generator
are runtime code.

**From another program** (the sister repo
[ramms-tools](https://github.com/rammp-org/ramms-tools), over the Remote
Control API on port 30010): `ramms-worldgen generate --preset PRE_Downtown
--seed 42`, `ramms-worldgen manifest --issues`, `ramms-worldgen batch --preset
PRE_Park --seeds 1-50 --out data/park`; or in Python `WorldGen().generator()
.generate(seed=42).manifest()`. The engine side is `URammsWorldGenBridge`
(see the plugin README); it works against the editor and against a running
game alike.

## Where things live

```
Plugins/RammsWorldGen/          (submodule: rammp-org/ramms-worldgen)
  Source/RammsWorldGen/Public/
    RammsWorldGenTypes.h         FRammsWorldGenParams, manifest structs, enums
    RammsWorldPreset.h           URammsWorldPreset
    RammsWorldPalette.h          URammsWorldPalette + slot names
    RammsAccessibilityProfile.h  URammsAccessibilityProfile (ADA thresholds)
    RammsWorldGenerator.h        ARammsWorldGenerator
    RammsProcPiece.h             ARammsProcPiece (GeometryScript pieces)
    PCG/                         the custom PCG nodes
  Content/Python/ramms_worldgen/ graph builder, palettes, presets, levels, MCP toolset
  Content/{Graphs,Presets,Palettes,Profiles,Materials}/
                                 generated assets (/RammsWorldGen/...), rebuilt by build_assets.py
Content/Maps/Gen/                example levels
Scripts/worldgen/                build_assets.py, build_levels.py, regenerate.py
```

## The PCG graphs

The graphs are written as code (`ramms_worldgen/graphs.py`, using the small
builder in `_graph.py`) and rebuilt by `build_assets.py`, so do not edit them
in the PCG editor: changes there are overwritten on the next build. There are
three:

| Graph | Used by | What it does |
|---|---|---|
| `PCG_Streets` | downtown, suburban, park and main street presets | street network, lots, buildings, parks, sidewalk hazards |
| `PCG_Indoor` | home, office and store presets | rooms, corridors, doors, restrooms, furniture, aisles |
| `PCG_SpawnAndRecord` | subgraph of both | turns point streams into meshes and actors, writes the manifest |

```
PCG_Streets
  Params --(named reroute "Params" -> Overrides of every node)
  Street Network --Blocks--> Subdivide Lots --Lots--> Building Massing
        |                         `--Parks--> Park Layout
        `--Sidewalks--> Hazard Placer <--Sidewalks-- Park Layout
  every layout node --Primitives/Props/Modules/Grass/Pieces/Routes/Features--> Spawn And Record --> Output

PCG_Indoor
  Params --> Indoor Layout --streams--> Spawn And Record --> Output

PCG_SpawnAndRecord (inputs = the seven streams)
  Primitives -> Static Mesh Spawner (cube + Material attribute)
  Props      -> Static Mesh Spawner (Mesh attribute)          \
  Modules    -> Static Mesh Spawner (Mesh + Material0..7)       all BlockAll collision
  Pieces     -> Spawn Actor ARammsProcPiece (attributes -> properties) /
  Grass      -> Static Mesh Spawner (no collision, culled)
  Routes + Features + Props -> Manifest -> Output "Manifest" (JSON the generator reads)
```

How it works:

- **No numbers in the graphs.** The `Params` node reads the generator's
  `FRammsWorldGenParams` (one attribute per member) and every Ramms node takes
  it on its `Overrides` pin. A preset is just a set of parameters, which is
  why one graph serves several presets. A named reroute carries `Params` to
  each node, so the graph has no long wires.
- **Layout nodes emit point streams.** Each custom node (C++, `Source/.../PCG/`)
  writes points with attributes into a fixed set of output pins: `Primitives`
  (cubes with a material), `Props` (palette meshes), `Modules` (facade
  kit), `Grass`, `Pieces` (procedural ramps, steps, walls, doors and mounds),
  `Routes` and `Features` (ground truth).
- **One shared spawn stage.** Both graphs end in `PCG_SpawnAndRecord`, so the
  spawner configuration (collision, culling, attribute-to-property mapping)
  and the manifest wiring live in one place. A new graph, for example a
  campus or a transit station, only has to emit the same streams and add this
  subgraph.
- **Shared code below the graphs.** The nodes share `RammsPCGCommon`: the
  `URammsPCGSettingsBase` / `FRammsPCGElementBase` base classes (common
  properties, params overrides, output pins), the point writers (`WritePiece`,
  `WriteCube`, `WritePaletteMesh`, `WriteComposite`, `WriteFoliage`,
  `WriteManifest`) and the palette lookups. The spawners are configured by `URammsWorldGenGraphLibrary`,
  because attribute selectors cannot be set from Python.
- **Screenshots.** `Scripts/worldgen/graph_shots.py` opens each graph and
  saves it as 1:1 PNG tiles under `Saved/WorldGen/graph_shots/`.

## Adding content

A Fab pack with trees, doors or hazard props plugs in through the palette:
add the mesh names to `MESH_SLOTS` in `palettes.py` (or edit `PAL_Default`),
rebuild, regenerate. The procedural stand-ins (low-poly trees, planters as
A-frames) stop being used as soon as the slot has a mesh. New presets are
entries in `presets.py`; new parameters are a struct member plus a
same-named node property; see the plugin README.

## Known limits

Streets are axis-aligned grids; buildings are shells the robot does not
enter; indoor and outdoor are separate presets; sidewalks have no cross
slope yet; generated geometry is Chaos collision only (not imported into
MuJoCo / Newton); pedestrians come from `RammsCrowd`, not the generator.
