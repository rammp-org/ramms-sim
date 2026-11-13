"""Stopping from speed: how hard the Chaos chair brakes when its stick is let go.

Runs on Map_RampTest (make_ramp_map.py) and starts PIE itself. For each case the chair
is teleported, driven at drive.forward = speed through its control surface until it
has run DRIVE_CM, let go, and watched for WATCH s. Logged per editor tick: its
speed along its heading, chassis pitch and height, and the parking brakes' state.
Reported per case: the speed it was let go at, the peak deceleration (over a
DECEL_WINDOW s window), the time and distance to rest, and how far the chassis
pitched nose-down and how high it rose (a tip onto the front casters shows as both).

  python Scripts/editor_remote_exec.py --file Scripts/pie_tests/base_component/chaos_brake.py

unreal._ramms_brake_cases may name the cases ("flat100 flat50 down50", the
default); unreal._ramms_brake_out the JSON written (Saved/RammsTests/brake.json);
unreal._ramms_brake_decel a BrakeDeceleration (cm/s^2) to run them with instead of the
chair's own (0: the brakes stop the wheels as hard as BrakeTorque can, as before the ramp);
unreal._ramms_brake_front_caster the angle (deg) the front casters are raised to and held at
through the cases (FRONT_CASTER_DEG, -30, unless set; None leaves them where the chair has
them). Left down, as the chair spawns, they leave it little room to pitch forward when it stops,
and a hard stop looks gentler than it is;
unreal._ramms_brake_frames a folder to record each case into, from the side, as PNG frames
(<folder>/<case>/f_0000.png ..., FRAME_FPS of game time; the frame it was let go at is in the
JSON). The game is paused for each frame's capture and export, so recording does not change what
the chair does: the drive's brakes act once a game tick, and a slowed or hitching game would
tick them at another rate.
"""
import json
import math
import os
import sys

import unreal

sys.path.insert(0, os.path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)

MAP = "/Game/Maps/Map_RampTest"
# Map_RampTest: lane B (1:8, 40 cm rise over 320 cm) rises along +X at y = 400 from x = 0.
LANE_B = {"y": 400.0, "rise": 40.0, "run": 320.0}
FLAT_Y = -400.0          # clear of both ramps
DRIVE_CM = 400.0         # run before letting go on the flat (reaches the commanded speed)
WATCH = 4.0              # s watched after letting go
SETTLE = 1.5             # s after a teleport before driving
DECEL_WINDOW = 0.1       # s over which deceleration is measured
REST_CMS = 1.0           # at rest below this speed
CASES = {"flat100": ("flat", 1.0), "flat50": ("flat", 0.5), "down50": ("down", 0.5)}
FRAME_FPS = 30.0
FRAME_RES = (1280, 720)
FRAME_FOV = 55.0
FRAME_EXPOSURE_BIAS = 1.0
CAM_SIDE = 360.0         # cm to the side of the lane the camera stands (+Y)
CAM_UP = 30.0            # cm above what it looks at
CAM_LOOK_UP = 75.0       # what it looks at: this far above the chair's origin (the seated operator's chest)


def _gt(w):
    return unreal.GameplayStatics.get_time_seconds(w)


def _has(obj, prop):
    try:
        obj.get_editor_property(prop)
        return True
    except Exception:  # noqa: BLE001 -- a property this build does not have
        return False


def _floor_x_range():
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in eas.get_all_level_actors():
        if a.get_actor_label() == "Floor":
            o, e = a.get_actor_bounds(False, False)
            return o.x - e.x, o.x + e.x, o.z + e.z
    return -1000.0, 1000.0, 0.0


def _speed_at(t, v, at):
    """The speed at time `at`, interpolated between the samples either side of it: every window is
    a whole DECEL_WINDOW long, however the editor's ticks fall."""
    k = next((i for i in range(1, len(t)) if t[i] >= at), len(t) - 1)
    if t[k] <= t[k - 1]:
        return v[k]
    f = min(1.0, max(0.0, (at - t[k - 1]) / (t[k] - t[k - 1])))
    return v[k - 1] + f * (v[k] - v[k - 1])


