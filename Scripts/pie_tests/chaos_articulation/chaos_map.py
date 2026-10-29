"""Editor: build a scratch level with URLab articulations to run on Chaos (see README.md).

    import unreal; D = unreal.Paths.project_dir() + "Scripts/pie_tests/chaos_articulation/"
    exec(open(D + "chaos_map.py").read())

Options (consumed): CA_MAP (level path, default /Game/ChaosProto/Map_ChaosArticulation),
CA_ACTORS ([(Blueprint path, (x, y, z))]; default: the Gen3 + 2F-85 and, when present locally, the
SimReady refrigerator and microwave and the lift-drive linkage base), CA_CAM ((location, look-at), or
None for no camera). The level gets a plain game mode,
so the project's default pawn stays out of the way, and no MuJoCo manager. It is scratch: don't commit
it. Writes Saved/ChaosArticulation/map.log.
"""
import os, unreal

_CA = {k: globals().pop(k) for k in list(globals()) if k.startswith("CA_")}

def _chaos_map(opts):
    out_dir = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "ChaosArticulation")
    os.makedirs(out_dir, exist_ok=True)
    log = []
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    acs = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    eas = unreal.EditorAssetLibrary
    actors = opts.get("CA_ACTORS") or [
        ("/Game/Robots/URL/gen3_2f85_fixed", (0.0, 0.0, 0.0)),
        ("/Game/SimReady/MuJoCo/sr_fc_refrigerator", (300.0, 0.0, 0.0)),
        ("/Game/SimReady/MuJoCo/sr_fc_microwave_oven", (300.0, 200.0, 60.0)),
        ("/RammsPrivateAssets/Robots/URL/lift_drive_linkage", (0.0, -300.0, 1.0)),
    ]
    level = opts.get("CA_MAP", "/Game/ChaosProto/Map_ChaosArticulation")
    try:
        if eas.does_asset_exist(level):
            les.load_level(level)
        else:
            les.new_level_from_template(level, "/Engine/Maps/Templates/Template_Default")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        world.get_world_settings().set_editor_property("default_game_mode", unreal.GameModeBase)
        for a in acs.get_all_level_actors():
            if str(a.get_folder_path()) == "ChaosArticulation":
                acs.destroy_actor(a)
            elif isinstance(a, unreal.PlayerStart):
                a.set_actor_location(unreal.Vector(-900.0, 0.0, 100.0), False, False)
        for path, loc in actors:
            if not eas.does_asset_exist(path):
                log.append("skip %s (not in this project)" % path)
                continue
            a = acs.spawn_actor_from_class(eas.load_blueprint_class(path), unreal.Vector(*loc), unreal.Rotator())
            a.set_folder_path("ChaosArticulation")
            log.append("placed %s at %s" % (path, loc))
        cam = opts.get("CA_CAM", ((470.0, -230.0, 210.0), (170.0, 90.0, 70.0)))   # frames the arm and the SimReady pair
        if cam:
            loc = unreal.Vector(*cam[0])
            c = acs.spawn_actor_from_class(unreal.CameraActor, loc, unreal.MathLibrary.find_look_at_rotation(loc, unreal.Vector(*cam[1])))
            c.set_folder_path("ChaosArticulation")
            c.set_editor_property("auto_activate_for_player", unreal.AutoReceiveInput.PLAYER0)
        les.save_current_level()
        log.append("saved %s" % level)
    except Exception:
        import traceback
        log.append(traceback.format_exc())
    with open(os.path.join(out_dir, "map.log"), "w") as f:
        f.write("\n".join(log) + "\n")

_chaos_map(_CA)
del _chaos_map, _CA
