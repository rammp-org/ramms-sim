"""One definition of a level-assist course run's figures, for every robot (`level.version`).

The question they answer: does the RIDER stay level -- or at the tilt they prefer -- on slopes, cross slopes and
combined ground, and what happens at each transition. Everything is taken from a run's trace (runner_op.py's
begin_course), against the course's own terrain (Scripts/level_maps/level_terrain.py). Only the standard library.

A trace's samples, one per editor frame (what measures.py's have, and):

    "level":  {"assist", "state", "tilt", "reach", "speed_scale", "status"} the robot's level.* controls (absent on a
              robot without them); state: STATES' index
    "pref":   [pitch, roll] the preference asked for (deg), whether or not the assist is on
    "stick":  [forward, turn] what the session held this frame
    "steer":  {"xt": cross-track cm (right of the path positive), "yaw_err": deg (clockwise of the path positive)}
    "mode":   the active drive mode's id
    "cmd":    {motor: [baseline, offset, joint]} per levelled motor
    "ground": {"n": {wheel: normal force N, None off the ground}, "others": N on anything else, "com": [x, y],
               "pts": {wheel: [x, y] where it bears}}

Attitudes are (pitch, roll) in degrees in the level assist's own convention: pitch nose up, roll with the right (+Y)
side up -- the sign of level.pref.roll. A trace's chassis and seat carry UE rotators (roll positive with the right
side DOWN): att() converts. The RIDER is the seat less its mount's offset from the chassis (the robot profile's
`rider_offset_deg`, else what the run's steady gate measured); a robot without a seat reads as its chassis.

Three attitudes are compared on every sample: the rider's and the chassis's own, the PREFERENCE (what the rider asked
to be held at; 0, 0 by default), and the GROUND's (the plane through the terrain under the standing wheels, at the
chassis's heading). The error against the preference is what the assist is to make zero; the difference from the
ground shows how much of the ground's attitude reached the rider.

    segment     a stretch of the path where every standing wheel is on one plane: mean and RMS of the error, and the
                RESIDUAL, its mean over the last STEADY_TAIL_S of the segment
    transition  each seam the wheels cross (from the first wheel reaching it) and each event (assist on or off, a
                preference change, a mode switch, a stop, a go): the peak error, the time outside OUTSIDE_DEG, the
                fastest tilt over RATE_WINDOW_S, and the time to settle within SETTLE_DEG for good
    pair        an assist-on run against the assist-off run of the same case: the rejection ratio (error RMS on over
                off), the speed kept, and what the standing gave up (margin, drive-wheel share)
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import course as course_mod  # noqa: E402
import measures  # noqa: E402

lt = course_mod.lt

LEVEL_VERSION = 1
STATES = ("Off", "Active", "Holding", "Releasing", "Yielded", "Suspended", "Faulted")
FAULTED = 6

STEADY_TAIL_S = 1.5  # a segment's residual: the mean error over this long at its end
OUTSIDE_DEG = 1.0
SETTLE_DEG = 0.5
RATE_WINDOW_S = 0.3
TRANSITION_HORIZON_S = 4.0  # a seam's window runs this long after the last wheel is past (or to the next one)
EVENT_HORIZON_S = 8.0
SEG_MARGIN_CM = 5.0  # a segment's figures leave this much out at each end
START_UP_S = 1.5  # after go, and after every "go": not yet at speed
STOPPED_CM_S = measures.STOPPED_CM_S
STOP_MIN_S = measures.STOP_MIN_S
FLOAT_N = 1.0  # a wheel bearing less than this is off the ground
REACH_AT = 0.02  # level.reach at or under this: at the end of the legs' reach
SETTLED_FOR_S = 1.0
QUIET_GRACE_S = 3.0  # standing: once the rider is settled the commands may still trim this long before they must be quiet
CMD_CHANGE = 1e-5
SLOPE_DEG = 3.0  # a segment at least this steep counts for the rejection ratio


def rnd(x, nd=3):
    if x is None or isinstance(x, bool):
        return x
    try:
        return round(float(x), nd) if math.isfinite(float(x)) else None
    except (TypeError, ValueError):
        return None


def att(pose):
    """(pitch, roll) (deg; roll with the right side up) of a UE rotator {"pitch", "roll"}: the elevation of the
    body's forward axis and of its right axis."""
    if not pose:
        return None
    p, r = pose.get("pitch", 0.0), pose.get("roll", 0.0)
    return (p, math.degrees(math.asin(max(-1.0, min(1.0, -math.sin(math.radians(r)) * math.cos(math.radians(p)))))))


def total(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def rms(xs):
    xs = [x for x in xs if x is not None]
    return math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def hull_margin(points, p):
    """How far inside the convex hull of `points` [(x, y), ...] the point p is (cm; negative: outside it, by its
    distance to the hull). With two points: minus its distance to their segment; with fewer: None."""
    pts = sorted(set((float(a[0]), float(a[1])) for a in points))
    if len(pts) < 2:
        return None

    def seg_dist(a, b):
        ab = (b[0] - a[0], b[1] - a[1])
        n2 = ab[0] ** 2 + ab[1] ** 2
        f = 0.0 if n2 == 0.0 else max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / n2))
        return math.hypot(p[0] - a[0] - f * ab[0], p[1] - a[1] - f * ab[1])

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for q in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return -seg_dist(pts[0], pts[-1])
    inside = True
    edge = float("inf")
    for a, b in zip(hull, hull[1:] + hull[:1]):
        if turn(a, b, p) < 0:
            inside = False
        edge = min(edge, seg_dist(a, b))
    return edge if inside else -edge


# --- the series -----------------------------------------------------------------------------------------------------

