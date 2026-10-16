"""The PCG graphs, written as code.

    PCG_Streets            downtown, suburban, park and main street presets
    PCG_Indoor             home, office and store presets
    PCG_SpawnAndRecord     shared subgraph: turns the point streams every layout node
                           emits into meshes / actors and writes the ground-truth manifest

Every Ramms node reads the generator's Params attribute set through its Overrides pin,
so the graphs carry no numbers of their own; the presets differ only in parameters.
Run build_all_graphs() after changing anything here (verify.py does).
"""

import unreal

from . import _helpers as H
from ._graph import GraphBuilder

STREETS = H.GRAPHS + "/PCG_Streets"
INDOOR = H.GRAPHS + "/PCG_Indoor"
SPAWN = H.GRAPHS + "/PCG_SpawnAndRecord"

# The point streams every layout node emits (pin names on the Ramms nodes and on PCG_SpawnAndRecord).
STREAMS = ["Primitives", "Props", "Modules", "Grass", "Pieces", "Routes", "Features"]

# Comment colours
C_PARAMS = (0.10, 0.25, 0.45)
C_LAYOUT = (0.15, 0.40, 0.20)
C_HAZARD = (0.50, 0.30, 0.08)
C_SPAWN = (0.35, 0.18, 0.45)
C_RECORD = (0.45, 0.12, 0.12)

PARAMS_NOTE = ("Generator's FRammsWorldGenParams, one attribute per member.\n"
               "Every Ramms node reads it on Overrides.")


def _params(g, x=-420, y=-220):
    """Params node + a 'Params' named reroute, so layout nodes read it without long wires."""
    params = g.actor_params(pos=(x, y), comment=PARAMS_NOTE)
    decl = g.named_reroute(params, "Out", "Params", x + 320, y + 30)
    g.comment("Parameters", x - 40, y - 120, 520, 230, C_PARAMS)
    return decl


def _overrides(g, decl, node):
    """A 'Params' reroute usage just left of `node`, wired to its Overrides pin."""
    p = node.get_node_position()
    x, y = (p[0], p[1]) if isinstance(p, (tuple, list)) else (p.x, p.y)
    use = g.reroute_usage(decl, x - 135, y + 90)
    g.edge(use, "Out", node, "Overrides")


def build_spawn_graph(path=SPAWN):
    """Shared by PCG_Streets and PCG_Indoor: one spawner per point stream, then the manifest."""
    with GraphBuilder(path, inputs=STREAMS, outputs=["Manifest"],
                      description="Spawn the Ramms point streams and record the ground-truth manifest. "
                                  "Shared by PCG_Streets and PCG_Indoor.") as g:
        g.place(g.input, -400, 300)
        x, dy = 0, 150
        prims = g.mesh_spawner("Spawn Primitives", material_attribute=True, pos=(x, 0),
                               comment="Scaled cube + Material attribute\n(ground, roads, floors, slabs)")
        props = g.mesh_spawner("Spawn Props", material_attribute=False, pos=(x, dy),
                               comment="Palette mesh from the Mesh attribute\n(furniture, street props, trees)")
        modules = g.module_spawner("Spawn Facade Modules", pos=(x, 2 * dy),
                                   comment="Facade kit modules,\nMaterial0..7 per slot")
        grass = g.foliage_spawner("Spawn Grass", pos=(x, 3 * dy),
                                  comment="Ground cover: no collision,\nculled 40-70 m")
        pieces = g.piece_spawner("Spawn Procedural Pieces", pos=(x, 4 * dy),
                                 comment="ARammsProcPiece actors (ramps, steps,\nwalls, doors, mounds) from attributes")
        my = 5 * dy + 60
        manifest = g.node(unreal.PCGRammsManifestSettings, title="Manifest", pos=(x, my),
                          comment="Features + Routes -> one JSON attribute set;\nthe generator merges it into its manifest")
        g.edges([
            (g.input, "Primitives", prims, "In"),
            (g.input, "Props", props, "In"),
            (g.input, "Modules", modules, "In"),
            (g.input, "Grass", grass, "In"),
            (g.input, "Pieces", pieces, "In"),
            (g.input, "Routes", manifest, "Routes"),
            (g.input, "Features", manifest, "Features"),
            (g.input, "Props", manifest, "Features"),  # placed props are features too (cars, trees, furniture)
        ])
        g.place(g.output, 420, my)
        g.to_output(manifest, "Out", "Manifest")
        g.comment("1  Spawn (everything collides except grass)", x - 60, -130, 400, 4 * dy + 230, C_SPAWN)
        g.comment("2  Record ground truth", x - 60, my - 110, 400, 230, C_RECORD)
        return g.graph


