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
    def __init__(self, path, clear=True, inputs=None, outputs=None, description=None):
        """`inputs` / `outputs` replace the Input / Output node pins (for graphs used as subgraphs)."""
        self.path = path
        self.inputs = inputs
        self.outputs = outputs
        self.description = description
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
        # An open PCG editor keeps its own copy of the comment boxes and writes it back on close.
        try:
            unreal.get_editor_subsystem(unreal.AssetEditorSubsystem).close_all_editors_for_asset(self.graph)
        except Exception:
            pass
        L = unreal.RammsWorldGenGraphLibrary
        L.clear_graph_comments(self.graph)
        if self.inputs is not None or self.outputs is not None:
            L.set_graph_pins(self.graph, [unreal.Name(n) for n in (self.inputs or [])], [unreal.Name(n) for n in (self.outputs or [])])
        self.input = self.graph.get_input_node()
        self.output = self.graph.get_output_node()
        self.input.set_node_position(-600, 0)
        self.output.set_node_position(2400, 0)
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            if self.description:
                self.graph.set_editor_property("description", unreal.Text(self.description))
            self.graph.force_notification_for_editor()
            H.save(self.graph)
            H.log("saved graph %s (%d nodes)" % (self.path, len(self.graph.get_editor_property("nodes"))))
        return False

    # --- nodes -----------------------------------------------------------------
    def node(self, settings_class, title=None, col=None, row=None, pos=None, comment=None, **props):
        """Add a node of `settings_class`, set `props` on its settings, place it on a grid (or at `pos`),
        and give it a pinned comment bubble if `comment` is set."""
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
        if pos is not None:
            node.set_node_position(int(pos[0]), int(pos[1]))
        else:
            node.set_node_position(int(col * 420), int(r * 260))
        if comment:
            unreal.RammsWorldGenGraphLibrary.set_node_comment(node, comment)
        return node

    def place(self, node, x, y, comment=None):
        node.set_node_position(int(x), int(y))
        if comment:
            unreal.RammsWorldGenGraphLibrary.set_node_comment(node, comment)
        return node

    def comment(self, text, x, y, w, h, color=(0.25, 0.25, 0.25), font=20):
        """A comment box (editor only) around a region of the graph."""
        unreal.RammsWorldGenGraphLibrary.add_graph_comment(
            self.graph, text, int(x), int(y), int(w), int(h), unreal.LinearColor(color[0], color[1], color[2], 1.0), int(font))

    def subgraph(self, graph, title=None, **kw):
        """A Subgraph node calling `graph` (a PCGGraph asset or path); its pins are the subgraph's Input / Output pins."""
        if isinstance(graph, str):
            graph = unreal.load_asset(graph)
        node = self.node(unreal.PCGSubgraphSettings, title=title, **kw)
        node.get_settings().set_subgraph(graph)
        unreal.RammsWorldGenGraphLibrary.refresh_node_pins(node)
        return node

    def named_reroute(self, src, src_pin, name, x, y):
        """Named reroute declaration fed by src.src_pin; use `reroute_usage` to read it elsewhere without a wire."""
        decl = self.node(unreal.PCGNamedRerouteDeclarationSettings, title=name, pos=(x, y))
        self.edge(src, src_pin, decl, "In")
        return decl

    def reroute_usage(self, decl, x, y):
        use = self.node(unreal.PCGNamedRerouteUsageSettings, title=str(decl.get_editor_property("node_title")), pos=(x, y))
        use.get_settings().set_editor_property("declaration", decl.get_settings())
        # The pairing is an edge from the declaration's invisible pin to the usage's (invisible) "In" pin.
        self.edge(decl, "InvisiblePin", use, "In")
        return use

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
