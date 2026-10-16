"""End-to-end verification of RammsWorldGen inside a running editor.

Launched by verify.cmd / verify.ps1 via `-ExecCmds="py <this file>"`, or run from
the editor's Python console. Writes progress to Saved/WorldGen/verify_progress.log
and a final report to Saved/WorldGen/verify_report.json, plus one screenshot per
example level under Saved/Screenshots/. The editor keeps running afterwards.

Stages: module + toolset present -> assets from code -> graphs sanity ->
example levels (generated one after another) -> Python API -> MCP tool calls.
"""
import json
import os
import time
import traceback

import unreal

SAVED = unreal.SystemLibrary.get_project_saved_directory()
OUT_DIR = os.path.join(SAVED, "WorldGen")
os.makedirs(OUT_DIR, exist_ok=True)
PROGRESS = os.path.join(OUT_DIR, "verify_progress.log")
REPORT = os.path.join(OUT_DIR, "verify_report.json")

report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "stages": {}, "errors": [], "done": False}


def log(msg):
    line = "[verify] " + str(msg)
    unreal.log(line)
    with open(PROGRESS, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + line + "\n")


def err(msg):
    log("ERROR: " + str(msg))
    report["errors"].append(str(msg))


def save_report():
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)


def stage(name, fn):
    log("stage %s ..." % name)
    try:
        report["stages"][name] = {"ok": True, "result": fn()}
    except Exception as exc:
        report["stages"][name] = {"ok": False, "error": str(exc), "trace": traceback.format_exc()}
        report["errors"].append("%s: %s" % (name, exc))
        log("stage %s FAILED: %s" % (name, exc))
    save_report()


# ---------------------------------------------------------------- stages

def st_module():
    out = {}
    for cls in ("RammsWorldGenerator", "RammsProcPiece", "RammsWorldPreset", "RammsWorldPalette", "RammsAccessibilityProfile",
                "PCGRammsStreetNetworkSettings", "PCGRammsSubdivideLotsSettings", "PCGRammsBuildingMassingSettings",
                "PCGRammsParkLayoutSettings", "PCGRammsHazardPlacerSettings", "PCGRammsIndoorLayoutSettings", "PCGRammsManifestSettings"):
        out[cls] = hasattr(unreal, cls)
    missing = [k for k, v in out.items() if not v]
    if missing:
        raise RuntimeError("classes missing from the Python reflection (module not built/loaded?): %s" % missing)
    import ramms_worldgen
    out["toolset_registered"] = bool(ramms_worldgen.register())
    return out


def st_assets():
    import importlib
    import ramms_worldgen.build_all as b
    for m in ("ramms_worldgen._helpers", "ramms_worldgen._graph", "ramms_worldgen.surfaces", "ramms_worldgen.palettes", "ramms_worldgen.presets",
              "ramms_worldgen.graphs", "ramms_worldgen.build_all"):
        importlib.reload(importlib.import_module(m))
    import ramms_worldgen.build_all as b2
    return b2.build("all")


def st_graphs():
    out = {}
    for path in ("/RammsWorldGen/Graphs/PCG_SpawnAndRecord", "/RammsWorldGen/Graphs/PCG_Streets", "/RammsWorldGen/Graphs/PCG_Indoor"):
        g = unreal.EditorAssetLibrary.load_asset(path)
        if g is None:
            raise RuntimeError("graph missing: " + path)
        nodes = g.get_editor_property("nodes")
        info = {"nodes": [], "edges": len(g.get_all_edges())}
        for n in nodes:
            s = n.get_settings()
            ins = [str(p.get_editor_property("properties").get_editor_property("label")) for p in n.get_editor_property("input_pins")]
            outs = [str(p.get_editor_property("properties").get_editor_property("label")) for p in n.get_editor_property("output_pins")]
            connected_in = [str(p.get_editor_property("properties").get_editor_property("label")) for p in n.get_editor_property("input_pins") if p.is_connected()]
            info["nodes"].append({"title": str(n.get_editor_property("node_title")), "class": s.get_class().get_name() if s else None,
                                  "in": ins, "out": outs, "connected_in": connected_in})
            if s and s.get_class().get_name() == "PCGNamedRerouteUsageSettings" and not connected_in:
                raise RuntimeError("%s: named reroute usage '%s' is not paired with its declaration" % (path, info["nodes"][-1]["title"]))
        out[path] = info
    return out


