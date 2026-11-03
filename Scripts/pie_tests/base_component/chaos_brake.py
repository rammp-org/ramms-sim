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
chair's own.
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
    peak_decel, j = 0.0, i0
    for k in range(i0, len(t)):
        while t[k] - t[j] > DECEL_WINDOW:
            j += 1
        if k > j and t[k] > t[j]:
            peak_decel = max(peak_decel, (abs(v[j]) - abs(v[k])) / (t[k] - t[j]))
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
            "brake_at_end": s["rows"][-1][4], "i_release": i0}


def run(cases=None, out=None, decel=None, on_done=None):
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    cases = (cases or getattr(unreal, "_ramms_brake_cases", "") or "flat100 flat50 down50").split()
    out = out or getattr(unreal, "_ramms_brake_out", "") or os.path.join(unreal.Paths.project_saved_dir(), "RammsTests", "brake.json")
    if ues.get_game_world() is None and unreal.EditorLevelLibrary.get_editor_world().get_path_name() != MAP + "." + MAP.rsplit("/", 1)[1]:
        les.load_level(MAP)
    decel = decel if decel is not None else getattr(unreal, "_ramms_brake_decel", None)
    x_min, x_max, _ = _floor_x_range()
    S = {"i": 0, "phase": "pie", "h": None, "results": [], "t_wall": 0.0}

    def finish():
        unreal.unregister_slate_post_tick_callback(S["h"])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump({"config": S.get("config"), "results": S["results"], "series": S.get("series", {})}, open(out, "w"), indent=1)
        for r in S["results"]:
            unreal.log("[brake] %s" % json.dumps(r))
        les.editor_request_end_play()
        if on_done:
            on_done(S["results"])

    def begin_case(w, p):
        name = cases[S["i"]]
        kind, speed = CASES[name]
        cs = cs_common.surface_of(p)
        cs_common.quiet_local_input(p)
        cs_common.release(cs, "drive.forward", "drive.turn")
        z = S["z_rest"]
        if kind == "flat":
            start = unreal.Vector(x_min + 200.0, FLAT_Y, z + 2.0)
            p.teleport_robot(unreal.Transform(start, unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0)), True)
            S["release_at"] = (start.x + DRIVE_CM, 1.0)
        else:   # from lane B's landing, facing down the ramp, let go halfway down
            p.teleport_robot(unreal.Transform(unreal.Vector(LANE_B["run"] + 150.0, LANE_B["y"], z + LANE_B["rise"] + 2.0),
                                              unreal.Rotator(roll=0.0, pitch=0.0, yaw=180.0)), True)
            S["release_at"] = (0.5 * LANE_B["run"], -1.0)
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
                S["w"], S["p"] = cs_common.find_chaos_pawn()
                S["dd"] = dd = S["p"].get_component_by_class(unreal.RammsDifferentialDriveController)
                if decel is not None:
                    dd.set_editor_property("brake_deceleration", float(decel))
                S["config"] = {k: (round(float(dd.get_editor_property(k)), 3) if dd and _has(dd, k) else None)
                               for k in ("brake_deceleration", "brake_ramp_in_seconds", "brake_torque", "parking_brake_speed", "wheel_radius")}
                S["config"]["control_mode"] = str(dd.get_editor_property("control_mode")) if dd else None
                S["z_rest"] = S["p"].get_actor_location().z
                begin_case(w, S["p"])
                return
            if w is None:
                S["results"].append({"case": S.get("name"), "error": "PIE ended"})
                return finish()
            p, t = S["p"], _gt(w) - S["t0"]
            loc, rot = p.get_actor_location(), p.get_actor_rotation()
            fwd = p.get_actor_forward_vector()
            fwd_h = unreal.Vector(fwd.x, fwd.y, 0.0)
            n = math.hypot(fwd_h.x, fwd_h.y) or 1.0
            vel = p.get_velocity()
            v = (vel.x * fwd_h.x + vel.y * fwd_h.y) / n
            if S["phase"] == "settle":
                if t >= SETTLE:
                    cs_common.set_control(S["cs"], "drive.forward", S["speed"])
                    S["phase"] = "drive"; S["t_drive"] = t
                return
            dd = S["dd"]
            w_rate = 0.5 * (dd.get_left_wheel_state().get_editor_property("angular_velocity") + dd.get_right_wheel_state().get_editor_property("angular_velocity")) if dd else 0.0
            S["rows"].append((t, v, rot.pitch, loc.z, bool(dd.is_parking_brake_engaged()) if dd else None, w_rate))
            if S["phase"] == "drive":
                x_rel, sgn = S["release_at"]
                if sgn * (loc.x - x_rel) >= 0.0:
                    cs_common.release(S["cs"], "drive.forward")
                    S["i_release"] = len(S["rows"]) - 1; S["t_rel"] = t; S["phase"] = "watch"
                elif t - S["t_drive"] > 20.0:
                    raise RuntimeError("%s: never reached x=%.0f (at %.0f)" % (S["name"], x_rel, loc.x))
            elif S["phase"] == "watch" and t - S["t_rel"] >= WATCH:
                r = summarise(S["name"], S["kind"], S["speed"], S)
                S["results"].append(r)
                S.setdefault("series", {})[S["name"]] = [[round(x, 4) for x in row[:4]] + [row[4], round(row[5], 3)] for row in S["rows"]]
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
