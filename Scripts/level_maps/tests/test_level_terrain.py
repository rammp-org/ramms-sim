"""level_terrain.py's maths (no editor; nothing written).

    python -I Scripts/level_maps/tests/test_level_terrain.py
"""

import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import level_terrain as lt  # noqa: E402

MIN_STEADY_CM = 240.0  # 4 s at 0.6 m/s


def made_up(segs, **kw):
    return lt.Layout(lt.Course("T", "made up", segs, **kw))


class Planes(unittest.TestCase):
    def test_tilt_signs(self):
        # A grade rises along +X: nose up heading +X, nose down heading -X. A cross fall rises toward +Y: the right
        # side up heading +X, the left side up heading -X.
        p, r = lt.tilt_of((lt.tand(5.0), 0.0), 0.0)
        self.assertAlmostEqual(p, 5.0, places=6)
        self.assertAlmostEqual(r, 0.0, places=6)
        p, r = lt.tilt_of((lt.tand(5.0), 0.0), 180.0)
        self.assertAlmostEqual(p, -5.0, places=6)
        p, r = lt.tilt_of((0.0, lt.tand(4.0)), 0.0)
        self.assertAlmostEqual(r, 4.0, places=6)
        self.assertAlmostEqual(p, 0.0, places=6)
        p, r = lt.tilt_of((0.0, lt.tand(4.0)), 180.0)
        self.assertAlmostEqual(r, -4.0, places=6)
        # Heading +Y (yaw 90) up a cross fall is a climb.
        p, r = lt.tilt_of((0.0, lt.tand(4.0)), 90.0)
        self.assertAlmostEqual(p, 4.0, places=6)

    def test_fit_gradient(self):
        g = (0.05, -0.03)
        pts = [(x, y, 7.0 + g[0] * x + g[1] * y) for x, y in ((0, 0), (60, 0), (0, 50), (60, 50), (30, 20))]
        got = lt.fit_gradient(pts)
        self.assertAlmostEqual(got[0], g[0], places=9)
        self.assertAlmostEqual(got[1], g[1], places=9)
        self.assertIsNone(lt.fit_gradient([(0, 0, 0), (1, 1, 1)]))
        self.assertIsNone(lt.fit_gradient([(0, 0, 0), (1, 1, 1), (2, 2, 2)]))  # in a line

    def test_centreline_is_continuous(self):
        L = lt.layout("RAMP5")
        rise = 600.0 * lt.tand(lt.RAMP_1_12)
        self.assertAlmostEqual(L.intended_z(1080.0, 0.0) - L.intended_z(480.0, 0.0), rise, places=6)
        self.assertAlmostEqual(rise, 50.0, places=6)  # 1:12 over 6 m
        self.assertAlmostEqual(L.intended_z(2040.0, 0.0), L.intended_z(480.0, 0.0), places=6)
        self.assertAlmostEqual(L.intended_z(0.0, 0.0), lt.FLOOR_TOP_Z + lt.FLOOR_CLEAR, places=6)  # never the floor itself


