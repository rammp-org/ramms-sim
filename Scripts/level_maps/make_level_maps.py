"""Build the level-assist course maps: /Game/Maps/Level/Map_Level_<id>_URL for every course in level_terrain.py.

    UnrealEditor-Cmd Ramms.uproject -run=pythonscript -script="Scripts/level_maps/make_level_maps.py"

(or inside a running editor through Scripts/editor_remote_exec.py --file). To build only some: RAMMS_LEVEL_MAPS=FLAT,RAMP5
in the environment, or unreal._ramms_level_maps = "FLAT,RAMP5" in a running editor (consumed by the run).

The maps name no robot, and are built as the curb maps are (Scripts/curb_maps/make_curb_maps.py), each from an empty
level:
  - WorldSettings' GameMode Override: the C++ ARammsRobotGameMode, which spawns the robot chosen at start at the
    PlayerStart;
  - an AMjManager with no scene option set: each robot's own MJCF <option> is adopted as it attaches;
  - the floor (an engine cube under the whole lane, top at level_terrain.FLOOR_TOP_Z) and the course's slabs (engine
    cubes on their planes), every one movable and static in MuJoCo (MjQuickConvert, its default contact);
  - the PlayerStart (the course's "centre" start heading +X, on its own run-in slab: a robot never drives from the
    floor onto a slab) and the lights.
Checked before a map is kept:
  - level_terrain's own flush check (the slabs build the planes meant, no seam has a step), before anything is spawned;
  - line traces from above find the terrain's surface (TRACE_TOLERANCE_CM) on a grid over the lane and both sides of
    every seam, as a robot's wheels and its traces meet it;
  - across every seam the traced surface changes by no more than the planes do (SEAM_TRACE_STEP_CM more): no lip;
  - the saved package references nothing under the private plugin's content root (public content must never need it).
"""

import importlib
import os
import sys
import time

import unreal

HERE = os.path.join(unreal.Paths.project_dir(), "Scripts", "level_maps")
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import level_terrain as lt  # noqa: E402

importlib.reload(lt)

ROAD_MATERIAL = "/Engine/OpenWorldTemplate/LandscapeMaterial/MI_ProcGrid"
FLOOR_MATERIAL = "/Engine/EngineMaterials/WorldGridMaterial"
GAME_MODE = "/Script/RammsMujocoSupport.RammsRobotGameMode"
FLOOR_MARGIN = 400.0  # the floor reaches this far past the lane all round
FLOOR_THICK = 100.0
TRACE_TOLERANCE_CM = 0.2
TRACE_GRID_CM = 60.0
SEAM_TRACE_DELTA_CM = 0.5  # either side of a seam
SEAM_TRACE_STEP_CM = 0.05  # more than the planes' own change across it: a lip
PRIVATE_ROOT = "/" + "Ramms" + "PrivateAssets"

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
    start = unreal.Vector(x, y, lt.FLOOR_TOP_Z + 1500.0)
    end = unreal.Vector(x, y, lt.FLOOR_TOP_Z - 100.0)
    hit = unreal.SystemLibrary.line_trace_single(world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1,
                                                 False, [], unreal.DrawDebugTrace.NONE, True)
    # A bool UFUNCTION's outs come back alone when it returned true, None otherwise.
    if hit is None:
        return None
    hit = hit[0] if isinstance(hit, tuple) else hit
    return hit.to_tuple()[4].z  # the impact point


def level_basics(world, L):
    """The game mode, the MuJoCo manager (no option set), the floor under the lane and the lights."""
    ws = world.get_world_settings()
    gm = unreal.load_class(None, GAME_MODE)
    ws.set_editor_property("default_game_type", gm)
    if ws.get_editor_property("default_game_type") != gm:
        raise RuntimeError("the game mode override did not take")
    manager = eas.spawn_actor_from_class(unreal.AMjManager, unreal.Vector(-200.0, -(L.half + 200.0), lt.FLOOR_TOP_Z))
    manager.set_actor_label("MjManager")
    option = manager.get_editor_property("scene_option")
    set_by_map = [f for f in ("timestep", "impratio", "cone") if option.get_editor_property(f) is not None]
    if set_by_map:
        raise RuntimeError("a new AMjManager came with %s set: the robots' own options would not be adopted" % set_by_map)
    size = (L.c.length + 2.0 * FLOOR_MARGIN, L.c.lane + 2.0 * FLOOR_MARGIN, FLOOR_THICK)
    box("Floor", (0.5 * L.c.length, 0.0, lt.FLOOR_TOP_Z - 0.5 * FLOOR_THICK), size, "floor")
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
    """Nothing of the private plugin in the saved map: neither in its dependencies nor anywhere in its bytes."""
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


