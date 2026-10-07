"""Regression test: cameras of DIFFERENT resolutions must all capture.

The readback pool handed a pooled FRHIGPUTextureReadback to whichever camera
asked next, regardless of size. FRHIGPUTextureReadback::EnqueueCopy recreates
its staging texture only when the texture DIMENSION changes (2D vs 3D) -- never
when the SIZE changes, and on platforms that read back through 2D textures only
it never recreates one at all. The engine says so in its own comment: "Assume
for now that every enqueue happens on a texture of the same format and size
(when reused)."

So a readback first used for a 640x360 camera stayed shaped for 640x360. Handed
to a 1280x720 camera it copied into the smaller staging texture, Lock() reported
pitch 640 / buffer height 360, and the harvest's geometry guard dropped the
frame:

  [CameraCaptureSubsystem] RGB readback geometry does not hold the expected
  image: 1280x720 requested, pitch 640, buffer height 360

A single-resolution scene cannot see this -- every camera asks for the same
shape, so every reuse happens to be valid, which is why the benchmark (uniform
cameras) and the mismatched-DEPTH test (one camera) both missed it. It needs at
least two cameras at different COLOUR resolutions.

It also could not appear at all until the pool actually pooled: before that fix
ReleaseReadback's IsUnique() check failed every time and every readback was
freshly allocated.

Run with PIE running:

    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/camera_capture/mixed_resolution_cameras.py

Then check the output directory: every camera must have the same frame count,
and no frame may be missing.
"""

import unreal

# Deliberately different shapes, and deliberately including two that share one
# so the test covers both the reuse-is-valid and reuse-is-invalid paths.
RESOLUTIONS = [(1280, 720), (640, 360), (1280, 720), (320, 240)]
FRAMES = 20

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_game_world()
if world is None:
    raise RuntimeError("PIE is not running")

mgr = None
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CameraCaptureManager):
    mgr = a
    break
if mgr is None:
    raise RuntimeError("no CameraCaptureManager in the PIE world")

sub = mgr.get_subsystem() if hasattr(mgr, "get_subsystem") else None
cameras = list(sub.get_registered_cameras()) if sub else []
if len(cameras) < 2:
    raise RuntimeError(
        "need at least 2 registered cameras; run bench_setup.py with camera_count >= 2 first")

# Give each camera its own intrinsic resolution. Done before capture starts so
# EnsureCameraRenderTarget sizes each target once rather than mid-flight.
for i, cam in enumerate(cameras):
    w, h = RESOLUTIONS[i % len(RESOLUTIONS)]
    intr = cam.get_editor_property("intrinsics")
    intr.image_width = w
    intr.image_height = h
    cam.set_editor_property("intrinsics", intr)
    print("[mixed] camera %d -> %dx%d" % (i, w, h))

state = {"n": 0, "handle": None, "errors": 0}


def _stop():
    if state["handle"] is not None:
        unreal.unregister_slate_post_tick_callback(state["handle"])
        state["handle"] = None


def tick(delta_seconds):
    """Count frames, then stop. Unregisters on ANY failure.

    A slate post-tick callback outlives PIE; left registered it fires against a
    destroyed world and throws every frame. An earlier version of another script
    here put 13331 tracebacks in the log that way.
    """
    try:
        if state["handle"] is None:
            return
        if ues.get_game_world() is None:
            _stop()
            return
        state["n"] += 1
        if state["n"] >= FRAMES:
            mgr.stop_capture()
            stats = sub.get_statistics() if sub else None
            print("[mixed] stopped after %d frames; frames captured: %s"
                  % (state["n"], stats.total_frames_captured if stats else "?"))
            print("[mixed] now grep the log for 'geometry does not hold' -- any hit is a FAILURE,")
            print("[mixed] and every camera directory must hold the same number of frames.")
            _stop()
    except Exception as e:
        print("[mixed] stopping after error: %s" % e)
        _stop()


mgr.set_serialization_enabled(True)
mgr.start_capture()
state["handle"] = unreal.register_slate_post_tick_callback(tick)
# Held on the module so the callback is not collected mid-run.
unreal.CamCapMixedResState = state
print("[mixed] capturing %d frames across %d cameras of differing resolution"
      % (FRAMES, len(cameras)))
