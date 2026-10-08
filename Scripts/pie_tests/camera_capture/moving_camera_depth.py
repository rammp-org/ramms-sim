"""Regression test: depth and motion must track a moving camera.

The readback pool let a pooled FRHIGPUTextureReadback arrive with its fence
still signalled from the previous use, so IsReady() answered true before the new
copy had been issued and the harvest read an earlier frame's staging buffer --
forever. Colour kept updating (different pool entry, different timing) while
depth and motion froze on the first frame they ever captured. Byte-identical
depth EXRs across frames, and motion vectors permanently zero.

A static scene cannot see this: the depth of a still scene is legitimately the
same every frame. The camera has to move, and the test has to prove it moved
before it is allowed to conclude anything about the depth.

Run with PIE already running and a camera placed by setup_mismatched_depth.py:

    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/camera_capture/moving_camera_depth.py

Then check the files:

    python3 Scripts/pie_tests/camera_capture/verify_moving_capture.py <camera dir>
"""

import unreal

SPEED_CM_PER_S = 500.0
FRAMES = 30

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_game_world()
if world is None:
    raise RuntimeError("PIE is not running")

actor = None
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
    if a.get_actor_label().startswith("CamCapDepthMismatchTest"):
        actor = a
        break
if actor is None:
    raise RuntimeError("no CamCapDepthMismatchTest actor; run setup_mismatched_depth.py first")

mgr = None
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CameraCaptureManager):
    mgr = a
    break
if mgr is None:
    raise RuntimeError("no CameraCaptureManager in the PIE world")

state = {"n": 0, "handle": None, "start_x": None, "end_x": None}


def _stop():
    if state["handle"] is not None:
        unreal.unregister_slate_post_tick_callback(state["handle"])
        state["handle"] = None


def tick(delta_seconds):
    """Move the camera, and unregister on ANY failure.

    A slate post-tick callback outlives PIE. Left registered, it keeps firing
    against a destroyed actor and throws every frame -- one run of an earlier
    version of this script put 13331 tracebacks in the log and added a per-frame
    exception to everything measured afterwards. Hence the blanket except and
    the explicit world check: a leaked callback is worse than a failed test.
    """
    try:
        if state["handle"] is None:
            return
        if ues.get_game_world() is None:
            _stop()
            return

        loc = actor.get_actor_location()
        if state["start_x"] is None:
            state["start_x"] = loc.x
        actor.set_actor_location(
            unreal.Vector(loc.x + SPEED_CM_PER_S * delta_seconds, loc.y, loc.z), False, False)
        state["end_x"] = actor.get_actor_location().x
        state["n"] += 1

        if state["n"] >= FRAMES:
            # Stop capturing, not just moving: every frame written after this
            # point is a static one the verifier would count against the result.
            mgr.stop_capture()
            print("[moving] moved x %.1f -> %.1f over %d frames; capture stopped"
                  % (state["start_x"], state["end_x"], state["n"]))
            _stop()
    except Exception as e:
        print("[moving] stopping after error: %s" % e)
        _stop()


# Start from an empty directory and stop when the movement does, so the frames
# on disk are exactly the moving ones. Left running, the manager keeps capturing
# STATIC frames after this script finishes, and the verifier -- which asks
# whether depth changed on most frames -- then measures a run that is mostly
# stationary and fails a capture that tracked perfectly.
mgr.stop_capture()
out = mgr.get_editor_property("output_directory")
if out:
    import os
    import shutil

    root = out if os.path.isabs(out) else os.path.join(unreal.Paths.project_dir(), out)
    root = os.path.normpath(root)
    if os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
        print("[moving] cleared %s so only the moving frames land in it" % root)

mgr.set_serialization_enabled(True)
mgr.start_capture()
state["handle"] = unreal.register_slate_post_tick_callback(tick)
# Held on the module so the callback is not collected mid-run.
unreal.CamCapMovingTestState = state
print("[moving] capturing while moving the camera at %.0f cm/s" % SPEED_CM_PER_S)
