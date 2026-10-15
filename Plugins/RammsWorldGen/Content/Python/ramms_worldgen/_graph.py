"""A tiny builder DSL for PCG graphs, so the graphs are code, not binary.

    with GraphBuilder("/Game/WorldGen/Graphs/PCG_Downtown") as g:
        params = g.node(unreal.PCGGetActorPropertySettings, property_name="Params", ...)
        street = g.node(unreal.PCGRammsStreetNetworkSettings)
        g.edge(g.input, "In", street, "In")
        g.edge(params, "Out", street, "Overrides")

Pin labels are checked against the live node, and a wrong one raises with the
labels that do exist, so a version drift in Epic's nodes fails loudly at build
time instead of silently leaving an edge out.
"""

import unreal

from . import _helpers as H


def _pin_labels(pins):
    return [str(p.get_editor_property("properties").get_editor_property("label")) for p in pins]


class GraphBuilder:
    def __init__(self, path, clear=True):
        self.path = path
        self.clear = clear
        self.graph = None
        self.input = None
        self.output = None
        self._col = 0
        self._rows = {}

    def __enter__(self):
        self.graph, created = H.get_or_create(self.path, unreal.PCGGraph, unreal.PCGGraphFactory())
        if not created and self.clear:
            # Rebuild from scratch. remove_nodes() is a no-op through the Python binding (its array
            # is an out-parameter), so remove one by one; the Input and Output nodes are not in `nodes`.
            for n in list(self.graph.get_editor_property("nodes")):
                self.graph.remove_node(n)
            remaining = len(self.graph.get_editor_property("nodes"))
            if remaining:
                raise RuntimeError("%s still has %d nodes after clearing" % (self.path, remaining))
        self.input = self.graph.get_input_node()
        self.output = self.graph.get_output_node()
        self.input.set_node_position(-600, 0)
        self.output.set_node_position(2400, 0)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.graph.force_notification_for_editor()
            H.save(self.graph)
            H.log("saved graph %s (%d nodes)" % (self.path, len(self.graph.get_editor_property("nodes"))))
        return False

    # --- nodes -----------------------------------------------------------------
    def node(self, settings_class, title=None, col=None, row=None, **props):
        """Add a node of `settings_class`, set `props` on its settings, place it on a grid."""
        node, settings = self.graph.add_node_of_type(settings_class)
        if settings is None:
            settings = node.get_settings()
        for k, v in props.items():
            settings.set_editor_property(k, v)
        if title:
            node.set_editor_property("node_title", title)
        if col is None:
            col = self._col
            self._col += 1
        r = self._rows.get(col, 0) if row is None else row
        if row is None:
            self._rows[col] = r + 1
        node.set_node_position(int(col * 420), int(r * 260))
        return node

    def settings(self, node):
        return node.get_settings()

    # --- edges -----------------------------------------------------------------
    def edge(self, src, src_pin, dst, dst_pin):
        outs = _pin_labels(src.get_editor_property("output_pins"))
        ins = _pin_labels(dst.get_editor_property("input_pins"))
        if src_pin not in outs:
            raise RuntimeError("%s has no output pin '%s' (has %s)" % (src.get_editor_property("node_title") or src.get_name(), src_pin, outs))
        if dst_pin not in ins:
            raise RuntimeError("%s has no input pin '%s' (has %s)" % (dst.get_editor_property("node_title") or dst.get_name(), dst_pin, ins))
        self.graph.add_edge(src, src_pin, dst, dst_pin)
        return dst

    def edges(self, pairs):
        for src, sp, dst, dp in pairs:
            self.edge(src, sp, dst, dp)

    def to_output(self, src, src_pin, out_pin="Out"):
        self.edge(src, src_pin, self.output, out_pin)

    # --- common configured nodes -----------------------------------------------
    def actor_params(self, property_name="Params", title="Params", **kw):
        """Get Actor Property on Self: the generator's FRammsWorldGenParams, one attribute per member."""
        sel = unreal.PCGActorSelectorSettings()
        sel.set_editor_property("actor_filter", unreal.PCGActorFilter.SELF)
        node = self.node(
            unreal.PCGGetActorPropertySettings,
            title=title,
            actor_selector=sel,
            property_name=property_name,
            struct_extractor_behavior=unreal.PCGStructExtractorBehavior.EXTRACT,
            always_requery_actors=True,
            **kw,
        )
        return node

    def mesh_spawner(self, title, material_attribute=True, **kw):
        """Static Mesh Spawner reading the mesh (and optionally slot-0 material) from attributes."""
        node = self.node(unreal.PCGStaticMeshSpawnerSettings, title=title, **kw)
        unreal.RammsWorldGenGraphLibrary.configure_mesh_spawner(node.get_settings(), bool(material_attribute))
        return node

    def foliage_spawner(self, title, **kw):
        """Static Mesh Spawner for ground cover: mesh from "Mesh", no collision, distance culled."""
        node = self.node(unreal.PCGStaticMeshSpawnerSettings, title=title, **kw)
        unreal.RammsWorldGenGraphLibrary.configure_foliage_spawner(node.get_settings())
        return node

    def module_spawner(self, title, **kw):
        """Static Mesh Spawner for facade modules: mesh from "Mesh", every material slot from Material0..7."""
        node = self.node(unreal.PCGStaticMeshSpawnerSettings, title=title, **kw)
        unreal.RammsWorldGenGraphLibrary.configure_module_spawner(node.get_settings())
        return node

    def piece_spawner(self, title, **kw):
        """Spawn Actor for ARammsProcPiece with every piece property mapped from the same-named attribute.
        Configured in C++ (URammsWorldGenGraphLibrary): attribute selectors are not settable from Python."""
        node = self.node(unreal.PCGSpawnActorSettings, title=title, **kw)
        unreal.RammsWorldGenGraphLibrary.configure_piece_spawner(node.get_settings())
        return node


# Mirrors URammsWorldGenGraphLibrary::PiecePropertyNames (documentation only; the C++ list is what gets wired).
PIECE_PROPERTIES = [
    "KindId", "SizeX", "SizeY", "SizeZ", "Rise", "Slope", "FlareSlope", "StepCount",
    "OpeningWidth", "OpeningOffset", "OpeningHeight", "LandingSize", "WarningDepth",
    "MaterialPath", "MaterialPath2", "ManifestKind", "ManifestSubtype", "bCompliant", "IssueId",
]
