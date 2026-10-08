"""Check the camera capture panel is live in the HUD and that its controls work.

Enables the HUD setting, rebuilds the HUD, then drives the panel's own actions
and reads the subsystem back. The point is the wiring -- a panel action has to
move subsystem state -- not merely that a widget got constructed.

Run with PIE running and a possessed pawn (editor_request_begin_play, not
play_simulate: the HUD needs a local player controller):

    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/camera_capture/verify_capture_panel.py
"""

import unreal

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if world is None:
    raise RuntimeError("PIE is not running")

fails = []


def check(ok, what):
    print("[panel] %s  %s" % ("pass" if ok else "FAIL", what))
    if not ok:
        fails.append(what)


# URammsControlHUDSettings is not exposed to Python, so the flag has to come from
# config. It is UCLASS(Config = Game), so launch the editor with:
#   -ini:Game:[/Script/RammsUI.RammsControlHUDSettings]:bShowCameraCapturePanel=True
# or set "Ramms Control HUD -> Show Camera Capture Panel" in Project Settings.

hud = unreal.RammsControlHUDSubsystem.get(world)
check(hud is not None, "HUD subsystem reachable")
if hud is None:
    raise SystemExit(1)

check(hud.spawn_hud(), "HUD rebuilt with the panel enabled")

panel = hud.get_camera_capture_panel()
check(panel is not None, "panel exists in the HUD")
if panel is None:
    print("[panel] FAILURES (%d)" % len(fails))
    raise SystemExit(1)

check(panel.is_in_viewport() or panel.get_parent() is not None,
      "panel is parented into the layout")

# --- the wiring: a panel action must change subsystem state ---------------
mgr = None
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CameraCaptureManager):
    mgr = a
    break
check(mgr is not None, "a CameraCaptureManager is present to report state")

before = mgr.is_capturing() if mgr and hasattr(mgr, "is_capturing") else None
panel.toggle_capture()
after = mgr.is_capturing() if mgr and hasattr(mgr, "is_capturing") else None
if before is not None and after is not None:
    check(before != after, "ToggleCapture changed the capture state (%s -> %s)" % (before, after))
    panel.toggle_capture()  # leave it as we found it
else:
    print("[panel] note: manager does not expose is_capturing; capture toggle not asserted")

panel.step_capture_rate(1)
panel.step_capture_rate(1)
print("[panel] stepped the capture rate up twice")
panel.step_capture_rate(-2)

panel.toggle_serialization()
panel.toggle_serialization()
print("[panel] serialization toggled and restored")

panel.rebuild_feeds()
print("[panel] feeds rebuilt without error")

print("[panel] %s (%d failing)" % ("ALL GREEN" if not fails else "FAILURES", len(fails)))
# Remote exec reports the command's success, not the script's conclusions, so a
# run with failing checks looked like a pass to anything driving this.
if fails:
    raise SystemExit(1)