def support_wheels(trace, level_prof):
    """The indices of the wheels the robot stands on: the profile's `support_wheels` names, else every wheel."""
    wheels = (trace.get("cfg") or {}).get("wheels") or []
    names = (level_prof or {}).get("support_wheels")
    if names:
        idx = [k for k, w in enumerate(wheels) if w.get("name") in names]
        if idx:
            return idx
    return list(range(len(wheels)))


def rider_zero(trace, level_prof):
    off = (level_prof or {}).get("rider_offset_deg")
    if off is not None:
        return (float(off[0]), float(off[1]))
    z = (trace.get("gate") or {}).get("rider_zero")
    return (float(z[0]), float(z[1])) if z else (0.0, 0.0)


def footprint_of(trace, level_prof):
    """The standing wheels' places about the chassis reference point, [(ahead, right), ...] cm, from the first sample
    that has them all: what the course's ground profile is laid out for."""
    idx = support_wheels(trace, level_prof)
    for s in trace.get("samples") or []:
        hubs = s.get("wheels") or []
        if not all(k < len(hubs) and hubs[k] for k in idx):
            continue
        c = s["chassis"]
        cy, sy = math.cos(math.radians(c["yaw"])), math.sin(math.radians(c["yaw"]))
        out = []
        for k in idx:
            dx, dy = hubs[k][0] - c["xyz"][0], hubs[k][1] - c["xyz"][1]
            out.append((dx * cy + dy * sy, -dx * sy + dy * cy))
        return out
    return None


def series(trace, layout, level_prof=None):
    """A trace as rows, one per sample: t, d (cm along the path), xt, yaw_err, the chassis's (cp, cr), the rider's
    (rp, rr), the ground's (gp, gr) and the preference's (pp, pr) pitch and roll, the level controls (state, reach,
    scale, tilt, assist, status), the stick (fwd, turn), mode, the standing wheels' heights in the chassis's frame
    (legs), the drive wheels' share of the load (share), which wheels are off the ground (floats), the standing
    margin (margin), cmd."""
    level_prof = level_prof or {}
    plan = (trace.get("cfg") or {}).get("plan") or {}
    path = plan.get("path") or {"origin": [0.0, 0.0], "yaw": 0.0}
    wheels = (trace.get("cfg") or {}).get("wheels") or []
    idx = support_wheels(trace, level_prof)
    zero = rider_zero(trace, level_prof)
    drive = set(level_prof.get("drive_wheels") or [])
    rows, status = [], None
    for s in trace.get("samples") or []:
        c = s.get("chassis")
        if not c:
            continue
        cp, cr = att(c)
        seat = att(s.get("seat"))
        rp, rr = (seat[0] - zero[0], seat[1] - zero[1]) if seat else (cp, cr)
        d, xt, yaw_err = course_mod.path_coords(path["origin"], path["yaw"], c["xyz"][0], c["xyz"][1], c["yaw"])
        hubs = s.get("wheels") or []
        pts = [(hubs[k][0], hubs[k][1]) for k in idx if k < len(hubs) and hubs[k]]
        if len(pts) >= 3:
            gp, gr = layout.ground_attitude(pts, c["yaw"])
        else:
            gp, gr = layout.plane_attitude(c["xyz"][0], c["xyz"][1], c["yaw"])
        up = measures.rotation_axes(c["pitch"], c["yaw"], c["roll"])[2]
        legs = [sum((hubs[k][i] - c["xyz"][i]) * up[i] for i in range(3)) if k < len(hubs) and hubs[k] else None for k in idx]
        lv = s.get("level") or {}
        if lv.get("status") is not None:
            status = lv["status"]
        pref = s.get("pref") or [0.0, 0.0]
        stick = s.get("stick") or [0.0, 0.0]
        row = {"t": s["t"], "d": d, "xt": xt, "yaw_err": yaw_err, "cp": cp, "cr": cr, "rp": rp, "rr": rr, "gp": gp, "gr": gr,
               "pp": pref[0], "pr": pref[1], "has_level": bool(lv), "state": lv.get("state"), "reach": lv.get("reach"),
               "scale": lv.get("speed_scale"), "tilt": lv.get("tilt"), "assist": lv.get("assist"), "status": status,
               "fwd": stick[0], "turn": stick[1], "mode": s.get("mode"), "legs": legs, "cmd": s.get("cmd"),
               "x": c["xyz"][0], "y": c["xyz"][1], "share": None, "floats": None, "margin": None}
        g = s.get("ground")
        if g and g.get("n") is not None:
            n = g["n"]
            tot = sum(v for v in n.values() if v) + (g.get("others") or 0.0)
            if tot > 0.0 and drive:
                row["share"] = sum(n.get(w) or 0.0 for w in drive) / tot
            row["floats"] = {w: (v is None or v < FLOAT_N) for w, v in n.items()}
            if g.get("com") and g.get("pts"):
                bearing = [g["pts"][w] for w, v in n.items() if v and v >= FLOAT_N and g["pts"].get(w)]
                row["margin"] = hull_margin(bearing, g["com"]) if len(bearing) >= 2 else None
        row["re"] = total((rp, rr), (row["pp"], row["pr"]))  # the rider against the preference
        row["ce"] = total((cp, cr), (row["pp"], row["pr"]))
        rows.append(row)
    return rows


# --- helpers over rows ----------------------------------------------------------------------------------------------

def between(rows, t_a, t_b):
    return [r for r in rows if t_a - 1e-9 <= r["t"] <= t_b + 1e-9]


def time_at_d(rows, d, t_from=None):
    """When the robot is first `d` along the path (interpolated), at or after t_from; None when it never is."""
    prev = None
    for r in rows:
        if t_from is not None and r["t"] < t_from - 1e-9:
            prev = r
            continue
        if r["d"] >= d:
            if prev is None or prev["d"] >= d or r["d"] == prev["d"]:
                return r["t"]
            return prev["t"] + (d - prev["d"]) / (r["d"] - prev["d"]) * (r["t"] - prev["t"])
        prev = r
    return None


