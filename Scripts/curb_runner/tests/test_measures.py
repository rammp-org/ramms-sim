"""measures.py on synthetic traces with known answers (no editor, no robot data).

    python -I Scripts/curb_runner/tests/test_measures.py
"""

import math
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "curb_maps")))
import curb_terrain as ct  # noqa: E402
import measures as m  # noqa: E402

R = 10.0  # every synthetic wheel's radius (cm)
V = 10.0  # the synthetic robot's speed (cm/s)
X0 = 300.0  # the chassis's x at rest
T_ASK = 2.0  # asked for, and starts moving, here
X_STOP = 510.0  # it stops with its chassis here ...
T_STOP = T_ASK + (X_STOP - X0) / V  # ... at 23.0 s
T_DONE = 24.0
NEAR_Z, TOP_Z = -199.0, -183.76  # S0's near road and sidewalk tops at the path


def bottom(a, raised=False):
    """A wheel's lowest point (z) on S0's climb with its hub `a` cm past the edge: on the road, lifted 3 cm over the
    sidewalk from a radius short of the edge, set down over 5..8 cm past it. A raised wheel rides 5 cm over either."""
    if raised:
        return (NEAR_Z if a < 0.0 else TOP_Z) + 5.0
    if a < -R:
        return NEAR_Z
    if a < 5.0:
        return TOP_Z + 3.0
    if a < 8.0:
        return TOP_Z + (8.0 - a)
    return TOP_Z


def chassis_x(t):
    if t <= T_ASK:
        return X0
    return min(X_STOP, X0 + V * (t - T_ASK))


def make_trace(seed=1, t_end=26.0, ripple=0.3, wheel_hook=None, phase_begin=T_ASK + 0.05):
    """Samples at jittered 50-70 ms frames. Wheels: front (+40 cm), rear (-40 cm), caster (+60 cm, held up 5 cm)."""
    rng = random.Random(seed)
    out, t = [], 0.0
    while t <= t_end:
        x = chassis_x(t)
        wheels = []
        for name, off, raised in (("front", 40.0, False), ("rear", -40.0, False), ("caster", 60.0, True)):
            hx = x + off
            a = hx - 450.0
            z = bottom(a, raised) + R
            if a >= 8.0 and not raised:
                z += ripple * math.sin(37.0 * t + off)
            if wheel_hook:
                z = wheel_hook(name, t, a, z)
            wheels.append([hx, 700.0, z])
        phase = "IDLE" if t < phase_begin else ("DONE" if t >= T_DONE else "CROSS")
        out.append({"t": t, "phase": phase, "chassis": {"xyz": [x, 700.0, -180.0], "pitch": 0.0, "yaw": 0.0, "roll": 0.0},
                    "wheels": wheels})
        t += rng.uniform(0.05, 0.07)
    return out


WHEELS = [{"name": "front", "radius_cm": R}, {"name": "rear", "radius_cm": R}, {"name": "caster", "radius_cm": R}]


def frame(direction="up"):
    return m.Frame(ct.Layout(ct.BY_ID["S0"]), direction)


