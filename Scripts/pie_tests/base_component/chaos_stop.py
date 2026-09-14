import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
for p in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Pawn):
    dd = p.get_component_by_class(unreal.RammsDifferentialDriveController)
    if dd:
        dd.set_drive_input(unreal.Vector2D(0.0, 0.0)); unreal.log("[stop] zeroed")
