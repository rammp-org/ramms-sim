import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, mj_find; importlib.reload(mj_find)
w, a = mj_find.find()
dd = a.get_component_by_class(unreal.RammsDifferentialDriveController)
dd.set_drive_input(unreal.Vector2D(0.0, 0.0))
import os
target = unreal.Vector2D(0.0, 10.0)
for c in a.get_components_by_class(unreal.Ramms5BarLinkageController):
    angles, ok = c.solve_target(target)
    res = c.set_endpoint_target(target)
    unreal.log("[lift] %s: solve(%s)->%s reachable=%s ; set_endpoint_target=%s ; joints now=%s endpoint now=%s" % (
        c.get_name(), target, angles, ok, res, c.get_current_joint_angles(), c.get_current_endpoint()))
