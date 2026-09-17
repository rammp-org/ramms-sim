"""Discard mj_setup.py's unsaved DefaultPawnClass change: reload the game mode
package from disk (so nothing is left dirty), falling back to setting the
documented default pawn back on the CDO."""
import unreal

PRIVATE = "/RammsPrivateAssets"
GAME_MODE = PRIVATE + "/Robots/BP_LiftDriveTestGameMode"
DEFAULT_PAWN = PRIVATE + "/Robots/BP_LiftDriveHolonomic_Ramms"

gm = unreal.EditorAssetLibrary.load_asset(GAME_MODE)
pkg = gm.get_outermost()
# UE 5.8 returns (any_packages_reloaded: bool, error_message: str).
result = unreal.EditorLoadingAndSavingUtils.reload_packages([pkg], unreal.ReloadPackagesInteractionMode.ASSUME_POSITIVE)
reloaded, error = (result[0], result[1]) if isinstance(result, (tuple, list)) else (bool(result), "")
if not reloaded:
    unreal.log_warning("[restore] reload_packages failed (%r); setting the default pawn back on the CDO instead" % (error,))
    cdo = unreal.get_default_object(unreal.EditorAssetLibrary.load_asset(GAME_MODE).generated_class())
    cdo.set_editor_property("default_pawn_class", unreal.EditorAssetLibrary.load_asset(DEFAULT_PAWN).generated_class())
cdo = unreal.get_default_object(unreal.EditorAssetLibrary.load_asset(GAME_MODE).generated_class())
dirty = [p.get_name() for p in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()]
unreal.log("[restore] reloaded=%s DefaultPawnClass=%s dirty=%s" % (reloaded, cdo.get_editor_property("default_pawn_class").get_name(), dirty))
if dirty:
    raise RuntimeError("[restore] packages still dirty after restore: %s" % dirty)
