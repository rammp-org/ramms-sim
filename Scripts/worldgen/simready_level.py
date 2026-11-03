"""Editor: generate a level from SimReady assets, with the articulated ones placed as URLab articulations that
run on MuJoCo or Chaos, and save it (outside Content/Maps/Gen; the level references /Game/SimReady, which is not
committed, so neither is the level).

    import unreal; exec(open(unreal.Paths.project_dir() + "Scripts/worldgen/simready_level.py").read())

Needs PAL_SimReady built with articulated stand-ins (ramms-worldgen README, "Articulated SimReady assets in
generated levels"). Options (consumed): SL_MAP (default /Game/Maps/SimReady/Map_SimReady_Home), SL_PRESET
(PRE_Indoor_Home), SL_SEED (19: a furnished home with eight articulations), SL_PALETTE (PAL_SimReady), SL_ENGINE
("Chaos", "MuJoCo" or "Auto": the level's ARammsPhysicsSettings; a run can still override it with -RammsPhysics= or
ramms.Physics.Engine), SL_SUN ((pitch, yaw) of the sun, default (-60, 200): high enough to light the roofless rooms
from above), SL_TIMEOUT (600 s of generation before giving up). Writes Saved/WorldGen/simready_level.json: the
level's articulations when it is saved, else {"error": ...}. It stops before touching any level when the target
cannot be opened or created (a cancelled save prompt), and without saving when the palette does not load, the
editor leaves the level or generation does not finish.
"""
import json, os, unreal

_SL = {k: globals().pop(k) for k in list(globals()) if k.startswith("SL_")}

def _simready_level(opts):
    import ramms_worldgen._helpers as H
    import ramms_worldgen.levels as L
    import ramms_worldgen.presets as PR
    path = opts.get("SL_MAP", "/Game/Maps/SimReady/Map_SimReady_Home")
    seed = int(opts.get("SL_SEED", 19))
    engine = opts.get("SL_ENGINE", "Chaos")
    out_dir = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "WorldGen")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "simready_level.json")
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    def report(rec):
        json.dump(rec, open(out, "w"), indent=1)
        (unreal.log_error if "error" in rec else unreal.log)("[simready_level] %s" % rec)

    def fail(msg):
        report({"map": path, "seed": seed, "error": msg})

    def on_target():
        # Nothing below may touch a level other than the one asked for (a cancelled save prompt leaves the old one open).
        w = H.editor_world()
        return w if w and w.get_outermost().get_name() == path else None

    preset = PR.load_preset(opts.get("SL_PRESET", "PRE_Indoor_Home"))
    if preset is None:
        return fail("preset %s did not load" % opts.get("SL_PRESET", "PRE_Indoor_Home"))
    if H.EAL.does_asset_exist(path):
        if not les.load_level(path) or not on_target():
            return fail("could not open %s (a save prompt cancelled?); nothing changed" % path)
        for a in list(eas.get_all_level_actors()):
            if isinstance(a, unreal.RammsWorldGenerator):
                a.cleanup()
        eas.destroy_actors(list(eas.get_all_level_actors()))
    else:
        H.ensure_dir(path.rsplit("/", 1)[0])
        if not les.new_level(path) or not on_target():
            return fail("could not create %s (a save prompt cancelled?); nothing changed" % path)
    world = on_target()
    indoor = preset.get_editor_property("scene_kind") == unreal.RammsSceneKind.INDOOR
    L._add_lighting(indoor)
    sun = opts.get("SL_SUN", (-60.0, 200.0))
    for a in eas.get_all_level_actors():
        if isinstance(a, unreal.DirectionalLight):
            a.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=sun[0], yaw=sun[1]), False)
    pal_name = opts.get("SL_PALETTE", "PAL_SimReady")
    pal = unreal.load_asset(H.PALETTES + "/" + pal_name)
    if pal is None:
        return fail("palette %s did not load (build it with ramms_worldgen.simready, see the RammsWorldGen README); level not saved" % pal_name)
    params = preset.get_editor_property("params")
    site = max(params.get_editor_property("site_size_x"), params.get_editor_property("site_size_y"))
    L._add_ground(max(site * 3.0, 24000.0), pal.material_path("Mat.Concrete" if indoor else "Mat.Lawn"))
    settings = L._spawn(unreal.RammsPhysicsSettings, label="PhysicsSettings")
    settings.set_editor_property("engine", {"chaos": unreal.RammsLevelPhysicsEngine.CHAOS, "mujoco": unreal.RammsLevelPhysicsEngine.MU_JO_CO}.get(engine.lower(), unreal.RammsLevelPhysicsEngine.AUTO))
    gen = L._spawn(unreal.RammsWorldGenerator, label="WorldGenerator")
    gen.set_editor_property("preset", preset)
    gen.set_editor_property("seed", seed)
    gen.set_editor_property("generate_on_begin_play", False)
    if not gen.set_palette(pal_name):
        return fail("the generator would not take palette %s; level not saved" % pal_name)
    world.get_world_settings().set_editor_property("default_game_mode", unreal.GameModeBase)
    unreal.EditorLoadingAndSavingUtils.save_current_level()
    if not gen.regenerate():
        return fail("generation could not start (no PCG graph?); the level is saved without a world")
    timeout = float(opts.get("SL_TIMEOUT", 600.0))
    state = {"t": 0.0}

    def tick(dt):
        state["t"] += dt
        try:
            # The generator this script started, in the level it made: never another level's.
            if on_target() is None or gen is None or gen.get_world() != world:
                raise RuntimeError("the editor left %s before generation finished; not saved" % path)
            if gen.is_generating():
                if state["t"] < timeout:
                    return
                raise RuntimeError("generation still running after %.0f s; not saved" % timeout)
            unreal.unregister_slate_post_tick_callback(state["h"])
            gen.place_player_start()
            arts = gen.get_articulated_actors()
            unreal.EditorLoadingAndSavingUtils.save_current_level()
            report({"map": path, "seed": seed, "engine": engine, "features": len(H.manifest_to_dict(gen).get("features", [])),
                    "articulated": sorted(["%s %s" % (a.get_class().get_name(), [str(t) for t in a.tags if str(t).startswith("RammsSlot:")]),
                                           [round(v) for v in (a.get_actor_location().x, a.get_actor_location().y, a.get_actor_location().z)],
                                           round(a.get_actor_rotation().yaw)] for a in arts)})
        except Exception as exc:  # noqa: BLE001
            try:
                unreal.unregister_slate_post_tick_callback(state["h"])
            except Exception:  # noqa: BLE001
                pass
            fail(str(exc))

    state["h"] = unreal.register_slate_post_tick_callback(tick)

_simready_level(_SL)
del _simready_level, _SL
