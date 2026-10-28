"""PIE segmentation capture: one camera at the level's PlayerStart, class masks on (see SEGMENTATION.md).

Runs inside the editor, from a slate tick so the console returns at once. Starts PIE, puts a camera
SEG_Z cm above the first PlayerStart looking along it, captures colour + depth + class masks every
SEG_EVERY frames for SEG_SECONDS, then stops capture and ends PIE. Optional settings, consumed when read
(the editor's Python globals outlive a console entry):

    SEG_OUT      output directory (default <project>/Saved/SegCapture/<map>)
    SEG_SECONDS  capture time, s (8)          SEG_EVERY  capture every N frames (20)
    SEG_W, SEG_H image size (640 x 480)       SEG_F      focal length, px (380)
    SEG_Z        camera height above the PlayerStart, cm (120)
    SEG_PITCH    camera pitch, deg (-8)       SEG_YAW    yaw added to the PlayerStart's, deg (0)
    SEG_SPEED    move the camera straight ahead at this speed, cm/s of game time (0: stand still)
    SEG_DEPTH    capture depth too (True)     SEG_PNG    write colour as PNG rather than EXR (False)

Progress goes to <project>/Saved/SegCapture/segmentation_capture.log.
"""
import os
import time

import unreal

_SEG_OPTS = {k: globals().pop(k) for k in ("SEG_OUT", "SEG_SECONDS", "SEG_EVERY", "SEG_W", "SEG_H", "SEG_F", "SEG_Z", "SEG_PITCH", "SEG_YAW", "SEG_SPEED", "SEG_DEPTH", "SEG_PNG")
             if k in globals()}


def _segmentation_capture(opts):
    saved = os.path.abspath(unreal.Paths.project_saved_dir())
    log_path = os.path.join(saved, "SegCapture", "segmentation_capture.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    st = {"phase": "start", "t0": time.time(), "log": []}
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    map_name = ues.get_editor_world().get_name()
    out = opts.get("SEG_OUT", os.path.join(saved, "SegCapture", map_name))

    def log(msg):
        st["log"].append("%.1f %s" % (time.time() - st["t0"], msg))
        with open(log_path, "w") as f:
            f.write("\n".join(st["log"]) + "\n")

    def finish():
        unreal.unregister_slate_post_tick_callback(st["handle"])
        st.clear()  # drop every reference into the PIE world, so it can be collected

    def capture_subsystem(world):
        for sub in unreal.ObjectIterator(unreal.CameraCaptureSubsystem):
            if sub.get_outer() == world:
                return sub
        return None

    def tick(_dt):
        try:
            now = time.time()
            gw = ues.get_game_world()
            if st["phase"] == "start":
                if gw is None:
                    les.editor_request_begin_play()
                st.update(phase="wait", until=now + 3.0)
                log("begin play (%s)" % map_name)
                return
            if st["phase"] == "wait":
                if gw is None or now < st["until"]:
                    if now - st["t0"] > 90:
                        log("PIE did not start")
                        finish()
                    return
                starts = unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.PlayerStart)
                loc = starts[0].get_actor_location() if starts else unreal.Vector(0, 0, 0)
                yaw = starts[0].get_actor_rotation().yaw if starts else 0.0
                xf = unreal.Transform(unreal.Vector(loc.x, loc.y, loc.z + opts.get("SEG_Z", 120.0)),
                                      unreal.Rotator(roll=0.0, pitch=opts.get("SEG_PITCH", -8.0), yaw=yaw + opts.get("SEG_YAW", 0.0)),
                                      unreal.Vector(1, 1, 1))
                w, h, f = opts.get("SEG_W", 640), opts.get("SEG_H", 480), opts.get("SEG_F", 380.0)
                intr = unreal.CameraIntrinsics()
                for k, v in (("image_width", w), ("image_height", h), ("focal_length_x", f), ("focal_length_y", f),
                             ("principal_point_x", w / 2.0), ("principal_point_y", h / 2.0)):
                    intr.set_editor_property(k, v)
                sub = capture_subsystem(gw)
                if sub is None:
                    log("no CameraCaptureSubsystem in the PIE world")
                    les.editor_request_end_play()
                    finish()
                    return
                sub.set_output_directory(out)
                sub.set_capture_rate(opts.get("SEG_EVERY", 20))
                sub.set_capture_channels(True, bool(opts.get("SEG_DEPTH", True)), False)
                if opts.get("SEG_PNG", False):
                    sub.set_color_format(unreal.RammsCaptureColorFormat.SEPARATE_PNG_AND_EXR)
                sub.set_capture_segmentation(True)
                cam = sub.spawn_camera("SegCam", xf, intr, True)
                sub.set_serialization_enabled(True)
                sub.start_capture()
                st.update(sub=sub, phase="run", until=now + opts.get("SEG_SECONDS", 8.0), cam=cam.get_owner(), origin=xf.translation,
                          ahead=unreal.MathLibrary.get_forward_vector(xf.rotation.rotator()), g0=unreal.GameplayStatics.get_time_seconds(gw))
                log("capturing %d camera(s) to %s" % (sub.get_registered_camera_count(), out))
                return
            if st["phase"] == "run":
                speed = opts.get("SEG_SPEED", 0.0)
                if speed and gw is not None:
                    # Game time, not wall time, so the path is the same however fast the editor runs.
                    t = unreal.GameplayStatics.get_time_seconds(gw) - st["g0"]
                    st["cam"].set_actor_location(st["origin"] + st["ahead"] * (speed * t), False, False)
                if now < st["until"]:
                    return
                stats = st["sub"].get_statistics()
                log("frames=%d" % stats.total_frames_captured)
                st["sub"].stop_capture()
                st.pop("sub")
                st.pop("cam", None)
                st.update(phase="flush", until=now + 3.0)  # let the last readbacks and writes land
                return
            if st["phase"] == "flush" and now >= st["until"]:
                les.editor_request_end_play()
                log("done")
                finish()
        except Exception:
            import traceback
            log("ERROR " + traceback.format_exc())
            try:
                les.editor_request_end_play()
            finally:
                finish()

    st["handle"] = unreal.register_slate_post_tick_callback(tick)


_segmentation_capture(_SEG_OPTS)
del _segmentation_capture, _SEG_OPTS
