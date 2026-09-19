"""Author a Newton-behind-URLab test level from scratch.

The scene is a URLab manager, the Newton solver component that installs a custom
step handler on its physics engine, lighting, a convertible ground, and a
framing camera. By default it also builds a one-hinge pendulum as a component
tree (URLab beta's "the component tree is the model") — the smallest thing that
exercises the path, and what the plugin's own parity harness uses.

Parameterised so a private level can reuse it without any private path
appearing in this file. Set these on `unreal` before running:

    unreal._ramms_newton_map       target level  (default the public one below)
    unreal._ramms_newton_gamemode  game mode class path; the default spawns no
                                   pawn. A game mode whose default pawn IS an
                                   MjArticulation supplies the robot itself, in
                                   which case set _ramms_newton_pendulum = False.
    unreal._ramms_newton_pendulum  build the pendulum (default True)

Run inside the editor:
    python3 Scripts/editor_remote_exec.py --file Scripts/pie_tests/newton/make_newton_map.py
"""

import unreal

MAP = getattr(unreal, "_ramms_newton_map", "/Game/Maps/URL/Map_NewtonTest_URL")
GAME_MODE = getattr(unreal, "_ramms_newton_gamemode", "")
BUILD_PENDULUM = getattr(unreal, "_ramms_newton_pendulum", True)

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)


def add_component(actor, cls, name, parent=None):
    """Add a component to a placed actor under `parent`, returning the instance.

    Parents are resolved by object on every call rather than by keeping handles
    around: a handle from an earlier gather goes stale once the next add
    reshapes the subobject tree, and using one silently attaches to the root
    instead — which is how an entire body level went missing here once.
    """
    handles = sub.k2_gather_subobject_data_for_instance(actor)
    parent_handle = handles[0]
    if parent is not None:
        parent_handle = None
        for h in handles:
            data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(h)
            if unreal.SubobjectDataBlueprintFunctionLibrary.get_object(data) == parent:
                parent_handle = h
                break
        if parent_handle is None:
            raise RuntimeError("no live handle for parent %s" % parent.get_name())

    params = unreal.AddNewSubobjectParams()
    params.set_editor_property("parent_handle", parent_handle)
    params.set_editor_property("new_class", cls)
    params.set_editor_property("blueprint_context", None)
    handle, fail = sub.add_new_subobject(params)
    if not fail.is_empty():
        raise RuntimeError("add %s failed: %s" % (cls.get_name(), fail))
    sub.rename_subobject(handle, unreal.Text(name))
    data = unreal.SubobjectDataBlueprintFunctionLibrary.get_data(handle)
    return unreal.SubobjectDataBlueprintFunctionLibrary.get_object(data)


def find_component(actor, cls):
    for c in actor.get_components_by_class(unreal.ActorComponent):
        if isinstance(c, cls):
            return c
    return None


# Authoring touches the editor world, which is not reachable while a PIE
# session owns the level; spawn_actor_from_class quietly returns None there.
if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running — stopped it; re-run this script")

# Start from nothing: new_level over an existing asset can bring the old one
# back rather than replacing it, which is how this ended up with two managers.
if unreal.EditorAssetLibrary.does_asset_exist(MAP):
    unreal.EditorAssetLibrary.delete_asset(MAP)
les.new_level(MAP)
world = ues.get_editor_world()

# Exactly one manager. AAMjManager::GetManager() resolves globally, so a second
# would make which engine the solver binds to a coin flip — which is precisely
# what happened when an earlier run left one behind in the old level asset.
managers = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.AMjManager)
for extra in managers[1:]:
    print("[map] removing duplicate manager", extra.get_name())
    unreal.EditorLevelLibrary.destroy_actor(extra)
manager = managers[0] if managers else unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.AMjManager, unreal.Vector(0, 0, 0))
manager.set_actor_label("MjManager")

ws = world.get_world_settings()
# The property is default_game_type, not default_game_mode. Setting the latter
# succeeds silently and overrides nothing, which is how the MeBot pawn kept
# spawning on top of the robot under test long after this looked handled.
game_mode_class = unreal.GameModeBase
if GAME_MODE:
    gm_asset = unreal.EditorAssetLibrary.load_asset(GAME_MODE)
    if not gm_asset:
        raise RuntimeError("game mode not found: %s" % GAME_MODE)
    game_mode_class = gm_asset.generated_class()
ws.set_editor_property("default_game_type", game_mode_class)
if ws.get_editor_property("default_game_type") is None:
    raise RuntimeError("game mode override did not take")
print("[map] game mode override -> %s" % (GAME_MODE or "GameModeBase (no default pawn)"))

