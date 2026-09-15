"""Turn check for a MuJoCo base: drive.turn = +1 must turn RIGHT.

The bases pivot slowly (passive wheels resist), so the primary check is the
wheel differential the mixing + Direction produce — left wheel forward, right
wheel backward — with the base_link yaw delta as the sign witness.

Set unreal._ramms_turn_op to 'start' or 'check' (see chaos_turn.py)."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, mj_find, cs_common; importlib.reload(mj_find); importlib.reload(cs_common)
w, a = mj_find.find()
dd = a.get_component_by_class(unreal.RammsDifferentialDriveController)
cs = cs_common.surface_of(a)
base_link = [c for c in a.get_components_by_class(unreal.SceneComponent) if c.get_name() == "base_link"][0]
op = getattr(unreal, "_ramms_turn_op", "check")
yaw = base_link.get_world_transform().rotation.rotator().yaw
if op == "start":
    cs_common.quiet_local_input(a)
    unreal._ramms_turn_yaw0 = yaw
    # (forward, turn); default is a pure right pivot. Set unreal._ramms_turn_input
    # to e.g. (0.5, 1.0) for an arc, which shows the direction sooner when the
    # passive wheels resist a pivot.
    fwd, turn = getattr(unreal, "_ramms_turn_input", (0.0, 1.0))
    cs_common.set_control(cs, "drive.forward", fwd)
    cs_common.set_control(cs, "drive.turn", turn)
    unreal.log("[turn] start base_link yaw=%.1f, drive.forward=%+.1f drive.turn=%+.1f via surface (must turn right)" % (yaw, fwd, turn))
else:
    y0 = getattr(unreal, "_ramms_turn_yaw0", 0.0)
    d = unreal.MathLibrary.normalize_axis(yaw - y0)
    base = a.get_component_by_class(unreal.RammsRobotBaseComponent)
    lv = base.get_motor_velocity(dd.get_editor_property("left_motor_id"))
    rv = base.get_motor_velocity(dd.get_editor_property("right_motor_id"))
    cs_common.release(cs, "drive.forward", "drive.turn")
    if lv - rv > 0.05 and d > -0.5:
        verdict = "left wheel forward, right backward, yaw %+.2f deg -> turning RIGHT (ok)" % d
    elif rv - lv > 0.05 or d < -0.5:
        verdict = "turning LEFT (WRONG): left vel %.2f right vel %.2f yaw %+.2f deg" % (lv, rv, d)
    else:
        verdict = "no differential (FAIL): left vel %.2f right vel %.2f yaw %+.2f deg" % (lv, rv, d)
    unreal.log("[turn] check base_link yaw=%.1f | %s" % (yaw, verdict))
    if "ok" not in verdict:
        raise RuntimeError("[turn] " + verdict)
