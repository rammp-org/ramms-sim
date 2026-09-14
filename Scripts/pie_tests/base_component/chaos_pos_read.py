"""Read the constraint-driven Position motors after a command, then send them back to 0."""
import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
pawn = unreal.GameplayStatics.get_player_pawn(w, 0)
base = pawn.get_component_by_class(unreal.RammsRobotBaseComponent)
EXPECT = {"left_elevator": 0.3, "right_elevator": 0.3, "front_caster_elevator": 0.3, "rear_caster_elevator": 0.3,
          "left_translator": 5.0, "right_translator": 5.0}
for m, v in EXPECT.items():
    val = base.get_motor_value(m)
    xf = base.get_motor_transform(m)  # Transform, or None when unresolved
    loc = xf.translation if xf else None
    unreal.log("[pos] %-22s value=%.4f (target %.2f, %s) vel=%.3f loc=%s" % (
        m, val, v, "moved" if abs(val) > 0.25 * abs(v) else "NOT MOVING", base.get_motor_velocity(m),
        "(%.1f, %.1f, %.1f)" % (loc.x, loc.y, loc.z) if loc else None))
    base.set_motor_command(m, 0.0)
