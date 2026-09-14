"""Discard mj_setup.py's unsaved DefaultPawnClass change: reload the game mode
package from disk (so nothing is left dirty), falling back to setting the
documented default pawn back on the CDO."""
import unreal

GAME_MODE = "/Game/Robots/BP_LiftDriveTestGameMode"
DEFAULT_PAWN = "/Game/Robots/BP_LiftDriveHolonomic_Ramms"

gm = unreal.EditorAssetLibrary.load_asset(GAME_MODE)
pkg = gm.get_outermost()
ok, reloaded = unreal.EditorLoadingAndSavingUtils.reload_packages([pkg], unreal.ReloadPackagesInteractionMode.ASSUME_POSITIVE)
if not (ok and reloaded):
    cdo = unreal.get_default_object(unreal.EditorAssetLibrary.load_asset(GAME_MODE).generated_class())
    cdo.set_editor_property("default_pawn_class", unreal.EditorAssetLibrary.load_asset(DEFAULT_PAWN).generated_class())
cdo = unreal.get_default_object(unreal.EditorAssetLibrary.load_asset(GAME_MODE).generated_class())
dirty = [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()]
unreal.log("[restore] reloaded=%s DefaultPawnClass=%s dirty=%s" % (bool(ok), cdo.get_editor_property("default_pawn_class").get_name(), dirty))