def _spawn(g, x, y):
    return g.subgraph(SPAWN, title="Spawn And Record", pos=(x, y),
                      comment="Shared subgraph PCG_SpawnAndRecord\n(the same one in PCG_Streets and PCG_Indoor)")


def build_streets_graph(path=STREETS):
    with GraphBuilder(path, description="Outdoor worlds: streets, blocks, lots, buildings, parks and sidewalk hazards. "
                                        "Downtown, suburban, park and main street presets.") as g:
        g.place(g.input, -420, 140)
        decl = _params(g)

        street = g.node(unreal.PCGRammsStreetNetworkSettings, title="Street Network", pos=(0, 120),
                        comment="Street grid from site + block size: roads, curbs,\nsidewalks, curb ramps, crosswalks, furniture")
        lots = g.node(unreal.PCGRammsSubdivideLotsSettings, title="Subdivide Lots", pos=(380, 120),
                      comment="Blocks -> building lots,\nyards and parks")
        massing = g.node(unreal.PCGRammsBuildingMassingSettings, title="Building Massing", pos=(760, 120),
                         comment="Per lot: facade-kit buildings, entrances\nwith steps / ramps, yards, driveways, trees")
        park = g.node(unreal.PCGRammsParkLayoutSettings, title="Park Layout", pos=(760, 540),
                      comment="Terrain mounds, pond, paths, plaza,\nbenches beside paths, trees, grass")
        hazards = g.node(unreal.PCGRammsHazardPlacerSettings, title="Hazard Placer", pos=(1140, 540),
                         comment="Along sidewalks and park paths: cracks,\nlips, slopes, obstacles; wheelchair Routes")
        spawn = _spawn(g, 1500, 180)
        for n in (street, lots, massing, park, hazards):
            _overrides(g, decl, n)

        g.edges([
            (g.input, "In", street, "In"),
            (street, "Blocks", lots, "In"),
            (lots, "Lots", massing, "In"),
            (lots, "Parks", park, "In"),
            (street, "Sidewalks", hazards, "In"),
            (park, "Sidewalks", hazards, "In"),
        ])
        # Every layout node feeds its point streams straight into the shared spawn subgraph.
        outputs = {
            street: ["Primitives", "Props", "Pieces", "Features"],
            massing: ["Primitives", "Props", "Modules", "Grass", "Pieces", "Features"],
            park: ["Primitives", "Props", "Grass", "Pieces", "Features"],
            hazards: ["Props", "Pieces", "Routes"],
        }
        for n, pins in outputs.items():
            for p in pins:
                g.edge(n, p, spawn, p)
        g.place(g.output, 1910, 200)
        g.to_output(spawn, "Manifest")

        g.comment("1  Layout: streets -> blocks -> lots -> buildings / parks", -200, -20, 1180, 820, C_LAYOUT)
        g.comment("2  Hazards and routes", 990, 420, 380, 340, C_HAZARD)
        g.comment("3  Spawn and record", 1450, 60, 400, 400, C_SPAWN)
        return g.graph


def build_indoor_graph(path=INDOOR):
    with GraphBuilder(path, description="Indoor worlds: rooms, corridors, doors, restrooms, furniture and store aisles. "
                                        "Home, office and store presets.") as g:
        g.place(g.input, -420, 140)
        decl = _params(g)
        indoor = g.node(unreal.PCGRammsIndoorLayoutSettings, title="Indoor Layout", pos=(0, 120),
                        comment="Rooms and corridors per preset (home / office / store):\nwalls, doorways >= MinPassableDoorWidth, doors,\nrestrooms, furniture, aisles; Routes through doorways")
        _overrides(g, decl, indoor)
        spawn = _spawn(g, 420, 120)
        g.edge(g.input, "In", indoor, "In")
        for p in ["Primitives", "Props", "Pieces", "Routes", "Features"]:
            g.edge(indoor, p, spawn, p)
        g.place(g.output, 780, 140)
        g.to_output(spawn, "Manifest")
        g.comment("1  Layout", -220, -40, 540, 420, C_LAYOUT)
        g.comment("2  Spawn and record", 360, -40, 380, 420, C_SPAWN)
        return g.graph


def build_all_graphs():
    spawn = build_spawn_graph()  # first: the others reference it
    return {"spawn": spawn, "streets": build_streets_graph(), "indoor": build_indoor_graph()}
