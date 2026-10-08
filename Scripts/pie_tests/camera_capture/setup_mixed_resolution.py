"""Place capture cameras of DIFFERENT resolutions, for the readback-pool regression.

Run in the EDITOR with PIE stopped. Capture starts itself on begin play, so the
whole test is: run this, start PIE, let it run, stop PIE, then count the files
and grep the log (see verify_mixed_resolution.sh).

What it is for
--------------
The readback pool handed a pooled FRHIGPUTextureReadback to whichever camera
asked next, regardless of size. FRHIGPUTextureReadback::EnqueueCopy recreates
its staging texture only when the texture DIMENSION changes (2D vs 3D) -- never
when the SIZE changes, and on platforms that read back through 2D textures only
it never recreates one at all. The engine states the assumption beside the
branch: "Assume for now that every enqueue happens on a texture of the same
format and size (when reused)."

So a readback first used for a 640x360 camera stayed shaped for 640x360. Handed
to a 1280x720 camera it copied into the smaller staging texture, Lock() reported
pitch 640 / buffer height 360, and the harvest's geometry guard dropped the
frame:

  [CameraCaptureSubsystem] RGB readback geometry does not hold the expected
  image: 1280x720 requested, pitch 640, buffer height 360

A single-resolution scene cannot see this: every camera asks for the same shape,
so every reuse happens to be valid. That is why the benchmark missed it -- it
scales camera COUNT at a fixed resolution, exactly the axis that cannot fail --
and why the mismatched-depth test missed it too, having only one camera.

The resolutions below repeat 1280x720 on purpose, so the run covers a reuse that
IS valid as well as ones that are not, and depth is half of colour on each
camera so both pool buckets are exercised.
"""

import math

import unreal

# (colour w, colour h) -- depth is half of each, set below.
RESOLUTIONS = [(1280, 720), (640, 360), (1280, 720), (320, 240)]

OUT_DIR = "camera_capture_mixedres"
CAM_LABEL = "MixedResCam"
MGR_LABEL = "MixedResManager"

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
B = unreal.SubobjectDataBlueprintFunctionLibrary

if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; re-run this script")


def intrinsics(width, height):
    i = unreal.CameraIntrinsics()
    i.set_editor_property("image_width", width)
    i.set_editor_property("image_height", height)
    i.set_editor_property("focal_length_x", float(width) * 0.72)
    i.set_editor_property("focal_length_y", float(width) * 0.72)
    i.set_editor_property("principal_point_x", width / 2.0)
    i.set_editor_property("principal_point_y", height / 2.0)
    i.set_editor_property("maintain_y_axis", False)
    return i


# Idempotent: a camera left over from a previous run would register too and
# change what is being measured.
removed = 0
for a in actors.get_all_level_actors():
    label = a.get_actor_label()
    if label.startswith(CAM_LABEL) or label == MGR_LABEL:
        actors.destroy_actor(a)
        removed += 1
if removed:
    print("[mixedres] removed %d actor(s) from a previous run" % removed)

made = []
for n, (w, h) in enumerate(RESOLUTIONS):
    # Spread around a circle looking outward, so the cameras do not all render
    # the same thing.
    angle = (2.0 * math.pi * n) / len(RESOLUTIONS)
    loc = unreal.Vector(220.0 * math.cos(angle), 220.0 * math.sin(angle), 250.0)
    rot = unreal.Rotator(0.0, math.degrees(angle), 0.0)
    actor = actors.spawn_actor_from_class(unreal.Actor, loc, rot)
    actor.set_actor_label("%s_%d" % (CAM_LABEL, n))

    handles = SDS.k2_gather_subobject_data_for_instance(actor)
    params = unreal.AddNewSubobjectParams()
    params.set_editor_property("parent_handle", handles[0])
    params.set_editor_property("new_class", unreal.IntrinsicSceneCaptureComponent2D)
    handle, fail = SDS.add_new_subobject(params)
    if not fail.is_empty():
        raise RuntimeError("adding camera %d failed: %s" % (n, fail))
    SDS.rename_subobject(handle, unreal.Text("%s_%d" % (CAM_LABEL, n)))
    cam = B.get_object(SDS.k2_find_subobject_data_from_handle(handle))

    dw, dh = max(1, w // 2), max(1, h // 2)
    cam.set_editor_property("use_custom_intrinsics", True)
    cam.set_editor_property("use_intrinsics_asset", False)
    cam.set_editor_property("inline_intrinsics", intrinsics(w, h))
    cam.set_editor_property("use_depth_intrinsics", True)
    cam.set_editor_property("use_depth_intrinsics_asset", False)
    cam.set_editor_property("depth_inline_intrinsics", intrinsics(dw, dh))
    made.append(cam)
    print("[mixedres] camera %d: colour %dx%d, depth %dx%d" % (n, w, h, dw, dh))

mgr = actors.spawn_actor_from_class(
    unreal.CameraCaptureManager, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0))
mgr.set_actor_label(MGR_LABEL)
mgr.set_editor_property("output_directory", OUT_DIR)
mgr.set_editor_property("capture_every_n_frames", 1)
mgr.set_editor_property("auto_configure_cameras_on_begin_play", True)
# Capture and write from begin play, so the test needs no tick callback at all --
# a leaked slate post-tick callback once put 13331 tracebacks in the log.
mgr.set_editor_property("auto_start_capture_on_begin_play", True)
mgr.set_editor_property("auto_start_serialization_on_begin_play", True)
mgr.set_editor_property("capture_rgb", True)
mgr.set_editor_property("capture_depth", True)
mgr.set_editor_property("capture_motion_vectors", True)
mgr.set_editor_property("capture_mode", unreal.RammsCaptureMode.TONEMAPPED_COLOR_PLUS_DEPTH)
# Manual: the demo map's robot carries cameras of its own, and registering those
# would add shapes this test did not choose.
mgr.set_editor_property("registration_mode", unreal.CameraRegistrationMode.MANUAL)
mgr.set_editor_property("cameras_to_capture", made)

print("[mixedres] %d cameras placed, writing to %s; start PIE to capture" % (len(made), OUT_DIR))
