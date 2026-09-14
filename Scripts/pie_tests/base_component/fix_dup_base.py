import unreal
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
SDL = unreal.SubobjectDataBlueprintFunctionLibrary
for path in ["/Game/Robots/BP_Mebot_Ramms", "/Game/Robots/BP_LiftDriveLinkage_Ramms"]:
    bp = unreal.EditorAssetLibrary.load_asset(path)
    handles = SDS.k2_gather_subobject_data_for_blueprint(bp)
    root = handles[0]
    bases = []
    for h in handles:
        d = SDL.get_data(h); obj = SDL.get_object(d)
        if obj and obj.get_class().get_name() in ("RammsRobotBaseComponent","RammsDifferentialDriveController","Ramms5BarLinkageController"):
            bases.append((h, str(SDL.get_variable_name(d)), obj))
    unreal.log("[fix] %s components: %s" % (path, [(n, o.get_class().get_name()) for _, n, o in bases]))
    for h, name, obj in bases:
        if obj.get_class().get_name() == "RammsRobotBaseComponent" and name != "RobotBase":
            n = SDS.delete_subobject(root, h, bp)
            unreal.log("[fix] deleted stray base component '%s' (removed %s)" % (name, n))
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    unreal.EditorAssetLibrary.save_loaded_asset(bp)
    # verify template config
    for h in SDS.k2_gather_subobject_data_for_blueprint(bp):
        d = SDL.get_data(h); obj = SDL.get_object(d)
        if obj and obj.get_class().get_name() == "RammsRobotBaseComponent":
            unreal.log("[fix] remaining base '%s': table=%s backend=%s mesh=%s" % (SDL.get_variable_name(d), obj.get_editor_property("motor_table"), obj.get_editor_property("backend"), obj.get_editor_property("chaos_skeletal_mesh_component_name")))
