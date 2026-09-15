"""Strip a robot Blueprint's direct input wiring (key events, input-action
reads, the per-tick SetDriveInput write) now that keys and the drive go through
the control surface. unreal._ramms_strip_bp: asset path (default BP_Mebot_Ramms)."""
import unreal
path = getattr(unreal, "_ramms_strip_bp", "/Game/Robots/BP_Mebot_Ramms")
bp = unreal.EditorAssetLibrary.load_asset(path)
L = unreal.RammsBlueprintCleanupLibrary
before = L.list_input_nodes(bp)
unreal.log("[strip] %s input nodes before: %s" % (path, [str(x) for x in before]))
n = L.remove_legacy_input_nodes(bp, ["SetDriveInput"])
unreal.BlueprintEditorLibrary.remove_unused_nodes(bp)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
unreal.EditorAssetLibrary.save_loaded_asset(bp)
unreal.log("[strip] removed %d ; after: %s ; saved" % (n, [str(x) for x in L.list_input_nodes(bp)]))
