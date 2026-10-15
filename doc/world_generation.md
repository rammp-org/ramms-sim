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
profile, the presets and the two PCG graphs under `/Game/WorldGen/`. The
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
Plugins/RammsWorldGen/
  Source/RammsWorldGen/Public/
    RammsWorldGenTypes.h         FRammsWorldGenParams, manifest structs, enums
    RammsWorldPreset.h           URammsWorldPreset
    RammsWorldPalette.h          URammsWorldPalette + slot names
    RammsAccessibilityProfile.h  URammsAccessibilityProfile (ADA thresholds)
    RammsWorldGenerator.h        ARammsWorldGenerator
    RammsProcPiece.h             ARammsProcPiece (GeometryScript pieces)
    PCG/                         the custom PCG nodes
  Content/Python/ramms_worldgen/ graph builder, palettes, presets, levels, MCP toolset
Content/WorldGen/                generated assets: Palettes, Profiles, Presets, Graphs
Content/Maps/Gen/                example levels
Scripts/worldgen/                build_assets.py, build_levels.py, regenerate.py
```

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
