"""Turn check for the Chaos chair: joystick X = +1 must turn RIGHT (UE yaw increases).

Set unreal._ramms_turn_op to 'start' (record yaw, command the turn), 'check'
(compare yaw, zero the input)."""
import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
p = [p for p in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Pawn) if p.get_component_by_class(unreal.RammsDifferentialDriveController)][0]
dd = p.get_component_by_class(unreal.RammsDifferentialDriveController)
op = getattr(unreal, "_ramms_turn_op", "check")
yaw = p.get_actor_rotation().yaw
if op == "start":
    unreal._ramms_turn_yaw0 = yaw
    dd.set_drive_input(unreal.Vector2D(1.0, 0.0))
    unreal.log("[turn] start yaw=%.1f, commanding X=+1 (turn right)" % yaw)
else:
    y0 = getattr(unreal, "_ramms_turn_yaw0", 0.0)
    d = unreal.MathLibrary.normalize_axis(yaw - y0)
    dd.set_drive_input(unreal.Vector2D(0.0, 0.0))
    verdict = "turned RIGHT (ok)" if d > 5.0 else ("turned LEFT (WRONG)" if d < -5.0 else "no turn (FAIL)")
    unreal.log("[turn] check yaw=%.1f delta=%+.1f deg -> %s" % (yaw, d, verdict))
    if "ok" not in verdict:
        raise RuntimeError("[turn] " + verdict)
