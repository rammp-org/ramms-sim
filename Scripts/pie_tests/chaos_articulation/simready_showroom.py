"""Editor: a showroom level of articulated SimReady assets (URLab articulations from Tools/simready_mjcf.py) and a
few static SimReady props, with an ARammsPhysicsSettings, for running the same assets on MuJoCo and on Chaos.
The level references /Game/SimReady, which is not committed, so neither is the level.

    import unreal; D = unreal.Paths.project_dir() + "Scripts/pie_tests/chaos_articulation/"
    exec(open(D + "simready_showroom.py").read())

Options (consumed): SH_MAP (default /Game/Maps/SimReady/Map_SimReady_Showroom), SH_ENGINE ("Chaos", the default,
"MuJoCo" or "Auto"; a run can override it with -RammsPhysics= or ramms.Physics.Engine; Auto leaves the imported
articulations unsimulated, as they carry no Chaos component and the level no MuJoCo manager), SH_ROWS (list of rows,
each a list of (Blueprint or static mesh path, yaw)). Writes Saved/ChaosArticulation/showroom.log; when the level
cannot be opened or created (a cancelled save prompt) it stops before touching any level.
"""
import os, unreal

_SH = {k: globals().pop(k) for k in list(globals()) if k.startswith("SH_")}

MJ = "/Game/SimReady/MuJoCo/"
ROWS = [
    # back row: tall appliances and cabinets, fronts toward -Y (the camera)
    [(MJ + "sr_fc_refrigerator", 180.0), (MJ + "sr_fc_kitchen_base_cabinet", 180.0), (MJ + "sr_fc_range_oven", 180.0),
     (MJ + "sr_fc_front_load_washer", 180.0), (MJ + "sr_fc_chest_of_drawers", 180.0), (MJ + "sr_fc_vanity_sink_faucet", 180.0)],
    # front row: small things
    [(MJ + "sr_fc_pedal_trash_can", 180.0), (MJ + "sr_fc_microwave_oven", 180.0), (MJ + "sr_fc_wheelie_bin", 180.0)],
]

def _showroom(opts):
    out_dir = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "ChaosArticulation")
    os.makedirs(out_dir, exist_ok=True)
    log = []
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    acs = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    eas = unreal.EditorAssetLibrary
    level = opts.get("SH_MAP", "/Game/Maps/SimReady/Map_SimReady_Showroom")
    rows = opts.get("SH_ROWS", ROWS)
    try:
        if eas.does_asset_exist(level):
            ok = les.load_level(level)
        else:
            ok = les.new_level_from_template(level, "/Engine/Maps/Templates/Template_Default")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        if not ok or not world or world.get_outermost().get_name() != level:
            raise RuntimeError("could not open or create %s (a save prompt cancelled?); nothing changed" % level)
        world.get_world_settings().set_editor_property("default_game_mode", unreal.GameModeBase)
        for a in acs.get_all_level_actors():
            if str(a.get_folder_path()) == "Showroom":
                acs.destroy_actor(a)
            elif isinstance(a, unreal.PlayerStart):
                a.set_actor_location(unreal.Vector(0.0, -900.0, 100.0), False, False)
            elif isinstance(a, unreal.DirectionalLight):
                a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=-35.0, yaw=60.0), False)   # light the fronts (they face -Y)
        st = acs.spawn_actor_from_class(unreal.RammsPhysicsSettings, unreal.Vector(0, 0, 0))
        st.set_folder_path("Showroom")
        st.set_editor_property("engine", {"chaos": unreal.RammsLevelPhysicsEngine.CHAOS, "mujoco": unreal.RammsLevelPhysicsEngine.MU_JO_CO}.get(str(opts.get("SH_ENGINE", "Chaos")).lower(), unreal.RammsLevelPhysicsEngine.AUTO))
        # a camera for recordings (simready_open.py's SO_FRAMES moves it to SO_CAM and turns it on)
        cl = unreal.Vector(0.0, -950.0, 280.0)
        sc = acs.spawn_actor_from_class(unreal.SceneCapture2D, cl, unreal.MathLibrary.find_look_at_rotation(cl, unreal.Vector(0.0, -150.0, 60.0)))
        sc.set_folder_path("Showroom")
        sc.capture_component2d.set_editor_property("capture_every_frame", False)
        y = 0.0
        for row in rows:
            # measure first, then lay the row out centred on x = 0 with 40 cm between pieces
            items = []
            for path, yaw in row:
                if not eas.does_asset_exist(path):
                    log.append("skip %s (not in this project)" % path)
                    continue
                asset = eas.load_asset(path)
                if isinstance(asset, unreal.StaticMesh):
                    a = acs.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, 0), unreal.Rotator(yaw=yaw))
                    a.static_mesh_component.set_static_mesh(asset)
                else:
                    a = acs.spawn_actor_from_class(eas.load_blueprint_class(path), unreal.Vector(0, 0, 0), unreal.Rotator(yaw=yaw))
                a.set_folder_path("Showroom")
                o, e = a.get_actor_bounds(False, False)
                items.append((a, path, o, e))
            width = sum(2.0 * e.x for _a, _p, _o, e in items) + 40.0 * max(len(items) - 1, 0)
            x = -width / 2.0
            depth = max([2.0 * e.y for _a, _p, _o, e in items] or [0.0])
            for a, path, o, e in items:
                loc = a.get_actor_location()
                # bounds centre to (x + half width, y), bottom on the floor (z = 0)
                a.set_actor_location(unreal.Vector(loc.x + (x + e.x) - o.x, loc.y + y - o.y, loc.z - (o.z - e.z)), False, False)
                x += 2.0 * e.x + 40.0
                log.append("placed %s" % path)
            y -= depth + 160.0
        les.save_current_level()
        log.append("saved %s" % level)
    except Exception:
        import traceback
        log.append(traceback.format_exc())
    with open(os.path.join(out_dir, "showroom.log"), "w") as f:
        f.write("\n".join(log) + "\n")

_showroom(_SH)
del _showroom, _SH
