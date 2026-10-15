"""Assemble the example levels: lights, a ground slab, a generator with a
preset and seed, the Mebot game mode, and a PlayerStart on the first route.

Generation is asynchronous, so the level is saved from a tick callback once
the generator reports it is done.
"""

import unreal

from . import _helpers as H
from . import presets as PR

GAME_MODE = "/Game/BP_MebotGameMode.BP_MebotGameMode_C"

EXAMPLES = {
    "downtown": ("Map_Gen_Downtown", "PRE_Downtown", 7),
    "suburban": ("Map_Gen_Suburban", "PRE_Suburban", 11),
    "park": ("Map_Gen_Park", "PRE_Park", 3),
    "indoor": ("Map_Gen_Indoor", "PRE_Indoor_Home", 5),
    "office": ("Map_Gen_Office", "PRE_Indoor_Office", 2),
    "mainstreet": ("Map_Gen_MainStreet", "PRE_MainStreet", 4),
    "store": ("Map_Gen_Store", "PRE_Indoor_Store", 6),
}

_pending = {}


def _spawn(cls, loc=(0, 0, 0), rot=(0, 0, 0), label=None):
    """rot is (pitch, yaw, roll) in degrees. unreal.Rotator's positional order is (roll, pitch, yaw),
    so it is built with keywords; getting this wrong points the sun at the sky."""
    pitch, yaw, roll = rot
    actor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(
        cls, unreal.Vector(*loc), unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw))
    if label and actor:
        actor.set_actor_label(label)
    return actor


def _add_lighting(indoor):
    sun = _spawn(unreal.DirectionalLight, (0, 0, 1000), (-50, 30, 0), "Sun")
    if sun:
        comp = sun.get_component_by_class(unreal.DirectionalLightComponent)
        comp.set_intensity(4.0 if indoor else 8.0)
        comp.set_editor_property("atmosphere_sun_light", True)
    sky = _spawn(unreal.SkyLight, (0, 0, 800), label="SkyLight")
    if sky:
        comp = sky.get_component_by_class(unreal.SkyLightComponent)
        comp.set_editor_property("real_time_capture", True)
        comp.set_intensity(1.5 if indoor else 1.0)
    _spawn(unreal.SkyAtmosphere, label="SkyAtmosphere")
    fog = _spawn(unreal.ExponentialHeightFog, (0, 0, -200), label="Fog")
    if fog:
        fog.get_component_by_class(unreal.ExponentialHeightFogComponent).set_editor_property("fog_density", 0.002 if indoor else 0.004)


def _add_ground(size, material_path):
    """A wide slab under the site so the robot never falls off the edge of the world."""
    piece = _spawn(unreal.RammsProcPiece, (-size * 0.5, 0, -45.0), label="Ground")
    if piece:
        piece.set_editor_property("kind", unreal.RammsProcPieceKind.SLAB)
        piece.set_editor_property("size_x", size)
        piece.set_editor_property("size_y", size)
        piece.set_editor_property("size_z", 50.0)
        piece.set_editor_property("material_path", material_path)
        piece.set_editor_property("uv_scale", 400.0)
        piece.rebuild()
    return piece


def build_level(kind, seed=None, open_after=True, watch=True):
    """Create (or recreate) one example level and start its generation."""
    if kind not in EXAMPLES:
        raise RuntimeError("unknown example '%s'; choose from %s" % (kind, list(EXAMPLES)))
    map_name, preset_name, default_seed = EXAMPLES[kind]
    seed = default_seed if seed is None else int(seed)
    preset = PR.load_preset(preset_name)
    indoor = preset.get_editor_property("scene_kind") == unreal.RammsSceneKind.INDOOR
    path = H.MAPS + "/" + map_name

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    H.ensure_dir(H.MAPS)
    if H.EAL.does_asset_exist(path):
        # new_level() refuses to overwrite and a loaded map cannot be deleted, so reuse it: load and empty it.
        if H.editor_world().get_path_name() != "%s.%s" % (path, map_name):
            if not les.load_level(path):
                raise RuntimeError("could not load existing level %s" % path)
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actors = list(eas.get_all_level_actors())
        for a in actors:
            if isinstance(a, unreal.RammsWorldGenerator):
                a.cleanup()
        eas.destroy_actors(actors)
    elif not les.new_level(path):
        raise RuntimeError("could not create level %s" % path)
    world = H.editor_world()

    _add_lighting(indoor)
    params = preset.get_editor_property("params")
    site = max(params.get_editor_property("site_size_x"), params.get_editor_property("site_size_y"))
    palette = preset.get_editor_property("palette")
    ground_mat = ""
    if palette:
        ground_mat = palette.material_path("Mat.Lawn" if not indoor else "Mat.Concrete")
    # Wide enough that the horizon is ground, not the black below-horizon side of the sky atmosphere.
    _add_ground(max(site * 3.0, 24000.0), ground_mat)

    gen = _spawn(unreal.RammsWorldGenerator, (0, 0, 0), label="WorldGenerator")
    gen.set_editor_property("preset", preset)
    gen.set_editor_property("seed", seed)
    gen.set_editor_property("generate_on_begin_play", False)

    gm = unreal.load_class(None, GAME_MODE)
    if gm:
        world.get_world_settings().set_editor_property("default_game_mode", gm)
    else:
        H.warn("game mode %s not found; the level keeps the project default" % GAME_MODE)

    unreal.EditorLoadingAndSavingUtils.save_current_level()
    gen.regenerate()
    if watch:
        _pending[path] = True
        _watch(path)
    H.log("level %s: preset %s seed %d, generating..." % (path, preset_name, seed))
    return path


def _watch(path):
    """Poll the generator; when done, place the PlayerStart and save the level.

    The generator is looked up every tick rather than captured: a Python
    reference to an actor keeps its world alive, and a world that survives
    the next new_level() is a fatal "World Memory Leaks" error in the editor.
    """
    state = {"ticks": 0, "busy": False, "handle": None}

    def on_tick(dt):
        if state["busy"]:
            return  # new_level / save pump Slate, which re-enters this callback
        state["busy"] = True
        finished = False
        try:
            state["ticks"] += 1
            gen = H.find_generator()
            if gen.is_generating() and state["ticks"] < 3000:
                return
            finished = True
            gen.place_player_start()
            unreal.EditorLoadingAndSavingUtils.save_current_level()
            m = H.manifest_to_dict(gen)
            H.log("level %s generated: %d features, %d routes, saved." % (path, len(m.get("features", [])), len(m.get("routes", []))))
        except Exception as exc:  # the editor must keep ticking whatever happens here
            finished = True
            H.warn("level %s: post-generation step failed: %s" % (path, exc))
        finally:
            if finished:
                unreal.unregister_slate_post_tick_callback(state["handle"])
                _pending.pop(path, None)
            state["busy"] = False

    state["handle"] = unreal.register_slate_post_tick_callback(on_tick)


def build_all_levels(kinds=None):
    """Build the example levels one after another (each waits for the previous generation)."""
    kinds = list(kinds or EXAMPLES)
    if not kinds:
        return []
    done = []
    guard = {"busy": False}

    def next_one(dt):
        if _pending or guard["busy"]:
            return
        guard["busy"] = True
        if not kinds:
            unreal.unregister_slate_post_tick_callback(state["handle"])
            H.log("all example levels built: %s" % done)
            return
        k = kinds.pop(0)
        try:
            done.append(build_level(k))
        except Exception as exc:
            H.warn("example '%s' failed: %s" % (k, exc))
        finally:
            guard["busy"] = False

    state = {"handle": unreal.register_slate_post_tick_callback(next_one)}
    return done
