"""Exercise UMebotControllerComponent's API now that it routes through the robot base.

Set unreal._ramms_mc_op to 'cmd' (command targets) or 'read' (read back, then zero)."""
import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
pawn = unreal.GameplayStatics.get_player_pawn(w, 0)
mc = pawn.get_component_by_class(unreal.MebotControllerComponent)
base = pawn.get_component_by_class(unreal.RammsRobotBaseComponent)
op = getattr(unreal, "_ramms_mc_op", "read")
ANG = {"front_caster_swing_arm": ("front_caster_elevator", 10.0)}   # degrees via MebotController
LIN = {"dw_main_plate_l": ("left_translator", 4.0)}                  # cm via MebotController
if op == "cmd":
    unreal.log("[mc] using_robot_base=%s" % mc.is_using_robot_base())
    for c, (mid, deg) in ANG.items():
        mc.set_angular_motor_target(c, deg)
    for c, (mid, cm) in LIN.items():
        mc.set_linear_motor_target(c, cm)
    unreal.log("[mc] commanded %s" % ({**{c: v[1] for c, v in ANG.items()}, **{c: v[1] for c, v in LIN.items()}}))
else:
    for c, (mid, deg) in ANG.items():
        got = mc.get_angular_motor_current_angle(c)
        # MebotController rate-limits toward the target (the BP's MaxSpeed may be
        # a few deg/s), so "moving the right way" is the check, not arrival.
        unreal.log("[mc] %s: MebotController angle=%.2f deg (target %.1f) | base %s=%.4f rad -> %s" % (
            c, got, deg, mid, base.get_motor_value(mid), "moved" if got > 0.25 * deg else "NOT MOVING"))
        mc.set_angular_motor_target(c, 0.0)
    for c, (mid, cm) in LIN.items():
        got = mc.get_linear_motor_current_position(c)
        unreal.log("[mc] %s: MebotController travel=%.2f cm (target %.1f) | base %s=%.3f cm -> %s" % (
            c, got, cm, mid, base.get_motor_value(mid), "moved" if got > 0.25 * cm else "NOT MOVING"))
        mc.set_linear_motor_target(c, 0.0)
