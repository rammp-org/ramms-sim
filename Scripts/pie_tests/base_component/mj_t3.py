import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, mj_find; importlib.reload(mj_find)
w, a = mj_find.find()
base = a.get_component_by_class(unreal.RammsRobotBaseComponent)
for c in a.get_components_by_class(unreal.Ramms5BarLinkageController):
    unreal.log("[t3] %s: target=%s joints=%s endpoint=%s" % (c.get_name(), c.get_last_target(), c.get_current_joint_angles(), c.get_current_endpoint()))
for m in ["left_center_hip_a","left_center_hip_b","right_center_hip_a","right_center_hip_b"]:
    unreal.log("[t3] %s value=%.4f" % (m, base.get_motor_value(m)))
unreal.log("[t3] loc=%s" % a.get_actor_location())
