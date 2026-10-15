"""The two PCG graphs, written as code.

PCG_Streets serves the downtown, suburban and park presets (the parameters
decide which features appear); PCG_Indoor serves the indoor presets. Every
custom node reads the generator's Params attribute set through its Overrides
pin, so the graphs carry no numbers of their own.
"""

import unreal

from . import _helpers as H
from ._graph import GraphBuilder

STREETS = H.GRAPHS + "/PCG_Streets"
INDOOR = H.GRAPHS + "/PCG_Indoor"


def build_streets_graph(path=STREETS):
    with GraphBuilder(path) as g:
        params = g.actor_params(col=0, row=0)

        street = g.node(unreal.PCGRammsStreetNetworkSettings, title="Street Network", col=1, row=0)
        lots = g.node(unreal.PCGRammsSubdivideLotsSettings, title="Subdivide Lots", col=2, row=0)
        massing = g.node(unreal.PCGRammsBuildingMassingSettings, title="Building Massing", col=3, row=0)
        park = g.node(unreal.PCGRammsParkLayoutSettings, title="Park Layout", col=3, row=1)
        hazards = g.node(unreal.PCGRammsHazardPlacerSettings, title="Hazard Placer", col=4, row=0)

        prims = g.mesh_spawner("Spawn Primitives (cube + material)", material_attribute=True, col=5, row=0)
        props = g.mesh_spawner("Spawn Props (palette meshes)", material_attribute=False, col=5, row=1)
        modules = g.module_spawner("Spawn Facade Modules (per-slot materials)", col=5, row=2)
        grass = g.foliage_spawner("Spawn Grass (no collision, culled)", col=6, row=1)
        pieces = g.piece_spawner("Spawn Procedural Pieces", col=5, row=3)
        manifest = g.node(unreal.PCGRammsManifestSettings, title="Manifest", col=5, row=4)

        g.edges([
            (g.input, "In", street, "In"),
            (params, "Out", street, "Overrides"),
            (street, "Blocks", lots, "In"),
            (params, "Out", lots, "Overrides"),
            (lots, "Lots", massing, "In"),
            (params, "Out", massing, "Overrides"),
            (lots, "Parks", park, "In"),
            (params, "Out", park, "Overrides"),
            (street, "Sidewalks", hazards, "In"),
            (park, "Sidewalks", hazards, "In"),
            (params, "Out", hazards, "Overrides"),
            # primitives: scaled cubes with a material attribute
            (street, "Primitives", prims, "In"),
            (massing, "Primitives", prims, "In"),
            (park, "Primitives", prims, "In"),
            # palette meshes
            (street, "Props", props, "In"),
            (massing, "Props", props, "In"),
            (hazards, "Props", props, "In"),
            (park, "Props", props, "In"),
            # ground cover
            (massing, "Grass", grass, "In"),
            (park, "Grass", grass, "In"),
            # facade kit modules
            (massing, "Modules", modules, "In"),
            # procedural pieces
            (street, "Pieces", pieces, "In"),
            (massing, "Pieces", pieces, "In"),
            (hazards, "Pieces", pieces, "In"),
            (park, "Pieces", pieces, "In"),
            # ground truth
            (hazards, "Routes", manifest, "Routes"),
            (street, "Features", manifest, "Features"),
            (massing, "Features", manifest, "Features"),
            (park, "Features", manifest, "Features"),
            (hazards, "Props", manifest, "Features"),
            (park, "Props", manifest, "Features"),
            (massing, "Props", manifest, "Features"),  # driveway cars, street trees, mailboxes, foundation shrubs
        ])
        g.to_output(manifest, "Out")
        return g.graph


def build_indoor_graph(path=INDOOR):
    with GraphBuilder(path) as g:
        params = g.actor_params(col=0, row=0)
        indoor = g.node(unreal.PCGRammsIndoorLayoutSettings, title="Indoor Layout", col=1, row=0)
        prims = g.mesh_spawner("Spawn Floors (cube + material)", material_attribute=True, col=2, row=0)
        props = g.mesh_spawner("Spawn Furniture (palette meshes)", material_attribute=False, col=2, row=1)
        pieces = g.piece_spawner("Spawn Walls / Doors", col=2, row=2)
        manifest = g.node(unreal.PCGRammsManifestSettings, title="Manifest", col=2, row=3)
        g.edges([
            (g.input, "In", indoor, "In"),
            (params, "Out", indoor, "Overrides"),
            (indoor, "Primitives", prims, "In"),
            (indoor, "Props", props, "In"),
            (indoor, "Pieces", pieces, "In"),
            (indoor, "Routes", manifest, "Routes"),
            (indoor, "Features", manifest, "Features"),
            (indoor, "Props", manifest, "Features"),
        ])
        g.to_output(manifest, "Out")
        return g.graph


def build_all_graphs():
    return {"streets": build_streets_graph(), "indoor": build_indoor_graph()}