def rate_peak(rows, kp, kr, window=RATE_WINDOW_S):
    """The fastest turn of (pitch, roll) together over windows exactly `window` long (deg/s); None when the rows are
    shorter than a window."""
    return max((math.hypot(d[0], d[1]) / window for d, _ in measures.window_changes(rows, lambda r: [r[kp], r[kr]], window)),
               default=None)


def time_over(rows, key, level):
    """The time `key` spends over `level` (each frame counted by where it ends)."""
    return sum(b["t"] - a["t"] for a, b in zip(rows, rows[1:]) if b[key] is not None and b[key] > level)


def settle(rows, key, level, t_ref):
    """How long after t_ref `key` is last over `level` in the rows: 0 when it never is, None when it still is at their
    end (not settled inside them)."""
    if not rows:
        return None
    if rows[-1][key] > level:
        return None
    last = None
    for r in rows:
        if r[key] > level:
            last = r["t"]
    return 0.0 if last is None else max(0.0, last - t_ref)


def speeds(rows):
    """[(t, speed along the path cm/s)] over windows exactly RATE_WINDOW_S long (measures.window_changes)."""
    out = [(s["t"], d[0] / RATE_WINDOW_S) for d, s in measures.window_changes(rows, lambda r: [r["d"]], RATE_WINDOW_S)]
    out.sort(key=lambda x: x[0])
    return out


def moving_spans(trace, t_go, t_end):
    """The stretches the robot is meant to be at speed in: from START_UP_S after go to the end, less every commanded
    stop (from its "stop" to START_UP_S after its "go")."""
    spans, t0 = [], t_go + START_UP_S
    for e in trace.get("events") or []:
        if e.get("do") == "stop" and e.get("t") is not None and e["t"] > t_go:
            if e["t"] > t0:
                spans.append((t0, e["t"]))
            t0 = None
        elif e.get("do") == "go" and t0 is None and e.get("t") is not None:
            t0 = e["t"] + START_UP_S
    if t0 is not None and t_end > t0:
        spans.append((t0, t_end))
    return spans


def in_spans(t, spans):
    return any(a - 1e-9 <= t <= b + 1e-9 for a, b in spans)


def longest_true(rows, pred):
    """The longest unbroken time pred(row) holds, and its total."""
    best = tot = 0.0
    run = None
    for a, b in zip(rows, rows[1:]):
        if pred(b):
            tot += b["t"] - a["t"]
            run = a["t"] if run is None else run
            best = max(best, b["t"] - run)
        else:
            run = None
    return best, tot


# --- the figures ----------------------------------------------------------------------------------------------------

def window_figures(rows, t_ref, t_exit=None):
    """A transition's figures over its rows."""
    if len(rows) < 2:
        return None
    out = {"t0": rnd(rows[0]["t"]), "t1": rnd(rows[-1]["t"]), "window_s": rnd(rows[-1]["t"] - rows[0]["t"]),
           "rider_peak_deg": rnd(max(r["re"] for r in rows)), "chassis_peak_deg": rnd(max(r["ce"] for r in rows)),
           "rider_pitch_peak_deg": rnd(max((r["rp"] - r["pp"] for r in rows), key=abs)),
           "rider_roll_peak_deg": rnd(max((r["rr"] - r["pr"] for r in rows), key=abs)),
           "rider_start_deg": rnd(rows[0]["re"]), "rider_end_deg": rnd(rows[-1]["re"]),
           "rider_outside_s": rnd(time_over(rows, "re", OUTSIDE_DEG)),
           "rider_rate_deg_s": rnd(rate_peak(rows, "rp", "rr")), "chassis_rate_deg_s": rnd(rate_peak(rows, "cp", "cr")),
           "ground_rate_deg_s": rnd(rate_peak(rows, "gp", "gr")),
           "settle_s": rnd(settle(rows, "re", SETTLE_DEG, t_ref)),
           "chassis_turn_deg": rnd(total((rows[-1]["cp"], rows[-1]["cr"]), (rows[0]["cp"], rows[0]["cr"]))),
           "yaw_change_deg": rnd(rows[-1]["yaw_err"] - rows[0]["yaw_err"]),
           "moved_cm": rnd(rows[-1]["d"] - rows[0]["d"], 1)}
    if t_exit is not None:
        out["exit_t"] = rnd(t_exit)
        out["settle_after_exit_s"] = rnd(settle(between(rows, t_exit, rows[-1]["t"]), "re", SETTLE_DEG, t_exit))
    reach = [r["reach"] for r in rows if r["reach"] is not None]
    scale = [r["scale"] for r in rows if r["scale"] is not None]
    out["reach_min"] = rnd(min(reach)) if reach else None
    out["speed_scale_min"] = rnd(min(scale)) if scale else None
    states = []
    for r in rows:
        if r["state"] is not None and (not states or states[-1][1] != int(r["state"])):
            states.append([rnd(r["t"] - t_ref, 2), int(r["state"])])
    out["states"] = states
    return out


