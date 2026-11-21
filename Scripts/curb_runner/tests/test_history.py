"""history.py and scoring.py on synthetic rows (no editor; nothing written outside a temporary folder).

    python -I Scripts/curb_runner/tests/test_history.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import history as h  # noqa: E402
import measures as m  # noqa: E402
import scoring  # noqa: E402


def row(sid="S0", direction="up", phase="DONE", met=True, robot="testbot"):
    return {"robot_id": "test_robot", "history_robot": robot, "scenario": sid, "dir": direction, "start": "standing",
            "descent_start": "top" if direction == "down" else None, "ran_at": "2026-11-21T12:00:00+00:00",
            "settings": {"max_fps": 16.0, "frame_ms": 62.5, "steady": True},
            "outcome": {"phase": phase, "pass": met, "met": met, "expect": "pass", "failed": [] if met else ["done"],
                        "status": "Done", "why": None},
            "shared": {"version": m.SHARED_VERSION, "times": {"edge_to_last_down_s": 12.0}},
            "rider": None, "controller": {"step_found": [15.24, 13.7]}}


class Records(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.hist = os.path.join(self.tmp, "test_history.jsonl")
        h.HISTORIES.clear()
        h.register("testbot", self.hist, standard=lambda r: r["settings"].get("max_fps") == 16.0)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        h.HISTORIES.clear()

    def run_dir(self, name, rows):
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        with open(os.path.join(d, "results.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f)
        h.write_run_side_file(d, {"sim": {"sha": "abc", "dirty": False}}, {"argv": ["run_curb.py", "--out", d],
                                                                           "started": "2026-11-21T12:00:00+00:00"})
        return d

    def test_record_fields(self):
        r = h.record(row(), 1, "x/results.json", self.tmp, {"argv": ["run_curb.py"]}, {"ran_on": {}}, "lab")
        self.assertEqual(r["schema"], 3)
        self.assertEqual(r["robot"], "testbot")
        self.assertEqual(r["robot_id"], "test_robot")
        self.assertTrue(r["settings"]["standard"])
        self.assertEqual(r["outcome"]["failed"], None)
        self.assertEqual(r["shared"]["times"]["edge_to_last_down_s"], 12.0)
        self.assertEqual(r["label"], "lab")

    def test_add_and_replace(self):
        d = self.run_dir("run1", [row(), row("S4"), {"scenario": "S8", "outcome": {"why": "error: no editor"}}])
        self.assertEqual(h.add_runs([d], quiet=True), 2)  # the error row is not a crossing
        recs = h.read_history(self.hist)
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["code"], {"ran_on": {"sim": {"sha": "abc", "dirty": False}}})
        # A run added again replaces its records.
        self.assertEqual(h.add_runs([d], quiet=True), 2)
        self.assertEqual(len(h.read_history(self.hist)), 2)

    def test_unregistered_robot_left_out(self):
        d = self.run_dir("run2", [row(robot="nobody")])
        self.assertEqual(h.add_runs([d], quiet=True), 0)
        self.assertFalse(os.path.exists(self.hist))

    def test_public_paths(self):
        self.assertEqual(h.rel_path(os.path.join(h.ROOT, "Saved", "x")), "Saved/x")
        self.assertEqual(h.rel_path(os.path.join(tempfile.gettempdir(), "elsewhere", "run7")), "run7")
        argv = h.public_argv(["Scripts/curb_runner/run_curb.py", "--out", os.path.join(tempfile.gettempdir(), "r1"), "--robot", "x"])
        self.assertEqual(argv, ["Scripts/curb_runner/run_curb.py", "--out", "r1", "--robot", "x"])
        for a in argv:
            self.assertFalse(os.path.isabs(a))

    def test_optional_submodules_excluded(self):
        sim = h.PUBLIC_REPOS[0]
        self.assertEqual(sim[0], "sim")
        for p in h.optional_submodules():
            self.assertIn(":(exclude)" + p, sim[2])
        self.assertNotIn("private", [r[0] for r in h.PUBLIC_REPOS])


class Scoring(unittest.TestCase):
    def crossing(self, **att):
        r = row()
        r["shared"] = {"across": True, "attitude": dict({"final_pitch_change_deg": 0.0, "final_roll_change_deg": 0.0,
                                                         "max_chassis_incl_deg": 2.0}, **att),
                       "landing": {"min_r": 0.8}}
        return r

    def test_pass(self):
        s = scoring.score(self.crossing(), "pass", [15.24, 15.24])
        self.assertEqual(s, {"pass": True, "met": True, "failed": []})

    def test_level_relative(self):
        s = scoring.score(self.crossing(final_pitch_change_deg=2.0), "pass", [15.24, 15.24])
        self.assertEqual(s["failed"], ["level"])

    def test_wrong_step(self):
        s = scoring.score(self.crossing(), "pass", [10.16, 10.16])
        self.assertIn("step", s["failed"])

    def test_refusal(self):
        r = row(phase="REFUSED")
        r["outcome"]["why"] = "the step ahead is 20.3 cm, more than 17"
        self.assertTrue(scoring.score(r, "refuse:more than 17", None)["met"])
        self.assertFalse(scoring.score(r, "refuse:off square", None)["met"])
        self.assertFalse(scoring.score(self.crossing(), "refuse:more than 17", None)["met"])

    def test_explore_not_scored(self):
        self.assertIsNone(scoring.score(self.crossing(), "explore", [15.24, 15.24])["met"])

    def test_robot_checks(self):
        s = scoring.score(self.crossing(), "pass", [15.24, 15.24], robot_checks=lambda r: ["lifts back"])
        self.assertEqual(s["failed"], ["lifts back"])
        self.assertFalse(s["met"])


class ImuClock(unittest.TestCase):
    def test_offset(self):
        samples = [{"t": 5.0 + 0.0625 * i, "imu_t": 5.0 + 0.0625 * i - 0.8 - (0.002 if i % 3 else 0.0)} for i in range(50)]
        self.assertAlmostEqual(m.imu_clock_offset(samples), 0.802, places=6)
        self.assertIsNone(m.imu_clock_offset([{"t": 1.0}]))

    def test_rider_window_shifted(self):
        imu = []
        for k in range(1500):
            t = k * 0.002
            a = 100.0 if 1.0 <= t < 2.0 else 0.0  # the physics clock: moving from 1 s
            imu.append({"seq": k, "sim_time": t, "orientation": {"x": 0, "y": 0, "z": 0, "w": 1},
                        "linear_acceleration": {"x": a, "y": 0.0, "z": m.GRAVITY_CM_S2}})
        # On the world clock (0.8 s later) the motion is at 1.8-2.8 s: a window over 0..1.7 s sees none of it.
        self.assertLess(m.rider_figures(imu, 0.0, 1.7, offset=0.8)["peak_fore_aft_m_s2"], 0.01)
        self.assertGreater(m.rider_figures(imu, 1.8, 2.8, offset=0.8)["peak_fore_aft_m_s2"], 0.9)


if __name__ == "__main__":
    unittest.main()
