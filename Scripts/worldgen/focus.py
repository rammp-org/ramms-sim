"""Close-ups aimed at generated features, found in the level's manifest.

    FOCUS_MAP = "/Game/Maps/Gen/Map_Gen_Store"
    FOCUS = [("Furniture", "Store.ProduceTable", 320.0, 165.0), ("Aisle", None, 0.0, 160.0)]
    exec(open(r"C:/Users/waemf/data/ramms/Scripts/worldgen/focus.py").read())

Each entry is (manifest kind, subtype or None, distance, eye height): the camera stands `distance` cm in
front of the first matching feature (along its yaw) at `eye height`, looking at it. Aisles (distance 0)
are looked down from one end. Screenshots: Saved/Screenshots/WindowsEditor/Focus_<Map>_<n>.png.
"""
import math
import time
import unreal


def _focus_views(entries):
    import ramms_worldgen._helpers as H
    gen = H.find_generator()
    feats = H.manifest_to_dict(gen).get("features", [])
    views = []
    used = set()
    for kind, sub, dist, eye in entries:
        for i, f in enumerate(feats):
            if i in used or f.get("kind") != kind or (sub is not None and f.get("subtype") != sub):
                continue
            used.add(i)
            loc, rot, size = f["location"], f["rotation"], f["size"]
            yaw = math.radians(rot.get("yaw", 0.0))
            tx, ty, tz = loc["x"], loc["y"], loc["z"]
            if dist <= 0.0:
                # Look down the long axis of a box feature (aisles, lanes) from just outside one end.
                lx, ly = (size["x"], 0.0) if size["x"] >= size["y"] else (0.0, size["y"])
                half = max(size["x"], size["y"]) * 0.5
                ax, ay = (1.0, 0.0) if size["x"] >= size["y"] else (0.0, 1.0)
                cam = unreal.Vector(tx - ax * (half + 60.0), ty - ay * (half + 60.0), tz + eye)
                tgt = unreal.Vector(tx + ax * half, ty + ay * half, tz + eye * 0.6)
            else:
                cam = unreal.Vector(tx + math.cos(yaw) * dist, ty + math.sin(yaw) * dist, tz + eye)
                tgt = unreal.Vector(tx, ty, tz + 80.0)
            views.append((cam, tgt))
            break
    return views


def _start_focus(map_path, entries, no_load):
    s = {"phase": "load", "until": 0.0, "i": 0, "handle": None, "views": []}

    def shot(name):
        import os
        path = os.path.join(unreal.SystemLibrary.get_project_saved_directory(), "Screenshots", "WindowsEditor", name + ".png").replace("\\", "/")
        unreal.SystemLibrary.execute_console_command(unreal.EditorLevelLibrary.get_editor_world(), "HighResShot 1600x900 filename=%s" % path)

    def tick(dt):
        if time.time() < s["until"]:
            return
        try:
            if s["phase"] == "load":
                if not no_load:
                    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(map_path)
                s["phase"] = "plan"; s["until"] = time.time() + 3.0
            elif s["phase"] == "plan":
                s["views"] = _focus_views(entries)
                unreal.log("[focus] %d views for %s" % (len(s["views"]), map_path))
                s["phase"] = "cam"
            elif s["phase"] == "cam":
                if s["i"] >= len(s["views"]):
                    unreal.unregister_slate_post_tick_callback(s["handle"])
                    unreal.log("[focus] done %s" % map_path)
                    return
                cam, tgt = s["views"][s["i"]]
                unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(cam, unreal.MathLibrary.find_look_at_rotation(cam, tgt))
                s["phase"] = "shoot"; s["until"] = time.time() + 4.0
            elif s["phase"] == "shoot":
                shot("Focus_%s_%d" % (map_path.rsplit("/", 1)[-1], s["i"]))
                s["i"] += 1; s["phase"] = "cam"; s["until"] = time.time() + 2.0
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning("[focus] %s" % exc)
            s["phase"] = "cam"; s["i"] += 1; s["until"] = time.time() + 1.0

    s["handle"] = unreal.register_slate_post_tick_callback(tick)


_start_focus(globals().get("FOCUS_MAP", "/Game/Maps/Gen/Map_Gen_Store"), list(globals().get("FOCUS", [])), bool(globals().get("FOCUS_NO_LOAD", False)))
for _k in ("FOCUS_MAP", "FOCUS", "FOCUS_NO_LOAD"):
    globals().pop(_k, None)
