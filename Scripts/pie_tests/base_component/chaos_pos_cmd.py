"""Command the chair's constraint-driven Position motors through the base (PIE on Map_Demo)."""
import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
pawn = unreal.GameplayStatics.get_player_pawn(w, 0)
base = pawn.get_component_by_class(unreal.RammsRobotBaseComponent)
CMDS = {"left_elevator": 0.3, "right_elevator": 0.3, "front_caster_elevator": 0.3, "rear_caster_elevator": 0.3,
        "left_translator": 5.0, "right_translator": 5.0}
for m, v in CMDS.items():
    unreal.log("[pos] %-22s type=%s before=%.4f -> command %.2f" % (m, base.get_motor_type(m), base.get_motor_value(m), v))
    base.set_motor_command(m, v)