def segment_figures(rows, seg, spans):
    tail = between(rows, rows[-1]["t"] - STEADY_TAIL_S, rows[-1]["t"])
    v = [x for t, x in speeds(rows) if in_spans(t, spans)]
    share = [r["share"] for r in rows if r["share"] is not None]
    margin = [r["margin"] for r in rows if r["margin"] is not None]
    reach = [r["reach"] for r in rows if r["reach"] is not None]
    scale = [r["scale"] for r in rows if r["scale"] is not None]
    turn = [r["turn"] for r in rows]
    return {
        "name": seg["name"], "d0": rnd(seg["d0"], 1), "d1": rnd(seg["d1"], 1), "t0": rnd(rows[0]["t"]), "t1": rnd(rows[-1]["t"]),
        "ground_pitch_deg": rnd(seg["pitch"]), "ground_roll_deg": rnd(seg["roll"]), "slope_deg": rnd(seg["slope"]),
        "ground_seen_deg": [rnd(mean(r["gp"] for r in rows)), rnd(mean(r["gr"] for r in rows))],
        "pref_deg": [rnd(rows[-1]["pp"]), rnd(rows[-1]["pr"])],
        "rider_mean_deg": [rnd(mean(r["rp"] - r["pp"] for r in rows)), rnd(mean(r["rr"] - r["pr"] for r in rows))],
        "rider_rms_deg": rnd(rms(r["re"] for r in rows)), "rider_peak_deg": rnd(max(r["re"] for r in rows)),
        "rider_residual_deg": rnd(mean(r["re"] for r in tail)),
        "rider_residual_axes_deg": [rnd(mean(r["rp"] - r["pp"] for r in tail)), rnd(mean(r["rr"] - r["pr"] for r in tail))],
        "chassis_mean_deg": [rnd(mean(r["cp"] - r["pp"] for r in rows)), rnd(mean(r["cr"] - r["pr"] for r in rows))],
        "chassis_rms_deg": rnd(rms(r["ce"] for r in rows)), "chassis_residual_deg": rnd(mean(r["ce"] for r in tail)),
        "rider_off_ground_deg": [rnd(mean(r["rp"] - r["gp"] for r in rows)), rnd(mean(r["rr"] - r["gr"] for r in rows))],
        "chassis_off_ground_deg": [rnd(mean(r["cp"] - r["gp"] for r in rows)), rnd(mean(r["cr"] - r["gr"] for r in rows))],
        "speed_mean_cm_s": rnd(mean(v), 2), "speed_min_cm_s": rnd(min(v), 2) if v else None,
        "reach_min": rnd(min(reach)) if reach else None, "speed_scale_min": rnd(min(scale)) if scale else None,
        "yaw_drift_deg": rnd(rows[-1]["yaw_err"] - rows[0]["yaw_err"]), "lateral_drift_cm": rnd(rows[-1]["xt"] - rows[0]["xt"], 2),
        "steer_mean": rnd(mean(turn), 4), "steer_peak": rnd(max(turn, key=abs), 4),
        "drive_share_min": rnd(min(share)) if share else None, "drive_share_mean": rnd(mean(share)),
        "margin_min_cm": rnd(min(margin), 2) if margin else None,
    }


