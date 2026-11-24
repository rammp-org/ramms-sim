"""A level-assist course run: a course map, where the robot starts, which way it goes, how hard the stick is held, and
what happens on the way (run_level.py makes these, runner_op.py's begin_course carries them out, level_measures.py
scores them). Plain CPython, only the standard library and ../level_maps/level_terrain.py -- runner_op.py loads this
file inside the editor too, for the event schedule and the heading hold, so both are tested without one.

The timeline of a run, by the physics' own clock:

    SETUP_AT_S   the robot's standard setup (its adapter's prepare)
    GATE_AT_S    the steady gate (at rest: runner_op.Steady); once it passes (at most STEADY_MAX_WAIT_S later) the
                 run's zero is taken (the rider's seat against the chassis, the lifts) and the events timed before the
                 start are armed
    + SETTLE_S   "go" (t = 0 of the events): the stick is held from here, steered by the hold
    ...          until the robot's reference point is `end_d` cm along the path (or `end_t` s after go, for a run that
                 stays where it is), then the stick is let go
    + POST_S     at rest: the trace is written

Events, a list in order, each {"label", "do", ...} with one of
    "t": seconds from go (negative: before it, not earlier than -SETTLE_S),
    "d": centimetres along the path from the start,
    "after": seconds after the event before it in the list fired;
and "do" one of
    "assist"  {"value": 0 | 1}            level.assist
    "pref"    {"pitch", "roll"}           level.pref.pitch / level.pref.roll (deg)
    "mode"    {"id"}                      the drive mode selector's SetActiveMode
    "stop" / "go"                         the stick let go / held again
    "stick"   {"value"}                   the stick's value from here
    "set"     {"id", "value"}             any control, source Script
An event fires once, on the first frame at or past its time or distance.

The hold (optional): a small heading and cross-track loop on drive.turn that keeps the robot on its path, so a run
with the assist on and one with it off cover the same ground. It hides nothing: the turn it asks for, the heading
error and the cross-track error are in every sample of the trace, and a run with the hold off shows what the robot
does by itself.
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_MAPS = os.path.normpath(os.path.join(HERE, "..", "level_maps"))
if _MAPS not in sys.path:
    sys.path.insert(0, _MAPS)
import level_terrain as lt  # noqa: E402

SETUP_AT_S = 1.0
GATE_AT_S = 3.0
SETTLE_S = 6.0
POST_S = 4.0
STOP_S = 3.0  # a stop-and-go's stop
MODE_STAY_S = 6.0  # how long a mode switch is stayed in
PARK_HOLD_S = 30.0
PARK_TAIL_S = 6.0  # after the assist is switched off at the end of a parked run
TIMEOUT_FACTOR = 2.5  # of the time the path takes at the stick's nominal speed
TIMEOUT_MIN_S = 30.0
YAW_RATE_TAU_S = 0.25  # the heading rate the hold damps on is smoothed over this long
LANE_GUARD_CM = 25.0  # a robot this close to the lane's side has left it: the run ends there
MIN_SLOPE_DEG = 0.5  # a segment at least this steep is a slope (where the on-the-way events go)

VARIANTS = ("drive", "toggle", "pref_step", "stop_go", "mode", "parked")
LEVELS = ("on", "off")
HOLD_DEFAULT = {"on": True, "k_yaw": 0.02, "k_xt": 0.004, "k_rate": 0.0, "deadzone": 0.0, "max_turn": 0.3, "turn_sign": 1.0}
DO = ("assist", "pref", "mode", "stop", "go", "stick", "set")


def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


def path_coords(origin, path_yaw, x, y, yaw):
    """(d, cross-track, heading error): how far (x, y) is along the path from its origin (cm), how far to the path's
    right (cm; UE: +Y is the right of +X), and how far the heading yaw is clockwise of the path's (deg)."""
    c, s = math.cos(math.radians(path_yaw)), math.sin(math.radians(path_yaw))
    dx, dy = x - origin[0], y - origin[1]
    return dx * c + dy * s, -dx * s + dy * c, wrap180(yaw - path_yaw)


def steer(hold, xtrack_cm, yaw_err_deg, stick, yaw_rate_deg_s=0.0):
    """The hold's drive.turn for a cross-track and a heading error, the stick held at `stick`: 0 with the hold off or
    the stick let go; a turn back toward the path (turn_sign: +1 where a positive drive.turn turns the robot
    clockwise from above, as RammsCore's differential drive does), within max_turn. k_rate (0 by default) damps on
    the heading's own rate (deg/s, clockwise positive), for a robot whose turn answers the stick late: without it
    such a robot weaves about its path. deadzone (0 by default): the drive's own stick dead zone, which the turn asked
    for is carried over (a drive that takes nothing under 0.05 and rescales the rest never sees the hold's small
    turns otherwise, and the robot wanders inside that band)."""
    if not hold or not hold.get("on") or abs(stick) < 1e-9:
        return 0.0
    u = -(hold["k_yaw"] * yaw_err_deg + hold.get("k_rate", 0.0) * yaw_rate_deg_s
          + hold["k_xt"] * xtrack_cm * (1.0 if stick > 0.0 else -1.0))
    u *= hold.get("turn_sign", 1.0)
    dz = hold.get("deadzone", 0.0)
    if dz > 0.0 and abs(u) > 1e-6:
        u = math.copysign(dz + abs(u) * (1.0 - dz), u)
    return max(-hold["max_turn"], min(hold["max_turn"], u))