def verify(world, L):
    """The traces' answers against the terrain: (how many points, the worst difference cm, the worst seam step cm)."""
    bad, worst, n = [], 0.0, 0
    xs = lt._steps(5.0, L.c.length - 5.0, TRACE_GRID_CM)
    ys = lt._steps(-(L.half - 5.0), L.half - 5.0, TRACE_GRID_CM)
    for x in xs:
        for y in ys:
            n += 1
            got, want = surface_by_trace(world, x, y), L.surface_z(x, y)
            if got is None or abs(got - want) > TRACE_TOLERANCE_CM:
                bad.append("(%.0f, %.0f): traced %s, the terrain says %.2f" % (x, y, got, want))
            else:
                worst = max(worst, abs(got - want))
    seam_worst = 0.0
    for label, p, q in L.seams():
        d = lt.ct.sub(q, p)
        length = (d[0] ** 2 + d[1] ** 2) ** 0.5
        nrm = (-d[1] / length, d[0] / length)
        for i in range(12):
            f = (i + 0.5) / 12.0
            m = (p[0] + f * d[0], p[1] + f * d[1])
            a = (m[0] - nrm[0] * SEAM_TRACE_DELTA_CM, m[1] - nrm[1] * SEAM_TRACE_DELTA_CM)
            b = (m[0] + nrm[0] * SEAM_TRACE_DELTA_CM, m[1] + nrm[1] * SEAM_TRACE_DELTA_CM)
            za, zb = surface_by_trace(world, *a), surface_by_trace(world, *b)
            n += 2
            if za is None or zb is None:
                bad.append("seam %s at (%.0f, %.0f): no surface traced" % (label, m[0], m[1]))
                continue
            for pt, z in ((a, za), (b, zb)):
                if abs(z - L.surface_z(*pt)) > TRACE_TOLERANCE_CM:
                    bad.append("seam %s (%.1f, %.1f): traced %.2f, the terrain says %.2f" % (label, pt[0], pt[1], z, L.surface_z(*pt)))
            step = abs(zb - za) - abs(L.intended_z(*b) - L.intended_z(*a))
            seam_worst = max(seam_worst, step)
            if step > SEAM_TRACE_STEP_CM:
                bad.append("seam %s at (%.0f, %.0f): a %.2f cm step (the planes change %.2f cm there)"
                           % (label, m[0], m[1], abs(zb - za), abs(L.intended_z(*b) - L.intended_z(*a))))
    if bad:
        raise RuntimeError("%s: the map's surfaces are not the terrain's (%d of %d points): %s"
                           % (L.c.id, len(bad), n, "; ".join(bad[:8])))
    return n, worst, seam_worst


def build(cid):
    L = lt.Layout(lt.BY_ID[cid])
    r = L.flush()
    if not r["ok"]:
        raise RuntimeError("%s is not flush as laid out: %s" % (cid, r))
    path = lt.map_path(cid)
    scratch = "/Temp/LevelMapAuthoring_%d" % int(time.time() * 1000)
    les.new_level(scratch)
    unreal.SystemLibrary.collect_garbage()
    world = ues.get_editor_world()
    if world.get_path_name() != "%s.%s" % (scratch, scratch.rsplit("/", 1)[-1]):
        raise RuntimeError("new_level did not open %s: the editor is on %s" % (scratch, world.get_path_name()))
    level_basics(world, L)
    for b in L.slabs:
        centre, x_axis, z_axis, size = b.placement()
        box(b.label, centre, size, "road", x_axis, z_axis)
    s = L.start("straddle" if L.c.kind == "crown" else "centre", "fwd")
    player_start(s["xyz"], s["x_axis"], s["z_axis"])
    n, worst, seam_worst = verify(world, L)
    if EAL.does_asset_exist(path):
        unreal.SystemLibrary.collect_garbage()
    if not unreal.EditorLoadingAndSavingUtils.save_map(world, path):
        raise RuntimeError("could not save %s" % path)
    deps = check_public(path)
    print("[level_maps] %s: %s -- %d slabs, %d traces within %.3f cm, worst seam step %.3f cm, %d dependencies, none private"
          % (path, L.c.title, len(L.slabs), n, worst, seam_worst, deps))
    les.new_level("/Temp/LevelMapDone_%d" % int(time.time() * 1000))
    unreal.SystemLibrary.collect_garbage()
    return path


wanted = (take("_ramms_level_maps") or [v.strip() for v in os.environ.get("RAMMS_LEVEL_MAPS", "").split(",") if v.strip()]
          or [c.id for c in lt.COURSES])
unknown = [w for w in wanted if w not in lt.BY_ID]
if unknown:
    raise RuntimeError("unknown course %s; the courses are %s" % (unknown, [c.id for c in lt.COURSES]))
built = [build(w) for w in wanted]
print("[level_maps] built %d: %s" % (len(built), ", ".join(p.rsplit("/", 1)[-1] for p in built)))
