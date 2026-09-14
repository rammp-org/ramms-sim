import unreal
def find():
    w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
    for a in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Actor):
        if a.get_component_by_class(unreal.RammsRobotBaseComponent):
            return w, a
    return w, None