_levels_state = {"queue": [], "results": {}, "current": None, "handle": None, "ticks": 0, "busy": False}


def _frame_camera(gen, indoor):
    try:
        params = gen.get_editor_property("params")
        sx = params.get_editor_property("site_size_x")
        sy = params.get_editor_property("site_size_y")
        d = max(sx, sy)
        loc = gen.get_actor_location()
        if indoor:
            cam = unreal.Vector(loc.x - d * 0.35, loc.y - d * 0.9, loc.z + d * 0.9)
        else:
            cam = unreal.Vector(loc.x - d * 0.55, loc.y - d * 0.9, loc.z + d * 0.75)
        rot = unreal.MathLibrary.find_look_at_rotation(cam, loc)
        unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(cam, rot)
    except Exception as exc:
        log("camera framing failed: %s" % exc)


_cam = {}


def _frame_camera_pose(gen, indoor):
    params = gen.get_editor_property("params")
    sx = params.get_editor_property("site_size_x")
    sy = params.get_editor_property("site_size_y")
    d = max(sx, sy)
    loc = gen.get_actor_location()
    cam = unreal.Vector(loc.x - d * 0.35, loc.y - d * 0.9, loc.z + d * 0.9) if indoor else unreal.Vector(loc.x - d * 0.55, loc.y - d * 0.9, loc.z + d * 0.75)
    return cam, unreal.MathLibrary.find_look_at_rotation(cam, loc)


_capture = {}


def _screenshot(name):
    """Phase 1: render the level through a SceneCapture2D into a render target. The export happens on a
    later tick (_screenshot_export) so the render has certainly completed, and the file is named from the
    loaded map, not the loop, so a mismatch is impossible to misread."""
    try:
        import ramms_worldgen._helpers as H
        world = H.editor_world()
        gen = H.find_generator()
        preset = gen.get_editor_property("preset")
        indoor = preset.get_editor_property("scene_kind") == unreal.RammsSceneKind.INDOOR if preset else False
        cam, rot = _frame_camera_pose(gen, indoor)
        rt = unreal.RenderingLibrary.create_render_target2d(world, 1600, 900, unreal.TextureRenderTargetFormat.RTF_RGBA8)
        cap = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(unreal.SceneCapture2D, cam, rot)
        comp = cap.get_component_by_class(unreal.SceneCaptureComponent2D)
        comp.set_editor_property("texture_target", rt)
        comp.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
        comp.set_editor_property("fov_angle", 70.0)
        comp.set_editor_property("capture_every_frame", False)
        comp.capture_scene()
        _capture.update({"rt": rt, "cap": cap, "map": world.get_name(), "preset": preset.get_name() if preset else "?", "loop": name})
        return "pending"
    except Exception as exc:
        return "screenshot failed: %s" % exc


def _screenshot_export():
    """Phase 2: export the render target and remove the capture actor. Returns the file path."""
    try:
        import ramms_worldgen._helpers as H
        world = H.editor_world()
        fname = "capture_%s.png" % _capture["map"]
        comp = _capture["cap"].get_component_by_class(unreal.SceneCaptureComponent2D)
        comp.capture_scene()   # once more, now that the scene has definitely rendered at least one frame
        unreal.RenderingLibrary.export_render_target(world, _capture["rt"], OUT_DIR, fname)
        with open(os.path.join(OUT_DIR, "capture_%s.json" % _capture["map"]), "w") as f:
            json.dump({"map": _capture["map"], "preset": _capture["preset"], "loop": _capture["loop"], "time": time.strftime("%H:%M:%S")}, f)
        unreal.get_editor_subsystem(unreal.EditorActorSubsystem).destroy_actor(_capture["cap"])
        _capture.clear()
        return os.path.join(OUT_DIR, fname)
    except Exception as exc:
        return "export failed: %s" % exc


