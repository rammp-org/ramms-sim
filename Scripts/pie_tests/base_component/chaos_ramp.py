"""Stop on a ramp: the Chaos chair drives up a Map_RampTest lane, the stick is let go on
the slope, and the chair must stay where it stopped rather than roll back down.

unreal._ramms_ramp_op:
  'go A' / 'go B'  teleport the chair to the lane's approach (A: 1:12, B: 1:8), drive up at
                   drive.forward = SPEED through the control surface and release it once the
                   chair is STOP_FRACTION of the way up; the rest runs on the game clock: SETTLE
                   seconds to come to rest, then HOLD seconds watched for creep.
  'go Ad' / 'go Bd'  the same downhill: from the lane's landing, facing down the ramp, let go
                   once the chair is STOP_FRACTION of the way down.
  'check A' / ...  assert it reached the slope, stopped there and did not roll back more than
                   MAX_ROLLBACK_CM over the hold (nor creep on uphill).
Also importable (start(world, pawn, lane)) for the validation video recorder.
"""
import math
import sys
import unreal

sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)

# Map_RampTest (make_ramp_map.py): both lanes rise along +X from x = 0.
LANES = {"A": {"label": "1:12", "y": 0.0, "rise": 30.0, "run": 360.0},
         "B": {"label": "1:8", "y": 400.0, "rise": 40.0, "run": 320.0}}
SPEED = 0.5
STOP_FRACTION = 0.5      # release with the chair's origin this far up the ramp's run
APPROACH_X = -250.0
LANDING_X = 150.0        # downhill runs start this far onto the landing
SETTLE = 2.0             # s after letting go before the hold is measured
HOLD = 6.0               # s watched for creep
DRIVE_TIMEOUT = 15.0     # s to reach the release point
MAX_ROLLBACK_CM = 2.0
MAX_SETTLE_BACK_CM = 5.0  # back down the slope from the furthest point reached after letting go


def _gt(w):
    return unreal.GameplayStatics.get_time_seconds(w)


def start(w, p, lane, on_done=None):
    """Teleport to the lane's approach and drive it; the result lands in
    unreal._ramms_ramp_result[lane] when the hold is over."""
    down = lane.endswith("d")
    L = LANES[lane[0]]
    cs = cs_common.surface_of(p)
    dd = p.get_component_by_class(unreal.RammsDifferentialDriveController)
    cs_common.quiet_local_input(p)
    cs_common.release(cs, "drive.forward", "drive.turn")
    # The chair's resting height on the flat: read while it is still on the
    # approach (as spawned), kept for the runs that start elsewhere.
    here = p.get_actor_location()
    if here.x < -100.0:
        unreal._ramms_ramp_z_flat = here.z
    zf = getattr(unreal, "_ramms_ramp_z_flat", here.z)
    if down:   # on the landing, facing down the ramp (-X)
        p.teleport_robot(unreal.Transform(unreal.Vector(L["run"] + LANDING_X, L["y"], zf + L["rise"] + 2.0), unreal.Rotator(roll=0.0, pitch=0.0, yaw=180.0)), True)
        stop_x = (1.0 - STOP_FRACTION) * L["run"]
    else:
        p.teleport_robot(unreal.Transform(unreal.Vector(APPROACH_X, L["y"], zf + 2.0), unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0)), True)
        stop_x = STOP_FRACTION * L["run"]
    sgn = -1.0 if down else 1.0     # +1: the drive direction is +X
    S = {"phase": "wait", "t0": _gt(w), "h": None, "samples": []}
    if not hasattr(unreal, "_ramms_ramp_result"):
        unreal._ramms_ramp_result = {}
    unreal._ramms_ramp_result[lane] = None

    def finish(result):
        unreal._ramms_ramp_result[lane] = result
        unreal.unregister_slate_post_tick_callback(S["h"])
        unreal.log("[ramp] %s %s done: %s" % (lane, L["label"], result))
        if on_done:
            on_done(result)

    def tick(dt):
        try:
            gw = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
            if not gw:
                return finish({"ok": False, "why": "PIE ended"})
            t = _gt(gw) - S["t0"]
            loc = p.get_actor_location()
            if S["phase"] == "wait":            # let the teleport settle
                if t >= 1.0:
                    cs_common.set_control(cs, "drive.forward", SPEED)
                    S["phase"] = "drive"; S["t_drive"] = t
            elif S["phase"] == "drive":
                if sgn * (loc.x - stop_x) >= 0.0:
                    cs_common.release(cs, "drive.forward")
                    S["phase"] = "settle"; S["t_stop"] = t; S["x_stop"] = loc.x; S["peak"] = sgn * loc.x
                elif t - S["t_drive"] > DRIVE_TIMEOUT:
                    cs_common.release(cs, "drive.forward")
                    return finish({"ok": False, "why": "never reached x=%.0f (at %.1f)" % (stop_x, loc.x)})
            elif S["phase"] == "settle":
                S["peak"] = max(S["peak"], sgn * loc.x)
                if t - S["t_stop"] >= SETTLE:
                    S["phase"] = "hold"; S["x0"] = loc.x; S["z0"] = loc.z; S["t0h"] = t
                    S["brake0"] = dd.is_parking_brake_engaged() if dd else None
            elif S["phase"] == "hold":
                S["samples"].append(loc.x)
                if t - S["t0h"] >= HOLD:
                    xs = S["samples"]
                    back = S["x0"] - min(xs)          # furthest it went down the slope (-X)
                    fwd = max(xs) - S["x0"]           # furthest it went up (+X)
                    finish({"ok": True, "down": down, "x_stop": round(S["x_stop"], 1), "coast_cm": round(sgn * (S["x0"] - S["x_stop"]), 2),
                            "x_hold": round(S["x0"], 1), "settle_back_cm": round(S["peak"] - sgn * S["x0"], 2) if not down else round(max(0.0, S["x0"] - min([S["x0"]] + xs)), 2), "rollback_cm": round(back, 2), "creep_up_cm": round(fwd, 2),
                            "end_drift_cm": round(xs[-1] - S["x0"], 2), "height_cm": round(S["z0"] - zf, 1),
                            "on_slope": 0.0 < S["x0"] < L["run"],
                            "brake": [S["brake0"], dd.is_parking_brake_engaged() if dd else None]})
        except Exception as exc:  # noqa: BLE001
            finish({"ok": False, "why": str(exc)})

    S["h"] = unreal.register_slate_post_tick_callback(tick)
    unreal.log("[ramp] %s %s %s: drive.forward=%.1f, let go at x=%.0f" % (lane, L["label"], "down" if down else "up", SPEED, stop_x))


