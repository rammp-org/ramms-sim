"""Build the curb test maps: /Game/Maps/Curb/Map_Curb_<id>_URL for every terrain in curb_terrain.py, and
Map_Curb_Flat_URL (a straight 6 in curb on a flat road).

    UnrealEditor-Cmd Ramms.uproject -run=pythonscript -script="Scripts/curb_maps/make_curb_maps.py"

(or inside a running editor through Scripts/editor_remote_exec.py --file). To build only some: RAMMS_CURB_MAPS=A30,Flat
in the environment, or unreal._ramms_curb_maps = "A30,Flat" in a running editor (consumed by the run).

The maps name no robot. Each is built from an empty level:
  - WorldSettings' GameMode Override: the C++ ARammsRobotGameMode, which spawns the robot chosen at start (?Robot=
    on the map URL, ramms.Robot / -RammsRobot=, the project's default -- URammsRobotSettings) at the PlayerStart;
  - an AMjManager with no scene option set: each robot's own MJCF <option> (timestep, cone, impratio) is adopted as
    it attaches;
  - the floor (an engine cube, top at curb_terrain.FLOOR_TOP_Z), the terrain's boxes (engine cubes on their planes),
    every one movable and static in MuJoCo (MjQuickConvert, its default contact);
  - the PlayerStart (curb_terrain.Layout.start_pose: over the near road at START, heading +X) and the lights.
Checked before it is kept: line traces from above find the surfaces the terrain puts there (as a robot's step
detection traces them), and the saved package references nothing under /RammsPrivateAssets/ (a private, optional
submodule: public content must never need it).
"""

import importlib
import os
import sys
import time

import unreal

HERE = os.path.join(unreal.Paths.project_dir(), "Scripts", "curb_maps")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import curb_terrain as ct  # noqa: E402

importlib.reload(ct)

ROAD_MATERIAL = "/Engine/OpenWorldTemplate/LandscapeMaterial/MI_ProcGrid"
FLOOR_MATERIAL = "/Engine/EngineMaterials/WorldGridMaterial"
GAME_MODE = "/Script/RammsMujocoSupport.RammsRobotGameMode"
# The floor: 20 x 20 x 1 m, its top at FLOOR_TOP_Z.
FLOOR = ((0.0, 0.0, ct.FLOOR_TOP_Z - 50.0), (2000.0, 2000.0, 100.0))
# The flat map's 6 in sidewalk: a box standing on the floor, its near edge at E0's x.
FLAT_SIDEWALK_X = (450.0, 750.0)
FLAT_SIDEWALK_Y = (450.0, 950.0)
FLAT_CURB_CM = 15.24
TRACE_TOLERANCE_CM = 0.2
PRIVATE_ROOT = "/RammsPrivateAssets"

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
EAL = unreal.EditorAssetLibrary

if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; run this again")


def take(name):
    # Consumed: the unreal module outlives this run, and a filter left behind would narrow every later one.
    value = getattr(unreal, name, None)
    if hasattr(unreal, name):
        delattr(unreal, name)
    return [v.strip() for v in value.split(",") if v.strip()] if value else None


def vec(t):
    return unreal.Vector(float(t[0]), float(t[1]), float(t[2]))


def add_component(actor, cls, name):
    h = sds.k2_gather_subobject_data_for_instance(actor)[0]
    new_h, fail = sds.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=h, new_class=cls))
    o = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(unreal.SubobjectDataBlueprintFunctionLibrary.get_data(new_h))
    if not o:
        raise RuntimeError("could not add %s to %s: %s" % (name, actor.get_actor_label(), fail))
    sds.rename_subobject(new_h, unreal.Text(name))
    return o


def load(path):
    # By path (load_object), not through the asset registry, which a commandlet has not scanned engine content into.
    o = unreal.load_object(None, "%s.%s" % (path, path.rsplit("/", 1)[-1]))
    if o is None:
        raise RuntimeError("could not load %s" % path)
    return o


CUBE = load("/Engine/BasicShapes/Cube")
MATERIALS = {"road": load(ROAD_MATERIAL), "floor": load(FLOOR_MATERIAL)}