def summarise(name, kind, speed, s):
    t = [r[0] for r in s["rows"]]
    v = [r[1] for r in s["rows"]]
    pitch = [r[2] for r in s["rows"]]
    z = [r[3] for r in s["rows"]]
    i0 = s["i_release"]
    v0 = v[i0]
    # reference attitude: the last 0.3 s before letting go
    pre = [k for k in range(i0) if t[i0] - t[k] <= 0.3] or [i0]
    p_ref = sum(pitch[k] for k in pre) / len(pre)
    z_ref = sum(z[k] for k in pre) / len(pre)
    peak_decel = 0.0
    for k in range(i0, len(t)):
        if t[k] - t[i0] >= DECEL_WINDOW:
            peak_decel = max(peak_decel, (abs(_speed_at(t, v, t[k] - DECEL_WINDOW)) - abs(v[k])) / DECEL_WINDOW)
    rest = next((k for k in range(i0, len(t)) if abs(v[k]) < REST_CMS), None)
    sgn = 1.0 if v0 >= 0 else -1.0
    dist = sum(0.5 * (v[k] + v[k - 1]) * (t[k] - t[k - 1]) for k in range(i0 + 1, (rest or len(t) - 1) + 1)) * sgn
    dips = [pitch[k] - p_ref for k in range(i0, len(t))]   # rotator pitch: nose-down is negative either way
    return {"case": name, "speed_cmd": speed, "v_release_cms": round(v0, 1),
            "peak_decel_cms2": round(peak_decel, 1), "peak_decel_g": round(peak_decel / 981.0, 3),
            "t_to_rest_s": round(t[rest] - t[i0], 3) if rest is not None else None,
            "stop_cm": round(dist, 1),
            "pitch_min_deg": round(min(dips), 2), "pitch_max_deg": round(max(dips), 2),
            "rise_cm": round(max(z[k] for k in range(i0, len(t))) - z_ref, 2),
            "brake_at_end": s["rows"][-1][4], "i_release": i0,
            "tick_hz": round((len(t) - 1) / (t[-1] - t[0]), 1) if len(t) > 1 and t[-1] > t[0] else None}


def _set_prop(dd, name, value):
    """A float property of the chair's controller (its C++ name), without an edit notification:
    one reruns the pawn's construction script mid-PIE, which drops its seated operator and
    replaces the controller. Through Python where its wrapper knows the property, else the
    engine's `set` command (every RammsDifferentialDriveController)."""
    snake = "".join("_" + c.lower() if c.isupper() else c for c in name).lstrip("_")
    for prop in (snake, name):
        try:
            dd.set_editor_property(prop, float(value), unreal.PropertyAccessChangeNotifyMode.NEVER)
            return "property"
        except Exception:  # noqa: BLE001 -- a wrapper generated before the property existed
            pass
    unreal.SystemLibrary.execute_console_command(dd, "set RammsDifferentialDriveController %s %g" % (name, float(value)))
    return "console set"


def _set_decel(dd, value):
    return _set_prop(dd, "BrakeDeceleration", value)


CAM_TAG = "ramms_brake_cam"
FRONT_CASTER = "lift.front_caster_swing_arm"
FRONT_CASTER_DEG = -30.0
CASTER_TOLERANCE = 2.0   # deg: how near the commanded angle the casters must be before a case drives
CASTER_TIMEOUT = 8.0     # s to wait for them


def _place_capture():
    """A SceneCapture2D in the editor's level for PIE to copy (Python cannot spawn into the PIE
    world). run() takes it out again once PIE has ended and reloads the level, unsaved."""
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    sc = eas.spawn_actor_from_class(unreal.SceneCapture2D, unreal.Vector(0, 0, 300), unreal.Rotator())
    sc.set_editor_property("tags", [unreal.Name(CAM_TAG)])
    sc.capture_component2d.set_editor_property("capture_every_frame", False)
    return sc


