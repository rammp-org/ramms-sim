"""course.py and level_measures.py on synthetic traces with known answers (no editor; nothing written).

    python -I Scripts/curb_runner/tests/test_level_measures.py
"""

import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import course  # noqa: E402
import level_measures as lm  # noqa: E402

lt = course.lt
DT = 0.0625
RADIUS = 10.0
FOOT = ((30.0, 30.0), (30.0, -30.0), (-30.0, 30.0), (-30.0, -30.0))  # FL(right), FR.., in (ahead, right)
WHEELS = [{"name": n, "radius_cm": RADIUS} for n in ("front_r", "front_l", "rear_r", "rear_l")]
LEVEL_PROF = {"drive_wheels": ["rear_r", "rear_l"], "rider_offset_deg": None}
MOUNT = (1.0, 0.0)  # the seat stands 1 deg nose up on its chassis


def rotator(pitch, roll_up, yaw):
    """A UE rotator for an attitude in the level convention (roll with the right side up)."""
    s = math.sin(math.radians(roll_up)) / math.cos(math.radians(pitch))
    return {"pitch": pitch, "yaw": yaw, "roll": -math.degrees(math.asin(s))}


def synth(course_id, level="off", pref=(0.0, 0.0), speed=60.0, tau=0.4, direction="fwd", start="centre", variant="drive",
          events=None, yaw_per_s=0.0, hunt_cm=0.0, float_at=None, turn=0.0, alt_mode=None, margin_shift=0.0):
    """A run as begin_course would trace it, of a made-up robot: its reference point goes along the path at `speed`
    from go (stopping where a "stop" says so), its wheels follow the ground, and its chassis is the ground's attitude
    with the assist off; with it on, the preference plus what is left of a first-order chase (time constant tau) of
    the ground and of the preference. The seat rides the chassis MOUNT above it."""
    plan = course.plan(course_id, direction, start, level, pref, 1.0, variant, alt_mode=alt_mode, events=events, footprint=FOOT)
    L = lt.layout(course_id)
    sched = course.Schedule(plan["events"], plan["settle_s"])
    gate_t = plan["gate_at_s"]
    go_t = gate_t + plan["settle_s"]
    yaw0 = plan["path"]["yaw"]
    h = (math.cos(math.radians(yaw0)), math.sin(math.radians(yaw0)))
    o = plan["path"]["origin"]
    samples, fired = [], []
    d, assist, asked, moving, mode = 0.0, 0, [0.0, 0.0], True, "differential"
    corr = None  # what the legs have taken out: chases (ground - preference) while the assist is on, 0 while off
    t, end_t = 1.0, None
    while True:
        t_rel = t - go_t
        yaw = yaw0 + yaw_per_s * max(0.0, t_rel)
        c = (o[0] + h[0] * d, o[1] + h[1] * d)
        pts = lt.footprint_at(c, yaw0, FOOT)
        # As a session's frame goes: the robot's state is what the last frame's commands made it; the events due
        # this frame fire after it is read, and the sample carries the preference as asked from here on.
        g = L.ground_attitude(pts, yaw0)
        want = (g[0] - asked[0], g[1] - asked[1]) if assist else (0.0, 0.0)
        if corr is None:
            corr = list(want)
        else:
            a = 1.0 - math.exp(-DT / tau)
            corr = [x + a * (y - x) for x, y in zip(corr, want)]
        if t >= gate_t:
            for e in sched.due(t_rel, d if t_rel >= 0.0 else None):
                rec = dict(e, t=t, d=d)
                if e["do"] == "assist":
                    assist = int(e["value"])
                elif e["do"] == "pref":
                    asked = [e["pitch"], e["roll"]]
                elif e["do"] == "stop":
                    moving = False
                elif e["do"] == "go":
                    moving = True
                elif e["do"] == "mode":
                    mode = e["id"]
                fired.append(rec)
        ch = (g[0] - corr[0], g[1] - corr[1])
        z = L.surface_z(*c)
        hubs = []
        for k, p in enumerate(pts):
            hz = L.surface_z(*p) + RADIUS + (hunt_cm * math.sin(2.0 * math.pi * t) if k == 0 else 0.0)
            hubs.append([p[0], p[1], hz])
        n = {w["name"]: 100.0 for w in WHEELS}
        if float_at and float_at[0] <= t < float_at[1]:
            n["rear_r"] = None
        com = [c[0] + margin_shift * h[0], c[1] + margin_shift * h[1]]
        s = {"t": round(t, 5), "chassis": dict(rotator(ch[0], ch[1], yaw), xyz=[c[0], c[1], z + 30.0]),
             "seat": {k: v for k, v in rotator(ch[0] + MOUNT[0], ch[1] + MOUNT[1], yaw).items() if k != "yaw"},
             "wheels": hubs, "pref": list(asked), "stick": [1.0 if (t_rel >= 0.0 and moving and end_t is None) else 0.0, turn],
             "steer": {"xt": 0.0, "yaw_err": yaw - yaw0}, "mode": mode,
             "level": {"assist": assist, "state": 1 if assist else 0, "tilt": math.hypot(*ch), "reach": 0.6 if assist else 1.0,
                       "speed_scale": 1.0, "status": "Levelling" if assist else "Off"},
             "cmd": {"leg": [0.1, (corr[0] + corr[1]) * 0.01, 0.1 + (corr[0] + corr[1]) * 0.01]},
             "ground": {"n": n, "others": 0.0, "com": com, "pts": {w["name"]: [p[0], p[1]] for w, p in zip(WHEELS, pts)}}}
        samples.append(s)
        if end_t is None:
            if "d" in plan["end"] and d >= plan["end"]["d"]:
                end_t = t
            elif "t" in plan["end"] and t_rel >= plan["end"]["t"]:
                end_t = t
        elif t >= end_t + plan["post_s"]:
            break
        if t_rel >= 0.0 and moving and end_t is None and "d" in plan["end"]:
            d += speed * DT
        t += DT
        if t > 900.0:
            raise AssertionError("the made-up run never ended (a stop without its go?)")
    return {"kind": "course", "cfg": {"plan": plan, "wheels": WHEELS}, "samples": samples, "events": fired, "go_t": go_t,
            "gate": {"t": gate_t, "rider_zero": list(MOUNT)}, "end": {"t": end_t, "why": "end line"}, "clock": "physics"}