def box(label, centre, size, material, x_axis=None, z_axis=None):
    """A static, quick-converted box: the engine cube (100 cm, pivot centred) scaled to `size` cm."""
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, vec(centre))
    a.set_actor_label(label)
    a.static_mesh_component.set_static_mesh(CUBE)
    a.static_mesh_component.set_material(0, MATERIALS[material])
    # Movable although static in MuJoCo: URLab writes a transform to every converted body each step.
    a.static_mesh_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    if x_axis is not None:
        a.set_actor_rotation(unreal.MathLibrary.make_rot_from_xz(vec(x_axis), vec(z_axis)), False)
    a.set_actor_scale3d(unreal.Vector(size[0] / 100.0, size[1] / 100.0, size[2] / 100.0))
    qc = add_component(a, unreal.MjQuickConvertComponent, "MjQuickConvert")
    qc.set_editor_property("static", True)
    got = a.get_actor_location()
    if (got - vec(centre)).length() > 0.01:
        raise RuntimeError("%s landed at %s, not %s" % (label, got, centre))
    return a


def surface_by_trace(world, x, y):
    start = unreal.Vector(x, y, ct.FLOOR_TOP_Z + 1000.0)
    end = unreal.Vector(x, y, ct.FLOOR_TOP_Z - 100.0)
    hit = unreal.SystemLibrary.line_trace_single(world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
                                                 False, [], unreal.DrawDebugTrace.NONE, True)
    # A bool UFUNCTION's outs come back alone when it returned true, None otherwise.
    if hit is None:
        return None
    hit = hit[0] if isinstance(hit, tuple) else hit
    return hit.to_tuple()[4].z  # the impact point


def probes(L):
    """(label, x, y) points whose surface the traces must agree on."""
    out = [("start", ct.START[0], ct.START[1])]
    for label, p in (("near edge", ct.E0), ("far edge", L.e1)):
        for d, side in ((-6.0, "before"), (6.0, "after")):
            out.append(("%s %s" % (side, label), p[0] + d * L.n[0], p[1] + d * L.n[1]))
    mid = ct.add(ct.E0, ct.mul(L.n, 0.5 * L.s.depth))
    out.append(("sidewalk", mid[0], mid[1]))
    return out


def level_basics(world):
    """The game mode, the MuJoCo manager (no option set), the floor and the lights."""
    ws = world.get_world_settings()
    gm = unreal.load_class(None, GAME_MODE)
    ws.set_editor_property("default_game_type", gm)
    if ws.get_editor_property("default_game_type") != gm:
        raise RuntimeError("the game mode override did not take")
    manager = eas.spawn_actor_from_class(unreal.AMjManager, unreal.Vector(340.0, 300.0, ct.FLOOR_TOP_Z))
    manager.set_actor_label("MjManager")
    option = manager.get_editor_property("scene_option")
    set_by_map = [f for f in ("timestep", "impratio", "cone") if option.get_editor_property(f) is not None]
    if set_by_map:
        raise RuntimeError("a new AMjManager came with %s set: the robots' own options would not be adopted" % set_by_map)
    box("Floor", FLOOR[0], FLOOR[1], "floor")
    sun = eas.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 0), unreal.Rotator(-105.0, -31.0, -14.0))
    sun.set_actor_label("DirectionalLight")
    sun.light_component.set_editor_property("atmosphere_sun_light", True)
    sky = eas.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 0))
    sky.set_actor_label("SkyLight")
    sky.light_component.set_editor_property("real_time_capture", True)
    eas.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0)).set_actor_label("SkyAtmosphere")
    eas.spawn_actor_from_class(unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0)).set_actor_label("ExponentialHeightFog")
    eas.spawn_actor_from_class(unreal.VolumetricCloud, unreal.Vector(0, 0, 0)).set_actor_label("VolumetricCloud")


def player_start(loc, x_axis=(1.0, 0.0, 0.0), z_axis=(0.0, 0.0, 1.0)):
    start = eas.spawn_actor_from_class(unreal.PlayerStart, vec(loc))
    start.set_actor_label("PlayerStart")
    start.set_actor_rotation(unreal.MathLibrary.make_rot_from_xz(vec(x_axis), vec(z_axis)), False)
    return start


