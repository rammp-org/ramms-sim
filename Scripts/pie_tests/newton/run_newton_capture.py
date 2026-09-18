"""Place the gen3 arm in the Newton test level, run it, and capture frames.

Swaps the pendulum for Content/Robots/URL/gen3_2f85_fixed, starts play, waits
for the Newton solver to take over stepping, unpauses, and writes a numbered
PNG sequence to Saved/Screenshots/MacEditor/. Assemble with ffmpeg afterwards.

    python3 Scripts/editor_remote_exec.py --file Scripts/pie_tests/newton/run_newton_capture.py
"""

import unreal

MAP = "/Game/Maps/URL/Map_NewtonTest_URL"
ROBOT = "/Game/Robots/URL/gen3_2f85_fixed"

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running — stopped it; re-run this script")

les.load_level(MAP)
world = ues.get_editor_world()

# Swap whatever robot is in the level for the arm.
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.MjArticulation):
    eas.destroy_actor(a)
cls = unreal.EditorAssetLibrary.load_asset(ROBOT).generated_class()
arm = unreal.EditorLevelLibrary.spawn_actor_from_class(cls, unreal.Vector(0, 0, 0))
arm.set_actor_label("Gen3")
print("[cap] placed", arm.get_name())

les.editor_request_begin_play()
print("[cap] begin play requested — poll, then call the capture helper")