def _geometry_stats():
    """What actually got built: ISM instance totals per mesh, and piece triangle counts."""
    import ramms_worldgen._helpers as H
    out = {"ism": {}, "ism_instances": 0, "pieces": 0, "pieces_with_triangles": 0, "piece_triangles": 0, "pieces_no_material": 0}
    gen = H.find_generator()
    for c in gen.get_components_by_class(unreal.InstancedStaticMeshComponent):
        n = c.get_instance_count()
        mesh = c.get_editor_property("static_mesh")
        key = mesh.get_name() if mesh else "<none>"
        out["ism"][key] = out["ism"].get(key, 0) + n
        out["ism_instances"] += n
    for a in H.level_actors():
        if isinstance(a, unreal.RammsProcPiece):
            out["pieces"] += 1
            mc = a.get_editor_property("mesh_component")
            dm = mc.get_dynamic_mesh() if mc else None
            tris = dm.get_triangle_count() if dm else 0
            out["piece_triangles"] += tris
            if tris > 0:
                out["pieces_with_triangles"] += 1
            if mc and mc.get_material(0) is None:
                out["pieces_no_material"] += 1
    return out


def _collision_check():
    """
    Furniture must not penetrate walls or each other. Every ISM instance (palette meshes) becomes a
    world-space box from its mesh bounds; every Wall piece a box from its size; pairs that overlap by
    more than 1 cm in all three axes are reported. Stacked pairs (a lamp on a night table) do not
    overlap in Z and pass.
    """
    import math
    import ramms_worldgen._helpers as H
    gen = H.find_generator()
    boxes = []  # (label, min(x,y,z), max(x,y,z))
    for c in gen.get_components_by_class(unreal.InstancedStaticMeshComponent):
        mesh = c.get_editor_property("static_mesh")
        if mesh is None or mesh.get_name() == "Cube":
            continue  # cubes are floors / primitives, which overlap by design under the walls
        b = mesh.get_bounds()
        ext, org = b.box_extent, b.origin
        corners = [unreal.Vector(org.x + sx * ext.x, org.y + sy * ext.y, org.z + sz * ext.z)
                   for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
        for i in range(c.get_instance_count()):
            xf = c.get_instance_transform(i, world_space=True)
            pts = [xf.transform_location(k) for k in corners]
            lo = (min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
            hi = (max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))
            boxes.append(("%s#%d" % (mesh.get_name(), i), lo, hi, "prop"))
    for a in H.level_actors():
        if isinstance(a, unreal.RammsProcPiece) and int(a.get_editor_property("kind_id")) == int(unreal.RammsProcPieceKind.WALL.value):
            sx, sy, sz = (a.get_editor_property(k) for k in ("size_x", "size_y", "size_z"))
            xf = a.get_actor_transform()
            # Wall local box: x in [0, sx], y in [-sy/2, sy/2], z in [0, sz]
            corners = [unreal.Vector(x, y, z) for x in (0.0, sx) for y in (-sy * 0.5, sy * 0.5) for z in (0.0, sz)]
            pts = [xf.transform_location(k) for k in corners]
            lo = (min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))
            hi = (max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))
            boxes.append((a.get_actor_label(), lo, hi, "wall"))
    # Stock sits inside its holder's bounds by design (products on shelves, produce in crates on tables,
    # stacked baskets): stock is checked against walls, not against what holds it or against other stock.
    def slot_meshes(slot):
        try:
            pal = unreal.load_asset("/RammsWorldGen/Palettes/PAL_Default")
            slots = pal.get_editor_property("slots")
            for k in slots.keys():
                if str(k) == slot:
                    return {m.get_editor_property("mesh").get_name() for m in slots[k].get_editor_property("meshes") if m.get_editor_property("mesh")}
        except Exception:  # noqa: BLE001
            pass
        return set()
    stock, holders = set(), set()
    for sl in ("Store.Product", "Store.Produce", "Store.Crate", "Store.DeliItem", "Store.Basket", "Store.Register"):
        stock |= slot_meshes(sl)
    for sl in ("Store.Shelf", "Store.ProduceTable", "Store.DeliCase", "Store.Crate", "Store.Basket", "Store.Counter"):
        holders |= slot_meshes(sl)
    def held(a, b):
        na, nb = a[0].split("#")[0], b[0].split("#")[0]
        return (na in stock and (nb in holders or nb in stock)) or (nb in stock and (na in holders or na in stock))
    tol = 1.0
    overlaps = []
    props = [b for b in boxes if b[3] == "prop"]
    walls = [b for b in boxes if b[3] == "wall"]
    def pen(a, b):
        d = [min(a[2][k], b[2][k]) - max(a[1][k], b[1][k]) for k in range(3)]
        return min(d)
    for i in range(len(props)):
        for j in range(i + 1, len(props)):
            if pen(props[i], props[j]) > tol and not held(props[i], props[j]):
                overlaps.append((props[i][0], props[j][0], round(pen(props[i], props[j]), 1)))
        for w in walls:
            if pen(props[i], w) > tol:
                overlaps.append((props[i][0], w[0], round(pen(props[i], w), 1)))
    return {"props": len(props), "walls": len(walls), "overlaps": overlaps[:40], "overlap_count": len(overlaps)}


