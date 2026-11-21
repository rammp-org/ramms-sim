"""One definition of a curb crossing's times and figures, for every robot (`shared.version`).

Every robot's crossing is measured by this code from a trace of the same samples, against the map's own terrain
(Scripts/curb_maps/curb_terrain.py), so two robots' figures compare: a figure a robot's controller reports about
itself is kept beside these (a record's `controller` group), never in their place.

A trace is a list of samples, oldest first, one per editor frame:

    {"t": simulated time (s),
     "phase": the controller's phase, generic: IDLE before the crossing, PLANNING while a controller plans it (not yet
              carrying it out), any other word while it runs, and DONE, FAULTED or ABORTED as it ends (TERMINAL),
     "chassis": {"xyz": [x, y, z] (cm, world), "pitch", "yaw", "roll" (deg, the chassis's world rotation)},
     "seat": {"pitch", "roll"} (deg, the rider's seat; optional: the chassis stands in),
     "wheels": [[x, y, z] (cm, world: the wheel's hub) or None, ...] in the robot's wheel order,
     "axles": [[x, y, z] (world unit vector) or None, ...] (optional: from the chassis rotation and each wheel's
              chassis-frame axle)}

and a robot's wheels are [{"name", "radius_cm", "axle": [x, y, z] in the chassis frame (default +Y)}, ...].

The crossing's events (seconds of simulated time):
  t_ask        the crossing was asked for.
  t_begin      the controller began to carry it out (after any planning): given by the robot's adapter.
  t_edge       the robot's leading wheel reached the edge: the first time any wheel's leading extent along the edge
               normal (its hub, plus its radius in its rolling plane) is at or past the edge line, interpolated.
  t0           max(t_edge, t_begin): the crossing's start. Planning, and a stall at rest before the edge, are never
               crossing time.
  t_down[k]    wheel k came down for good on the surface the crossing ends on: the start of its last stretch, up to
               SETTLE_S after the crossing's end (a wheel still settling as the controller says Done is down when it
               gets there; what the robot does after that is not the crossing's), with its lowest point within DOWN_GAP_CM of that surface (less the gap it
               stood with at rest before the ask) and its hub past the edge; dips out of it shorter than BRIDGE_S are
               bridged (a roller's ripple, a bounce). Interpolated where the gap crosses DOWN_GAP_CM.
  t_last_down  the latest t_down over the wheels the crossing counts: every wheel that stood on the start surface at
               the ask (a wheel held up, like a raised caster, is not counted). Every one of them must be down past
               the edge SETTLE_S after the end, or the crossing did not get across and has no crossing times.
  t_done       the first DONE sample.
  t_rest       the first time from t_last_down that the chassis then stays within REST_MOVE_CM horizontally and
               REST_ATT_DEG in pitch and roll for REST_WINDOW_S (the steady gate's limits).

The headline time is edge_to_last_down_s = t_last_down - t0; edge_to_done_s and edge_to_rest_s go on to Done and to
rest. Only the standard library.
"""

import math

SHARED_VERSION = 1

TERMINAL = ("DONE", "FAULTED", "ABORTED")
INACTIVE = ("IDLE", "PLANNING")  # not yet carrying the crossing out: t_begin is the first sample after these

DOWN_GAP_CM = 1.0  # a wheel's lowest point this close to the destination surface is down on it
RAISED_GAP_CM = 2.0  # a wheel further than this over the start surface at the ask is held up: not counted
CALIBRATE_S = 1.0  # the gap a wheel stands with at rest: its mean over this long before the ask
BRIDGE_S = 0.1  # a wheel's dip out of "down" shorter than this is bridged
SETTLE_S = 1.0  # a wheel may come down this long after the crossing's end and still count
REST_WINDOW_S = 0.5
REST_MOVE_CM = 0.25
REST_ATT_DEG = 0.1

