"""Palette lineup: spawn every mesh of some slots the way the generator places them at yaw 0 (front to +X),
with a red marker in front of each, and screenshot them from the front.

    LINEUP = ["Furniture.TV", "Furniture.Sofa"]
    exec(open(r"C:/Users/waemf/data/ramms/Scripts/worldgen/lineup.py").read())

LINEUP_ONLY = {"SM_TV"} limits it to some meshes; LINEUP_CAM_YAW = 90 looks from +Y instead of +X.
A mesh whose back (or side) faces the camera has a wrong facing. Screenshots:
Saved/Screenshots/WindowsEditor/Lineup_<slot>_<n>.png (3 meshes per shot, +Y to the left), names in Saved/WorldGen/lineup.json.
"""
import json
import time
import unreal


def _lineup_rows(slots):
    pal = unreal.load_asset("/RammsWorldGen/Palettes/PAL_Default")
    smap = pal.get_editor_property("slots")
    rows = []
    for si, slot in enumerate(slots):
        entry = smap.get(unreal.Name(slot)) if hasattr(smap, "get") else None
        if entry is None:
            unreal.log_warning("[lineup] no slot %s" % slot)
            continue
        for mi, m in enumerate(entry.get_editor_property("meshes")):
            rows.append((slot, m))
    return rows