def figs(*a, **k):
    return lm.figures(synth(*a, **k), LEVEL_PROF)


class Schedules(unittest.TestCase):
    def test_each_event_once_in_order(self):
        s = course.Schedule([{"t": -6.0, "do": "assist", "value": 1}, {"d": 100.0, "do": "stop"}, {"after": 3.0, "do": "go"},
                             {"t": 2.0, "do": "pref", "pitch": 1.0, "roll": 0.0}])
        self.assertEqual([e["do"] for e in s.due(-6.0)], ["assist"])
        self.assertEqual(s.due(-5.9), [])
        self.assertEqual([e["do"] for e in s.due(2.0, 50.0)], ["pref"])
        self.assertEqual([e["do"] for e in s.due(4.0, 100.0)], ["stop"])
        self.assertEqual(s.due(6.9, 100.0), [])  # 3 s after the stop fired, not yet
        self.assertEqual([e["do"] for e in s.due(7.0, 100.0)], ["go"])
        self.assertEqual(s.due(99.0, 999.0), [])
        self.assertEqual(s.pending(), [])

    def test_a_distance_event_waits_for_the_robot(self):
        s = course.Schedule([{"d": 0.0, "do": "stop"}])
        self.assertEqual(s.due(-1.0, None), [])  # no distance before the run is under way
        self.assertEqual(len(s.due(0.0, 0.0)), 1)

    def test_bad_events_are_refused(self):
        for ev in ([{"do": "stop"}], [{"t": 0.0, "d": 1.0, "do": "stop"}], [{"after": 1.0, "do": "go"}],
                   [{"t": -7.0, "do": "assist", "value": 1}], [{"t": 0.0, "do": "fly"}], [{"t": 0.0, "do": "pref", "pitch": 1.0}],
                   [{"t": 0.0, "do": "mode"}], [{"t": 0.0, "do": "assist"}]):
            with self.assertRaises(ValueError):
                course.Schedule(ev)

    def test_variants(self):
        L = lt.layout("RAMP5")
        prof = L.profile(L.start("centre", "fwd"))
        on = course.events_for("drive", "on", (0.0, 0.0), prof)
        self.assertEqual([(e["do"], e.get("t")) for e in on], [("pref", -6.0), ("assist", -6.0)])
        self.assertEqual([e["do"] for e in course.events_for("drive", "off", (0.0, 0.0), prof)], ["pref"])
        tg = course.events_for("toggle", "on", (0.0, 0.0), prof)
        up, down = prof["segments"][1], prof["segments"][3]
        self.assertAlmostEqual(tg[1]["d"], 0.5 * (up["d0"] + up["d1"]))  # on halfway up the first slope
        self.assertAlmostEqual(tg[2]["d"], 0.5 * (down["d0"] + down["d1"]))  # off halfway down the last
        self.assertEqual([e.get("value") for e in tg[1:]], [1, 0])
        self.assertEqual([e["do"] for e in course.events_for("toggle", "off", (0.0, 0.0), prof)], ["pref"])  # a baseline
        sg = course.events_for("stop_go", "on", (0.0, 0.0), prof)
        self.assertEqual([e["do"] for e in sg], ["pref", "assist", "stop", "go", "stop", "go"])
        with self.assertRaises(ValueError):
            course.events_for("mode", "on", (0.0, 0.0), prof)
        md = course.events_for("mode", "on", (0.0, 0.0), prof, alt_mode=("differential", "holonomic"))
        self.assertEqual([e.get("id") for e in md if e["do"] == "mode"], ["holonomic", "differential"])
        pk = course.events_for("parked", "on", (3.0, -2.0), prof)
        self.assertEqual((pk[0]["pitch"], pk[0]["roll"]), (3.0, -2.0))
        self.assertEqual(pk[-1], {"t": course.PARK_HOLD_S, "do": "assist", "value": 0, "label": "assist off"})

    def test_plan(self):
        p = course.plan("RAMP5", "rev", "left20", "on", (0.0, 0.0), 0.5)
        self.assertEqual(p["map"], "/Game/Maps/Level/Map_Level_RAMP5_URL")
        self.assertEqual(p["path"]["yaw"], 180.0)
        self.assertEqual(p["end"], {"d": p["start"]["length"]})
        self.assertGreater(p["timeout_sim_s"], p["start"]["length"] / 60.0 + course.SETTLE_S)
        q = course.plan("PARK", "fwd", "pad_cross", "on", (0.0, 0.0), 1.0, "parked")
        self.assertEqual(q["stick"], 0.0)
        self.assertEqual(q["end"], {"t": course.PARK_HOLD_S + course.PARK_TAIL_S})
        self.assertEqual(course.case_name("FLAT", "fwd", "centre", "drive", "on", (3.0, -2.0), 1.0), "FLAT_fwd_centre_drive_p+3-2_s1.00_on")


