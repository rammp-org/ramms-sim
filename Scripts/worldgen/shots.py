"""Open each example level in turn, frame it, let it render, and take a viewport screenshot.

Run from the editor's Python console:
    exec(open(r"C:/Users/waemf/data/ramms/Scripts/worldgen/shots.py").read())
Screenshots land in Saved/Screenshots/WindowsEditor/Shot_<Map>.png; a summary in Saved/WorldGen/shots.json.
"""
import json, os, time
import unreal

MAPS = ["/Game/Maps/Gen/Map_Gen_Downtown", "/Game/Maps/Gen/Map_Gen_Suburban", "/Game/Maps/Gen/Map_Gen_Park",
        "/Game/Maps/Gen/Map_Gen_Indoor", "/Game/Maps/Gen/Map_Gen_Office", "/Game/Maps/Gen/Map_Gen_MainStreet",
        "/Game/Maps/Gen/Map_Gen_Store"]
OUT = os.path.join(unreal.SystemLibrary.get_project_saved_directory(), "WorldGen", "shots.json")
state = {"queue": list(MAPS), "phase": "load", "until": 0.0, "results": {}, "handle": None, "busy": False}


def frame():
    import ramms_worldgen._helpers as H
    gen = H.find_generator()
    params = gen.get_editor_property("params")
    d = max(params.get_editor_property("site_size_x"), params.get_editor_property("site_size_y"))
    preset = gen.get_editor_property("preset")
    indoor = preset.get_editor_property("scene_kind") == unreal.RammsSceneKind.INDOOR if preset else False
    loc = gen.get_actor_location()
    cam = unreal.Vector(loc.x - d * 0.35, loc.y - d * 0.9, loc.z + d * 0.9) if indoor else unreal.Vector(loc.x - d * 0.55, loc.y - d * 0.9, loc.z + d * 0.75)
    rot = unreal.MathLibrary.find_look_at_rotation(cam, loc)
    unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(cam, rot)
    # what is actually in the level
    kinds = {}
    for a in H.level_actors():
        if isinstance(a, unreal.RammsProcPiece):
            k = str(a.get_editor_property("manifest_kind")) or "piece"
            kinds[k] = kinds.get(k, 0) + 1
    ism = sum(c.get_instance_count() for c in gen.get_components_by_class(unreal.InstancedStaticMeshComponent))
    return {"preset": preset.get_name() if preset else None, "seed": gen.get_editor_property("seed"), "pieces_by_kind": kinds, "ism_instances": ism}


def tick(dt):
    if state["busy"]:
        return
    state["busy"] = True
    try:
        if time.time() < state["until"]:
            return
        if state["phase"] == "load":
            if not state["queue"]:
                unreal.unregister_slate_post_tick_callback(state["handle"])
                json.dump(state["results"], open(OUT, "w"), indent=2)
                unreal.log("[shots] done -> " + OUT)
                return
            path = state["queue"].pop(0)
            unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(path)
            state["current"] = path.rsplit("/", 1)[-1]
            state["phase"] = "frame"
            state["until"] = time.time() + 2.0
        elif state["phase"] == "frame":
            state["results"][state["current"]] = frame()
            state["phase"] = "shoot"
            state["until"] = time.time() + 5.0
        elif state["phase"] == "shoot":
            import os
            path = os.path.join(unreal.SystemLibrary.get_project_saved_directory(), "Screenshots", "WindowsEditor", "Shot_%s.png" % state["current"]).replace("\\", "/")
            unreal.SystemLibrary.execute_console_command(unreal.EditorLevelLibrary.get_editor_world(), "HighResShot 1600x900 filename=%s" % path)
            state["phase"] = "load"
            state["until"] = time.time() + 2.0
    except Exception as exc:
        unreal.log_warning("[shots] %s: %s" % (state.get("current"), exc))
        state["phase"] = "load"
        state["until"] = time.time() + 1.0
    finally:
        state["busy"] = False


state["handle"] = unreal.register_slate_post_tick_callback(tick)
unreal.log("[shots] started")