def _start_lineup(slots, top, only=(), cam_yaw=0):
    s = {"phase": "level", "until": 0.0, "i": 0, "handle": None, "views": [], "names": {}}
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    def spawn(cls, loc, rot=unreal.Rotator(0, 0, 0)):
        return eas.spawn_actor_from_class(cls, unreal.Vector(loc.x, loc.y + 300000.0, loc.z + 20000.0), rot)

    def build():
        rows = _lineup_rows(slots)
        sp = 320.0
        # lights + floor
        sun = spawn(unreal.DirectionalLight, unreal.Vector(0, 0, 1000), unreal.Rotator(roll=0, pitch=-50, yaw=200))
        spawn(unreal.SkyLight, unreal.Vector(0, 0, 500))
        try:
            spawn(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
        except Exception:  # noqa: BLE001
            pass
        cube = unreal.load_asset("/Engine/BasicShapes/Cube")
        red = unreal.load_asset("/Engine/BasicShapes/BasicShapeMaterial")
        groups = {}
        for i, (slot, m) in enumerate(rows):
            groups.setdefault(slot, []).append(m)
        y0 = 0.0
        for slot, metas in groups.items():
            for m in metas:
                y = y0
                mesh = m.get_editor_property("mesh")
                rot = m.get_editor_property("rotation_offset")
                off = m.get_editor_property("location_offset")
                sc = m.get_editor_property("scale")
                fp = m.get_editor_property("footprint")
                h = m.get_editor_property("height")
                parts = m.get_editor_property("parts")
                if mesh is None and not parts:
                    continue
                label = mesh.get_name() if mesh is not None else "composite%02d" % len(s["views"])
                if only and label not in only:
                    continue
                if parts:
                    # Composite (a captured house blueprint): every part placed as the generator does.
                    pivot = unreal.Transform(unreal.Vector(off.x, y + off.y + 300000.0, off.z + 20000.0), rot, unreal.Vector(sc, sc, sc))
                    for part in parts:
                        pm = part.get_editor_property("mesh")
                        if pm is None:
                            continue
                        xf = unreal.MathLibrary.compose_transforms(part.get_editor_property("relative_transform"), pivot)
                        a = eas.spawn_actor_from_class(unreal.StaticMeshActor, xf.translation, xf.rotation.rotator())
                        a.static_mesh_component.set_static_mesh(pm)
                        a.set_actor_scale3d(xf.scale3d)
                        for i, mat in enumerate(part.get_editor_property("materials")):
                            a.static_mesh_component.set_material(i, mat)
                else:
                    a = spawn(unreal.StaticMeshActor, unreal.Vector(off.x, y + off.y, off.z), rot)
                    a.static_mesh_component.set_static_mesh(mesh)
                    a.set_actor_scale3d(unreal.Vector(sc, sc, sc))
                mk = spawn(unreal.StaticMeshActor, unreal.Vector(fp.x * 0.5 + 40.0, y, 2.0))
                mk.static_mesh_component.set_static_mesh(cube)
                mk.set_actor_scale3d(unreal.Vector(0.4, 0.1, 0.04))
                size = max(fp.x, fp.y, h)
                name = "Lineup_%s_%s%s" % (slot, label, ("_y%d" % cam_yaw) if cam_yaw else "")
                # From the front, a little to the side (+Y) so depth reads.
                import math
                d = max(fp.x, fp.y) * 0.5 + size * 1.5 + 120.0
                cy = math.radians(cam_yaw)
                cam = unreal.Vector(math.cos(cy) * d - math.sin(cy) * size * 0.6, y + math.sin(cy) * d + math.cos(cy) * size * 0.6, h * 0.6 + 80.0)
                tgt = unreal.Vector(0, y, h * 0.45)
                off3 = unreal.Vector(0, 300000.0, 20000.0)
                s["views"].append((name, cam + off3, tgt + off3))
                s["names"][name] = mesh.get_path_name() if mesh is not None else label
                y0 += max(size * 3.0, 600.0)
        floor = spawn(unreal.StaticMeshActor, unreal.Vector(0, y0 * 0.5, -50))
        floor.static_mesh_component.set_static_mesh(cube)
        floor.set_actor_scale3d(unreal.Vector(40, y0 / 100.0 + 40, 1))
        json.dump(s["names"], open(unreal.Paths.project_saved_dir() + "WorldGen/lineup.json", "w"), indent=1)

    def shot(name):
        import os
        path = os.path.join(unreal.SystemLibrary.get_project_saved_directory(), "Screenshots", "WindowsEditor", name + ".png").replace("\\", "/")
        unreal.SystemLibrary.execute_console_command(unreal.EditorLevelLibrary.get_editor_world(), "HighResShot 1600x900 filename=%s" % path)

    def tick(dt):
        if time.time() < s["until"]:
            return
        try:
            if s["phase"] == "level":
                # Built far from the origin of a freshly loaded level (new_level crashes from a tick callback);
                # nothing is saved.
                unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level("/Game/Maps/Gen/Map_Gen_Indoor")
                s["phase"] = "build"; s["until"] = time.time() + 3.0
            elif s["phase"] == "build":
                build()
                s["phase"] = "cam"; s["until"] = time.time() + 5.0
            elif s["phase"] == "cam":
                if s["i"] >= len(s["views"]):
                    unreal.unregister_slate_post_tick_callback(s["handle"])
                    unreal.log("[lineup] done")
                    return
                name, cam, tgt = s["views"][s["i"]]
                unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(cam, unreal.MathLibrary.find_look_at_rotation(cam, tgt))
                s["phase"] = "shoot"; s["until"] = time.time() + 3.0
            elif s["phase"] == "shoot":
                shot(s["views"][s["i"]][0] + ("_top" if top else ""))
                s["i"] += 1; s["phase"] = "cam"; s["until"] = time.time() + 2.0
        except Exception as exc:  # noqa: BLE001
            unreal.log_warning("[lineup] %s" % exc)
            s["phase"] = "cam"; s["i"] += 1; s["until"] = time.time() + 1.0

    s["handle"] = unreal.register_slate_post_tick_callback(tick)


_start_lineup(list(globals().get("LINEUP", ["Furniture.TV"])), bool(globals().get("LINEUP_TOP", False)),
              set(globals().get("LINEUP_ONLY", ())), float(globals().get("LINEUP_CAM_YAW", 0.0)))
for _k in ("LINEUP", "LINEUP_TOP", "LINEUP_ONLY", "LINEUP_CAM_YAW"):
    globals().pop(_k, None)