class Hold(unittest.TestCase):
    def test_path_coords(self):
        d, xt, ye = course.path_coords((100.0, 0.0), 0.0, 150.0, 20.0, 5.0)
        self.assertEqual((d, xt, ye), (50.0, 20.0, 5.0))  # +Y is the right of +X
        d, xt, ye = course.path_coords((100.0, 0.0), 180.0, 50.0, 20.0, -175.0)
        self.assertAlmostEqual(d, 50.0)
        self.assertAlmostEqual(xt, -20.0)  # heading -X, +Y is the left
        self.assertAlmostEqual(ye, 5.0)

    def test_steer_turns_back(self):
        h = dict(course.HOLD_DEFAULT)
        self.assertLess(course.steer(h, 0.0, 5.0, 1.0), 0.0)  # pointing right of the path: turn left
        self.assertLess(course.steer(h, 20.0, 0.0, 1.0), 0.0)  # right of the path: turn left
        self.assertGreater(course.steer(h, -20.0, 0.0, 1.0), 0.0)
        self.assertGreater(course.steer(h, 20.0, 0.0, -1.0), 0.0)  # reversing, the cross-track term turns the other way
        self.assertEqual(course.steer(h, 500.0, 90.0, 1.0), -h["max_turn"])
        self.assertEqual(course.steer(h, 20.0, 5.0, 0.0), 0.0)  # the stick let go
        self.assertEqual(course.steer(dict(h, on=False), 20.0, 5.0, 1.0), 0.0)
        self.assertGreater(course.steer(dict(h, turn_sign=-1.0), 0.0, 5.0, 1.0), 0.0)

    def test_the_hold_converges(self):
        # A unicycle at 60 cm/s whose full turn stick is 60 deg/s, started 20 cm off and 5 deg out, with a steady pull
        # to one side (a cross slope's): the hold brings it back and what is left shows as steering effort.
        h = dict(course.HOLD_DEFAULT)
        for rate, pull in ((60.0, 0.0), (90.0, 0.0), (60.0, 3.0)):
            xt, yaw = 20.0, 5.0
            for _ in range(int(20.0 / DT)):
                u = course.steer(h, xt, yaw, 1.0)
                yaw += (rate * u + pull) * DT
                xt += 60.0 * math.sin(math.radians(yaw)) * DT
            self.assertLess(abs(yaw), 0.6, (rate, pull))
            self.assertLess(abs(xt), 16.0, (rate, pull))
            if pull:
                self.assertAlmostEqual(u, -pull / rate, places=2)  # the effort that cancels the pull