class Events(unittest.TestCase):
    def check(self, got, want, tol=0.005):
        self.assertIsNotNone(got)
        self.assertLessEqual(abs(got - want), tol, "%s, not %s" % (got, want))

    def test_climb(self):
        f = m.shared_figures(make_trace(), WHEELS, frame(), T_ASK)
        e, tm = f["events"], f["times"]
        self.assertTrue(f["across"])
        self.assertEqual(f["wheels"]["counted"], ["front", "rear"])
        self.assertEqual(f["wheels"]["raised"], ["caster"])
        # The caster leads: its hub 60 cm ahead reaches a radius short of the edge at chassis x 380.
        self.check(e["t_edge"], T_ASK + (380.0 - X0) / V)
        # A wheel is down at a gap of 1 cm: 7 cm past the edge (chassis 417 for the front, 497 for the rear).
        self.check(e["down"]["front"], T_ASK + (417.0 - X0) / V)
        self.check(e["down"]["rear"], T_ASK + (497.0 - X0) / V)
        self.assertEqual(e["last_down_wheel"], "rear")
        self.check(tm["edge_to_last_down_s"], (497.0 - 380.0) / V, 0.011)
        self.check(e["t_done"], T_DONE, 0.07)
        self.check(e["t_rest"], T_STOP, 0.07)
        self.assertGreaterEqual(e["t_rest"], T_STOP - m.REST_MOVE_CM / V - 1e-6)
        self.check(f["speed"]["v_min_cm_s"], V, 0.1)
        self.assertEqual(f["speed"]["stops"], 0)
        # Stopped from 23 s to Done: its time counts, not as a stop (the crossing's own end).
        self.assertEqual(f["speed"]["stops_to_done"], 0)
        self.assertGreater(f["speed"]["stopped_to_done_s"], 0.5)
        self.assertEqual(f["times"]["planning_after_edge_s"], 0.0)
        self.check(f["landing"]["min_r"], 0.7, 0.01)
        self.assertAlmostEqual(f["path"]["drift_cm"], 0.0, places=3)

    def test_jitter_does_not_move_the_events(self):
        a = [m.shared_figures(make_trace(seed=s), WHEELS, frame(), T_ASK)["times"]["edge_to_last_down_s"] for s in range(1, 8)]
        self.assertLessEqual(max(a) - min(a), 0.011)

    def test_bounce_bridged(self):
        def hook(name, t, a, z):
            if name == "rear" and 22.2 <= t < 22.25:
                return z + 2.0  # a 50 ms bounce, after it landed
            return z
        f = m.shared_figures(make_trace(wheel_hook=hook), WHEELS, frame(), T_ASK)
        self.check(f["events"]["down"]["rear"], T_ASK + (497.0 - X0) / V)

    def test_long_dip_not_bridged(self):
        def hook(name, t, a, z):
            if name == "rear" and 22.2 <= t < 22.5:
                return z + 2.0  # off the ground for 0.3 s: it came down again later
            return z
        f = m.shared_figures(make_trace(wheel_hook=hook), WHEELS, frame(), T_ASK)
        self.assertGreater(f["events"]["down"]["rear"], 22.4)

    def test_not_across(self):
        def hook(name, t, a, z):
            return z + 3.0 if name == "rear" and a >= 5.0 else z  # the rear never sets down
        f = m.shared_figures(make_trace(wheel_hook=hook), WHEELS, frame(), T_ASK)
        self.assertFalse(f["across"])
        self.assertIsNone(f["times"]["edge_to_last_down_s"])
        self.assertIsNone(f["times"]["edge_to_done_s"])
        self.assertIsNotNone(f["times"]["edge_to_end_s"])

    def test_planning_past_the_edge(self):
        f = m.shared_figures(make_trace(), WHEELS, frame(), T_ASK, t_begin=12.0)
        self.check(f["events"]["t0"], 12.0)
        self.check(f["times"]["edge_to_last_down_s"], T_ASK + (497.0 - X0) / V - 12.0, 0.006)
        self.check(f["times"]["planning_after_edge_s"], 12.0 - (T_ASK + (380.0 - X0) / V), 0.006)

    def test_t_begin_defaults_to_first_active_sample(self):
        f = m.shared_figures(make_trace(phase_begin=3.0), WHEELS, frame(), T_ASK)
        self.assertGreaterEqual(f["events"]["t_begin"], 3.0)
        self.assertLess(f["events"]["t_begin"], 3.08)

    def test_never_reached_the_edge(self):
        tr = [s for s in make_trace() if s["t"] < 5.0]
        f = m.shared_figures(tr, WHEELS, frame(), T_ASK)
        self.assertIsNone(f["events"]["t_edge"])
        self.assertFalse(f["across"])
        self.assertIsNone(f["times"]["edge_to_end_s"])

    def test_descent_frame(self):
        f = frame("down")
        self.assertAlmostEqual(f.along((760.0, 700.0)), 10.0)
        self.assertAlmostEqual(f.gap_to((800.0, 700.0, NEAR_Z + R), R), 0.0, places=3)


class Surfaces(unittest.TestCase):
    def test_plane_rotator_matches_rotation_axes(self):
        for sid in ("W6", "X6P_G", "A30_X6", "A30N_G4X4", "G6", "T6"):
            L = ct.Layout(ct.BY_ID[sid])
            for name, plane in L.planes.items():
                for yaw in (0.0, 17.0, -30.0):
                    pitch, roll = m.plane_rotator(plane, yaw)
                    x, y, z = m.rotation_axes(pitch, yaw, roll)
                    nrm = (-plane.gradient[0], -plane.gradient[1], 1.0)
                    k = math.sqrt(sum(v * v for v in nrm))
                    for i in range(3):
                        self.assertAlmostEqual(z[i], nrm[i] / k, places=9, msg="%s %s %s" % (sid, name, yaw))

    def test_following_the_surfaces_is_level(self):
        """A W6 climb whose chassis lies on the near road at the ask and on the twisted sidewalk at Done has no
        attitude change the surfaces do not explain (the roll convention and the heading at each end)."""
        L = ct.Layout(ct.BY_ID["W6"])
        f = m.Frame(L, "up")
        p0, r0 = m.plane_rotator(L.planes["near"], 0.0)
        p1, r1 = m.plane_rotator(L.planes["top"], 4.0)
        tr = make_trace()
        for s in tr:
            done = s["t"] >= T_DONE - 1.0
            s["chassis"].update({"pitch": p1 if done else p0, "roll": r1 if done else r0, "yaw": 4.0 if done else 0.0})
        sh = m.shared_figures(tr, WHEELS, f, T_ASK)
        self.assertAlmostEqual(sh["attitude"]["final_roll_change_deg"], 0.0, places=2)
        self.assertAlmostEqual(sh["attitude"]["final_pitch_change_deg"], 0.0, places=2)
        self.assertGreater(abs(r1 - r0), 3.0)  # the test means something: the twist changes the roll

    def test_dip_at_the_settle_sample_bridged(self):
        tr = make_trace()
        i = max(k for k, s in enumerate(tr) if s["t"] <= T_DONE + 0.05 + m.SETTLE_S)
        def hook(name, t, a, z):
            return z + 1.5 if name == "rear" and abs(t - tr[i]["t"]) < 1e-9 else z
        f = m.shared_figures(make_trace(wheel_hook=hook), WHEELS, frame(), T_ASK)
        self.assertTrue(f["across"])
        self.check_t(f["events"]["down"]["rear"], T_ASK + (497.0 - X0) / V)

    def check_t(self, got, want):
        self.assertIsNotNone(got)
        self.assertLessEqual(abs(got - want), 0.005)


