"""End the MuJoCo PIE test. Run mj_restore.py afterwards (once PIE has ended) to
discard the unsaved DefaultPawnClass change on the game mode."""
import unreal
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_end_play()
unreal.log("[pie] end play requested")