class Small(unittest.TestCase):
    def test_att(self):
        self.assertEqual(lm.att({"pitch": 3.0, "roll": 0.0}), (3.0, 0.0))
        p, r = lm.att({"pitch": 0.0, "roll": -4.0})  # a UE roll is positive with the right side down
        self.assertAlmostEqual(r, 4.0)
        p, r = lm.att(rotator(5.0, 3.0, 40.0))
        self.assertAlmostEqual(p, 5.0)
        self.assertAlmostEqual(r, 3.0, places=9)
        self.assertIsNone(lm.att(None))

    def test_hull_margin(self):
        sq = [(-30, -30), (30, -30), (30, 30), (-30, 30)]
        self.assertAlmostEqual(lm.hull_margin(sq, (0, 0)), 30.0)
        self.assertAlmostEqual(lm.hull_margin(sq, (20, 0)), 10.0)
        self.assertAlmostEqual(lm.hull_margin(sq, (40, 0)), -10.0)
        self.assertAlmostEqual(lm.hull_margin(sq + [(0, 0)], (20, 0)), 10.0)  # a point inside changes nothing
        tri = [(-30, -30), (30, -30), (0, 30)]  # three points: nearer an edge
        self.assertLess(lm.hull_margin(tri, (0, 0)), 30.0)
        self.assertGreater(lm.hull_margin(tri, (0, 0)), 0.0)
        self.assertAlmostEqual(lm.hull_margin([(-30, 0), (30, 0)], (0, 5)), -5.0)
        self.assertIsNone(lm.hull_margin([(0, 0)], (0, 0)))

    def rows(self, f, n=200):
        return [{"t": i * 0.05, "re": f(i * 0.05)} for i in range(n)]

    def test_settle_and_time_over(self):
        rows = self.rows(lambda t: 4.0 * math.exp(-t / 0.5))
        # 4 e^(-t / 0.5) is last over 0.5 deg at t = 0.5 ln 8 = 1.04 s, and over 1 deg until 0.5 ln 4 = 0.69 s.
        self.assertAlmostEqual(lm.settle(rows, "re", 0.5, 0.0), 0.5 * math.log(8.0), delta=0.05)
        self.assertAlmostEqual(lm.time_over(rows, "re", 1.0), 0.5 * math.log(4.0), delta=0.05)
        self.assertEqual(lm.settle(self.rows(lambda t: 0.2), "re", 0.5, 0.0), 0.0)  # never out
        self.assertIsNone(lm.settle(self.rows(lambda t: 2.0), "re", 0.5, 0.0))  # still out at the end

    def test_rate_peak(self):
        rows = [{"t": i * DT, "p": min(3.0 * i * DT, 3.0), "r": 0.0} for i in range(80)]  # 3 deg/s for 1 s, then still
        self.assertAlmostEqual(lm.rate_peak(rows, "p", "r"), 3.0, places=6)
        both = [{"t": i * DT, "p": 3.0 * i * DT, "r": -4.0 * i * DT} for i in range(40)]
        self.assertAlmostEqual(lm.rate_peak(both, "p", "r"), 5.0, places=6)  # pitch and roll together
        self.assertIsNone(lm.rate_peak(rows[:3], "p", "r"))

    def test_time_at_d(self):
        rows = [{"t": float(i), "d": 10.0 * i} for i in range(10)]
        self.assertAlmostEqual(lm.time_at_d(rows, 25.0), 2.5)
        self.assertIsNone(lm.time_at_d(rows, 500.0))
        self.assertAlmostEqual(lm.time_at_d(rows, 5.0, t_from=3.0), 3.0)