def figures(trace, level_prof=None):
    """A run's figures from its trace: {"version", "overall", "segments", "transitions", "parked", "return_level",
    "footprint", "profile"}, or {"version", "why"} when it cannot be measured."""
    level_prof = level_prof or {}
    plan = (trace.get("cfg") or {}).get("plan") or {}
    if not plan.get("course") or plan["course"] not in lt.BY_ID:
        return {"version": LEVEL_VERSION, "why": "no course in the trace"}
    layout = lt.layout(plan["course"])
    rows = series(trace, layout, level_prof)
    t_go = trace.get("go_t")
    end = trace.get("end") or {}
    if len(rows) < 3 or t_go is None or end.get("t") is None:
        return {"version": LEVEL_VERSION, "why": "the run never started" if t_go is None else "too few samples"}
    t_end = end["t"]
    fp = footprint_of(trace, level_prof)
    prof = layout.profile(plan["start"], fp or lt.REF_FOOTPRINT) if plan.get("start") else plan.get("profile")
    driven = between(rows, t_go, t_end)
    spans = moving_spans(trace, t_go, t_end)
    parked = "t" in (plan.get("end") or {})
    out = {"version": LEVEL_VERSION, "footprint": [[rnd(a, 1), rnd(b, 1)] for a, b in fp] if fp else None,
           "profile": {"length": rnd(prof["length"], 1), "segments": len(prof["segments"]), "transitions": len(prof["transitions"])}}

    # Overall, over the driven span.
    v = [] if parked else [x for t, x in speeds(driven) if in_spans(t, spans)]  # a run that stays where it is has no speed
    stops, run = 0, None
    for t, x in ([] if parked else speeds(driven)):
        if in_spans(t, spans) and abs(x) < STOPPED_CM_S:
            run = t if run is None else run
        else:
            if run is not None and t - run >= STOP_MIN_S:
                stops += 1
            run = None
    if run is not None and driven[-1]["t"] - run >= STOP_MIN_S:
        stops += 1
    has_level = any(r["has_level"] for r in rows)
    reach = [r["reach"] for r in driven if r["reach"] is not None]
    scale = [r["scale"] for r in driven if r["scale"] is not None]
    share = [r["share"] for r in driven if r["share"] is not None]
    margin = [r["margin"] for r in driven if r["margin"] is not None]
    turn = [r["turn"] for r in driven]
    legs = []
    moving = [r for r in driven if in_spans(r["t"], spans)] or driven
    for k in range(len(moving[0]["legs"])):
        hs = [r["legs"][k] for r in moving if r["legs"][k] is not None]
        if hs:
            m = sum(hs) / len(hs)
            legs.append((math.sqrt(sum((h - m) ** 2 for h in hs) / len(hs)), max(hs) - min(hs)))
    drive = set(level_prof.get("drive_wheels") or [])
    float_longest = float_total = None
    if any(r["floats"] is not None for r in driven):
        fl = [r for r in driven if r["floats"] is not None]
        names = [w for w in (drive or set(fl[0]["floats"])) if w in fl[0]["floats"]]
        res = [longest_true(fl, lambda r, w=w: r["floats"].get(w)) for w in names]
        float_longest = max((x[0] for x in res), default=0.0)
        float_total = max((x[1] for x in res), default=0.0)
    offsets = {}
    for r in driven:
        for m, c in (r["cmd"] or {}).items():
            if c and c[1] is not None:
                offsets[m] = max(offsets.get(m, 0.0), abs(c[1]))
    at_reach = longest_true(driven, lambda r: (r["reach"] is not None and r["reach"] <= REACH_AT)
                            or ("reach" in (r["status"] or "").lower()))[1]
    out["overall"] = {
        "t_go": rnd(t_go), "t_end": rnd(t_end), "drive_s": rnd(t_end - t_go), "distance_cm": rnd(driven[-1]["d"] - driven[0]["d"], 1),
        "end": end.get("why"), "has_level": has_level,
        "rider_rms_deg": rnd(rms(r["re"] for r in driven)), "rider_peak_deg": rnd(max(r["re"] for r in driven)),
        "rider_pitch_rms_deg": rnd(rms(r["rp"] - r["pp"] for r in driven)), "rider_roll_rms_deg": rnd(rms(r["rr"] - r["pr"] for r in driven)),
        "chassis_rms_deg": rnd(rms(r["ce"] for r in driven)), "chassis_peak_deg": rnd(max(r["ce"] for r in driven)),
        "rider_incl_rms_deg": rnd(rms(math.hypot(r["rp"], r["rr"]) for r in driven)),
        "rider_incl_peak_deg": rnd(max(math.hypot(r["rp"], r["rr"]) for r in driven)),
        "ground_incl_rms_deg": rnd(rms(math.hypot(r["gp"], r["gr"]) for r in driven)),
        "ground_incl_peak_deg": rnd(max(math.hypot(r["gp"], r["gr"]) for r in driven)),
        "rider_off_ground_rms_deg": rnd(rms(total((r["rp"], r["rr"]), (r["gp"], r["gr"])) for r in driven)),
        "rider_rate_deg_s": rnd(rate_peak(driven, "rp", "rr")), "chassis_rate_deg_s": rnd(rate_peak(driven, "cp", "cr")),
        "ground_rate_deg_s": rnd(rate_peak(driven, "gp", "gr")),
        "speed_mean_cm_s": rnd(mean(v), 2), "speed_min_cm_s": rnd(min(v), 2) if v else None, "stops": stops if v else None,
        "reach_min": rnd(min(reach)) if reach else None, "speed_scale_min": rnd(min(scale)) if scale else None,
        "speed_scale_under_1_s": rnd(time_over([dict(r, inv=(1.0 - r["scale"]) if r["scale"] is not None else None) for r in driven],
                                               "inv", 1e-3)) if scale else None,
        "at_reach_s": rnd(at_reach) if has_level else None,
        "level_tilt_max_deg": rnd(max((r["tilt"] for r in driven if r["tilt"] is not None), default=None)),
        "faulted": any(r["state"] is not None and int(r["state"]) == FAULTED for r in rows) if has_level else None,
        "correction_peak": {m: rnd(x, 4) for m, x in sorted(offsets.items())} or None,
        "yaw_end_deg": rnd(driven[-1]["yaw_err"]), "yaw_peak_deg": rnd(max((r["yaw_err"] for r in driven), key=abs)),
        "yaw_change_deg": rnd(driven[-1]["yaw_err"] - driven[0]["yaw_err"]),
        "lateral_end_cm": rnd(driven[-1]["xt"], 2), "lateral_peak_cm": rnd(max((r["xt"] for r in driven), key=abs), 2),
        "steer_mean": rnd(mean(turn), 4), "steer_abs_mean": rnd(mean(abs(x) for x in turn), 4),
        "steer_peak": rnd(max(turn, key=abs), 4),
        "steer_saturated_s": rnd(longest_true(driven, lambda r: abs(r["turn"]) >= 0.999 * (plan.get("hold") or {}).get("max_turn", 9.9))[1]),
        "drive_share_min": rnd(min(share)) if share else None, "drive_share_mean": rnd(mean(share)),
        "margin_min_cm": rnd(min(margin), 2) if margin else None,
        "float_longest_s": rnd(float_longest), "float_total_s": rnd(float_total),
        "leg_travel_rms_cm": rnd(max(x[0] for x in legs)) if legs else None,
        "leg_travel_range_cm": rnd(max(x[1] for x in legs)) if legs else None,
    }

    # Segments and the seams between them.
    segs, trans = [], []
    if not parked:
        for seg in prof["segments"]:
            t_a = time_at_d(rows, seg["d0"] + SEG_MARGIN_CM, t_go)
            t_b = time_at_d(rows, seg["d1"] - SEG_MARGIN_CM, t_go)
            if t_a is None:
                continue
            sr = between(rows, max(t_a, t_go), min(t_b if t_b is not None else t_end, t_end))
            if len(sr) >= 3:
                f = segment_figures(sr, seg, spans)
                f["complete"] = t_b is not None
                segs.append(f)
        onsets = [time_at_d(rows, tr["d0"] - SEG_MARGIN_CM, t_go) for tr in prof["transitions"]]
        for k, tr in enumerate(prof["transitions"]):
            t_a = onsets[k]
            if t_a is None:
                continue
            t_exit = time_at_d(rows, tr["d1"], t_a)
            later = [t for t in onsets[k + 1:] if t is not None]
            t_b = min([(t_exit if t_exit is not None else t_a) + TRANSITION_HORIZON_S, rows[-1]["t"]] + later[:1])
            f = window_figures(between(rows, t_a, t_b), t_a, t_exit)
            if f:
                f.update({"kind": "seam", "label": "%s -> %s" % (tr["from"], tr["to"]), "d": rnd(tr["d"], 1),
                          "pitch_change_deg": rnd(tr["pitch_change"]), "roll_change_deg": rnd(tr["roll_change"]),
                          "error_meant": True})
                trans.append(f)
    out["segments"] = segs
    events = [e for e in (trace.get("events") or []) if e.get("t") is not None]
    marks = sorted([e["t"] for e in events] + [t for t in [time_at_d(rows, tr["d0"] - SEG_MARGIN_CM, t_go)
                                                         for tr in (prof["transitions"] if not parked else [])] if t is not None])
    for e in events:
        if e.get("do") == "pref" and e["t"] < t_go and not any(abs(x) > 1e-9 for x in (e.get("pitch", 0.0), e.get("roll", 0.0))):
            continue  # the zero preference set at the gate: nothing happens
        nxt = [t for t in marks if t > e["t"] + 1e-6]
        t_b = min([e["t"] + EVENT_HORIZON_S, rows[-1]["t"]] + nxt[:1])
        f = window_figures(between(rows, e["t"], t_b), e["t"])
        if f:
            f.update({"kind": "event", "label": e.get("label") or e.get("do"), "do": e.get("do"), "d": rnd(e.get("d"), 1),
                      # After the assist is switched off, or in a mode it does not level in, the attitude is meant to
                      # go back to the ground's: read the rates there, not the error.
                      "error_meant": not (e.get("do") == "assist" and not e.get("value")) and e.get("do") != "mode"})
            trans.append(f)
    # The stop at the end of the run (the stick let go at speed): a transition of its own, reported and not scored.
    if not parked and end.get("t") is not None and rows[-1]["t"] > t_end:
        f = window_figures(between(rows, t_end, rows[-1]["t"]), t_end)
        if f:
            f.update({"kind": "event", "label": "stop at the end", "do": "end", "d": rnd(end.get("d"), 1), "error_meant": True})
            trans.append(f)
    trans.sort(key=lambda f: f["t0"])
    out["transitions"] = trans

    # Back on the level: after the last seam onto ground under MIN_SLOPE, how the rider comes back -- while it is
    # still driven: the stop at the end pitches the rider by itself, and is a transition of its own above.
    out["return_level"] = None
    if not parked and prof["transitions"] and prof["segments"][-1]["slope"] < course_mod.MIN_SLOPE_DEG:
        t_exit = time_at_d(rows, prof["transitions"][-1]["d1"], t_go)
        if t_exit is not None:
            after = between(rows, t_exit, t_end)
            at3 = [r for r in after if r["t"] >= t_exit + 3.0]
            out["return_level"] = {"t": rnd(t_exit), "settle_s": rnd(settle(after, "re", SETTLE_DEG, t_exit)),
                                   "rider_after_3s_deg": rnd(max(r["re"] for r in at3)) if at3 else None,
                                   "window_s": rnd(after[-1]["t"] - t_exit) if after else None}

    # Standing: how far it crept, and whether the commands went quiet once it had settled.
    out["parked"] = None
    if parked:
        x0, y0 = driven[0]["x"], driven[0]["y"]
        # drift_cm: the farthest the reference point is from where it stood at go, over the whole run -- the creep
        # while it holds, and what every switch on the way moved it (the assist in and out, a mode switch).
        # hold_drift_cm: the creep alone, from settled to the next event. quiet_after_s: when the commands last
        # changed after the switch-on (before the next event).
        p = {"drift_cm": rnd(max(math.hypot(r["x"] - x0, r["y"] - y0) for r in driven), 2), "cmd_changes_after_settle": None,
             "settled_after_s": None, "hold_drift_cm": None, "hold_s": None, "quiet_after_s": None}
        on = next((e for e in events if e.get("do") == "assist" and e.get("value")), None)
        nxt = min([e["t"] for e in events if on and e["t"] > on["t"] + 1e-6] + [t_end])
        if on:
            hold = between(rows, on["t"], nxt)
            t_set = None
            for i, r in enumerate(hold):
                w = [q for q in hold[i:] if q["t"] <= r["t"] + SETTLED_FOR_S]
                if r["re"] <= SETTLE_DEG and w and w[-1]["t"] - r["t"] >= SETTLED_FOR_S - 0.1 and all(q["re"] <= SETTLE_DEG for q in w):
                    t_set = r["t"]
                    break
            if t_set is not None:
                p["settled_after_s"] = rnd(t_set - on["t"])
                def told(r, m):
                    c = r["cmd"].get(m) or [0, 0]
                    return (c[0] or 0.0) + (c[1] or 0.0)

                def changed(a, b):
                    return any(abs(told(b, m) - told(a, m)) > CMD_CHANGE for m in b["cmd"])
                with_cmd = [r for r in hold if r["cmd"]]
                last = [b["t"] for a, b in zip(with_cmd, with_cmd[1:]) if changed(a, b)]
                p["quiet_after_s"] = rnd(last[-1] - on["t"]) if last else 0.0
                # Settled is the rider within SETTLE_DEG; a controller still trims inside that for a moment, which is
                # not hunting: the commands are counted from QUIET_GRACE_S after it.
                quiet = [r for r in with_cmd if r["t"] >= t_set + QUIET_GRACE_S]
                if len(quiet) >= 2:
                    p["cmd_changes_after_settle"] = sum(1 for a, b in zip(quiet, quiet[1:]) if changed(a, b))
                held = [r for r in hold if r["t"] >= t_set]
                if len(held) >= 2:
                    p["hold_drift_cm"] = rnd(max(math.hypot(r["x"] - held[0]["x"], r["y"] - held[0]["y"]) for r in held), 2)
                    p["hold_s"] = rnd(held[-1]["t"] - held[0]["t"], 1)
        out["parked"] = p
    return out