class Seams(unittest.TestCase):
    def test_fold_kinds(self):
        L = lt.layout("BREAK6")
        self.assertEqual([(j.kind, j.valley) for j in L.joints], [("fold", True), ("fold", False), ("fold", True)])
        self.assertTrue(all(abs(j.skew_deg) < 1e-9 for j in L.joints))

    def test_fold_skew_follows_the_planes(self):
        L = lt.layout("FOLD")
        self.assertAlmostEqual(L.joints[0].skew_deg, 30.0, places=6)
        self.assertAlmostEqual(L.joints[1].skew_deg, 30.0, places=6)  # left across a parallel line
        self.assertTrue(L.joints[0].valley)
        self.assertFalse(L.joints[1].valley)
        self.assertAlmostEqual(L.c.segs[1].slope_deg(), 6.0, places=6)

    def test_cross_fall_alone_is_a_twist(self):
        L = lt.layout("WARP")
        self.assertEqual([j.kind for j in L.joints], ["twist", "twist", "twist"])
        j = L.joints[1]  # 6 deg one way to 6 deg the other
        x = j.p[0]
        # The centreline keeps its height through the twist.
        zs = [L.intended_z(x + d, 0.0) for d in (-300.0, -50.0, 0.0, 50.0, 300.0)]
        self.assertLess(max(zs) - min(zs), 1e-9)
        # The wedges carry the mean cross fall (none here) and climb or fall by half the change times k.
        want = abs(j.ds) * j.k / 2.0
        self.assertAlmostEqual(abs(j.left.gradient[0]), want, places=9)
        self.assertAlmostEqual(j.left.gradient[0], -j.right.gradient[0], places=9)
        self.assertAlmostEqual(j.left.gradient[1], 0.0, places=9)
        self.assertEqual(L.piece_at(x, 100.0), j.left.name)
        self.assertEqual(L.piece_at(x, -100.0), j.right.name)
        self.assertEqual(L.piece_at(x - 250.0, 0.0), "fall_left")
        self.assertEqual(L.piece_at(x + 250.0, 0.0), "fall_right")

    def test_a_fold_too_skewed_is_refused(self):
        with self.assertRaises(ValueError):
            made_up([lt.Seg("a", 600.0), lt.Seg("b", 600.0, 0.5, 6.0), lt.Seg("c", 600.0)])

    def test_one_plane_twice_is_refused(self):
        with self.assertRaises(ValueError):
            made_up([lt.Seg("a", 600.0, 2.0), lt.Seg("b", 600.0, 2.0)])

    def test_a_segment_too_short_for_its_twists_is_refused(self):
        with self.assertRaises(ValueError):
            made_up([lt.Seg("a", 600.0), lt.Seg("b", 300.0, 0.0, 4.0), lt.Seg("c", 600.0)])

    def test_planes_agree_on_every_seam(self):
        for c in lt.COURSES:
            L = lt.layout(c.id)
            for label, a, b in L.seam_points(per_seam=9):
                self.assertLess(abs(L.intended_z(*a) - L.intended_z(*b)), 0.01, "%s %s" % (c.id, label))


class Flush(unittest.TestCase):
    def test_every_course_is_flush(self):
        for c in lt.COURSES:
            r = lt.layout(c.id).flush(step=10.0)
            self.assertTrue(r["ok"], "%s: %s" % (c.id, r))
            self.assertLess(r["max_seam_step_cm"], lt.SEAM_STEP_TOL_CM)

    def test_a_lip_is_found(self):
        # The curb maps' fault: a slab standing 1 cm proud of its neighbour.
        L = lt.Layout(lt.BY_ID["RAMP5"])
        slab = next(s for s in L.slabs if s.label.endswith("_up"))
        slab.plane = lt.ct.Plane("lifted", slab.plane.p_ref, slab.plane.z_ref + 1.0, slab.plane.gradient)
        slab._placed = None
        r = L.flush(step=10.0)
        self.assertFalse(r["ok"])
        self.assertGreater(r["max_seam_step_cm"], 0.9)
        self.assertGreater(r["max_dev_cm"], 0.9)

    def test_a_slab_past_a_crest_is_found(self):
        # A slab that runs on past a crest stands over the ground beyond it.
        L = lt.Layout(lt.BY_ID["RAMP5"])
        i = next(k for k, s in enumerate(L.slabs) if s.label.endswith("_up"))
        s = L.slabs[i]
        L.slabs[i] = lt.Slab(s.label, s.plane, s.origin, s.along, (s.n_range[0], s.n_range[1] + 30.0), s.e_range, s.thick)
        self.assertFalse(L.flush(step=10.0)["ok"])

    def test_a_gap_is_found(self):
        L = lt.Layout(lt.BY_ID["WARP"])
        L.slabs = [s for s in L.slabs if not s.label.endswith("twist01_left")]
        r = L.flush(step=10.0)
        self.assertFalse(r["ok"])

    def test_slab_edges_lie_on_the_crest(self):
        # The slab before a skewed crest ends exactly on the fold line: just short of it is on the slab, just past is not.
        L = lt.layout("FOLD")
        j = L.joints[1]
        slab = next(s for s in L.slabs if "plane" in s.label)
        for v in (-120.0, 0.0, 120.0):
            x = j.line_x(v)
            self.assertTrue(slab.contains(x - 0.01 * j.n[0], v - 0.01 * j.n[1]))
            self.assertFalse(slab.contains(x + 0.01 * j.n[0], v + 0.01 * j.n[1]))

    def test_surface_is_the_built_one(self):
        L = lt.layout("TRANSITIONS")
        for x in (10.0, 600.0, 1300.0, 1900.0, 2500.0, 3100.0):
            for y in (-140.0, -30.0, 0.0, 30.0, 140.0):
                self.assertAlmostEqual(L.surface_z(x, y), L.intended_z(x, y), places=6)
        self.assertEqual(L.surface_z(-500.0, 0.0), lt.FLOOR_TOP_Z)  # off the slabs: the floor


