"""Start the MuJoCo PIE test on Map_BaseTest_URL with the linkage pawn.

The map's BP_LiftDriveTestGameMode spawns DefaultPawnClass before the MuJoCo
scene compiles (nothing is placed in the map any more), so the test just points
the game mode at BP_LiftDriveLinkage_Ramms for this run and begins play.
mj_restore.py (run after mj_teardown.py) reloads the game mode from disk, so the
change is never saved.
"""
import unreal

MAP = "/Game/Maps/URL/Map_BaseTest_URL"
GAME_MODE = "/Game/Robots/BP_LiftDriveTestGameMode"
PAWN = "/Game/Robots/BP_LiftDriveLinkage_Ramms"

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_path_name() != MAP + "." + MAP.split("/")[-1]:
    les.load_level(MAP)

gm_cdo = unreal.get_default_object(unreal.EditorAssetLibrary.load_asset(GAME_MODE).generated_class())
prev = gm_cdo.get_editor_property("default_pawn_class")
gm_cdo.set_editor_property("default_pawn_class", unreal.EditorAssetLibrary.load_asset(PAWN).generated_class())
unreal.log("[setup] %s DefaultPawnClass %s -> %s (unsaved; mj_restore.py reloads it from disk)" % (
    GAME_MODE.split("/")[-1], prev.get_name() if prev else None, gm_cdo.get_editor_property("default_pawn_class").get_name()))

les.editor_request_begin_play()
unreal.log("[pie] begin play requested (Map_BaseTest_URL)")