def rider_accel(imu, t_a, t_b, tau=measures.RIDER_TAU_S):
    """The rider's acceleration over [t_a, t_b] as measures.rider_figures takes it (every physics step's IMU sample,
    rotated to the world, gravity off, two low-passes), with its LATERAL part beside the fore/aft and vertical ones:
    {"peak_<part>_m_s2", "rms_<part>_m_s2"} for fore_aft, lateral, vertical, total; None without samples."""
    pts = sorted((s for s in imu or [] if isinstance(s.get("sim_time"), (int, float))), key=lambda s: s["sim_time"])
    if len(pts) < 2 or t_a is None or t_b is None:
        return None
    f1 = f2 = prev_t = None
    acc = {"fore_aft": [], "lateral": [], "vertical": [], "total": []}
    for s in pts:
        o = s.get("orientation") or {}
        q = (o.get("x", 0.0), o.get("y", 0.0), o.get("z", 0.0), o.get("w", 1.0))
        la = s.get("linear_acceleration") or {}
        a_s = (la.get("x", 0.0), la.get("y", 0.0), la.get("z", 0.0)) if isinstance(la, dict) else tuple(la[:3])
        a = measures.quat_rotate(q, a_s)
        a = (a[0], a[1], a[2] - measures.GRAVITY_CM_S2)
        h = measures.unit2(measures.quat_rotate(q, (1.0, 0.0, 0.0))[:2])
        t = s["sim_time"]
        if f1 is None:
            f1 = f2 = list(a)
        else:
            alpha = 1.0 - math.exp(-max(0.0, t - prev_t) / tau)
            f1 = [x + alpha * (y - x) for x, y in zip(f1, a)]
            f2 = [x + alpha * (y - x) for x, y in zip(f2, f1)]
        prev_t = t
        if t_a <= t <= t_b:
            acc["fore_aft"].append((f2[0] * h[0] + f2[1] * h[1]) / 100.0)
            acc["lateral"].append((-f2[0] * h[1] + f2[1] * h[0]) / 100.0)
            acc["vertical"].append(f2[2] / 100.0)
            acc["total"].append(math.sqrt(f2[0] ** 2 + f2[1] ** 2 + f2[2] ** 2) / 100.0)
    if not acc["total"]:
        return None
    out = {"samples": len(acc["total"])}
    for k, xs in acc.items():
        out["peak_%s_m_s2" % k] = rnd(max(abs(x) for x in xs))
        out["rms_%s_m_s2" % k] = rnd(math.sqrt(sum(x * x for x in xs) / len(xs)))
    return out


