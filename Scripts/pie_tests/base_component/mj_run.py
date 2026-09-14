import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
m = [x for x in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Actor) if x.get_class().get_name() == "AMjManager"][0]
unreal.log("[run] before: is_running=%s sim_time=%.4f timestep=%.5f step_mode=%s last_err=%r" % (m.is_running(), m.get_sim_time(), m.get_timestep(), m.get_editor_property("step_mode"), m.get_last_compile_error()))
if not m.is_running():
    m.set_paused(False)
    unreal.log("[run] set_paused(False) -> is_running=%s" % m.is_running())