if BUILD_PENDULUM:
    # Skipped when a game mode supplies the robot as its default pawn.
    # The articulation: its own model root -> body -> (hinge joint, capsule geom).
    art = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.MjArticulation, unreal.Vector(0, 0, 150))
    art.set_actor_label("Pendulum")

    # It ships with a model component; adding a second would compile two roots.
    model = find_component(art, unreal.MjModel)
    if model is None:
        raise RuntimeError("articulation has no MjModel component to build under")
    # The FIRST body under the model root IS the world body: URLab writes its
    # children straight onto the spec's existing worldbody rather than nesting a
    # new one (MjSpecBuild.cpp, "The root's body IS the world body"). So a link
    # needs two levels, not one — hanging the joint one level up puts it in the
    # world body, which MuJoCo rejects with "joint found in world body".
    world_body = add_component(art, unreal.MjBody, "World", model)
    link = add_component(art, unreal.MjBody, "Link", world_body)

    hinge = add_component(art, unreal.MjJoint, "Hinge", link)
    hinge.set_editor_property("type", unreal.MjJointType.HINGE)
    hinge.set_editor_property("axis", [0.0, 1.0, 0.0])

    # MuJoCo rejects a sizeless geom ("size 0 must be positive in geom"), and these
    # are TOptional properties that stay unset until written — a freshly added geom
    # has no type and no size, so both have to be set explicitly.
    capsule = add_component(art, unreal.MjGeom, "Capsule", link)
    capsule.set_editor_property("type", unreal.MjGeomType.CAPSULE)
    capsule.set_editor_property("size", [0.05, 0.3])      # radius, half-length (m)
    capsule.set_editor_property("pos", [0.3, 0.0, 0.0])   # out along +X, not straight down

    # The project's default game mode spawns the MeBot chair and a crowd character,
    # which then sit in front of whatever this level is meant to show. A bare
    # GameModeBase with no default pawn keeps the level to its own contents.
# Lighting. A level made with new_level is unlit, which makes a capture of the
# running sim useless: the robot is there and simulating, and the image is
# black. Directional light + sky light + atmosphere is the smallest set that
# reads as a lit scene; the floor gives the eye a ground plane and something
# for shadows to land on.
sun = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.DirectionalLight, unreal.Vector(0, 0, 400), unreal.Rotator(-45, -45, 0))
sun.set_actor_label("Sun")
sun.light_component.set_intensity(6.0)
sun.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)

sky_light = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.SkyLight, unreal.Vector(0, 0, 400))
sky_light.set_actor_label("SkyLight")
sky_light.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
sky_light.light_component.set_intensity(1.0)

sky = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
sky.set_actor_label("SkyAtmosphere")

# A cube, not a plane, and carrying MjQuickConvertComponent: the ground has to
# exist in the MuJoCo scene or the robot has nothing to stand on, and a plain
# StaticMeshActor contributes no geom at all. A plane is also not convertible.
# Static = true gives it no free joint, so it is a fixed collider.
floor = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.StaticMeshActor, unreal.Vector(0, 0, -50))
floor.set_actor_label("Ground")
floor.set_actor_scale3d(unreal.Vector(40.0, 40.0, 1.0))
floor_mesh = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube")
if floor_mesh:
    floor.static_mesh_component.set_static_mesh(floor_mesh)
    floor.static_mesh_component.set_mobility(unreal.ComponentMobility.STATIC)
quick_convert = add_component(floor, unreal.MjQuickConvertComponent, "MjQuickConvert")
quick_convert.set_editor_property("static", True)

# A camera to frame the robot, so a capture does not depend on wherever the
# editor viewport happened to be pointing.
cam = unreal.EditorLevelLibrary.spawn_actor_from_class(
    unreal.CameraActor, unreal.Vector(-320, -260, 210), unreal.Rotator(-12, 38, 0))
cam.set_actor_label("ShowcaseCamera")
cam.camera_component.set_editor_property("field_of_view", 70.0)

# The component under test. It finds the manager globally, so it can live here.
solver = add_component(manager, unreal.RammsNewtonSolverComponent, "NewtonSolver")
print("[map] solver component:", solver.get_name())

# save_current_level() returns nothing and fails silently for a level mounted
# from a plugin, which left a stale .umap on disk looking like a save. Save the
# asset by path and check the result instead.
if not unreal.EditorAssetLibrary.save_asset(MAP, only_if_is_dirty=False):
    raise RuntimeError("failed to save %s" % MAP)
print("[map] saved", MAP)
print("[map] actors:", [a.get_actor_label() for a in
                        unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)])
