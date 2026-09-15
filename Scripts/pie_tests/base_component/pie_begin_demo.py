import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if unreal.EditorLevelLibrary.get_editor_world().get_path_name() != "/Game/Maps/Map_Demo.Map_Demo":
    les.load_level("/Game/Maps/Map_Demo")
les.editor_request_begin_play()
unreal.log("[pie] begin play requested (Map_Demo)")
