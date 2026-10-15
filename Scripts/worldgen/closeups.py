"""Street-level close-ups of one example level, for judging facades and props.

    exec(open(r"C:/Users/waemf/data/ramms/Scripts/worldgen/closeups.py").read())
Set CLOSEUP_MAP / CLOSEUP_VIEWS before exec to change the level or the camera list; CLOSEUP_NO_LOAD = True
shoots the level that is already open (e.g. freshly regenerated) instead of reloading it from disk.
Each run keeps its own state, so overlapping runs do not interfere (they queue behind each other).
Screenshots: Saved/Screenshots/WindowsEditor/Close_<Map>_<n>.png
"""
import time
import unreal

_DEFAULT_VIEWS = [
    ((-0.02, -0.52, 0.012), (-0.02, 0.0, 0.03)),   # standing on a street, looking along it
    ((-0.26, -0.30, 0.015), (0.0, -0.10, 0.05)),   # a facade from the sidewalk
    ((0.20, 0.05, 0.10), (0.0, 0.30, 0.0)),        # low oblique over a block
    ((0.0, -0.40, 0.25), (0.0, 0.0, 0.0)),         # elevated
]
# Park callbacks left by the old global-state version of this script.
if isinstance(globals().get("st"), dict):
    globals()["st"]["until"] = 1e18
_q = globals().setdefault("_RAMMS_CLOSEUP_QUEUE", {"busy": False})


def _shot(name):
    # The console command is more dependable than AutomationLibrary.take_high_res_screenshot, which can stop
    # producing files after an interrupted request.
    import os
    path = os.path.join(unreal.SystemLibrary.get_project_saved_directory(), "Screenshots", "WindowsEditor", name + ".png").replace("\\", "/")
    unreal.SystemLibrary.execute_console_command(unreal.EditorLevelLibrary.get_editor_world(), "HighResShot 1600x900 filename=%s" % path)


def _start_closeups(map_path, views, no_load):
    s = {"phase": "wait", "until": 0.0, "i": 0, "handle": None}

    def cam(i):
        import ramms_worldgen._helpers as H
        gen = H.find_generator()
        p = gen.get_editor_property("params")
        d = max(p.get_editor_property("site_size_x"), p.get_editor_property("site_size_y"))
        loc = gen.get_actor_location()
        (ox, oy, oz), (tx, ty, tz) = views[i]
        c = unreal.Vector(loc.x + d * ox, loc.y + d * oy, loc.z + d * oz)
        t = unreal.Vector(loc.x + d * tx, loc.y + d * ty, loc.z + d * tz)
        unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(c, unreal.MathLibrary.find_look_at_rotation(c, t))

    def tick(dt):
        if time.time() < s["until"]:
            return
        try:
            if s["phase"] == "wait":
                if _q["busy"]:
                    return
                _q["busy"] = True
                if not no_load:
                    unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(map_path)
                s["phase"] = "cam"; s["until"] = time.time() + 3.0
            elif s["phase"] == "cam":
                if s["i"] >= len(views):
                    unreal.unregister_slate_post_tick_callback(s["handle"])
                    _q["busy"] = False
                    unreal.log("[closeups] done %s" % map_path)
                    return
                cam(s["i"]); s["phase"] = "shoot"; s["until"] = time.time() + 4.0
            elif s["phase"] == "shoot":
                _shot("Close_%s_%d" % (map_path.rsplit("/", 1)[-1], s["i"]))
                s["i"] += 1; s["phase"] = "cam"; s["until"] = time.time() + 2.0
        except Exception as exc:
            unreal.log_warning("[closeups] %s" % exc); s["phase"] = "cam"; s["i"] += 1; s["until"] = time.time() + 1.0

    s["handle"] = unreal.register_slate_post_tick_callback(tick)
    unreal.log("[closeups] queued %s (%d views)" % (map_path, len(views)))


_start_closeups(globals().get("CLOSEUP_MAP", "/Game/Maps/Gen/Map_Gen_Downtown"), list(globals().get("CLOSEUP_VIEWS", _DEFAULT_VIEWS)),
                bool(globals().get("CLOSEUP_NO_LOAD", False)))
for _k in ("CLOSEUP_MAP", "CLOSEUP_VIEWS", "CLOSEUP_NO_LOAD"):
    globals().pop(_k, None)
