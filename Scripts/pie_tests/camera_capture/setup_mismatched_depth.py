"""Place a camera whose depth resolution differs from its colour, plus a manager.

Run in the EDITOR with PIE stopped; then start PIE and the manager does the rest
on BeginPlay. The automation tests pin the arithmetic -- this exists to drive the
real GPU path and leave files on disk to inspect.

The camera is 640x480 colour and 320x240 depth, so both the size and the pixel
count differ. What should land in <project>/camera_capture_pie_test/<actor>/<cam>/:

  frame_NNNNNNN.exr         colour grid, depth resampled into alpha
  frame_NNNNNNN_depth.exr   depth grid, the measured values
  frame_NNNNNNN_motion.exr  depth grid
  frame_NNNNNNN.json        color_width/height, depth_width/height,
                            depth_resampled_into_alpha

Before the fix there was one EXR whose alpha was 0.0 everywhere: the depth plane
was judged against the colour pixel count and dropped. Nothing crashed and
nothing warned at the default log level, which is why this has to be checked on
disk rather than in a log.

    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/camera_capture/setup_mismatched_depth.py
"""

import unreal

COLOR_W, COLOR_H = 640, 480
DEPTH_W, DEPTH_H = 320, 240
OUT_DIR = "camera_capture_pie_test"
CAM_ACTOR_LABEL = "CamCapDepthMismatchTest"
MGR_ACTOR_LABEL = "CamCapTestManager"

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
actors_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; re-run this script")


def make_intrinsics(width, height):
    i = unreal.CameraIntrinsics()
    i.set_editor_property("image_width", width)
    i.set_editor_property("image_height", height)
    i.set_editor_property("focal_length_x", float(width) * 0.72)
    i.set_editor_property("focal_length_y", float(width) * 0.72)
    i.set_editor_property("principal_point_x", width / 2.0)
    i.set_editor_property("principal_point_y", height / 2.0)
    i.set_editor_property("maintain_y_axis", False)
    return i


# Idempotent: clear anything a previous run left, so repeated runs do not stack
# cameras (the manager registers every camera in the level).
for a in actors_sub.get_all_level_actors():
    if a.get_actor_label() in (CAM_ACTOR_LABEL, MGR_ACTOR_LABEL):
        print("[setup] removing previous %s" % a.get_actor_label())
        actors_sub.destroy_actor(a)

# --- the camera ------------------------------------------------------------
cam_actor = actors_sub.spawn_actor_from_class(
    unreal.Actor, unreal.Vector(0.0, 0.0, 250.0), unreal.Rotator(0.0, -20.0, 0.0))
cam_actor.set_actor_label(CAM_ACTOR_LABEL)

# Components go on through the SubobjectDataSubsystem: neither
# add_component_by_class nor register_component is exposed to Python, and a
# directly constructed component is never registered, so the capture subsystem
# would not see it. Same machinery the mebot setup scripts use, with
# ..._for_instance instead of ..._for_blueprint because this is a level actor.
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
B = unreal.SubobjectDataBlueprintFunctionLibrary

handles = SDS.k2_gather_subobject_data_for_instance(cam_actor)
params = unreal.AddNewSubobjectParams()
params.set_editor_property("parent_handle", handles[0])
params.set_editor_property("new_class", unreal.IntrinsicSceneCaptureComponent2D)
cam_handle, fail = SDS.add_new_subobject(params)
if not fail.is_empty():
    raise RuntimeError("adding the capture component failed: %s" % fail)
SDS.rename_subobject(cam_handle, unreal.Text("TestDepthMismatchCam"))
cam = B.get_object(SDS.k2_find_subobject_data_from_handle(cam_handle))
if cam is None:
    raise RuntimeError("could not resolve the new capture component")
cam.set_editor_property("use_custom_intrinsics", True)
cam.set_editor_property("use_intrinsics_asset", False)
cam.set_editor_property("inline_intrinsics", make_intrinsics(COLOR_W, COLOR_H))
# The configuration under test. Without this the depth camera inherits the
# colour intrinsics and the two grids are identical.
cam.set_editor_property("use_depth_intrinsics", True)
cam.set_editor_property("use_depth_intrinsics_asset", False)
cam.set_editor_property("depth_inline_intrinsics", make_intrinsics(DEPTH_W, DEPTH_H))

ci = cam.get_active_intrinsics()
di = cam.get_active_depth_intrinsics()
print("[setup] separate depth intrinsics: %s" % cam.has_separate_depth_intrinsics())
print("[setup] colour %dx%d, depth %dx%d"
      % (ci.image_width, ci.image_height, di.image_width, di.image_height))
if (ci.image_width, ci.image_height) == (di.image_width, di.image_height):
    raise RuntimeError("the two grids are identical -- this would not test anything")

# --- the manager -----------------------------------------------------------
mgr = actors_sub.spawn_actor_from_class(
    unreal.CameraCaptureManager, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0))
mgr.set_actor_label(MGR_ACTOR_LABEL)
mgr.set_editor_property("output_directory", OUT_DIR)
mgr.set_editor_property("capture_every_n_frames", 1)
mgr.set_editor_property("auto_configure_cameras_on_begin_play", True)
mgr.set_editor_property("auto_start_capture_on_begin_play", True)
mgr.set_editor_property("auto_start_serialization_on_begin_play", True)
mgr.set_editor_property("capture_rgb", True)
mgr.set_editor_property("capture_depth", True)
# The whole point of this scenario is a depth plane at its own resolution, and
# only the two-render mode has a depth camera of its own to give it one. The
# default is now SingleCaptureColorDepth, which takes both planes from one
# target and so one resolution -- leaving the mode alone would collapse the
# mismatch this test exists to exercise and still pass.
mgr.set_editor_property("capture_mode", unreal.RammsCaptureMode.TONEMAPPED_COLOR_PLUS_DEPTH)
mgr.set_editor_property("capture_motion_vectors", True)
mgr.set_editor_property("registration_mode", unreal.CameraRegistrationMode.ALL_IN_LEVEL)

print("[setup] manager writing to <project>/%s, every frame, serialization on" % OUT_DIR)
print("[setup] ready -- start PIE")
