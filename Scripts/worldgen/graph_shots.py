"""Capture the WorldGen PCG graphs as tiled 1:1 screenshots for docs / PRs.

Run inside the editor (after build_assets). For each graph it opens the PCG
editor, steps the view across the graph at zoom 1:1 and saves the panel as
PNG tiles plus tiles.json under Saved/WorldGen/graph_shots/<graph>/. Stitch
them with any image tool (the PR images were stitched with PIL), cropping
CROP_TOP / CROP_BOTTOM px from every tile to drop the editor overlays.
"""
import json
import os

import unreal

GRAPHS = ["PCG_Streets", "PCG_Indoor", "PCG_SpawnAndRecord"]
OUT = os.path.join(unreal.Paths.project_saved_dir(), "WorldGen", "graph_shots")
CROP_TOP, CROP_BOTTOM, CROP_RIGHT = 50, 90, 0
PAD = (120, 160, 330, 300)  # left, top, right, bottom around node positions (nodes are ~300 x 320)

L = unreal.RammsWorldGenGraphLibrary
_state = {"jobs": [], "wait": 0, "handle": None, "cur": None}


def _bounds(graph):
    xs, ys = [], []
    nodes = list(graph.get_editor_property("nodes")) + [graph.get_input_node(), graph.get_output_node()]
    for n in nodes:
        p = n.get_node_position()
        x, y = (p[0], p[1]) if isinstance(p, (tuple, list)) else (p.x, p.y)
        xs.append(x)
        ys.append(y)
    return min(xs) - PAD[0], min(ys) - PAD[1], max(xs) + PAD[2], max(ys) + PAD[3]


def _plan(name):
    graph = unreal.load_asset("/RammsWorldGen/Graphs/" + name)
    unreal.get_editor_subsystem(unreal.AssetEditorSubsystem).open_editor_for_assets([graph])
    return graph


def _tick(dt):
    s = _state
    if s["wait"] > 0:
        s["wait"] -= 1
        return
    if s["cur"] is None:
        if not s["jobs"]:
            unreal.unregister_slate_post_tick_callback(s["handle"])
            unreal.log("graph_shots: done -> " + OUT)
            return
        name = s["jobs"].pop(0)
        graph = _plan(name)
        s["cur"] = {"name": name, "graph": graph, "tiles": None, "i": 0, "meta": []}
        s["wait"] = 30
        return
    cur = s["cur"]
    graph = cur["graph"]
    if cur["tiles"] is None:
        size = L.set_graph_editor_view(graph, unreal.Vector2D(0, 0), 1.0)
        w, h = size.x, size.y
        if w <= 0:
            unreal.log_warning("graph_shots: %s is not open" % cur["name"])
            s["cur"] = None
            return
        x0, y0, x1, y1 = _bounds(graph)
        step_x, step_y = w - CROP_RIGHT, h - CROP_TOP - CROP_BOTTOM
        tiles = []
        y = y0
        while y < y1:
            x = x0
            while x < x1:
                tiles.append((x, y))
                x += step_x
            y += step_y
        cur.update(tiles=tiles, w=w, h=h, bounds=(x0, y0, x1, y1))
        os.makedirs(os.path.join(OUT, cur["name"]), exist_ok=True)
        cur["phase"] = "set"
        return
    if cur["i"] >= len(cur["tiles"]):
        meta = {"panel": [cur["w"], cur["h"]], "crop": [CROP_TOP, CROP_BOTTOM, CROP_RIGHT], "bounds": cur["bounds"], "tiles": cur["meta"]}
        with open(os.path.join(OUT, cur["name"], "tiles.json"), "w") as f:
            json.dump(meta, f, indent=1)
        unreal.get_editor_subsystem(unreal.AssetEditorSubsystem).close_all_editors_for_asset(graph)
        s["cur"] = None
        s["wait"] = 10
        return
    x, y = cur["tiles"][cur["i"]]
    if cur["phase"] == "set":
        # The tile's visible region starts CROP_TOP px below the panel top.
        L.set_graph_editor_view(graph, unreal.Vector2D(x, y - CROP_TOP), 1.0)
        cur["phase"] = "shoot"
        s["wait"] = 6
        return
    path = os.path.join(OUT, cur["name"], "tile_%03d.png" % cur["i"])
    ok = L.capture_graph_editor(graph, path)
    cur["meta"].append({"file": os.path.basename(path), "x": x, "y": y, "ok": bool(ok)})
    cur["i"] += 1
    cur["phase"] = "set"


def run(graphs=GRAPHS):
    _state.update(jobs=list(graphs), wait=0, cur=None)
    _state["handle"] = unreal.register_slate_post_tick_callback(_tick)


run()