def check_events(events, settle_s=SETTLE_S):
    """Raise ValueError for an event list the schedule cannot carry out."""
    for i, e in enumerate(events):
        keys = [k for k in ("t", "d", "after") if k in e]
        if len(keys) != 1:
            raise ValueError("event %d (%s) needs exactly one of t, d, after" % (i, e.get("label")))
        if e.get("do") not in DO:
            raise ValueError("event %d: do is one of %s, not %r" % (i, ", ".join(DO), e.get("do")))
        if "after" in e and i == 0:
            raise ValueError("the first event has none before it to be after")
        if "t" in e and e["t"] < -settle_s - 1e-9:
            raise ValueError("event %d is timed before the steady gate (%s s before go; at most %s)" % (i, -e["t"], settle_s))
        if e["do"] == "pref" and not ("pitch" in e and "roll" in e):
            raise ValueError("event %d: a preference needs pitch and roll" % i)
        if e["do"] in ("assist", "stick") and "value" not in e:
            raise ValueError("event %d: %s needs a value" % (i, e["do"]))
        if e["do"] == "mode" and not e.get("id"):
            raise ValueError("event %d: a mode switch needs the mode's id" % i)
        if e["do"] == "set" and not (e.get("id") and "value" in e):
            raise ValueError("event %d: set needs an id and a value" % i)


class Schedule(object):
    """Which events are due: due(t, d) gives those to fire now, in the list's order, each once. t: seconds from go;
    d: centimetres along the path (None before the robot is placed)."""

    def __init__(self, events, settle_s=SETTLE_S):
        check_events(events, settle_s)
        self.events = [dict(e) for e in events]
        self.fired = [None] * len(self.events)  # the t each fired at

    def due(self, t, d=None):
        out = []
        for i, e in enumerate(self.events):
            if self.fired[i] is not None:
                continue
            if "t" in e:
                ready = t >= e["t"] - 1e-9
            elif "d" in e:
                ready = d is not None and d >= e["d"] - 1e-9
            else:
                prev = self.fired[i - 1]
                ready = prev is not None and t >= prev + e["after"] - 1e-9
            if ready:
                self.fired[i] = t
                out.append(e)
        return out

    def pending(self):
        return [e for e, f in zip(self.events, self.fired) if f is None]


def slopes(profile):
    """A path profile's sloped segments (level_terrain.Layout.profile), in the order the path meets them."""
    return [s for s in profile["segments"] if s["slope"] >= MIN_SLOPE_DEG]


def _mid(seg, frac=0.5):
    return seg["d0"] + frac * (seg["d1"] - seg["d0"])


def events_for(variant, level, pref, profile, alt_mode=None, pref_step=(3.0, -2.0), settle_s=SETTLE_S):
    """A variant's events for one case. level: "on" | "off"; pref: (pitch, roll) deg, the rider's preference for the
    run, set at the gate whatever the level (the run with the assist off is scored against the same preference).

        drive      the assist on (or left off) at the gate; drive to the end
        toggle     the assist off at the start; on halfway along the first slope, off halfway along the last one (or
                   at 4/5 of the only one); with level "off": as drive
        pref_step  as drive, and the preference stepped to pref_step halfway along the first slope and back halfway
                   along the last one (or at 4/5 of the only one)
        stop_go    as drive, with a stop of STOP_S halfway along every slope
        mode       as drive; a stop halfway along the first slope, a switch to alt_mode, MODE_STAY_S later a switch
                   back, MODE_STAY_S later on again
        parked     no driving: the assist on at the gate, held PARK_HOLD_S (a switch to alt_mode and back at a third
                   and two thirds of it, when there is one), then off; the run ends PARK_TAIL_S later
    """
    if variant not in VARIANTS:
        raise ValueError("a variant is one of %s, not %r" % (", ".join(VARIANTS), variant))
    on = level == "on"
    ev = [{"t": -settle_s, "do": "pref", "pitch": float(pref[0]), "roll": float(pref[1]), "label": "preference %+g, %+g" % tuple(pref)}]
    sl = slopes(profile)
    first = sl[0] if sl else None
    last = sl[-1] if sl else None
    d_first = _mid(first) if first else 0.4 * profile["length"]
    d_last = (_mid(last) if last is not first else _mid(first, 0.8)) if first else 0.7 * profile["length"]
    if variant == "toggle" and on:
        ev.append({"d": d_first, "do": "assist", "value": 1, "label": "assist on"})
        ev.append({"d": d_last, "do": "assist", "value": 0, "label": "assist off"})
        return ev
    if on:
        ev.append({"t": -settle_s, "do": "assist", "value": 1, "label": "assist on"})
    if variant == "pref_step":
        ev.append({"d": d_first, "do": "pref", "pitch": float(pref_step[0]), "roll": float(pref_step[1]),
                   "label": "preference %+g, %+g" % tuple(pref_step)})
        ev.append({"d": d_last, "do": "pref", "pitch": float(pref[0]), "roll": float(pref[1]),
                   "label": "preference %+g, %+g" % tuple(pref)})
    elif variant == "stop_go":
        for s in (sl or [None]):
            ev.append({"d": _mid(s) if s else 0.5 * profile["length"], "do": "stop", "label": "stop"})
            ev.append({"after": STOP_S, "do": "go", "label": "go"})
    elif variant == "mode":
        if not alt_mode:
            raise ValueError("the mode variant needs the robot's other drive mode (its profile's level alt_mode)")
        ev.append({"d": d_first, "do": "stop", "label": "stop"})
        ev.append({"after": 1.5, "do": "mode", "id": alt_mode[1], "label": "mode " + alt_mode[1]})
        ev.append({"after": MODE_STAY_S, "do": "mode", "id": alt_mode[0], "label": "mode " + alt_mode[0]})
        ev.append({"after": MODE_STAY_S, "do": "go", "label": "go"})
    elif variant == "parked":
        if alt_mode:
            ev.append({"t": PARK_HOLD_S / 3.0, "do": "mode", "id": alt_mode[1], "label": "mode " + alt_mode[1]})
            ev.append({"t": 2.0 * PARK_HOLD_S / 3.0, "do": "mode", "id": alt_mode[0], "label": "mode " + alt_mode[0]})
        if on:
            ev.append({"t": PARK_HOLD_S, "do": "assist", "value": 0, "label": "assist off"})
    return ev