class OnOff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.off = figs("TRANSITIONS", "off")
        cls.on = figs("TRANSITIONS", "on")

    def test_segments_follow_the_course(self):
        names = [s["name"] for s in self.off["segments"]]
        self.assertEqual(names, ["in", "up", "top", "fall_left", "fall_right", "down_cross", "out"])
        self.assertEqual(len([t for t in self.off["transitions"] if t["kind"] == "seam"]), 6)

    def test_off_the_rider_has_the_slope(self):
        by = {s["name"]: s for s in self.off["segments"]}
        self.assertAlmostEqual(by["up"]["rider_residual_deg"], 5.0, delta=0.02)
        self.assertAlmostEqual(by["up"]["rider_mean_deg"][0], 5.0, delta=0.02)  # nose up
        self.assertAlmostEqual(by["fall_left"]["rider_mean_deg"][1], 4.0, delta=0.02)  # the right side up
        self.assertAlmostEqual(by["fall_right"]["rider_mean_deg"][1], -4.0, delta=0.02)
        self.assertAlmostEqual(by["down_cross"]["rider_rms_deg"], math.hypot(5.0, 4.0), delta=0.05)
        self.assertAlmostEqual(by["top"]["rider_residual_deg"], 0.0, delta=0.01)
        # Against the ground's own attitude it is nowhere off: it follows the ground.
        for s in self.off["segments"]:
            self.assertAlmostEqual(s["rider_off_ground_deg"][0], 0.0, delta=0.01)
            self.assertAlmostEqual(s["rider_off_ground_deg"][1], 0.0, delta=0.01)
        self.assertAlmostEqual(by["up"]["ground_seen_deg"][0], 5.0, delta=0.01)
        self.assertAlmostEqual(by["up"]["ground_pitch_deg"], 5.0, delta=0.01)

    def test_on_the_rider_is_level_once_steady(self):
        for s in self.on["segments"]:
            self.assertLess(s["rider_residual_deg"], 0.02, s["name"])
        by = {s["name"]: s for s in self.on["segments"]}
        # And the ground's attitude is what the legs took out.
        self.assertAlmostEqual(by["fall_left"]["chassis_off_ground_deg"][1], -4.0, delta=0.2)

    def test_the_rider_is_the_seat_less_its_mount(self):
        # The seat stands 1 deg over the chassis: the rider's and the chassis's errors are the same.
        self.assertAlmostEqual(self.off["overall"]["rider_rms_deg"], self.off["overall"]["chassis_rms_deg"], places=2)
        t = synth("TRANSITIONS", "off")
        del t["gate"]["rider_zero"]
        raw = lm.figures(t, LEVEL_PROF)
        self.assertAlmostEqual(raw["segments"][2]["rider_mean_deg"][0], 1.0, delta=0.02)  # without its zero it reads the mount
        fixed = lm.figures(t, dict(LEVEL_PROF, rider_offset_deg=[1.0, 0.0]))  # the profile's own offset
        self.assertAlmostEqual(fixed["segments"][2]["rider_mean_deg"][0], 0.0, delta=0.02)

    def test_transitions(self):
        seams_on = [t for t in self.on["transitions"] if t["kind"] == "seam"]
        seams_off = [t for t in self.off["transitions"] if t["kind"] == "seam"]
        for a, b in zip(seams_on, seams_off):
            self.assertEqual(a["label"], b["label"])
            self.assertLess(a["rider_peak_deg"], b["rider_peak_deg"])  # the chase is behind, never as far as the ground
            self.assertGreater(a["rider_peak_deg"], 0.3)
            self.assertIsNotNone(a["settle_s"])
            self.assertLess(a["settle_after_exit_s"], 2.0)
        first = seams_on[0]  # flat -> 5 deg: one wheelbase long at 60 cm/s
        self.assertEqual(first["label"], "in -> up")
        self.assertAlmostEqual(first["pitch_change_deg"], 5.0, delta=0.01)
        self.assertAlmostEqual(first["ground_rate_deg_s"], 5.0, delta=0.6)  # 5 deg over 60 cm at 60 cm/s
        self.assertAlmostEqual(seams_off[0]["rider_rate_deg_s"], first["ground_rate_deg_s"], delta=0.01)
        # Off, the rider goes to the slope and stays out: never settled, outside 1 deg most of the window.
        self.assertIsNone(seams_off[0]["settle_s"])
        self.assertGreater(seams_off[0]["rider_outside_s"], 3.0)

    def test_pair(self):
        p = lm.pair(self.on, self.off)
        self.assertLess(p["rejection"], 0.25)
        self.assertLess(p["rejection_slopes_max"], 0.25)
        self.assertAlmostEqual(p["speed_kept"], 1.0, delta=0.01)
        self.assertAlmostEqual(p["speed_kept_slopes_min"], 1.0, delta=0.01)
        self.assertEqual([s["name"] for s in p["segments"]], [s["name"] for s in self.on["segments"]])
        self.assertIsNone(lm.pair(self.on, None))

    def test_overall(self):
        o = self.off["overall"]
        self.assertAlmostEqual(o["speed_mean_cm_s"], 60.0, delta=0.5)
        self.assertEqual(o["stops"], 0)
        self.assertAlmostEqual(o["ground_incl_peak_deg"], math.degrees(math.atan(math.hypot(math.tan(math.radians(5)), math.tan(math.radians(4))))), delta=0.05)
        self.assertAlmostEqual(o["rider_incl_peak_deg"], o["ground_incl_peak_deg"], delta=0.01)
        self.assertAlmostEqual(o["drive_share_min"], 0.5, places=6)
        self.assertEqual(o["float_longest_s"], 0.0)
        self.assertAlmostEqual(o["margin_min_cm"], 30.0, delta=0.01)
        self.assertEqual(o["end"], "end line")
        self.assertLess(self.on["overall"]["reach_min"], 1.0)
        rl = self.on["return_level"]
        self.assertLess(rl["rider_after_3s_deg"], 0.05)
        self.assertLess(rl["settle_s"], 2.0)

    def test_the_other_way(self):
        rev = figs("TRANSITIONS", "off", direction="rev")
        by = {s["name"]: s for s in rev["segments"]}
        self.assertAlmostEqual(by["up"]["rider_mean_deg"][0], -5.0, delta=0.02)  # down it
        self.assertAlmostEqual(by["fall_left"]["rider_mean_deg"][1], -4.0, delta=0.02)


