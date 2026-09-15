"""Turn check for a MuJoCo base: joystick X = +1 must turn RIGHT.

The bases pivot slowly (passive wheels resist), so the primary check is the
wheel differential the mixing + Direction produce — left wheel forward, right
wheel backward — with the base_link yaw delta as the sign witness.

Set unreal._ramms_turn_op to 'start' or 'check' (see chaos_turn.py)."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, mj_find; importlib.reload(mj_find)
w, a = mj_find.find()
dd = a.get_component_by_class(unreal.RammsDifferentialDriveController)
tele = a.get_component_by_class(unreal.RammsKeyboardTeleopComponent)
base_link = [c for c in a.get_components_by_class(unreal.SceneComponent) if c.get_name() == "base_link"][0]
op = getattr(unreal, "_ramms_turn_op", "check")
yaw = base_link.get_world_transform().rotation.rotator().yaw
if op == "start":
    if tele:
        tele.set_component_tick_enabled(False)
    unreal._ramms_turn_yaw0 = yaw
    # Arc rather than spin in place: the passive wheels resist a pure pivot, so
    # a forward + right command shows the turn direction much sooner.
    turn_input = getattr(unreal, "_ramms_turn_input", unreal.Vector2D(1.0, 0.0))
    dd.set_drive_input(turn_input)
    unreal.log("[turn] start base_link yaw=%.1f, commanding X=%+.1f Y=%+.1f (must turn right)" % (yaw, turn_input.x, turn_input.y))
else:
    y0 = getattr(unreal, "_ramms_turn_yaw0", 0.0)
    d = unreal.MathLibrary.normalize_axis(yaw - y0)
    base = a.get_component_by_class(unreal.RammsRobotBaseComponent)
    lv = base.get_motor_velocity(dd.get_editor_property("left_motor_id"))
    rv = base.get_motor_velocity(dd.get_editor_property("right_motor_id"))
    dd.set_drive_input(unreal.Vector2D(0.0, 0.0))
    if lv - rv > 0.05 and d > -0.5:
        verdict = "left wheel forward, right backward, yaw %+.2f deg -> turning RIGHT (ok)" % d
    elif rv - lv > 0.05 or d < -0.5:
        verdict = "turning LEFT (WRONG): left vel %.2f right vel %.2f yaw %+.2f deg" % (lv, rv, d)
    else:
        verdict = "no differential (FAIL): left vel %.2f right vel %.2f yaw %+.2f deg" % (lv, rv, d)
    unreal.log("[turn] check base_link yaw=%.1f | %s" % (yaw, verdict))
    if "ok" not in verdict:
        raise RuntimeError("[turn] " + verdict)