def check(lane):
    L = LANES[lane[0]]
    r = getattr(unreal, "_ramms_ramp_result", {}).get(lane)
    if r is None:
        raise RuntimeError("[ramp] %s: no result yet (still running?)" % lane)
    if not r.get("ok"):
        raise RuntimeError("[ramp] %s: %s" % (lane, r.get("why")))
    unreal.log("[ramp] %s %s %s: let go at x=%.1f, came to rest %.2f cm on at x=%.1f (%.1f cm up, %.2f cm back from its furthest); over %.0f s moved %.2f cm down, %.2f cm up; parking brake %s"
               % (lane, L["label"], "down" if r["down"] else "up", r["x_stop"], r["coast_cm"], r["x_hold"], r["height_cm"], r["settle_back_cm"], HOLD, r["rollback_cm"], r["creep_up_cm"], r["brake"]))
    if not r["on_slope"]:
        raise RuntimeError("[ramp] %s: came to rest off the slope (x=%.1f)" % (lane, r["x_hold"]))
    if not r["down"] and r["settle_back_cm"] > MAX_SETTLE_BACK_CM:
        raise RuntimeError("[ramp] %s: rolled %.2f cm back down after letting go before it held (max %.1f)" % (lane, r["settle_back_cm"], MAX_SETTLE_BACK_CM))
    if r["rollback_cm"] > MAX_ROLLBACK_CM or r["creep_up_cm"] > MAX_ROLLBACK_CM:
        raise RuntimeError("[ramp] %s: moved %.2f cm back / %.2f cm up while stopped (max %.1f)" % (lane, r["rollback_cm"], r["creep_up_cm"], MAX_ROLLBACK_CM))


# Run as an op script: take the op first, so a failed check never leaves it
# behind to fire again on a later import.
_op = getattr(unreal, "_ramms_ramp_op", "")
unreal._ramms_ramp_op = ""
if _op:
    _verb, _lane = _op.split()
    if _verb == "go":
        _w, _p = cs_common.find_chaos_pawn()
        start(_w, _p, _lane)
    elif _verb == "check":
        check(_lane)
