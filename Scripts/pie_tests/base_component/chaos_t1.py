import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
target = None
for p in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Pawn):
    if p.get_component_by_class(unreal.RammsDifferentialDriveController):
        target = p; break
dd = target.get_component_by_class(unreal.RammsDifferentialDriveController)
base = target.get_component_by_class(unreal.RammsRobotBaseComponent)
unreal.log("[t1] pawn=%s base=%s has_backend=%s mode=%s has_left=%s type=%s sep3D=%.2f" % (
    target.get_name(), base.get_name(), base.has_backend(), base.get_editor_property("backend"),
    base.has_motor("left_motor"), base.get_motor_type("left_motor"), base.get_motor_separation("left_motor", "right_motor")))
for c in target.get_components_by_class(unreal.ActorComponent):
    if c.get_class().get_name() == "RammsAccessInputComponent":
        c.set_component_tick_enabled(False); unreal.log("[t1] disabled tick on %s" % c.get_name())
unreal.log("[t1] loc0=%s" % target.get_actor_location())
# The pawn's own Event Tick writes the (zero) joystick every frame; silence it so
# the persistent player-path input holds (components still tick).
target.set_actor_tick_enabled(False)
dd.set_drive_input(unreal.Vector2D(0.0, 1.0))
unreal.log("[t1] commanded forward via set_drive_input: input=%s ext=%s" % (dd.get_editor_property("drive_input"), dd.is_external_drive_active()))
