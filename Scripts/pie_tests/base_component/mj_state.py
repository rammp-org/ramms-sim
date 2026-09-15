import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, mj_find; importlib.reload(mj_find)
w, a = mj_find.find()
base = a.get_component_by_class(unreal.RammsRobotBaseComponent)
dd = a.get_component_by_class(unreal.RammsDifferentialDriveController)
AR = unreal.MjActuatorRuntime; JR = unreal.MjJointRuntime
mgrs = [m for m in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Actor) if m.get_class().get_name() == "AMjManager"]
mgr = mgrs[0] if mgrs else None
if mgr:
    props = [p for p in dir(mgr) if any(k in p.lower() for k in ("pause","run","start","time","step","simulat","paused","play"))]
    vals = {}
    for p in props:
        try:
            v = getattr(mgr, p)
            if not callable(v): vals[p] = v
        except Exception: pass
    unreal.log("[st] manager %s props: %s" % (mgr.get_name(), vals))
for m, jn in [("left_center_wheel","left_center_wheel_joint"), ("right_center_wheel","right_center_wheel_joint"), ("left_center_hip_a","left_center_hip_a_joint")]:
    node = a.get_actuator(m); j = a.get_joint(jn)
    unreal.log("[st] %-18s staged=%8.3f applied=%8.3f force=%8.3f | qpos=%8.4f qvel=%8.4f | dd input=%s" % (
        m, AR.get_control(node), AR.get_applied_control(node), AR.get_force(node), JR.get_position(j), JR.get_velocity(j), dd.get_editor_property("drive_input").y))
b = a.get_body("base_link"); fw = a.get_body("left_front_wheel")
bl = b.get_world_location()
unreal.log("[st] base_link x=%.2f y=%.2f z=%.3f  left_front_wheel z=%.3f  left_center_wheel z=%.3f" % (bl.x, bl.y, bl.z, fw.get_world_location().z, a.get_body("left_center_wheel").get_world_location().z))
