import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
for p in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Pawn):
    dd = p.get_component_by_class(unreal.RammsDifferentialDriveController)
    if not dd: continue
    base = p.get_component_by_class(unreal.RammsRobotBaseComponent)
    L = dd.get_left_wheel_state(); R = dd.get_right_wheel_state(); loc = p.get_actor_location()
    unreal.log("[s] x=%.1f y=%.1f | L angvel=%.2f applied=%.2f | R angvel=%.2f applied=%.2f | base vel L=%.2f R=%.2f | in=%s ext=%s" % (
        loc.x, loc.y, L.get_editor_property("angular_velocity"), L.get_editor_property("applied_torque"),
        R.get_editor_property("angular_velocity"), R.get_editor_property("applied_torque"),
        base.get_motor_velocity("left_motor"), base.get_motor_velocity("right_motor"),
        dd.get_editor_property("drive_input").y, dd.is_external_drive_active()))
