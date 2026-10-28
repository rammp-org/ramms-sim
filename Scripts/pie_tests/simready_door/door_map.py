"""Scratch level for the SimReady door test under URLab (see README.md): AMjManager, the Gen3 + 2F-85 (fixed
base) and a converted SimReady appliance, placed as mujoco/articulation_test.py placed them (MuJoCo world: the
arm's base at (0, 0, base_z) facing +x, the appliance at app_pos with yaw app_yaw, on a counter if the plan had
one). URLab maps MuJoCo (x, y, z) m to Unreal (100x, -100y, 100z) cm, so a MuJoCo yaw a is an Unreal yaw -a.
Nothing is saved; an unsaved /Temp scratch level is replaced, unsaved changes to a real map stop it.

Globals: DM_PLAN (the plan .json), DM_APP (the appliance Blueprint), optional DM_CAM (MuJoCo lookat x y z,
distance, azimuth, elevation), DM_GEN3 (default /Game/Robots/URL/gen3_2f85_fixed), DM_OUT (a report file).
"""
import json, math, os, traceback
import unreal
OUT = globals().get("DM_OUT") or os.path.join(unreal.Paths.project_saved_dir(), "SimReadyDoor", "map.txt")
GEN3 = globals().get("DM_GEN3", "/Game/Robots/URL/gen3_2f85_fixed")
L = []
try:
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    eal = unreal.EditorAssetLibrary
    if ues.get_game_world() is not None:
        raise RuntimeError("PIE is running")
    # Unsaved scratch levels (/Temp/..., e.g. this builder's last one) may go; real maps may not.
    dirty = [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()
             if not p.get_name().startswith("/Temp/")]
    if dirty:
        raise RuntimeError("unsaved map changes, not discarding: %s" % dirty)
    sc = json.load(open(DM_PLAN))["result"]["scene"]
    unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    world = ues.get_editor_world()
    ws = world.get_world_settings()
    ws.set_editor_property("default_game_type", unreal.GameModeBase.static_class())
    mgr = eas.spawn_actor_from_class(unreal.AMjManager, unreal.Vector(0, 0, 0))
    mgr.set_actor_label("MjManager")
    # The scene's solver options are the manager's: match the Gen3 MJCF (and the offline test), whose
    # elliptic friction cone with impratio 10 is what lets the 2F-85 hold a flat door edge.
    opt = mgr.get_editor_property("scene_option")
    opt.set_timestep(float(sc["timestep"]))
    opt.set_cone(unreal.MjCone.ELLIPTIC)
    opt.set_impratio(10.0)
    opt.set_integrator(unreal.MjIntegrator.IMPLICITFAST)
    bz = 100.0 * sc["base_z"]
    gen3 = eas.spawn_actor_from_class(eal.load_asset(GEN3).generated_class(), unreal.Vector(0, 0, bz), unreal.Rotator(0, 0, 0))
    gen3.set_actor_label("Gen3")
    n_gc = 0
    if sc.get("gravcomp"):
        for b in gen3.get_components_by_class(unreal.MjBody):
            try:
                b.set_gravcomp(1.0); n_gc += 1
            except Exception as e:
                L.append("gravcomp %s: %s" % (b.get_name(), e)); break
    ax, ay, az = sc["app_pos"]
    cube = eal.load_asset("/Engine/BasicShapes/Cube")
    if sc.get("table"):
        # The counter is visual here: the appliance's root body is welded to the world at its actor.
        hx, hy, th = sc["table"]
        ct = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(100 * ax, -100 * ay, 50 * th), unreal.Rotator(0, 0, 0))
        ct.static_mesh_component.set_static_mesh(cube); ct.set_actor_scale3d(unreal.Vector(2 * hx, 2 * hy, th)); ct.set_actor_label("Counter")
        az += th
    app = eas.spawn_actor_from_class(eal.load_asset(DM_APP).generated_class(),
                                     unreal.Vector(100 * ax, -100 * ay, 100 * az), unreal.Rotator(0, 0, -sc["app_yaw"]))
    app.set_actor_label("Appliance")
    # Visual only (MuJoCo does not see these): floor, pedestal, light, sky, camera.
    plane = eal.load_asset("/Engine/BasicShapes/Plane")
    fl = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(50, 0, -0.5), unreal.Rotator(0, 0, 0))
    fl.static_mesh_component.set_static_mesh(plane); fl.set_actor_scale3d(unreal.Vector(12, 12, 1)); fl.set_actor_label("Floor")
    pd = eas.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0, 0, bz / 2 - 0.5), unreal.Rotator(0, 0, 0))
    pd.static_mesh_component.set_static_mesh(cube); pd.set_actor_scale3d(unreal.Vector(0.24, 0.24, (bz - 1) / 100)); pd.set_actor_label("Pedestal")
    sun = eas.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 400), unreal.Rotator(0, -45, -30))
    sun.light_component.set_mobility(unreal.ComponentMobility.MOVABLE); sun.light_component.set_intensity(6.0)
    eas.spawn_actor_from_class(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
    sky = eas.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 300))
    sky.light_component.set_mobility(unreal.ComponentMobility.MOVABLE); sky.light_component.set_editor_property("real_time_capture", True)
    # The offline video's view (MuJoCo lookat xyz, distance, azimuth, elevation), mirrored into Unreal.
    lx, ly, lz, dist, azm, el = globals().get("DM_CAM", (0.5, 0.05, 0.95, 2.4, 50, -24))
    dx = math.cos(math.radians(el)) * math.cos(math.radians(azm))
    dy = math.cos(math.radians(el)) * math.sin(math.radians(azm))
    dz = math.sin(math.radians(el))
    cx, cy, cz = lx - dist * dx, ly - dist * dy, lz - dist * dz
    cam = eas.spawn_actor_from_class(unreal.CameraActor, unreal.Vector(100 * cx, -100 * cy, 100 * cz),
                                     unreal.Rotator(0, el, -azm))
    cam.tags = [unreal.Name("door_cam")]; cam.set_actor_label("DoorCam")
    eas.select_nothing()
    L.append("ok: manager, gen3 (gravcomp on %d bodies), %s at %s yaw %s" % (n_gc, DM_APP, sc["app_pos"], -sc["app_yaw"]))
    L.append("gen3 joints %s" % list(gen3.get_joint_names())[:9])
    L.append("app joints %s" % list(app.get_joint_names()))
    ctl = gen3.get_components_by_class(unreal.RammsMjEndEffectorController)
    L.append("ee controller %s" % [(c.get_name(), c.get_editor_property("end_effector_site_name")) for c in ctl])
except Exception:
    L.append(traceback.format_exc())
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w").write("\n".join(str(x) for x in L) + "\n")
print("\n".join(str(x) for x in L))