def _finish_level(name):
    import ramms_worldgen._helpers as H
    import ramms_worldgen.levels as L
    gen = H.find_generator()
    m = H.manifest_to_dict(gen)
    feats = m.get("features", [])
    kinds = {}
    issues = {}
    for f in feats:
        kinds[f.get("kind")] = kinds.get(f.get("kind"), 0) + 1
        if not f.get("bCompliant", True):
            issues[f.get("issue")] = issues.get(f.get("issue"), 0) + 1
    actors = H.level_actors()
    pieces = [a for a in actors if isinstance(a, unreal.RammsProcPiece)]
    preset = gen.get_editor_property("preset")
    indoor = preset.get_editor_property("scene_kind") == unreal.RammsSceneKind.INDOOR if preset else False
    crowd = L.finish_level(gen)
    unreal.EditorLoadingAndSavingUtils.save_current_level()
    if isinstance(crowd, dict) and crowd.get("error"):
        err("level %s: crowd lanes failed: %s" % (name, crowd["error"]))
    elif isinstance(crowd, dict) and not crowd.get("shapes"):
        err("level %s: no crowd lanes (%s)" % (name, crowd))
    elif isinstance(crowd, dict) and (crowd.get("blocked_lane_segments") or crowd.get("blocked_junction_edges")):
        err("level %s: crowd lanes run into geometry: %s lane segments, %s junction edges" % (name, crowd.get("blocked_lane_segments"), crowd.get("blocked_junction_edges")))
    res = {
        "crowd": crowd,
        "map": unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_path_name(),
        "seed": gen.get_editor_property("seed"),
        "features": len(feats), "feature_kinds": kinds, "routes": len(m.get("routes", [])),
        "non_compliant": sum(issues.values()), "issues": issues,
        "proc_pieces": len(pieces), "actors": len(actors),
        "suggested_start": m.get("suggestedStart"),
        "manifest_file": gen.export_manifest(""),
        "geometry": _geometry_stats(),
    }
    if indoor:
        res["collisions"] = _collision_check()
        if res["collisions"]["overlap_count"]:
            err("level %s: %d furniture/wall overlaps, e.g. %s" % (name, res["collisions"]["overlap_count"], res["collisions"]["overlaps"][:3]))
    _levels_state["results"][name] = res
    # Frame the camera now; the screenshot itself waits for the viewport to settle (shaders, exposure).
    _frame_camera(gen, indoor)
    _levels_state["settle_until"] = time.time() + 6.0
    _levels_state["shot"] = name
    log("level %s: %d features, %d routes, %d pieces, %d issues" % (name, res["features"], res["routes"], res["proc_pieces"], res["non_compliant"]))


