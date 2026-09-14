import unreal
# Discard the in-editor actor swap: reload the map from disk without saving.
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
unreal.EditorLoadingAndSavingUtils.load_map("/Game/Maps/URL/Map_BaseTest_URL")
unreal.log("[reload] dirty maps now: %s" % [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()])
