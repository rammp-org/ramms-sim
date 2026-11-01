"""Game mode and curb level for driving the MeBot MuJoCo pawn (powered-front variant).

Step 3 of 3 (after import_mebot_mjcf.py and make_mebot_pawn.py). Writes:

  /Game/Robots/MeBot/BP_MebotPoweredFrontGameMode   ARammsMujocoTestGameMode with the pawn as its
                                                    default pawn: it spawns the pawn before the MuJoCo
                                                    scene compiles (a pawn spawned at login would not
                                                    be simulated) and starts the simulation
  /Game/Maps/Map_MebotCurb_URL                      a floor and two kerbed platforms, 15 cm and 8 cm
                                                    high, 3 m ahead of the spawn and 3 m deep (climb
                                                    on at the near face, descend off the far one)

The level's URLab manager carries the scene options the omni wheels' rollers need: elliptic friction
cones with impratio 10 (braked rollers creep on pyramidal cones), at the MJCF's 2 ms step. The floor
and the platforms are static, quick-converted boxes; the platform tops are flat and their faces square.

Run inside the editor, with PIE stopped:
    python Scripts/editor_remote_exec.py --file Scripts/mebot_mujoco/make_mebot_curb_map.py
"""

import time

import unreal

PAWN = "/Game/Robots/MeBot/BP_MebotPoweredFront_Ramms"
GM_DIR, GM_NAME = "/Game/Robots/MeBot", "BP_MebotPoweredFrontGameMode"
MAP = "/Game/Maps/Map_MebotCurb_URL"
# Platforms: (label, near face x cm, centre y cm, depth cm, width cm, height cm).
PLATFORMS = [("Curb15", 300.0, 0.0, 300.0, 300.0, 15.0), ("Curb8", 300.0, 400.0, 300.0, 300.0, 8.0)]
FRICTION = (1.0, 0.005, 0.0001)   # MuJoCo's default sliding / torsional / rolling
CURB_MATERIAL, CURB_COLOR = "/Game/Robots/MeBot/MI_MebotCurb", (0.55, 0.30, 0.10)   # the platforms stand out from the floor
TIMESTEP = 0.002

EAL = unreal.EditorAssetLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
ell = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)

if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; re-run this script")

# --- the game mode -------------------------------------------------------------------------------
pawn = EAL.load_asset(PAWN)
if not pawn:
    raise RuntimeError("missing %s: run make_mebot_pawn.py first" % PAWN)
gm_path = GM_DIR + "/" + GM_NAME
gm = EAL.load_asset(gm_path) if EAL.does_asset_exist(gm_path) else None
if not gm:
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.RammsMujocoTestGameMode.static_class())
    gm = AT.create_asset(GM_NAME, GM_DIR, unreal.Blueprint, factory)
cdo = unreal.get_default_object(gm.generated_class())
cdo.set_editor_property("default_pawn_class", pawn.generated_class())
unreal.BlueprintEditorLibrary.compile_blueprint(gm)
if not EAL.save_loaded_asset(gm, False):
    raise RuntimeError("could not save %s" % gm_path)
print("[mebot_map] %s spawns %s" % (gm_path, pawn.get_name()))

# --- the level -----------------------------------------------------------------------------------
CUBE = EAL.load_asset("/Engine/BasicShapes/Cube")
mi = EAL.load_asset(CURB_MATERIAL) if EAL.does_asset_exist(CURB_MATERIAL) else None
if not mi:
    mi = AT.create_asset(CURB_MATERIAL.rsplit("/", 1)[1], CURB_MATERIAL.rsplit("/", 1)[0], unreal.MaterialInstanceConstant,
                         unreal.MaterialInstanceConstantFactoryNew())
mi.set_editor_property("parent", EAL.load_asset("/Engine/BasicShapes/BasicShapeMaterial"))
unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(mi, "Color", unreal.LinearColor(*CURB_COLOR, 1.0))
EAL.save_loaded_asset(mi, False)


def vec3d(v):
    out = unreal.Vector3d()
    for k, val in zip(("x", "y", "z"), v):
        out.set_editor_property(k, float(val))
    return out