# --- an on run against its off run ----------------------------------------------------------------------------------

def ratio(a, b):
    return None if a is None or b is None or abs(b) < 1e-9 else a / b


def pair(on, off):
    """An assist-on run's figures against the assist-off run of the same case: {"rejection": the rider's error RMS on
    over off, "rejection_slopes_max": the worst of that over the segments at least SLOPE_DEG steep, "segments":
    [{"name", "rejection", "speed_kept"}], "speed_kept", "speed_kept_slopes_min", "rms_change_deg" (on less off),
    "margin_change_cm", "drive_share_change", "leg_travel_change_cm"}; None when either has no figures."""
    if not on or not off or not on.get("overall") or not off.get("overall"):
        return None
    a, b = on["overall"], off["overall"]
    by_name = {s["name"]: s for s in off.get("segments") or []}
    segs = []
    for s in on.get("segments") or []:
        o = by_name.get(s["name"])
        if o:
            segs.append({"name": s["name"], "slope_deg": s["slope_deg"], "rejection": rnd(ratio(s["rider_rms_deg"], o["rider_rms_deg"])),
                         "speed_kept": rnd(ratio(s["speed_mean_cm_s"], o["speed_mean_cm_s"])),
                         "on_rms_deg": s["rider_rms_deg"], "off_rms_deg": o["rider_rms_deg"]})
    slopes = [s for s in segs if (s["slope_deg"] or 0.0) >= SLOPE_DEG]

    def diff(k):
        return None if a.get(k) is None or b.get(k) is None else rnd(a[k] - b[k])
    return {"rejection": rnd(ratio(a["rider_rms_deg"], b["rider_rms_deg"])),
            "rejection_slopes_max": rnd(max((s["rejection"] for s in slopes if s["rejection"] is not None), default=None)),
            "speed_kept": rnd(ratio(a["speed_mean_cm_s"], b["speed_mean_cm_s"])),
            "speed_kept_slopes_min": rnd(min((s["speed_kept"] for s in slopes if s["speed_kept"] is not None), default=None)),
            "rms_change_deg": diff("rider_rms_deg"), "peak_change_deg": diff("rider_peak_deg"),
            "margin_change_cm": diff("margin_min_cm"), "drive_share_change": diff("drive_share_min"),
            "leg_travel_change_cm": diff("leg_travel_rms_cm"), "yaw_change_more_deg": diff("yaw_change_deg"),
            "steer_abs_mean_change": diff("steer_abs_mean"), "segments": segs}


# --- scoring --------------------------------------------------------------------------------------------------------

def _check(checks, name, value, limit, kind="max"):
    """One check: value at most (kind "max") or at least (kind "min") limit; a value that was not measured is listed
    and fails nothing."""
    if limit is None:
        return
    ok = None if value is None else (value <= limit + 1e-9 if kind == "max" else value >= limit - 1e-9)
    checks.append({"name": name, "value": rnd(value), "limit": limit, "kind": kind, "ok": ok})