class Paths(unittest.TestCase):
    def test_starts(self):
        L = lt.layout("RAMP5")
        s = L.start("centre", "fwd")
        self.assertEqual(s["origin"], [lt.START_IN, 0.0])
        self.assertAlmostEqual(s["xyz"][2], L.intended_z(lt.START_IN, 0.0) + lt.START_ABOVE_SURFACE, places=6)
        self.assertAlmostEqual(s["length"], L.c.length - lt.END_MARGIN - lt.START_IN, places=6)
        r = L.start("right20", "rev")
        self.assertEqual(r["origin"], [L.c.length - lt.START_IN, -20.0])  # heading -X, the right is -Y
        self.assertAlmostEqual(r["path_yaw"], 180.0)
        y = L.start("yaw5", "fwd")
        self.assertAlmostEqual(y["yaw"] - y["path_yaw"], 5.0)
        with self.assertRaises(ValueError):
            L.start("nowhere", "fwd")

    def test_a_start_on_a_slope_lies_on_it(self):
        L = lt.layout("PARK")
        s = L.start("pad_grade", "fwd")
        self.assertAlmostEqual(math.degrees(math.asin(s["x_axis"][2])), 6.0, places=4)
        dot = sum(a * b for a, b in zip(s["x_axis"], s["z_axis"]))
        self.assertAlmostEqual(dot, 0.0, places=9)
        c = lt.layout("PARK").start("pad_cross", "fwd")
        self.assertAlmostEqual(math.degrees(math.asin(-c["z_axis"][1])), 6.0, places=4)  # the normal leans away from +Y

    def test_profile_segments_and_transitions(self):
        L = lt.layout("TRANSITIONS")
        pr = L.profile(L.start("centre", "fwd"))
        self.assertEqual([s["name"] for s in pr["segments"]], ["in", "up", "top", "fall_left", "fall_right", "down_cross", "out"])
        want = [(0, 0), (5, 0), (0, 0), (0, 4), (0, -4), (-5, -4), (0, 0)]
        for s, (p, r) in zip(pr["segments"], want):
            self.assertAlmostEqual(s["pitch"], p, delta=0.05)
            self.assertAlmostEqual(s["roll"], r, delta=0.05)
        self.assertEqual(len(pr["transitions"]), 6)
        t = pr["transitions"][0]  # a square fold: the footprint's 60 cm of wheelbase long, about the seam at x = 480
        self.assertAlmostEqual(t["d"] + lt.START_IN, 480.0, delta=2.5)
        self.assertAlmostEqual(t["d1"] - t["d0"], 60.0, delta=4.5)
        self.assertAlmostEqual(t["pitch_change"], 5.0, delta=0.05)
        # The other way the same ground reads with its signs turned.
        rev = L.profile(L.start("centre", "rev"))
        self.assertEqual([s["name"] for s in rev["segments"]], ["out", "down_cross", "fall_right", "fall_left", "top", "up", "in"])
        self.assertAlmostEqual(rev["segments"][1]["pitch"], 5.0, delta=0.05)
        self.assertAlmostEqual(rev["segments"][1]["roll"], 4.0, delta=0.05)

    def test_every_plane_gives_a_steady_state(self):
        # At least 4 s at 0.6 m/s with every wheel on the plane, for every plane of every course, both ways.
        for c in lt.COURSES:
            if c.kind != "path":
                continue
            L = lt.layout(c.id)
            for d in lt.DIRECTIONS:
                pr = L.profile(L.start("centre", d))
                self.assertEqual(len(pr["segments"]), len(c.segs), c.id)
                for s in pr["segments"][1:-1]:
                    self.assertGreaterEqual(s["d1"] - s["d0"], MIN_STEADY_CM, "%s %s %s" % (c.id, d, s["name"]))

    def test_crown_paths(self):
        L = lt.layout("CROWN")
        a = L.profile(L.start("straddle", "fwd"))
        self.assertEqual(len(a["segments"]), 1)
        self.assertAlmostEqual(a["segments"][0]["roll"], 0.0, places=6)  # a wheel pair on each side: level across
        b = L.profile(L.start("left", "fwd"))
        self.assertAlmostEqual(b["segments"][0]["roll"], 2.3, places=4)  # the ridge on its right
        x = L.profile(L.start("cross20", "fwd"))
        self.assertEqual(len(x["segments"]), 2)
        self.assertEqual(len(x["transitions"]), 1)
        self.assertGreater(x["segments"][0]["pitch"], 0.5)  # climbing to the ridge at 20 deg
        self.assertLess(x["segments"][1]["pitch"], -0.5)

    def test_ground_attitude_turns_through_a_fold(self):
        L = lt.layout("BREAK6")
        x = L.joints[0].p[0]
        fp = lt.footprint_at((x - 100.0, 0.0), 0.0, lt.REF_FOOTPRINT)
        self.assertAlmostEqual(L.ground_attitude(fp, 0.0)[0], 0.0, places=6)
        fp = lt.footprint_at((x + 100.0, 0.0), 0.0, lt.REF_FOOTPRINT)
        self.assertAlmostEqual(L.ground_attitude(fp, 0.0)[0], 6.0, places=4)
        mid = L.ground_attitude(lt.footprint_at((x, 0.0), 0.0, lt.REF_FOOTPRINT), 0.0)[0]
        self.assertTrue(1.0 < mid < 5.0, mid)  # the front wheels on the grade, the rear ones still on the flat
        self.assertAlmostEqual(L.ground_attitude(lt.footprint_at((x + 100.0, 0.0), 180.0, lt.REF_FOOTPRINT), 180.0)[0], -6.0, places=4)

    def test_footprint_right_is_plus_y(self):
        pts = lt.footprint_at((0.0, 0.0), 0.0, [(10.0, 3.0)])
        self.assertAlmostEqual(pts[0][0], 10.0)
        self.assertAlmostEqual(pts[0][1], 3.0)
        pts = lt.footprint_at((0.0, 0.0), 90.0, [(10.0, 3.0)])  # heading +Y: ahead is +Y, the right is -X
        self.assertAlmostEqual(pts[0][0], -3.0)
        self.assertAlmostEqual(pts[0][1], 10.0)

    def test_names(self):
        self.assertEqual(lt.map_path("RAMP5"), "/Game/Maps/Level/Map_Level_RAMP5_URL")
        for cid in ("FLAT", "RAMP5", "RAMP8", "RAMP12", "CROSS2", "CROSS6", "BREAK6", "CROWN", "FOLD", "COMBO", "PARK", "TRANSITIONS"):
            self.assertIn(cid, lt.BY_ID)


if __name__ == "__main__":
    unittest.main()