class Events(unittest.TestCase):
    def test_preference_step_on_the_flat(self):
        # On flat ground a preference stepped by 3.6 deg is chased with tau 0.4 s: the error starts at the step and
        # decays as 3.6 e^(-t / 0.4).
        ev = [{"t": -6.0, "do": "pref", "pitch": 0.0, "roll": 0.0, "label": "preference 0"},
              {"t": -6.0, "do": "assist", "value": 1, "label": "assist on"},
              {"t": 5.0, "do": "pref", "pitch": 3.0, "roll": -2.0, "label": "preference +3, -2"}]
        f = lm.figures(synth("FLAT", "on", events=ev), LEVEL_PROF)
        e = next(t for t in f["transitions"] if t["label"] == "preference +3, -2")
        step = math.hypot(3.0, 2.0)
        self.assertAlmostEqual(e["rider_peak_deg"], step, delta=0.01)
        self.assertAlmostEqual(e["rider_start_deg"], step, delta=0.01)
        self.assertAlmostEqual(e["settle_s"], 0.4 * math.log(step / 0.5), delta=DT)
        self.assertAlmostEqual(e["rider_outside_s"], 0.4 * math.log(step / 1.0), delta=DT)
        self.assertAlmostEqual(e["rider_rate_deg_s"], step * (1.0 - math.exp(-0.3 / 0.4)) / 0.3, delta=0.25)
        self.assertLess(e["rider_end_deg"], 0.01)
        self.assertTrue(e["error_meant"])
        self.assertEqual(e["states"][0][1], 1)
        # The zero preference set at the gate is no event; the switch-on is.
        self.assertEqual([t["label"] for t in f["transitions"]], ["assist on", "preference +3, -2", "stop at the end"])
        self.assertEqual(f["segments"][0]["pref_deg"], [3.0, -2.0])

    def test_the_off_run_is_scored_against_the_same_preference(self):
        off = figs("FLAT", "off", pref=(3.0, -2.0))
        self.assertAlmostEqual(off["overall"]["rider_rms_deg"], math.hypot(3.0, 2.0), delta=0.01)
        on = figs("FLAT", "on", pref=(3.0, -2.0))
        self.assertLess(on["overall"]["rider_rms_deg"], 0.01)  # at the preference before go
        self.assertAlmostEqual(on["overall"]["rider_incl_rms_deg"], math.hypot(3.0, 2.0), delta=0.02)  # and so off level

    def test_toggle_on_a_ramp(self):
        f = figs("RAMP5", "on", variant="toggle")
        labels = [t["label"] for t in f["transitions"] if t["kind"] == "event"]
        self.assertEqual(labels, ["assist on", "assist off", "stop at the end"])
        on = next(t for t in f["transitions"] if t["label"] == "assist on")
        self.assertAlmostEqual(on["rider_start_deg"], lt.RAMP_1_12, delta=0.05)  # switched on halfway up, at the slope
        self.assertLess(on["rider_end_deg"], 0.1)
        off = next(t for t in f["transitions"] if t["label"] == "assist off")
        self.assertFalse(off["error_meant"])  # back to the ground's attitude: read its rate
        self.assertGreater(off["rider_rate_deg_s"], 1.0)

    def test_stop_and_go(self):
        f = figs("RAMP5", "on", variant="stop_go")
        self.assertEqual(f["overall"]["stops"], 0)  # asked for: not counted
        self.assertAlmostEqual(f["overall"]["speed_mean_cm_s"], 60.0, delta=0.5)
        self.assertAlmostEqual(f["overall"]["drive_s"], figs("RAMP5", "on")["overall"]["drive_s"] + 2 * course.STOP_S, delta=0.2)
        stalled = synth("RAMP5", "on")
        for s in stalled["samples"]:  # the same trace with the robot stuck from 600 cm on: a stop nobody asked for
            if s["chassis"]["xyz"][0] > 720.0:
                s["chassis"]["xyz"][0] = 720.0
        g = lm.figures(stalled, LEVEL_PROF)
        self.assertEqual(g["overall"]["stops"], 1)
        self.assertLess(g["overall"]["speed_min_cm_s"], 1.0)

    def test_parked(self):
        f = figs("PARK", "on", start="pad_cross", variant="parked", alt_mode=("differential", "holonomic"))
        self.assertEqual(f["segments"], [])
        p = f["parked"]
        self.assertEqual(p["drift_cm"], 0.0)
        self.assertIsNotNone(p["settled_after_s"])
        self.assertAlmostEqual(p["settled_after_s"], 0.4 * math.log(6.0 / 0.5), delta=2 * DT)
        labels = [t["label"] for t in f["transitions"]]
        self.assertEqual(labels, ["assist on", "mode holonomic", "mode differential", "assist off"])
        on = f["transitions"][0]
        self.assertAlmostEqual(on["rider_start_deg"], 6.0, delta=0.05)  # standing across 6 deg
        self.assertAlmostEqual(on["rider_roll_peak_deg"], 6.0, delta=0.05)
        self.assertEqual(f["overall"]["distance_cm"], 0.0)
        # The toy's chase runs out inside the grace the commands are given (QUIET_GRACE_S after the rider is settled):
        # not hunting. Commands that go on flipping are counted; quiet ones count none.
        self.assertEqual(p["cmd_changes_after_settle"], 0)
        self.assertGreater(p["quiet_after_s"], p["settled_after_s"])
        self.assertEqual(p["hold_drift_cm"], 0.0)
        t = synth("PARK", "on", start="pad_cross", variant="parked")
        for i, s in enumerate(t["samples"]):
            s["cmd"] = {"leg": [0.1, 0.02 + 0.001 * (i % 2), 0.12]}
        self.assertGreater(lm.figures(t, LEVEL_PROF)["parked"]["cmd_changes_after_settle"], 100)
        for s in t["samples"]:
            s["cmd"] = {"leg": [0.1, 0.02, 0.12]}
        quiet = lm.figures(t, LEVEL_PROF)["parked"]
        self.assertEqual(quiet["cmd_changes_after_settle"], 0)
        self.assertEqual(quiet["quiet_after_s"], 0.0)