SPEED_WINDOW_S = 0.3  # speeds and tilt rates are changes over windows exactly this long
STOPPED_CM_S = 2.0  # slower than this is stopped ...
STOP_MIN_S = 0.2  # ... and a stop lasts at least this long
TILT_RATE_WINDOW_S = 0.3
# A window end interpolated between two samples further apart than this (a gap in the trace) is not used.
TILT_RATE_MAX_GAP_S = 0.2

GRAVITY_CM_S2 = 980.665
RIDER_TAU_S = 0.05  # the rider's acceleration: two first-order low-passes of this time constant


# --- small maths ----------------------------------------------------------------------------------------------------

def rnd(x, nd=2):
    return None if x is None or not math.isfinite(x) else round(x, nd)


def unit2(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 0.0 else (1.0, 0.0)


def rotation_axes(pitch, yaw, roll):
    """The world directions of a rotation's X, Y and Z axes (UE's FRotationMatrix, degrees)."""
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    x = (cp * cy, cp * sy, sp)
    y = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
    z = (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp)
    return x, y, z


def to_world(axes, v):
    x, y, z = axes
    return tuple(v[0] * x[i] + v[1] * y[i] + v[2] * z[i] for i in range(3))


def incl(pitch, roll):
    """The inclination from level (deg) of a frame at a pitch and roll (deg): atan(sqrt(tan^2 pitch + tan^2 roll)),
    its total tilt -- RammsCurb::InclinationDeg."""
    return math.degrees(math.atan(math.hypot(math.tan(math.radians(pitch)), math.tan(math.radians(roll)))))


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def _lerp(a, b, t, get):
    """get(sample) linearly interpolated at simulated time t between samples a and b."""
    va, vb = get(a), get(b)
    f = (t - a["t"]) / (b["t"] - a["t"]) if b["t"] > a["t"] else 0.0
    return [x + f * (y - x) for x, y in zip(va, vb)]


def window_changes(samples, get, window=TILT_RATE_WINDOW_S):
    """The change of get(sample) (a list of numbers) over windows exactly `window` long inside the samples, the
    signal taken as linear between samples: every window that ends on a sample (its start interpolated) and every
    one that begins on a sample (its end interpolated) -- the largest change over any window of a piecewise-linear
    signal is among them. Yields (change, the sample at or after the window's end). A window whose interpolated end
    falls in a gap longer than TILT_RATE_MAX_GAP_S is skipped."""
    n = len(samples)
    if n < 2 or samples[-1]["t"] - samples[0]["t"] < window - 1e-9:
        return
    j = 0
    for i in range(n):  # windows ending on sample i
        ts = samples[i]["t"] - window
        if ts < samples[0]["t"] - 1e-9:
            continue
        while j + 1 < n and samples[j + 1]["t"] < ts:
            j += 1
        a, b = samples[j], samples[min(j + 1, n - 1)]
        if b["t"] - a["t"] > TILT_RATE_MAX_GAP_S and a["t"] < ts < b["t"]:
            continue
        v0 = get(a) if b is a else _lerp(a, b, ts, get)
        yield [y - x for x, y in zip(v0, get(samples[i]))], samples[i]
    k = 0
    for j in range(n):  # windows beginning on sample j
        te = samples[j]["t"] + window
        if te > samples[-1]["t"] + 1e-9:
            break
        k = max(k, j)
        while k + 1 < n and samples[k + 1]["t"] < te:
            k += 1
        a, b = samples[k], samples[min(k + 1, n - 1)]
        if b["t"] - a["t"] > TILT_RATE_MAX_GAP_S and a["t"] < te < b["t"]:
            continue
        v1 = get(a) if b is a else _lerp(a, b, te, get)
        yield [y - x for x, y in zip(get(samples[j]), v1)], b


def tilt_rate_total(samples, get):
    """The fastest turn of a frame (deg/s): hypot(pitch change, roll change) over windows exactly TILT_RATE_WINDOW_S
    long -- what the Gen2 controller's TiltRateDegPerSec bounds."""
    w = TILT_RATE_WINDOW_S
    return max((math.hypot(d[0], d[1]) / w for d, _ in window_changes(samples, get, w)), default=None)


def interp_time(t_a, v_a, t_b, v_b, level):
    """Where a signal linear between (t_a, v_a) and (t_b, v_b) crosses level (t_b when it does not)."""
    if v_b == v_a:
        return t_b
    f = (level - v_a) / (v_b - v_a)
    return t_a + max(0.0, min(1.0, f)) * (t_b - t_a)


def value_at(samples, t, get):
    """get(sample) interpolated at simulated time t (clamped to the samples)."""
    if not samples:
        return None
    if t <= samples[0]["t"]:
        return get(samples[0])
    for a, b in zip(samples, samples[1:]):
        if a["t"] <= t <= b["t"]:
            return _lerp(a, b, t, get)
    return get(samples[-1])


# --- the crossing's frame -------------------------------------------------------------------------------------------

class Frame(object):
    """The edge a crossing goes over and the surfaces either side, from a curb_terrain Layout: the edge line through
    `point` with unit `normal` (the direction of travel), the plane it starts on and the one it ends on."""

    def __init__(self, layout, direction):
        d = layout.expected()[direction]
        self.direction = direction
        self.point = (float(d["edge_point"][0]), float(d["edge_point"][1]))
        self.normal = unit2(d["normal"])
        self.plane_from = layout.planes[d["from"]]
        self.plane_to = layout.planes[d["to"]]
        self.step = d["step"]
        self.step_range = d["step_range"]

    def along(self, p):
        """How far p is past the edge line, along the normal (cm; negative: short of it)."""
        return (p[0] - self.point[0]) * self.normal[0] + (p[1] - self.point[1]) * self.normal[1]

    def gap_from(self, hub, radius):
        return hub[2] - radius - self.plane_from.z(hub[0], hub[1])

    def gap_to(self, hub, radius):
        return hub[2] - radius - self.plane_to.z(hub[0], hub[1])


def sample_axle(sample, k, wheel):
    """Wheel k's world axle in this sample: the sample's own, else its chassis-frame axle (+Y) rotated."""
    axles = sample.get("axles")
    if axles and k < len(axles) and axles[k]:
        return axles[k]
    c = sample.get("chassis") or {}
    return to_world(rotation_axes(c.get("pitch", 0.0), c.get("yaw", 0.0), c.get("roll", 0.0)), wheel.get("axle") or (0.0, 1.0, 0.0))


def leading_extent(frame, hub, radius, axle):
    """How far a wheel reaches past the edge line along the normal: its hub, plus its radius in its rolling plane
    (all of it when the axle runs along the edge, none when it points across it)."""
    an = axle[0] * frame.normal[0] + axle[1] * frame.normal[1]
    return frame.along(hub) + radius * math.sqrt(max(0.0, 1.0 - an * an))


def hub(sample, k):
    w = sample.get("wheels")
    return w[k] if w and k < len(w) and w[k] else None


def seat_attitude(sample):
    s = sample.get("seat") or sample.get("chassis") or {}
    return [s.get("pitch", 0.0), s.get("roll", 0.0)]


def chassis_attitude(sample):
    c = sample.get("chassis") or {}
    return [c.get("pitch", 0.0), c.get("roll", 0.0)]


def chassis_xy(sample):
    c = sample.get("chassis") or {}
    xyz = c.get("xyz") or (0.0, 0.0, 0.0)
    return [xyz[0], xyz[1]]


# --- events ---------------------------------------------------------------------------------------------------------

def t_edge_of(frame, samples, wheels, t_from):
    """The first time from t_from that any wheel's leading extent reaches the edge line (interpolated), or None."""
    prev = None
    for s in samples:
        if s["t"] < t_from:
            continue
        ext = [leading_extent(frame, h, w["radius_cm"], sample_axle(s, k, w))
               for k, w in enumerate(wheels) for h in [hub(s, k)] if h]
        if not ext:
            continue
        lead = max(ext)
        if lead >= 0.0:
            return s["t"] if prev is None else interp_time(prev[0], prev[1], s["t"], lead, 0.0)
        prev = (s["t"], lead)
    return None


def rest_gaps(frame, samples, wheels, t_ask):
    """Each wheel's mean gap over the start surface across CALIBRATE_S before the ask (the sample nearest the ask when
    there are none), and whether it stood on it (within RAISED_GAP_CM)."""
    before = [s for s in samples if t_ask - CALIBRATE_S <= s["t"] <= t_ask + 1e-9]
    if not before:
        near = min(samples, key=lambda s: abs(s["t"] - t_ask)) if samples else None
        before = [near] if near else []
    out = []
    for k, w in enumerate(wheels):
        g = [frame.gap_from(h, w["radius_cm"]) for s in before for h in [hub(s, k)] if h]
        if not g:
            out.append((None, False))
            continue
        mean = sum(g) / len(g)
        out.append((mean, mean <= RAISED_GAP_CM))
    return out


def down_time(frame, samples, k, wheel, calib, i_end):
    """Wheel k's t_down: the start of its last stretch, up to sample i_end, down on the destination surface past the
    edge, dips shorter than BRIDGE_S bridged; None when it is not down at i_end."""
    r = wheel["radius_cm"]

    def state(i):
        h = hub(samples[i], k)
        if not h:
            return None, None
        return frame.gap_to(h, r) - calib, frame.along(h)

    def ok(i):
        g, a = state(i)
        return g is not None and g <= DOWN_GAP_CM and a >= 0.0

    if not ok(i_end):
        return None
    i = i_end
    while i > 0:
        if ok(i - 1):
            i -= 1
            continue
        j = i - 1  # a run of samples out of "down" ends at j
        while j >= 0 and not ok(j):
            j -= 1
        if j < 0:
            break
        # The dip lasts from where it left "down" (between j and j + 1) to where it came back (between i - 1 and i).
        left = _out_time(samples, state, j, j + 1)
        back = _out_time(samples, state, i - 1, i)
        if back - left < BRIDGE_S:
            i = j
            continue
        break
    if i == 0:
        return samples[0]["t"]
    g_prev, a_prev = state(i - 1)
    g_i, _ = state(i)
    if g_prev is not None and a_prev is not None and a_prev >= 0.0 and g_prev > DOWN_GAP_CM:
        return interp_time(samples[i - 1]["t"], g_prev, samples[i]["t"], g_i, DOWN_GAP_CM)
    return samples[i]["t"]


def _out_time(samples, state, i_a, i_b):
    """Between samples i_a and i_b, where one is down and the other is not: where the gap crosses DOWN_GAP_CM (the
    later sample's time when it is not the gap that changes)."""
    ga, _ = state(i_a)
    gb, _ = state(i_b)
    if ga is None or gb is None or (ga > DOWN_GAP_CM) == (gb > DOWN_GAP_CM):
        return samples[i_b]["t"]
    return interp_time(samples[i_a]["t"], ga, samples[i_b]["t"], gb, DOWN_GAP_CM)


def t_rest_of(samples, t_from):
    """The first sample time from t_from after which the chassis stays within REST_MOVE_CM horizontally and
    REST_ATT_DEG in pitch and roll for REST_WINDOW_S; None when the trace never shows it."""
    n = len(samples)
    for i in range(n):
        s = samples[i]
        if s["t"] < t_from - 1e-9:
            continue
        if samples[-1]["t"] < s["t"] + REST_WINDOW_S - 1e-9:
            return None
        p0, a0 = chassis_xy(s), chassis_attitude(s)
        still = True
        for q in samples[i + 1:]:
            if q["t"] > s["t"] + REST_WINDOW_S + 1e-9:
                break
            p, a = chassis_xy(q), chassis_attitude(q)
            if (math.hypot(p[0] - p0[0], p[1] - p0[1]) > REST_MOVE_CM or abs(a[0] - a0[0]) > REST_ATT_DEG
                    or abs(a[1] - a0[1]) > REST_ATT_DEG):
                still = False
                break
        if still:
            return s["t"]
    return None


# --- figures --------------------------------------------------------------------------------------------------------

def span(samples, t_a, t_b):
    """The samples from t_a to t_b, the ends interpolated in (so a window figure covers exactly that span)."""
    if t_a is None or t_b is None or t_b <= t_a or not samples:
        return []
    keys = ("chassis", "seat")
    inner = [s for s in samples if t_a < s["t"] < t_b]

    def at(t):
        out = {"t": t}
        for key in keys:
            if any(key in s for s in samples):
                v = value_at(samples, t, lambda s, key=key: _flat(s.get(key) or samples[0].get(key) or {}))
                out[key] = _unflat(v)
        return out

    return [at(t_a)] + inner + [at(t_b)]


_FIELDS = ("x", "y", "z", "pitch", "yaw", "roll")


def _flat(d):
    xyz = d.get("xyz") or (0.0, 0.0, 0.0)
    return [xyz[0], xyz[1], xyz[2], d.get("pitch", 0.0), d.get("yaw", 0.0), d.get("roll", 0.0)]


def _unflat(v):
    return {"xyz": v[:3], "pitch": v[3], "yaw": v[4], "roll": v[5]}


def forward_speeds(samples):
    """(t, signed speed along the chassis's heading, cm/s) over windows exactly SPEED_WINDOW_S long that end on a
    sample (window_changes' first kind), the heading taken at the window's end."""
    out = []
    for d, s in window_changes(samples, chassis_xy, SPEED_WINDOW_S):
        yaw = math.radians((s.get("chassis") or {}).get("yaw", 0.0))
        out.append((s["t"], (d[0] * math.cos(yaw) + d[1] * math.sin(yaw)) / SPEED_WINDOW_S))
    out.sort(key=lambda x: x[0])
    return out


def speed_figures(samples, count_final_stop=True):
    """{v_min, stops, stopped_s} over the samples: the least speed, and the stops (slower than STOPPED_CM_S for at
    least STOP_MIN_S) and the time spent slower than STOPPED_CM_S, from the windowed speeds. count_final_stop False:
    a stop still going at the end is the crossing's own end (a robot that stops before Done), not counted as a stop
    (its time still is)."""
    v = forward_speeds(samples)
    if not v:
        return {"v_min_cm_s": None, "stops": None, "stopped_s": None}
    stopped, stops, run, prev = 0.0, 0, None, v[0][0]
    for t, x in v:
        if x < STOPPED_CM_S:
            stopped += t - prev
            run = t if run is None else run
        else:
            if run is not None and t - run >= STOP_MIN_S:
                stops += 1
            run = None
        prev = t
    if run is not None and v[-1][0] - run >= STOP_MIN_S and count_final_stop:
        stops += 1
    return {"v_min_cm_s": rnd(min(x for _, x in v)), "stops": stops, "stopped_s": rnd(stopped)}


def max_incl(samples, get):
    return max((incl(*get(s)) for s in samples), default=None)


def drift(sample_ask, xy, yaw):
    """How far the chassis went across its heading at the ask (cm, + to its left), and its heading change (deg)."""
    c = sample_ask.get("chassis") or {}
    p0 = c.get("xyz") or (0.0, 0.0, 0.0)
    y0 = math.radians(c.get("yaw", 0.0))
    # UE: X forward, Y right, Z up; left of a heading yaw is (sin yaw, -cos yaw).
    left = (math.sin(y0), -math.cos(y0))
    d = (xy[0] - p0[0]) * left[0] + (xy[1] - p0[1]) * left[1]
    return d, wrap180(yaw - c.get("yaw", 0.0))


def shared_figures(samples, wheels, frame, t_ask, t_begin=None, source="trace"):
    """The shared events, times and figures of one crossing (see the module's docstring), as a record's `shared`
    group. samples: the crossing's trace (from at least CALIBRATE_S before the ask to its end); wheels: the robot's;
    frame: a Frame; t_ask: when it was asked for; t_begin: when its controller began to carry it out (None: the
    first active sample after the ask)."""
    samples = sorted((s for s in samples if isinstance(s.get("t"), (int, float))), key=lambda s: s["t"])
    out = {"version": SHARED_VERSION, "source": source, "across": False, "wheels": {}, "events": {}, "times": {},
           "speed": {}, "attitude": {}, "path": {}, "landing": {}}
    if not samples:
        return out
    steps = sorted(b["t"] - a["t"] for a, b in zip(samples, samples[1:]) if b["t"] > a["t"])
    out["resolution_s"] = rnd(steps[len(steps) // 2], 4) if steps else None
    if t_begin is None:
        t_begin = next((s["t"] for s in samples if s["t"] >= t_ask and s.get("phase") not in INACTIVE), None)
    i_done = next((i for i, s in enumerate(samples) if s["t"] >= t_ask and s.get("phase") == "DONE"), None)
    i_end = i_done if i_done is not None else next(
        (i for i, s in enumerate(samples) if s["t"] >= t_ask and s.get("phase") in TERMINAL), len(samples) - 1)
    t_done = samples[i_done]["t"] if i_done is not None else None
    t_end = samples[i_end]["t"]

    rest = rest_gaps(frame, samples, wheels, t_ask)
    counted = [k for k, (_, stood) in enumerate(rest) if stood]
    out["wheels"] = {"counted": [wheels[k]["name"] for k in counted],
                     "raised": [wheels[k]["name"] for k, (_, stood) in enumerate(rest) if not stood]}
    t_edge = t_edge_of(frame, samples, wheels, t_ask)
    t0 = max(t_edge, t_begin) if t_edge is not None and t_begin is not None else None

    i_settled = max(i for i, s in enumerate(samples) if s["t"] <= t_end + SETTLE_S + 1e-9)
    downs = {}
    for k in counted:
        downs[k] = down_time(frame, samples, k, wheels[k], rest[k][0] if rest[k][0] is not None else 0.0, i_settled)
    across = bool(counted) and all(downs[k] is not None for k in counted) and t0 is not None
    t_last_down = max(downs.values()) if across else None
    last_k = max(downs, key=lambda k: downs[k]) if across else None
    t_rest = t_rest_of(samples, t_last_down) if t_last_down is not None else None

    out["across"] = across
    out["events"] = {"t_ask": rnd(t_ask, 3), "t_begin": rnd(t_begin, 3), "t_edge": rnd(t_edge, 3), "t0": rnd(t0, 3),
                     "t_last_down": rnd(t_last_down, 3), "t_done": rnd(t_done, 3), "t_rest": rnd(t_rest, 3),
                     "t_end": rnd(t_end, 3), "last_down_wheel": wheels[last_k]["name"] if last_k is not None else None,
                     "down": {wheels[k]["name"]: rnd(v, 3) for k, v in downs.items()}}

    def since(t):
        return rnd(t - t0) if t is not None and t0 is not None else None

    out["times"] = {"edge_to_last_down_s": since(t_last_down) if across else None,
                    "edge_to_done_s": since(t_done) if across else None,
                    "edge_to_rest_s": since(t_rest) if across else None,
                    "edge_to_end_s": since(t_end),
                    "ask_to_edge_s": rnd(t_edge - t_ask) if t_edge is not None else None,
                    "planning_after_edge_s": rnd(max(0.0, t_begin - t_edge)) if t_edge is not None and t_begin is not None else None}

    ask = value_at(samples, t_ask, lambda s: _flat(s.get("chassis") or {}))
    sample_ask = {"chassis": _unflat(ask)} if ask else samples[0]
    cross_to = t_last_down if across else t_end
    a = span(samples, t0, cross_to)
    b = span(samples, t0, t_done) if t_done is not None else []
    if a:
        out["speed"] = speed_figures(a)
        along0 = frame.along(chassis_xy(a[0]))
        along1 = frame.along(chassis_xy(a[-1]))
        dt = a[-1]["t"] - a[0]["t"]
        out["speed"]["mean_cm_s"] = rnd((along1 - along0) / dt) if dt > 0 else None
    if b:
        sb = speed_figures(b, count_final_stop=False)
        out["speed"].update({"v_min_to_done_cm_s": sb["v_min_cm_s"], "stops_to_done": sb["stops"],
                             "stopped_to_done_s": sb["stopped_s"]})

    def final(t):
        if t is None:
            return None, None, None
        c = value_at(samples, t, chassis_attitude)
        st = value_at(samples, t, seat_attitude)
        return incl(*st), c[0], c[1]

    fd, fr = final(t_done), final(t_rest)
    att_ask = value_at(samples, t_ask, chassis_attitude)
    # The final attitude less the ask's, less what the surfaces explain (the end surface's tilt at the heading less the
    # start surface's): ~0 for a robot that ends as it stood.
    unexplained = (None, None)
    if fd[1] is not None and att_ask and hasattr(frame.plane_to, "tilt_deg"):
        yaw = (sample_ask.get("chassis") or {}).get("yaw", 0.0)
        tf, tt = frame.plane_from.tilt_deg(yaw), frame.plane_to.tilt_deg(yaw)
        unexplained = (fd[1] - att_ask[0] - (tt[0] - tf[0]), fd[2] - att_ask[1] - (tt[1] - tf[1]))
    seat_ask = value_at(samples, t_ask, seat_attitude)
    out["attitude"] = {
        "max_seat_incl_deg": rnd(max_incl(a, seat_attitude)) if a else None,
        "max_chassis_incl_deg": rnd(max_incl(a, chassis_attitude)) if a else None,
        "max_seat_incl_to_done_deg": rnd(max_incl(b, seat_attitude)) if b else None,
        "seat_tilt_rate_deg_s": rnd(tilt_rate_total(a, seat_attitude)) if a else None,
        "chassis_tilt_rate_deg_s": rnd(tilt_rate_total(a, chassis_attitude)) if a else None,
        "seat_tilt_rate_to_done_deg_s": rnd(tilt_rate_total(b, seat_attitude)) if b else None,
        "final_seat_incl_deg": rnd(fd[0]), "final_pitch_deg": rnd(fd[1]), "final_roll_deg": rnd(fd[2]),
        "rest_seat_incl_deg": rnd(fr[0]), "rest_pitch_deg": rnd(fr[1]), "rest_roll_deg": rnd(fr[2]),
        "ask_seat_incl_deg": rnd(incl(*seat_ask)) if seat_ask else None,
        "ask_pitch_deg": rnd(att_ask[0]) if att_ask else None, "ask_roll_deg": rnd(att_ask[1]) if att_ask else None,
        "final_pitch_change_deg": rnd(unexplained[0]), "final_roll_change_deg": rnd(unexplained[1]),
    }

    def path_at(t):
        if t is None:
            return None, None
        c = value_at(samples, t, lambda s: _flat(s.get("chassis") or {}))
        return drift(sample_ask, c[:2], c[4])

    pl, pd = path_at(t_last_down), path_at(t_done)
    out["path"] = {"drift_cm": rnd(pl[0], 1), "yaw_change_deg": rnd(pl[1]),
                   "drift_to_done_cm": rnd(pd[0], 1), "yaw_change_to_done_deg": rnd(pd[1])}

    landed = []
    for k, t in downs.items():
        if t is None:
            continue
        h = value_at(samples, t, lambda s, k=k: list(hub(s, k) or (0.0, 0.0, 0.0)))
        landed.append(frame.along(h) / wheels[k]["radius_cm"])
    out["landing"] = {"min_r": rnd(min(landed)) if landed else None}
    return out


# --- the rider ------------------------------------------------------------------------------------------------------

def quat_rotate(q, v):
    """v rotated by the unit quaternion q = (x, y, z, w)."""
    x, y, z, w = q
    # t = 2 * cross(q.xyz, v); v' = v + w * t + cross(q.xyz, t)
    tx = 2.0 * (y * v[2] - z * v[1])
    ty = 2.0 * (z * v[0] - x * v[2])
    tz = 2.0 * (x * v[1] - y * v[0])
    return (v[0] + w * tx + (y * tz - z * ty), v[1] + w * ty + (z * tx - x * tz), v[2] + w * tz + (x * ty - y * tx))


def imu_clock_offset(samples):
    """The world clock less the physics' (s): the median over the trace's samples of t - imu_t (the newest IMU sample
    read on that frame). The physics (MuJoCo) starts its clock some time after the world does, and its IMU samples
    carry its own; None without imu_t."""
    d = sorted(s["t"] - s["imu_t"] for s in samples if isinstance(s.get("imu_t"), (int, float)))
    return d[len(d) // 2] if d else None


def rider_figures(imu, t_a, t_b, tau=RIDER_TAU_S, offset=0.0):
    """The rider's acceleration over [t_a, t_b] from every physics step's IMU sample of the rider's body
    (URammsSensingBridge::ReadImuSamplesJson's samples, gathered over the crossing: sim_time, linear_acceleration in
    the sensor frame with gravity included, orientation {x, y, z, w}): rotated to the world, gravity taken off, two
    first-order low-passes of time constant tau by simulated time, then the peak and RMS (m/s^2) of its fore/aft
    (along the body's heading), vertical and total parts. offset: added to each sample's sim_time to put it on the
    trace's clock (imu_clock_offset). None without samples in the span."""
    seen, pts = set(), []
    for s in imu or []:
        if s.get("seq") in seen or not isinstance(s.get("sim_time"), (int, float)):
            continue
        seen.add(s.get("seq"))
        pts.append(s)
    pts.sort(key=lambda s: s["sim_time"])
    if len(pts) < 2 or t_a is None or t_b is None:
        return None
    f1 = f2 = None
    prev_t = None
    acc = {"fore_aft": [], "vertical": [], "total": []}
    for s in pts:
        o = s.get("orientation") or {}
        q = (o.get("x", 0.0), o.get("y", 0.0), o.get("z", 0.0), o.get("w", 1.0))
        la = s.get("linear_acceleration") or {}
        a_s = (la.get("x", 0.0), la.get("y", 0.0), la.get("z", 0.0)) if isinstance(la, dict) else tuple(la[:3])
        a = quat_rotate(q, a_s)
        a = (a[0], a[1], a[2] - GRAVITY_CM_S2)
        fwd = quat_rotate(q, (1.0, 0.0, 0.0))
        h = unit2(fwd[:2])
        t = s["sim_time"] + offset
        if f1 is None:
            f1 = f2 = list(a)
        else:
            alpha = 1.0 - math.exp(-max(0.0, t - prev_t) / tau)
            f1 = [x + alpha * (y - x) for x, y in zip(f1, a)]
            f2 = [x + alpha * (y - x) for x, y in zip(f2, f1)]
        prev_t = t
        if t_a <= t <= t_b:
            fore = (f2[0] * h[0] + f2[1] * h[1]) / 100.0
            acc["fore_aft"].append(fore)
            acc["vertical"].append(f2[2] / 100.0)
            acc["total"].append(math.sqrt(f2[0] ** 2 + f2[1] ** 2 + f2[2] ** 2) / 100.0)
    if not acc["total"]:
        return None
    out = {"samples": len(acc["total"]), "clock_offset_s": rnd(offset, 4)}
    for k, xs in acc.items():
        out["peak_%s_m_s2" % k] = rnd(max(abs(x) for x in xs), 3)
        out["rms_%s_m_s2" % k] = rnd(math.sqrt(sum(x * x for x in xs) / len(xs)), 3)
    return out