def check_public(path):
    """No /RammsPrivateAssets/ in the saved map: neither in its dependencies nor anywhere in its bytes."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    options = unreal.AssetRegistryDependencyOptions()
    options.set_editor_property("include_hard_package_references", True)
    options.set_editor_property("include_soft_package_references", True)
    deps = registry.get_dependencies(path, options) or []
    private = sorted(str(d) for d in deps if str(d).startswith(PRIVATE_ROOT))
    if private:
        raise RuntimeError("%s references private content: %s" % (path, ", ".join(private)))
    filename = unreal.Paths.convert_relative_path_to_full(
        os.path.join(unreal.Paths.project_content_dir(), path[len("/Game/"):] + ".umap"))
    with open(filename, "rb") as f:
        data = f.read()
    if PRIVATE_ROOT.encode() in data or PRIVATE_ROOT.encode("utf-16-le") in data:
        raise RuntimeError("%s holds the bytes %s" % (filename, PRIVATE_ROOT))
    return len(deps)


def build(sid):
    path = ct.map_path(None if sid == ct.FLAT else sid)
    scratch = "/Temp/CurbMapAuthoring_%d" % int(time.time() * 1000)
    les.new_level(scratch)
    unreal.SystemLibrary.collect_garbage()
    world = ues.get_editor_world()
    if world.get_path_name() != "%s.%s" % (scratch, scratch.rsplit("/", 1)[-1]):
        raise RuntimeError("new_level did not open %s: the editor is on %s" % (scratch, world.get_path_name()))
    level_basics(world)
    if sid == ct.FLAT:
        centre = (sum(FLAT_SIDEWALK_X) / 2.0, sum(FLAT_SIDEWALK_Y) / 2.0, ct.FLOOR_TOP_Z + FLAT_CURB_CM / 2.0)
        size = (FLAT_SIDEWALK_X[1] - FLAT_SIDEWALK_X[0], FLAT_SIDEWALK_Y[1] - FLAT_SIDEWALK_Y[0], FLAT_CURB_CM)
        box("Curb_Sidewalk", centre, size, "road")
        player_start((ct.START[0], ct.START[1], ct.FLOOR_TOP_Z + ct.START_ABOVE_SURFACE))
        probe = [("start", ct.START[0], ct.START[1], ct.FLOOR_TOP_Z), ("sidewalk", 600.0, 700.0, ct.FLOOR_TOP_Z + FLAT_CURB_CM)]
        title = "flat road, straight 6 in curb"
    else:
        L = ct.layout(sid)
        for b in L.boxes:
            centre, x_axis, z_axis, size = b.placement()
            box(b.label, centre, size, "road", x_axis, z_axis)
        player_start(*L.start_pose())
        probe = [(label, x, y, L.surface_z(x, y)) for label, x, y in probes(L)]
        title = L.s.title
    bad = []
    for label, x, y, want in probe:
        got = surface_by_trace(world, x, y)
        if got is None or abs(got - want) > TRACE_TOLERANCE_CM:
            bad.append("%s (%.0f, %.0f): traced %s, expected %.2f" % (label, x, y, got, want))
    if bad:
        raise RuntimeError("%s: the map's surfaces are not the terrain's: %s" % (sid, "; ".join(bad)))
    if EAL.does_asset_exist(path):
        unreal.SystemLibrary.collect_garbage()
    if not unreal.EditorLoadingAndSavingUtils.save_map(world, path):
        raise RuntimeError("could not save %s" % path)
    deps = check_public(path)
    print("[curb_maps] %s: %s (%d dependencies, none private)" % (path, title, deps))
    les.new_level("/Temp/CurbMapDone_%d" % int(time.time() * 1000))
    unreal.SystemLibrary.collect_garbage()
    return path


wanted = (take("_ramms_curb_maps") or [v.strip() for v in os.environ.get("RAMMS_CURB_MAPS", "").split(",") if v.strip()]
          or [ct.FLAT] + [t.id for t in ct.TERRAINS])
unknown = [w for w in wanted if w != ct.FLAT and w not in ct.BY_ID]
if unknown:
    raise RuntimeError("unknown terrain %s; the terrains are %s" % (unknown, [ct.FLAT] + [t.id for t in ct.TERRAINS]))
built = [build(w) for w in wanted]
print("[curb_maps] built %d: %s" % (len(built), ", ".join(p.rsplit("/", 1)[-1] for p in built)))
