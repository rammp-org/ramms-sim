import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, target = cs_common.find_chaos_pawn()
dd = target.get_component_by_class(unreal.RammsDifferentialDriveController)
base = target.get_component_by_class(unreal.RammsRobotBaseComponent)
cs = cs_common.surface_of(target)
unreal.log("[t1] pawn=%s base=%s has_backend=%s mode=%s has_left=%s type=%s sep3D=%.2f" % (
    target.get_name(), base.get_name(), base.has_backend(), base.get_editor_property("backend"),
    base.has_motor("left_motor"), base.get_motor_type("left_motor"), base.get_motor_separation("left_motor", "right_motor")))
surf = cs.describe_control_surface()
unreal.log("[t1] surface: %d controls in %s" % (len(surf.get_editor_property("axes")), [str(g) for g in surf.get_editor_property("groups")]))
unreal.log("[t1] loc0=%s" % target.get_actor_location())
cs_common.quiet_local_input(target)
cs_common.set_control(cs, "drive.forward", 1.0)
unreal.log("[t1] commanded forward via control surface: dd input=%s ext=%s" % (dd.get_editor_property("drive_input"), dd.is_external_drive_active()))