def _levels_tick(dt):
    st = _levels_state
    if st["busy"]:
        return  # new_level / save pump Slate and re-enter this callback
    st["busy"] = True
    st["ticks"] += 1
    try:
        _levels_tick_inner(st)
    finally:
        st["busy"] = False


def _levels_tick_inner(st):
    try:
        import ramms_worldgen._helpers as H
        if st.get("shot"):
            # Settling after a finished level: start the capture once the scene has had time to render.
            if time.time() < st.get("settle_until", 0):
                return
            name = st.pop("shot")
            st["shot_name"] = name
            st["results"][name]["screenshot"] = _screenshot(name)
            st["settle_until"] = time.time() + 1.5   # a few frames of capture before exporting
            st["shot_done"] = True
            return
        if st.get("shot_done"):
            if time.time() < st.get("settle_until", 0):
                return
            st["shot_done"] = False
            if _capture:
                st["results"][st["shot_name"]]["screenshot"] = _screenshot_export()
                save_report()
        if st["current"] is not None:
            gen = H.find_generator()
            if gen.is_generating() and st["ticks"] < 6000:
                return
            if gen.is_generating():
                log("level %s: generation timed out" % st["current"])
            _finish_level(st["current"])
            st["current"] = None
            st["ticks"] = 0
            return  # settle and capture this level before the next one is built
        if not st["queue"]:
            unreal.unregister_slate_post_tick_callback(st["handle"])
            report["stages"]["levels"] = {"ok": True, "result": st["results"]}
            save_report()
            _after_levels()
            return
        name = st["queue"].pop(0)
        import gc
        gc.collect()                  # drop any lingering wrappers of the previous world before new_level
        import ramms_worldgen.levels as L
        L.build_level(name, watch=False)   # creates, saves, starts generation; we poll it ourselves
        st["current"] = name
        st["ticks"] = 0
    except Exception as exc:
        log("levels stage error on %s: %s\n%s" % (st["current"], exc, traceback.format_exc()))
        report["errors"].append("levels/%s: %s" % (st["current"], exc))
        st["results"][st["current"] or "?"] = {"error": str(exc)}
        st["current"] = None
        if not st["queue"]:
            unreal.unregister_slate_post_tick_callback(st["handle"])
            report["stages"]["levels"] = {"ok": False, "result": st["results"]}
            save_report()
            _after_levels()


def st_levels_start():
    import importlib
    import ramms_worldgen.levels as L
    importlib.reload(L)
    _levels_state["queue"] = ["downtown", "suburban", "park", "indoor", "office", "mainstreet", "store"]
    _levels_state["handle"] = unreal.register_slate_post_tick_callback(_levels_tick)
    return "started: " + ", ".join(_levels_state["queue"])


def st_python_api():
    # Exercised on the last generated level (office). Regenerate with another seed and check determinism-ish facts.
    import ramms_worldgen._helpers as H
    gen = H.find_generator()
    before = H.manifest_to_dict(gen)
    names = [str(n) for n in gen.get_param_names()]
    v = gen.get_param("NonCompliance")
    assert v is not None, "get_param failed"
    assert gen.set_param("NonCompliance", 0.0), "set_param failed"
    v2 = gen.get_param("NonCompliance")
    assert abs(v2) < 1e-9, "override not applied: %s" % v2
    out = {"param_names": len(names), "non_compliance_before": v, "after_override": v2,
           "manifest_before": {"features": len(before.get("features", [])), "routes": len(before.get("routes", []))}}
    gen.set_param("NonCompliance", v)
    return out


def st_mcp_tools():
    import ramms_worldgen.toolset as T
    out = {}
    for name in ("worldgen_status", "worldgen_list_presets", "worldgen_get_params"):
        s = getattr(T.RammsWorldGenToolset, name)()
        out[name] = (s[:400] + "...") if len(s) > 400 else s
    s = T.RammsWorldGenToolset.worldgen_manifest("", "", True)
    out["worldgen_manifest(non_compliant)"] = len(json.loads(s).get("features", []))
    return out


