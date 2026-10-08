"""Put the camera capture panel on screen in PIE.

Creates URammsCameraCapturePanel and adds it to the viewport, so the feeds and
controls can be seen and clicked without authoring a Blueprint for it.

    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/camera_capture/show_capture_panel.py
"""

import unreal

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_game_world()
if world is None:
    raise RuntimeError("PIE is not running")

pc = unreal.GameplayStatics.get_player_controller(world, 0)
if pc is None:
    raise RuntimeError("no player controller; PIE needs a possessed pawn")

panel = unreal.WidgetBlueprintLibrary.create(pc, unreal.RammsCameraCapturePanel)
if panel is None:
    raise RuntimeError("could not create URammsCameraCapturePanel")
panel.add_to_viewport(100)

print("[panel] added to viewport")
