"""Place N capture cameras plus a manager, for bench_capture.py.

Reads bench_config.json beside this file. Run in the EDITOR with PIE stopped.

The cameras are spread around a circle looking outward so they do not all
render the same thing -- identical views would let the renderer share work
between them and understate the cost of adding a camera.
"""

import json
import math
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "bench_config.json")))

COUNT = int(CFG.get("camera_count", 1))
W, H = int(CFG.get("width", 640)), int(CFG.get("height", 480))
DW, DH = int(CFG.get("depth_width", W)), int(CFG.get("depth_height", H))
OUT_DIR = CFG.get("output_dir", "camera_capture_bench")
SEPARATE_DEPTH = bool(CFG.get("separate_depth", True))

CAM_LABEL = "BenchCam"
MGR_LABEL = "BenchManager"

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


# Idempotent: a stale camera from a previous sweep step would be registered too
# and silently change the camera count being measured.
removed = 0
for a in actors.get_all_level_actors():
    label = a.get_actor_label()
    if label.startswith(CAM_LABEL) or label == MGR_LABEL:
        actors.destroy_actor(a)
        removed += 1
if removed:
    print("[bench-setup] removed %d actor(s) from a previous run" % removed)

made = []
for n in range(COUNT):
    angle = (2.0 * math.pi * n) / max(1, COUNT)
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
    SDS.rename_subobject(handle, unreal.Text("BenchCam_%d" % n))
    cam = B.get_object(SDS.k2_find_subobject_data_from_handle(handle))

    cam.set_editor_property("use_custom_intrinsics", True)
    cam.set_editor_property("use_intrinsics_asset", False)
    cam.set_editor_property("inline_intrinsics", intrinsics(W, H))
    cam.set_editor_property("use_depth_intrinsics", SEPARATE_DEPTH)
    cam.set_editor_property("use_depth_intrinsics_asset", False)
    cam.set_editor_property("depth_inline_intrinsics", intrinsics(DW, DH))
    made.append(cam)

mgr = actors.spawn_actor_from_class(
    unreal.CameraCaptureManager, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0))
mgr.set_actor_label(MGR_LABEL)
mgr.set_editor_property("output_directory", OUT_DIR)
mgr.set_editor_property("capture_every_n_frames", 1)
mgr.set_editor_property("auto_configure_cameras_on_begin_play", True)
# The benchmark drives capture itself, so BeginPlay must not start it.
mgr.set_editor_property("auto_start_capture_on_begin_play", False)
mgr.set_editor_property("auto_start_serialization_on_begin_play", False)
mgr.set_editor_property("capture_rgb", True)
mgr.set_editor_property("capture_depth", True)
# Motion is its OWN pass now, available in both modes and costing its own render
# in either, so it is set the same way for both. It used to be disabled for
# single capture only -- because that mode genuinely could not produce it -- and
# leaving that in place after the decoupling would compare a mode WITH motion
# against a mode WITHOUT it and report the difference as the mode's saving.
SINGLE = bool(CFG.get("single_capture", False))
mgr.set_editor_property("capture_motion_vectors", bool(CFG.get("capture_motion", True)))
mgr.set_editor_property(
    "capture_mode",
    unreal.RammsCaptureMode.SINGLE_CAPTURE_COLOR_DEPTH if SINGLE
    else unreal.RammsCaptureMode.TONEMAPPED_COLOR_PLUS_DEPTH)
# Manual, not AllInLevel: the demo map's robot carries five cameras of its own,
# and registering those would mean the measurement is not of COUNT cameras.
mgr.set_editor_property("registration_mode", unreal.CameraRegistrationMode.MANUAL)
mgr.set_editor_property("cameras_to_capture", made)

# NOTE on throttling: UEditorPerformanceSettings is not exposed to Python, so
# bThrottleCPUWhenNotForeground cannot be cleared from here. It is config=
# EditorSettings, so the editor must be launched with
#   -ini:EditorSettings:[/Script/UnrealEd.EditorPerformanceSettings]:bThrottleCPUWhenNotForeground=False
# Without that the editor hard-caps its frame rate whenever its window is not in
# the foreground, and every measurement describes the cap instead of the
# workload -- it shows up as an identical p95 across all phases.

print("[bench-setup] %d camera(s) at %dx%d colour / %dx%d depth (separate_depth=%s, single_capture=%s)"
      % (len(made), W, H, DW, DH, SEPARATE_DEPTH, SINGLE))
if len(made) != COUNT:
    raise RuntimeError("expected %d cameras, made %d" % (COUNT, len(made)))