def _setup_capture(w):
    sc = [a for a in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.SceneCapture2D) if unreal.Name(CAM_TAG) in a.tags][0]
    rt = unreal.RenderingLibrary.create_render_target2d(w, FRAME_RES[0], FRAME_RES[1], unreal.TextureRenderTargetFormat.RTF_RGBA8,
                                                        unreal.LinearColor(0, 0, 0, 1), False)
    cap = sc.capture_component2d
    cap.set_editor_property("texture_target", rt)
    cap.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
    cap.set_editor_property("capture_every_frame", False)
    cap.set_editor_property("always_persist_rendering_state", True)
    cap.set_editor_property("fov_angle", FRAME_FOV)
    pp = cap.get_editor_property("post_process_settings")
    pp.set_editor_property("override_auto_exposure_bias", True)
    pp.set_editor_property("auto_exposure_bias", FRAME_EXPOSURE_BIAS)   # the chair's side to the camera is in its own shade
    cap.set_editor_property("post_process_settings", pp)
    return sc, rt


def run(cases=None, out=None, decel=None, frames=None, fps=FRAME_FPS, max_fps=None, props=None, front_caster=FRONT_CASTER_DEG, on_done=None):
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    cases = (cases or getattr(unreal, "_ramms_brake_cases", "") or "flat100 flat50 down50").split()
    # A bare file name goes in Saved/RammsTests; a path with a folder in it is taken as given.
    tests_dir = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "RammsTests")

    def resolve(path):
        return os.path.abspath(path) if os.path.dirname(path) else os.path.join(tests_dir, path)

    out = resolve(out or getattr(unreal, "_ramms_brake_out", "") or "brake.json")
    map_name = MAP.rsplit("/", 1)[1]
    pie = ues.get_game_world()
    if pie is not None and unreal.GameplayStatics.get_current_level_name(pie) != map_name:
        # The cases' coordinates are Map_RampTest's: on another map the downhill case would
        # drop the chair onto whatever is there and report an ordinary-looking stop.
        raise RuntimeError("[brake] PIE is running %s, not %s: end it first" % (unreal.GameplayStatics.get_current_level_name(pie), map_name))
    if pie is None and unreal.EditorLevelLibrary.get_editor_world().get_path_name() != MAP + "." + map_name:
        les.load_level(MAP)
    decel = decel if decel is not None else getattr(unreal, "_ramms_brake_decel", None)
    frames = frames or getattr(unreal, "_ramms_brake_frames", "") or None
    front_caster = getattr(unreal, "_ramms_brake_front_caster", front_caster)
    if frames:
        frames = resolve(frames)
    x_min, x_max, _ = _floor_x_range()
    S = {"i": 0, "phase": "pie", "h": None, "results": [], "t_wall": 0.0}
    if frames:
        if pie is not None:
            # The capture is placed in the editor's level for PIE to copy; a session already
            # running has none.
            raise RuntimeError("[brake] recording needs PIE started by run(): end the running session first")
        S["editor_cam"] = _place_capture()

    def after_pie(_dt):
        # Once PIE has ended (so on_done may start another run): the editor's level as it was
        # (a capture placed for frames out, the level reloaded rather than left dirty), then on_done.
        if ues.get_game_world() is not None:
            return
        unreal.unregister_slate_post_tick_callback(S["h_after"])
        if S.get("editor_cam"):
            unreal.get_editor_subsystem(unreal.EditorActorSubsystem).destroy_actor(S["editor_cam"])
            les.load_level(MAP)
        if on_done:
            on_done(S["results"])

    def finish():
        unreal.unregister_slate_post_tick_callback(S["h"])
        os.makedirs(os.path.dirname(out), exist_ok=True)   # absolute (resolve): always has a folder
        json.dump({"config": S.get("config"), "results": S["results"], "series": S.get("series", {})}, open(out, "w"), indent=1)
        for r in S["results"]:
            unreal.log("[brake] %s" % json.dumps(r))
        if max_fps:
            unreal.SystemLibrary.execute_console_command(None, "t.MaxFPS 0")
        les.editor_request_end_play()
        S["h_after"] = unreal.register_slate_post_tick_callback(after_pie)

    def begin_case(w, p):
        name = cases[S["i"]]
        S["w"], p = cs_common.find_chaos_pawn()
        S["p"], S["dd"] = p, p.get_component_by_class(unreal.RammsDifferentialDriveController)
        kind, speed = CASES[name]
        cs = cs_common.surface_of(p)
        cs_common.quiet_local_input(p)
        cs_common.release(cs, "drive.forward", "drive.turn")
        z = S["z_rest"]
        if kind == "flat":
            start = unreal.Vector(x_min + 200.0, FLAT_Y, z + 2.0)
            p.teleport_robot(unreal.Transform(start, unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0)), True)
            S["release_at"] = (start.x + DRIVE_CM, 1.0)
            # from the lit side, between where it is let go and where it stops at 150 cm/s^2
            look = unreal.Vector(start.x + DRIVE_CM + 75.0, FLAT_Y, z + CAM_LOOK_UP)
            cam = unreal.Vector(look.x, FLAT_Y + CAM_SIDE, look.z + CAM_UP)
        else:   # from lane B's landing, facing down the ramp, let go halfway down
            p.teleport_robot(unreal.Transform(unreal.Vector(LANE_B["run"] + 150.0, LANE_B["y"], z + LANE_B["rise"] + 2.0),
                                              unreal.Rotator(roll=0.0, pitch=0.0, yaw=180.0)), True)
            S["release_at"] = (0.5 * LANE_B["run"], -1.0)
            look = unreal.Vector(0.31 * LANE_B["run"], LANE_B["y"], z + 0.3 * LANE_B["rise"] + CAM_LOOK_UP)
            cam = unreal.Vector(look.x, LANE_B["y"] + CAM_SIDE, look.z + CAM_UP)
        if S.get("sc"):
            S["sc"].set_actor_location_and_rotation(cam, unreal.MathLibrary.find_look_at_rotation(cam, look), False, False)
            # A case run more than once records each take into its own folder (<case>_<index>).
            S["fdir"] = os.path.join(frames, name if cases.count(name) == 1 else "%s_%d" % (name, S["i"]))
            os.makedirs(S["fdir"], exist_ok=True)
            for f in os.listdir(S["fdir"]):
                if f.startswith("f_"):
                    os.remove(os.path.join(S["fdir"], f))
            S.update(frame=0, next_frame=None, release_frame=None)
        S.update({"name": name, "kind": kind, "speed": speed, "cs": cs, "phase": "settle", "t0": _gt(w), "rows": [], "i_release": None})

    def tick(dt):
        try:
            w = ues.get_game_world()
            if S["phase"] == "pie":
                if w is None:
                    if S["t_wall"] == 0.0:
                        les.editor_request_begin_play()
                    S["t_wall"] += dt
                    if S["t_wall"] > 60.0:
                        raise RuntimeError("PIE did not start")
                    return
                if _gt(w) < 3.0:      # the chair is put down as it spawns
                    return
                if unreal.GameplayStatics.get_current_level_name(w) != map_name:
                    raise RuntimeError("PIE started on %s, not %s" % (unreal.GameplayStatics.get_current_level_name(w), map_name))
                S["w"], S["p"] = cs_common.find_chaos_pawn()
                S["dd"] = dd = S["p"].get_component_by_class(unreal.RammsDifferentialDriveController)
                how = _set_decel(dd, decel) if decel is not None else None
                for k, val in (props or {}).items():   # other controller settings, by C++ name
                    _set_prop(dd, k, val)
                if max_fps:
                    unreal.SystemLibrary.execute_console_command(w, "t.MaxFPS %d" % int(max_fps))
                S["config"] = {k: (round(float(dd.get_editor_property(k)), 3) if dd and _has(dd, k) else None)
                               for k in ("brake_deceleration", "brake_ramp_in_seconds", "brake_torque", "parking_brake_speed", "wheel_radius")}
                S["config"]["control_mode"] = str(dd.get_editor_property("control_mode")) if dd else None
                if decel is not None:
                    S["config"].update(brake_deceleration_set=float(decel), set_by=how)
                if props:
                    S["config"]["props_set"] = dict(props)
                if front_caster is not None:
                    # Held by the Script source through every case: releasing the drive axes
                    # between cases leaves it alone.
                    cs_common.set_control(cs_common.surface_of(S["p"]), FRONT_CASTER, float(front_caster))
                    S["config"]["front_caster_cmd"] = float(front_caster)
                if frames:
                    S["sc"], S["rt"] = _setup_capture(w)
                S["z_rest"] = S["p"].get_actor_location().z
                begin_case(w, S["p"])
                return
            if w is None:
                S["results"].append({"case": S.get("name"), "error": "PIE ended"})
                return finish()
            if S.get("paused"):
                # Paused over the last frame's export (the hitch went by without game time): go on.
                unreal.GameplayStatics.set_game_paused(w, False)
                S["paused"] = False
                return
            p, t = S["p"], _gt(w) - S["t0"]
            loc, rot = p.get_actor_location(), p.get_actor_rotation()
            fwd = p.get_actor_forward_vector()
            fwd_h = unreal.Vector(fwd.x, fwd.y, 0.0)
            n = math.hypot(fwd_h.x, fwd_h.y) or 1.0
            vel = p.get_velocity()
            v = (vel.x * fwd_h.x + vel.y * fwd_h.y) / n
            if S["phase"] == "settle":
                caster = S["cs"].get_control_value(FRONT_CASTER) if front_caster is not None else None
                caster_ready = front_caster is None or abs(caster - float(front_caster)) <= CASTER_TOLERANCE
                if t >= SETTLE and not caster_ready and t >= SETTLE + CASTER_TIMEOUT:
                    raise RuntimeError("%s: the front casters reached %.1f deg, not %.1f" % (S["name"], caster, float(front_caster)))
                if t >= SETTLE and caster_ready:
                    cs_common.set_control(S["cs"], "drive.forward", S["speed"])
                    S["phase"] = "drive"; S["t_drive"] = t
                return
            dd = S["dd"]
            w_rate = 0.5 * (dd.get_left_wheel_state().get_editor_property("angular_velocity") + dd.get_right_wheel_state().get_editor_property("angular_velocity")) if dd else 0.0
            S["rows"].append((t, v, rot.pitch, loc.z, bool(dd.is_parking_brake_engaged()) if dd else None, w_rate))
            S["captured"] = False
            if S.get("sc"):
                if S["next_frame"] is None:
                    S["next_frame"] = t
                if t >= S["next_frame"]:
                    unreal.GameplayStatics.set_game_paused(w, True)
                    S["paused"] = True
                    S["sc"].capture_component2d.capture_scene()
                    unreal.RenderingLibrary.export_render_target(w, S["rt"], S["fdir"], "f_%04d" % S["frame"])
                    S["frame"] += 1
                    S["next_frame"] += 1.0 / fps
                    S["captured"] = True
            if S["phase"] == "drive":
                x_rel, sgn = S["release_at"]
                if sgn * (loc.x - x_rel) >= 0.0:
                    cs_common.release(S["cs"], "drive.forward")
                    S["i_release"] = len(S["rows"]) - 1; S["t_rel"] = t; S["phase"] = "watch"
                    if front_caster is not None:
                        S["caster_at_release"] = S["cs"].get_control_value(FRONT_CASTER)
                    # The frame of this tick's pose: the one just captured, else the next.
                    if S.get("sc"):
                        S["release_frame"] = S["frame"] - 1 if S["captured"] else S["frame"]
                elif t - S["t_drive"] > 20.0:
                    raise RuntimeError("%s: never reached x=%.0f (at %.0f)" % (S["name"], x_rel, loc.x))
            elif S["phase"] == "watch" and t - S["t_rel"] >= WATCH:
                r = summarise(S["name"], S["kind"], S["speed"], S)
                if front_caster is not None:
                    r["front_caster_deg"] = round(S.get("caster_at_release", float("nan")), 1)
                if S.get("sc"):
                    r["frames"] = {"dir": S["fdir"], "count": S["frame"], "release_frame": S["release_frame"], "fps": fps}
                S["results"].append(r)
                S.setdefault("series", {})["%s#%d" % (S["name"], S["i"])] = [[round(x, 4) for x in row[:4]] + [row[4], round(row[5], 3)] for row in S["rows"]]
                unreal.log("[brake] %s" % json.dumps(r))
                S["i"] += 1
                if S["i"] >= len(cases):
                    return finish()
                begin_case(w, p)
        except Exception as exc:  # noqa: BLE001
            S["results"].append({"case": S.get("name"), "error": str(exc)})
            unreal.log_warning("[brake] %s" % exc)
            finish()

    S["h"] = unreal.register_slate_post_tick_callback(tick)
    unreal.log("[brake] cases %s -> %s" % (cases, out))


if __name__ == "__main__":
    run()
