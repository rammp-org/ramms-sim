import unreal
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if unreal.EditorLevelLibrary.get_editor_world().get_path_name() != "/Game/Maps/URL/Map_BaseTest_URL.Map_BaseTest_URL":
    les.load_level("/Game/Maps/URL/Map_BaseTest_URL")
child = unreal.EditorAssetLibrary.load_asset("/Game/Robots/BP_LiftDriveLinkage_Ramms").generated_class()
placed = None
for a in unreal.EditorLevelLibrary.get_all_level_actors():
    cn = a.get_class().get_name()
    if cn.startswith("lift_drive_linkage"):
        placed = a
    if "Mj" in cn or "lift_drive" in cn.lower():
        unreal.log("[setup] level actor %s (%s) at %s" % (a.get_name(), cn, a.get_actor_location()))
if placed is None:
    raise RuntimeError("no placed lift_drive_linkage actor")
xf = placed.get_actor_transform()
unreal.EditorLevelLibrary.destroy_actor(placed)
new = unreal.EditorLevelLibrary.spawn_actor_from_class(child, xf.translation, xf.rotation.rotator())
unreal.log("[setup] replaced placed linkage with %s (%s)" % (new.get_name(), new.get_class().get_name()))
les.editor_request_begin_play()
unreal.log("[pie] begin play requested (Map_BaseTest_URL)")