class Standing(unittest.TestCase):
    def test_floating_wheel_and_share(self):
        f = figs("FLAT", "on", float_at=(12.0, 12.5))
        self.assertAlmostEqual(f["overall"]["float_longest_s"], 0.5, delta=DT)
        self.assertAlmostEqual(f["overall"]["drive_share_min"], 1.0 / 3.0, delta=0.001)  # one of two drive wheels, of three bearing
        self.assertLess(f["overall"]["margin_min_cm"], 30.0)  # three points: the centre of mass nearer an edge

    def test_leg_travel_on_the_flat(self):
        f = figs("FLAT", "on", hunt_cm=0.5)
        self.assertAlmostEqual(f["overall"]["leg_travel_rms_cm"], 0.5 / math.sqrt(2.0), delta=0.02)
        self.assertAlmostEqual(figs("FLAT", "on")["overall"]["leg_travel_rms_cm"], 0.0, delta=1e-6)

    def test_yaw_and_steering(self):
        f = figs("CROSS6", "off", yaw_per_s=1.0, turn=-0.05)
        o = f["overall"]
        self.assertAlmostEqual(o["yaw_change_deg"], o["drive_s"], delta=0.1)  # 1 deg/s
        self.assertAlmostEqual(o["steer_mean"], -0.05, places=6)
        self.assertAlmostEqual(o["steer_abs_mean"], 0.05, places=6)
        self.assertEqual(len(f["segments"]), 1)
        self.assertAlmostEqual(f["segments"][0]["rider_mean_deg"][1], 6.0, delta=0.3)
        self.assertAlmostEqual(f["segments"][0]["yaw_drift_deg"], f["segments"][0]["t1"] - f["segments"][0]["t0"], delta=0.1)

    def test_rider_accel_has_a_lateral_part(self):
        imu = []
        for k in range(1500):
            t = k * 0.002
            imu.append({"seq": k, "sim_time": t, "orientation": {"x": 0, "y": 0, "z": 0, "w": 1},
                        "linear_acceleration": {"x": 0.0, "y": 100.0 if 1.0 <= t < 2.0 else 0.0, "z": lm.measures.GRAVITY_CM_S2}})
        r = lm.rider_accel(imu, 0.0, 3.0)
        self.assertGreater(r["peak_lateral_m_s2"], 0.9)
        self.assertLess(r["peak_fore_aft_m_s2"], 0.01)
        self.assertIsNone(lm.rider_accel([], 0.0, 1.0))


CRITERIA = {"steady_residual_deg": 0.5, "rider_rms_deg": 1.0, "rider_peak_deg": 3.0, "tilt_rate_deg_s": 4.0, "rejection_max": 0.3,
            "stops": 0, "speed_kept_slope": 0.8, "speed_kept_overall": 0.6, "at_reach_s": 0.0, "margin_cm": 3.0,
            "margin_under_off_cm": 1.0, "drive_share_under_off": 0.02, "float_s": 0.2, "level_after_flat_deg": 0.5,
            "flat_rms_over_off_deg": 0.2, "flat_leg_travel_rms_cm": 0.2,
            "past_reach": {"reach_deg": 7.0, "tilt_over_deg": 0.5, "rate_deg_s": 3.5, "speed_floor": 0.25},
            "parked": {"drift_cm": 1.0, "cmd_changes": 0, "toggle_rate_deg_s": 3.5, "mode_switch_deg": 0.5}}