def score(fig, pair_fig, criteria, expect, level="on"):
    """A run against its robot's criteria (the profile's level `criteria`, the plan's section I as data): {"expect",
    "met": True / False / None (not scored), "failed": [names], "checks": [{"name", "value", "limit", "kind", "ok"}],
    "not_measured": [names]}. expect:

        "pass"        inside the robot's reach: every check
        "rates"       a run that switches the assist, the mode or the preference on the way: the tilt rates, no fault,
                      no stop; the errors are reported, not scored
        "past_reach"  a slope past the legs' reach: the tilt bounded, the rates, never under the speed floor, no fault
        "parked"      standing: the creep, the commands quiet once settled, the switch-on and switch-off rates
        "explore"     run and recorded, not scored
    An assist-off run is a baseline and is never scored."""
    out = {"expect": expect, "met": None, "failed": [], "checks": [], "not_measured": []}
    if level != "on" or expect == "explore" or not fig or not fig.get("overall"):
        if level == "on" and expect != "explore":
            out.update({"met": False, "failed": ["not measured"]})
        return out
    c, o, ch = criteria or {}, fig["overall"], []
    p = pair_fig or {}
    if not o.get("has_level"):
        out.update({"met": False, "failed": ["no level assist on this robot"]})
        return out
    _check(ch, "no fault", 1.0 if o.get("faulted") else 0.0, 0.0)
    if expect in ("pass", "rates", "past_reach"):
        _check(ch, "no stops", o.get("stops"), c.get("stops"))
    if expect == "pass":
        segs = fig.get("segments") or []
        _check(ch, "steady residual", max((s["rider_residual_deg"] for s in segs if s.get("complete")), default=None),
               c.get("steady_residual_deg"))
        _check(ch, "rider RMS", o.get("rider_rms_deg"), c.get("rider_rms_deg"))
        _check(ch, "rider peak", o.get("rider_peak_deg"), c.get("rider_peak_deg"))
        _check(ch, "tilt rate", o.get("rider_rate_deg_s"), c.get("tilt_rate_deg_s"))
        if any((s.get("slope_deg") or 0.0) >= SLOPE_DEG for s in segs):
            _check(ch, "rejection on slopes", p.get("rejection_slopes_max"), c.get("rejection_max"))
            _check(ch, "speed kept on slopes", p.get("speed_kept_slopes_min"), c.get("speed_kept_slope"), "min")
        elif all((s.get("slope_deg") or 0.0) < course_mod.MIN_SLOPE_DEG for s in segs):
            # Flat ground only (a gentle slope, under SLOPE_DEG, is neither: its legs must move, and its off run's
            # error is too small for a ratio). On less off, signed: a robot whose stance is not level on the flat is brought level by the assist, and
            # that is not a failure (only an on run worse than its off run by more than the limit is).
            _check(ch, "RMS on the flat over off", p.get("rms_change_deg"), c.get("flat_rms_over_off_deg"))
            _check(ch, "leg travel on the flat", o.get("leg_travel_rms_cm"), c.get("flat_leg_travel_rms_cm"))
        _check(ch, "speed kept", p.get("speed_kept"), c.get("speed_kept_overall"), "min")
        _check(ch, "time at reach", o.get("at_reach_s"), c.get("at_reach_s"))
        _check(ch, "margin", o.get("margin_min_cm"), c.get("margin_cm"), "min")
        _check(ch, "margin against off", p.get("margin_change_cm"),
               -c["margin_under_off_cm"] if c.get("margin_under_off_cm") is not None else None, "min")
        _check(ch, "drive-wheel share against off", p.get("drive_share_change"),
               -c["drive_share_under_off"] if c.get("drive_share_under_off") is not None else None, "min")
        _check(ch, "drive wheel off the ground", o.get("float_longest_s"), c.get("float_s"))
        rl = fig.get("return_level")
        if rl:
            _check(ch, "level 3 s after the flat", rl.get("rider_after_3s_deg"), c.get("level_after_flat_deg"))
    elif expect == "rates":
        _check(ch, "tilt rate", o.get("rider_rate_deg_s"), c.get("tilt_rate_deg_s"))
    elif expect == "past_reach":
        pr = c.get("past_reach") or {}
        reach = pr.get("reach_deg")
        over = None if reach is None or o.get("ground_incl_peak_deg") is None else max(0.0, o["ground_incl_peak_deg"] - reach)
        _check(ch, "tilt past reach", o.get("chassis_peak_deg"), None if over is None else over + pr.get("tilt_over_deg", 0.5))
        _check(ch, "tilt rate", o.get("rider_rate_deg_s"), pr.get("rate_deg_s"))
        _check(ch, "speed floor", o.get("speed_scale_min"), pr.get("speed_floor"), "min")
    elif expect == "parked":
        pk, park = c.get("parked") or {}, fig.get("parked") or {}
        _check(ch, "creep", park.get("drift_cm"), pk.get("drift_cm"))
        _check(ch, "commands after settling", park.get("cmd_changes_after_settle"), pk.get("cmd_changes"))
        ev = [t for t in fig.get("transitions") or [] if t.get("kind") == "event" and t.get("do") == "assist"]
        _check(ch, "switch-on and switch-off tilt rate", max((t["rider_rate_deg_s"] for t in ev if t["rider_rate_deg_s"] is not None),
                                                           default=None), pk.get("toggle_rate_deg_s"))
        modes = [t for t in fig.get("transitions") or [] if t.get("kind") == "event" and t.get("do") == "mode"]
        if modes:
            _check(ch, "mode switch moves the base", max(t["chassis_turn_deg"] for t in modes), pk.get("mode_switch_deg"))
    out["checks"] = ch
    out["failed"] = [x["name"] for x in ch if x["ok"] is False]
    out["not_measured"] = [x["name"] for x in ch if x["ok"] is None]
    out["met"] = not out["failed"]
    return out