def add_component(actor, cls, name):
    h = SDS.k2_gather_subobject_data_for_instance(actor)[0]
    new_h, fail = SDS.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=h, new_class=cls))
    o = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(unreal.SubobjectDataBlueprintFunctionLibrary.get_data(new_h))
    if not o:
        raise RuntimeError("could not add %s to %s: %s" % (name, actor.get_actor_label(), fail))
    SDS.rename_subobject(new_h, unreal.Text(name))
    return o


def box(label, center, size, material=None):
    """A static, quick-converted box: the engine cube (100 cm, pivot centred) scaled to size cm."""
    a = ell.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(*center))
    a.set_actor_label(label)
    a.static_mesh_component.set_static_mesh(CUBE)
    if material:
        a.static_mesh_component.set_material(0, material)
    # Movable although static in MuJoCo: URLab writes a transform to every converted body each step.
    a.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    a.set_actor_scale3d(unreal.Vector(size[0] / 100.0, size[1] / 100.0, size[2] / 100.0))
    qc = add_component(a, unreal.MjQuickConvertComponent, "MjQuickConvert")
    qc.set_editor_property("static", True)
    qc.set_editor_property("friction", vec3d(FRICTION))
    return a


# Author into a fresh scratch world and write it out with save_map (new_level and
# save_current_level report success without doing the work in some states; save_map fails honestly).
SCRATCH = "/Temp/MebotCurbAuthoring_%d" % int(time.time() * 1000)
les.new_level(SCRATCH)
world = ues.get_editor_world()
if world.get_path_name() != "%s.%s" % (SCRATCH, SCRATCH.rsplit("/", 1)[-1]):
    raise RuntimeError("new_level did not open %s: the editor is on %s" % (SCRATCH, world.get_path_name()))

manager = ell.spawn_actor_from_class(unreal.AMjManager, unreal.Vector(0, 0, 0))
manager.set_actor_label("MjManager")
option = manager.get_editor_property("scene_option")   # an object, edited in place
option.modify()
option.set_timestep(TIMESTEP)
option.set_cone(unreal.MjCone.ELLIPTIC)
option.set_impratio(10.0)
if hasattr(unreal, "MjIntegrator") and hasattr(option, "set_integrator"):
    option.set_integrator(unreal.MjIntegrator.IMPLICITFAST)
manager.modify()

ws = world.get_world_settings()
ws.set_editor_property("default_game_type", gm.generated_class())
if ws.get_editor_property("default_game_type") != gm.generated_class():
    raise RuntimeError("the game mode override did not take")

box("Floor", (500.0, 0.0, -10.0), (4000.0, 4000.0, 20.0))
for label, near, y, depth, width, height in PLATFORMS:
    box(label, (near + depth / 2.0, y, height / 2.0), (depth, width, height), material=mi)

start = ell.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0.0, 0.0, 20.0))
start.set_actor_label("PlayerStart")
sun = ell.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 400), unreal.Rotator(-50, -40, 0))
sun.set_actor_label("Sun")
sun.light_component.set_editor_property("atmosphere_sun_light", True)
ell.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 400)).set_actor_label("SkyLight")
ell.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0)).set_actor_label("SkyAtmosphere")

if EAL.does_asset_exist(MAP):
    unreal.SystemLibrary.collect_garbage()
if not unreal.EditorLoadingAndSavingUtils.save_map(world, MAP):
    raise RuntimeError("could not save %s" % MAP)
les.load_level(MAP)
check = ues.get_editor_world()
managers = [a for a in ell.get_all_level_actors() if a.get_class().get_name() == "AMjManager"]
opt = managers[0].get_editor_property("scene_option") if managers else None
if len(managers) != 1 or check.get_world_settings().get_editor_property("default_game_type") != gm.generated_class() \
        or opt.get_cone() != unreal.MjCone.ELLIPTIC or abs(opt.get_impratio() - 10.0) > 1e-9 or abs(opt.get_timestep() - TIMESTEP) > 1e-12:
    raise RuntimeError("%s did not read back as written" % MAP)
print("[mebot_map] saved %s: %s; timestep %g, elliptic cones, impratio 10" % (
    MAP, ", ".join("%s %.0f cm at x %.0f..%.0f" % (p[0], p[5], p[1], p[1] + p[3]) for p in PLATFORMS), TIMESTEP))