class Scoring(unittest.TestCase):
    def test_a_good_run_passes(self):
        on, off = figs("RAMP5", "on", tau=0.15), figs("RAMP5", "off")
        s = lm.score(on, lm.pair(on, off), CRITERIA, "pass")
        self.assertTrue(s["met"], s)
        names = [c["name"] for c in s["checks"]]
        for n in ("steady residual", "rider RMS", "rider peak", "tilt rate", "rejection on slopes", "speed kept on slopes",
                  "no stops", "margin", "drive wheel off the ground", "level 3 s after the flat"):
            self.assertIn(n, names)
        self.assertEqual(s["not_measured"], [])

    def test_each_failure_is_named(self):
        off = figs("RAMP5", "off")
        slow = figs("RAMP5", "on", tau=3.0)  # too slow a chase: never level on the ramp
        s = lm.score(slow, lm.pair(slow, off), CRITERIA, "pass")
        self.assertFalse(s["met"])
        self.assertIn("steady residual", s["failed"])
        self.assertIn("rejection on slopes", s["failed"])
        fl = figs("RAMP5", "on", tau=0.15, float_at=(15.0, 16.0))
        self.assertIn("drive wheel off the ground", lm.score(fl, lm.pair(fl, off), CRITERIA, "pass")["failed"])
        crawl = figs("RAMP5", "on", tau=0.15, speed=30.0)
        self.assertIn("speed kept", lm.score(crawl, lm.pair(crawl, off), CRITERIA, "pass")["failed"])
        tip = figs("RAMP5", "on", tau=0.15, margin_shift=29.0)  # the centre of mass 1 cm from the edge of its support
        failed = lm.score(tip, lm.pair(tip, off), CRITERIA, "pass")["failed"]
        self.assertIn("margin", failed)
        self.assertIn("margin against off", failed)

    def test_flat_checks(self):
        on, off = figs("FLAT", "on", hunt_cm=0.5), figs("FLAT", "off")
        s = lm.score(on, lm.pair(on, off), CRITERIA, "pass")
        self.assertEqual(s["failed"], ["leg travel on the flat"])
        self.assertIn("RMS on the flat over off", [c["name"] for c in s["checks"]])
        self.assertNotIn("rejection on slopes", [c["name"] for c in s["checks"]])

    def test_off_and_explore_are_not_scored(self):
        off = figs("RAMP5", "off")
        self.assertIsNone(lm.score(off, None, CRITERIA, "pass", level="off")["met"])
        self.assertIsNone(lm.score(off, None, CRITERIA, "explore")["met"])

    def test_a_robot_without_the_assist_fails_an_on_run(self):
        t = synth("RAMP5", "on")
        for s in t["samples"]:
            del s["level"]
        s = lm.score(lm.figures(t, LEVEL_PROF), None, CRITERIA, "pass")
        self.assertEqual(s["failed"], ["no level assist on this robot"])

    def test_without_the_off_run_the_pair_checks_are_not_measured(self):
        on = figs("RAMP5", "on", tau=0.15)
        s = lm.score(on, None, CRITERIA, "pass")
        self.assertTrue(s["met"])  # nothing failed ...
        self.assertIn("rejection on slopes", s["not_measured"])  # ... and what could not be judged is said

    def test_rates_and_parked(self):
        tg = figs("RAMP5", "on", variant="toggle", tau=0.15)
        s = lm.score(tg, None, CRITERIA, "rates")
        self.assertEqual([c["name"] for c in s["checks"]], ["no fault", "no stops", "tilt rate"])
        self.assertFalse(s["met"])  # 4.76 deg taken out with tau 0.15 s is far over 4 deg/s
        pk = figs("PARK", "on", start="pad_cross", variant="parked", tau=2.5)
        s = lm.score(pk, None, CRITERIA, "parked")
        self.assertIn("creep", [c["name"] for c in s["checks"]])
        self.assertIn("commands after settling", s["failed"])  # the toy never goes quiet
        self.assertNotIn("creep", s["failed"])

    def test_past_reach(self):
        # 12 deg with 7 of reach: a robot that takes out all of it reads as within the bound; one that takes out
        # nothing is 12 deg off, over the 5.5 allowed.
        on = figs("RAMP12", "on", tau=0.15)
        s = lm.score(on, None, CRITERIA, "past_reach")
        self.assertIn("tilt past reach", [c["name"] for c in s["checks"]])
        self.assertNotIn("tilt past reach", s["failed"])
        t = synth("RAMP12", "off")
        for x in t["samples"]:
            x["level"].update({"assist": 1, "state": 1})
        lim = next(c for c in lm.score(lm.figures(t, LEVEL_PROF), None, CRITERIA, "past_reach")["checks"] if c["name"] == "tilt past reach")
        self.assertAlmostEqual(lim["limit"], 12.0 - 7.0 + 0.5, delta=0.05)
        self.assertFalse(lim["ok"])


if __name__ == "__main__":
    unittest.main()