class Speeds(unittest.TestCase):
    def test_stop_counted(self):
        tr = []
        t = 0.0
        while t <= 10.0:
            x = V * min(t, 3.0) + V * max(0.0, t - 4.0)  # stopped from 3 s to 4 s
            tr.append({"t": t, "chassis": {"xyz": [x, 0.0, 0.0], "yaw": 0.0}})
            t += 0.0625
        f = m.speed_figures(tr)
        self.assertEqual(f["stops"], 1)
        self.assertLess(f["v_min_cm_s"], 0.5)
        self.assertAlmostEqual(f["stopped_s"], 1.0 - m.SPEED_WINDOW_S, delta=0.13)

    def test_window_speed_exact(self):
        rng = random.Random(3)
        tr, t = [], 0.0
        while t <= 5.0:
            tr.append({"t": t, "chassis": {"xyz": [V * t, 0.0, 0.0], "yaw": 0.0}})
            t += rng.uniform(0.05, 0.07)
        for _, v in m.forward_speeds(tr):
            self.assertAlmostEqual(v, V, delta=0.1)

    def test_reverse_is_negative(self):
        tr = [{"t": i * 0.05, "chassis": {"xyz": [-V * i * 0.05, 0.0, 0.0], "yaw": 0.0}} for i in range(40)]
        self.assertLess(m.speed_figures(tr)["v_min_cm_s"], -9.0)


class Attitude(unittest.TestCase):
    def test_incl(self):
        self.assertAlmostEqual(m.incl(3.0, 0.0), 3.0, places=6)
        self.assertAlmostEqual(m.incl(0.0, -4.0), 4.0, places=6)
        self.assertGreater(m.incl(3.0, 4.0), 4.9)

    def test_tilt_rate(self):
        tr = [{"t": i * 0.05, "chassis": {"pitch": 2.0 * i * 0.05, "roll": 0.0}} for i in range(40)]
        self.assertAlmostEqual(m.tilt_rate_total(tr, m.chassis_attitude), 2.0, places=6)

    def test_rotation_axes(self):
        x, y, z = m.rotation_axes(0.0, 90.0, 0.0)  # yawed right: X to +Y, Y to -X
        self.assertAlmostEqual(x[1], 1.0)
        self.assertAlmostEqual(y[0], -1.0)
        x, y, z = m.rotation_axes(10.0, 0.0, 0.0)  # pitched nose up
        self.assertAlmostEqual(x[2], math.sin(math.radians(10.0)))


class Rider(unittest.TestCase):
    def imu(self, accel_x, t1=3.0, dt=0.002):
        out, t, seq = [], 0.0, 0
        while t <= t1:
            a = accel_x if 1.0 <= t < 2.0 else 0.0
            out.append({"seq": seq, "sim_time": t, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
                        "linear_acceleration": {"x": a, "y": 0.0, "z": m.GRAVITY_CM_S2}})
            t += dt
            seq += 1
        return out

    def test_at_rest_reads_zero(self):
        r = m.rider_figures(self.imu(0.0), 0.0, 3.0)
        self.assertLess(r["peak_total_m_s2"], 1e-6)

    def test_forward_acceleration(self):
        r = m.rider_figures(self.imu(100.0), 0.0, 3.0)  # 1 m/s^2 for a second
        self.assertAlmostEqual(r["peak_fore_aft_m_s2"], 1.0, delta=0.01)
        self.assertLess(r["peak_vertical_m_s2"], 1e-6)

    def test_duplicates_dropped(self):
        s = self.imu(100.0)
        self.assertEqual(m.rider_figures(s + s, 0.0, 3.0)["samples"], m.rider_figures(s, 0.0, 3.0)["samples"])


if __name__ == "__main__":
    unittest.main()