def plan(course_id, direction="fwd", start="centre", level="off", pref=(0.0, 0.0), stick=1.0, variant="drive",
         hold=None, footprint=None, speed_cm_s=60.0, alt_mode=None, pref_step=(3.0, -2.0), events=None):
    """Everything a session needs for one case: {"course", "map", "dir", "start": the start's pose and path
    (level_terrain.Layout.start), "path": {"origin", "yaw", "length"}, "lane_half", "level", "pref", "stick",
    "variant", "hold", "events", "end": {"d"} or {"t"}, "settle_s", "post_s", "timeout_sim_s", "profile": the ground
    along the path (level_terrain.Layout.profile, for `footprint` or the stand-in one)}. alt_mode: (the mode the
    robot drives in, its other mode), for the variants that switch. events: your own, in place of the variant's."""
    if level not in LEVELS:
        raise ValueError("level is on or off, not %r" % level)
    L = lt.layout(course_id)
    st = L.start(start, direction)
    prof = L.profile(st, footprint or lt.REF_FOOTPRINT)
    ev = list(events) if events is not None else events_for(variant, level, pref, prof, alt_mode, pref_step)
    check_events(ev)
    h = dict(HOLD_DEFAULT)
    h.update(hold or {})
    parked = variant == "parked"
    if parked:
        end = {"t": PARK_HOLD_S + PARK_TAIL_S}
        drive_s = end["t"]
    else:
        end = {"d": st["length"]}
        drive_s = st["length"] / max(1.0, abs(speed_cm_s))
        drive_s += sum(e.get("after", 0.0) for e in ev)
    return {"course": course_id, "map": lt.map_path(course_id), "dir": direction, "start": st,
            "path": {"origin": st["origin"], "yaw": st["path_yaw"], "length": st["length"]},
            "lane_half": L.half, "level": level, "pref": [float(pref[0]), float(pref[1])],
            "stick": 0.0 if parked else float(stick), "variant": variant, "hold": h, "events": ev, "end": end,
            "setup_at_s": SETUP_AT_S, "gate_at_s": GATE_AT_S, "settle_s": SETTLE_S, "post_s": POST_S,
            "timeout_sim_s": GATE_AT_S + 5.0 + SETTLE_S + max(TIMEOUT_MIN_S, TIMEOUT_FACTOR * drive_s) + POST_S,
            "profile": prof}


def case_name(course_id, direction, start, variant, level, pref, stick, hold_on=True):
    """A case's name, as its files are called: FLAT_fwd_centre_drive_p+0+0_s1.00_on (and _nohold with the hold off)."""
    return "%s_%s_%s_%s_p%+g%+g_s%.2f%s_%s" % (course_id, direction, start, variant, pref[0], pref[1], stick,
                                               "" if hold_on else "_nohold", level)


def pair_key(row):
    """What an on run and an off run share when they are a pair: everything but the level."""
    return (row.get("course"), row.get("dir"), row.get("start"), row.get("variant"), tuple(row.get("pref") or (0.0, 0.0)),
            row.get("stick"), bool((row.get("hold") or {}).get("on")), row.get("rep", 1))