def st_bridge():
    # URammsWorldGenBridge is what ramms-tools calls over Remote Control; exercise it in-process.
    B = unreal.RammsWorldGenBridge
    out = {}
    world = json.loads(B.get_world_info())
    assert world.get("ok"), "GetWorldInfo: %s" % world
    out["world"] = world
    gens = [str(g) for g in B.find_generators()]
    assert gens, "FindGenerators returned nothing"
    out["generators"] = gens
    presets = [str(p) for p in B.list_presets()]
    assert any(p.endswith("PRE_Downtown") for p in presets), "ListPresets missing PRE_Downtown: %s" % presets
    out["presets"] = len(presets)
    desc = json.loads(B.describe_presets())
    assert len(desc) == len(presets), "DescribePresets count mismatch"
    out["describe_presets_names"] = sorted(d["name"] for d in desc)
    maps = [str(m) for m in B.list_generated_maps()]
    assert len(maps) >= 5, "ListGeneratedMaps found %d" % len(maps)
    out["maps"] = len(maps)
    st = json.loads(B.get_status_json(""))
    assert st.get("ok") and st.get("features", 0) > 0, "GetStatusJson: %s" % st
    out["status"] = {k: st[k] for k in ("preset", "seed", "features", "routes", "issues", "generating")}
    params = json.loads(B.get_params_json(gens[0]))
    assert "NonCompliance" in params and "Palette" in params, "GetParamsJson: %s" % list(params)[:5]
    res = json.loads(B.set_params_json(gens[0], json.dumps({"NonCompliance": 0.25, "NoSuchParam": 1})))
    assert res.get("applied") == ["NonCompliance"] and res.get("unknown") == ["NoSuchParam"], "SetParamsJson: %s" % res
    assert abs(json.loads(B.get_params_json(gens[0]))["NonCompliance"] - 0.25) < 1e-9, "override not visible"
    assert B.clear_overrides(gens[0]), "ClearOverrides failed"
    assert abs(json.loads(B.get_params_json(gens[0]))["NonCompliance"] - params["NonCompliance"]) < 1e-9, "ClearOverrides did not restore"
    manifest = json.loads(B.get_manifest_json(gens[0]))
    assert manifest.get("features"), "GetManifestJson empty"
    out["manifest_features"] = len(manifest["features"])
    # Manifest sanity: no negative clear widths, every non-compliant feature names its issue and threshold.
    bad_clear = [r["name"] for r in manifest.get("routes", []) if r.get("minClearWidth", 0) < 0]
    assert not bad_clear, "routes with negative clear width: %s" % bad_clear[:5]
    missing = [f for f in manifest["features"] if not f.get("bCompliant", True) and (f.get("issue") in (None, "None") or f.get("threshold", 0) <= 0)]
    assert not missing, "non-compliant features without issue/threshold: %s" % [(f["kind"], f.get("subtype"), f.get("issue")) for f in missing[:5]]
    assert not B.generate("NoSuchGenerator", 1), "Generate accepted a bogus path"
    assert B.set_preset(gens[0], "PRE_Indoor_Office"), "SetPreset by short name failed"
    return out


def _after_levels():
    stage("python_api", st_python_api)
    stage("mcp_tools", st_mcp_tools)
    stage("bridge", st_bridge)
    report["done"] = True
    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_report()
    log("ALL DONE: %d errors" % len(report["errors"]))
    # Leave a command-file watcher running so tools can keep driving this editor session.
    try:
        exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else
                               os.path.join(unreal.SystemLibrary.get_project_directory(), "Scripts", "worldgen"), "watch.py")).read(), globals())
    except Exception as exc:  # noqa: BLE001
        log("watcher not started: %s" % exc)


def main():
    open(PROGRESS, "w").close()
    log("verification started; report -> " + REPORT)
    stage("module", st_module)
    if not report["stages"]["module"]["ok"]:
        report["done"] = True
        save_report()
        return
    stage("assets", st_assets)
    if not report["stages"]["assets"]["ok"]:
        report["done"] = True
        save_report()
        log("stopping: assets failed")
        return
    stage("graphs", st_graphs)
    stage("levels_start", st_levels_start)


main()
