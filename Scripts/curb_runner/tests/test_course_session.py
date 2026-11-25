"""The course session end to end without an editor: runner_op.py's begin_course run against a stand-in `unreal` module
and a made-up robot, then run_level.py's rows, the history and the report made from the traces it wrote. Nothing is
written outside a temporary folder.

    python -I Scripts/curb_runner/tests/test_course_session.py

The stand-in robot is a unicycle on the course's own terrain: the stick's forward value is its speed (60 cm/s at 1),
drive.turn its yaw rate (60 deg/s at 1) plus a pull to one side where the ground falls sideways (the yaw the first
simulator checks found on cross slopes); its chassis lies on the ground with the assist off and chases the preference
with it on; it stands on four wheels.
"""

import json
import math
import os
import shutil
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.dirname(HERE)
sys.path.insert(0, RUNNER)
import course  # noqa: E402
import history  # noqa: E402
import level_measures as lm  # noqa: E402

lt = course.lt
DT = 0.0625
FOOT = ((30.0, 30.0), (30.0, -30.0), (-30.0, 30.0), (-30.0, -30.0))
WHEELS = [{"name": n, "radius_cm": 10.0} for n in ("front_r", "front_l", "rear_r", "rear_l")]
ROBOT_ID = "test_robot"
PROFILE = {"robot_id": ROBOT_ID, "name": "Test robot", "history_robot": "testbot", "editor": os.path.join(HERE, "fake_robot_editor.py"),
           "wheels": WHEELS, "rider_body": None, "max_fps": 16.0,
           "level": {"stick": 1.0, "speed_cm_s": 60.0, "locked_frame_s": 0.0625, "setup": {"stance": "outdoor"},
                     "drive_wheels": ["rear_r", "rear_l"], "alt_mode": ("differential", "holonomic"),
                     "criteria": {"steady_residual_deg": 0.5, "rider_rms_deg": 1.0, "rider_peak_deg": 3.0, "tilt_rate_deg_s": 6.0,
                                  "rejection_max": 0.3, "stops": 0, "speed_kept_slope": 0.8, "speed_kept_overall": 0.6},
                     "expect": lambda c, d, s, v: "rates" if v in ("toggle", "mode") else "pass",
                     "standard": lambda row: (row.get("settings") or {}).get("locked_frame_s") == 0.0625}}


class Vec(object):
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z


class Robot(object):
    """The made-up robot (see the module's words), with the adapter's interface."""

    def __init__(self, layout, start, has_level=True, tau=0.2, pull_per_deg=0.4):
        self.L, self.has_level, self.tau, self.pull = layout, has_level, tau, pull_per_deg
        self.x, self.y = start["xyz"][0], start["xyz"][1]
        self.yaw = start["yaw"]
        self.t = 0.0
        self.fwd = self.turn = 0.0
        self.assist, self.pref, self.mode_id = 0, [0.0, 0.0], "differential"
        self.corr = [0.0, 0.0]
        self.calls = []
        self.pawn = types.SimpleNamespace(get_path_name=lambda: "/Temp/Test.Robot")

    def step(self):
        """One frame of physics."""
        self.t += DT
        g = self.ground_att()
        self.yaw += (60.0 * self.turn + (self.pull * g[1] if abs(self.fwd) > 0 else 0.0)) * DT
        v = 60.0 * self.fwd
        self.x += v * math.cos(math.radians(self.yaw)) * DT
        self.y += v * math.sin(math.radians(self.yaw)) * DT
        g = self.ground_att()
        want = (g[0] - self.pref[0], g[1] - self.pref[1]) if (self.assist and self.mode_id == "differential") else (0.0, 0.0)
        a = 1.0 - math.exp(-DT / self.tau)
        self.corr = [c + a * (w - c) for c, w in zip(self.corr, want)]

    def pts(self):
        return lt.footprint_at((self.x, self.y), self.yaw, FOOT)

    def ground_att(self):
        return self.L.ground_attitude(self.pts(), self.yaw)

    # --- the adapter ---
    def sim_time(self):
        return self.t

    def chassis(self):
        g = self.ground_att()
        p, r = g[0] - self.corr[0], g[1] - self.corr[1]
        roll = -math.degrees(math.asin(math.sin(math.radians(r)) / math.cos(math.radians(p))))
        return {"xyz": [self.x, self.y, self.L.surface_z(self.x, self.y) + 30.0], "pitch": p, "yaw": self.yaw, "roll": roll}

    def seat(self):
        c = self.chassis()
        return {"pitch": c["pitch"] + 1.5, "roll": c["roll"]}  # a mount 1.5 deg nose up

    def wheel_hubs(self):
        return [[p[0], p[1], self.L.surface_z(*p) + 10.0] for p in self.pts()]

    def wheel_rates(self):
        return [6.0 * self.fwd] * 4

    def prepare(self, setup):
        self.calls.append(("prepare", dict(setup)))
        return dict(setup)

    def lifts(self):
        return {"leg": 0.1}

    def drive(self, forward, turn):
        self.fwd, self.turn = forward, turn

    def release_drive(self):
        self.fwd = self.turn = 0.0

    release_stick = release_drive

    def set_control(self, cid, value):
        if not self.has_level and cid.startswith("level."):
            return False
        if cid == "level.assist":
            self.assist = int(value)
        elif cid == "level.pref.pitch":
            self.pref[0] = value
        elif cid == "level.pref.roll":
            self.pref[1] = value
        self.calls.append(("set", cid, value))
        return True

    def level(self):
        if not self.has_level:
            return None
        on = self.assist and self.mode_id == "differential"
        return {"assist": float(self.assist), "state": 1.0 if on else (5.0 if self.assist else 0.0), "tilt": 0.0,
                "reach": 0.7 if on else 1.0, "speed_scale": 1.0, "pref_pitch": self.pref[0], "pref_roll": self.pref[1],
                "status": "Levelling" if on else "Off", "sev": 0.0}

    def mode(self):
        return self.mode_id

    def set_mode(self, mode_id):
        self.mode_id = mode_id
        return True

    def commands(self):
        return {"leg": [0.1, 0.01 * (self.corr[0] + self.corr[1]), 0.1]}

    def ground(self):
        return {"n": {w["name"]: 100.0 for w in WHEELS}, "others": 0.0, "com": [self.x, self.y],
                "pts": {w["name"]: [p[0], p[1]] for w, p in zip(WHEELS, self.pts())}}

    def status(self):
        return ""

    def abort(self):
        pass


class Editor(object):
    """A stand-in `unreal` module with as much editor behind it as runner_op.py touches."""

    def __init__(self):
        ed = self
        self.game_world = None
        self.loaded = None
        self.cvars = {"t.MaxFPS": 0.0, "urlab.LockedFrameSeconds": 0.0, "Ramms.Curb.PlanInStep": 0.0}
        self.console_robot = ""
        self.callback = None
        self.pending_world = None
        start = types.SimpleNamespace(loc=Vec(1.0, 2.0, 3.0), rot="rot0")
        start.get_class = lambda: types.SimpleNamespace(get_name=lambda: "PlayerStart")
        start.get_actor_location = lambda: start.loc
        start.get_actor_rotation = lambda: start.rot
        start.set_actor_location = lambda v, a, b: setattr(start, "loc", v)
        start.set_actor_rotation = lambda r, a: setattr(start, "rot", r)
        self.start = start
        m = types.ModuleType("unreal")
        m.Vector = Vec
        m.LevelEditorSubsystem, m.UnrealEditorSubsystem, m.EditorActorSubsystem = "les", "ues", "eas"
        subsystems = {
            "les": types.SimpleNamespace(load_level=lambda p: setattr(ed, "loaded", p) or True,
                                         editor_request_begin_play=lambda: setattr(ed, "game_world", ed.pending_world),
                                         editor_request_end_play=lambda: setattr(ed, "game_world", None)),
            "ues": types.SimpleNamespace(get_game_world=lambda: ed.game_world,
                                         get_editor_world=lambda: types.SimpleNamespace(get_path_name=lambda: "/Game/Maps/Level/X.X")),
            "eas": types.SimpleNamespace(get_all_level_actors=lambda: [ed.start]),
        }
        m.get_editor_subsystem = lambda c: subsystems[c]
        m.Paths = types.SimpleNamespace(project_dir=lambda: os.path.normpath(os.path.join(RUNNER, "..", "..")) + os.sep,
                                        get_project_file_path=lambda: "C:/x/Ramms.uproject")

        def console(_, cmd):
            name, value = cmd.split(None, 1)
            ed.cvars[name] = float(value)
        m.SystemLibrary = types.SimpleNamespace(execute_console_command=console,
                                                get_console_variable_float_value=lambda n: ed.cvars.get(n))
        m.GameplayStatics = types.SimpleNamespace(get_time_seconds=lambda w: w.robot.t)
        m.RammsRobotBridge = types.SimpleNamespace(get_active_robot_id=lambda: ROBOT_ID, get_active_robot_source=lambda: "console")
        m.RammsRobotCatalog = types.SimpleNamespace(get_console_robot=lambda: ed.console_robot,
                                                    set_console_robot=lambda r: setattr(ed, "console_robot", r))
        m.MathLibrary = types.SimpleNamespace(make_rot_from_xz=lambda x, z: ("rot", x.x, x.y, x.z, z.x, z.y, z.z))
        m.register_slate_post_tick_callback = lambda f: setattr(ed, "callback", f) or 1
        m.unregister_slate_post_tick_callback = lambda h: setattr(ed, "callback", None)
        self.module = m

    def load_runner(self):
        sys.modules["unreal"] = self.module
        path = os.path.join(RUNNER, "runner_op.py")
        ns = {"__name__": "runner_op_under_test", "__file__": path}
        with open(path, encoding="utf-8") as f:
            exec(compile(f.read(), path, "exec"), ns)  # its main() answers "status" with no session
        return ns


def run_session(tmp, course_id, level, robot_kw=None, max_frames=6000, timeout_wall_s=1800.0, **plan_kw):
    """Run one case through begin_course; returns (the trace, the robot, the editor, runner_op's namespace)."""
    ed = Editor()
    ns = ed.load_runner()
    plan = course.plan(course_id, level=level, alt_mode=PROFILE["level"]["alt_mode"], **plan_kw)
    robot = Robot(lt.layout(course_id), plan["start"], **(robot_kw or {}))
    ed.pending_world = types.SimpleNamespace(robot=robot)
    name = course.case_name(course_id, plan["dir"], plan["start"]["name"], plan["variant"], level, plan["pref"], plan["stick"],
                            plan["hold"]["on"])
    cfg = {"robot_id": ROBOT_ID, "adapter": PROFILE["editor"], "wheels": WHEELS, "rider_body": None, "imu": False,
           "setup": {"stance": "outdoor"}, "plan": plan, "max_fps": 30.0, "locked_frame_s": 0.0625, "timeout_wall_s": timeout_wall_s,
           "trace_path": os.path.join(tmp, name + ".trace.json"), "token": name}
    cfg = json.loads(json.dumps(cfg))  # as it arrives: through JSON
    ns["op_begin_course"](cfg)
    frames = 0
    while ed.callback is not None and frames < max_frames:
        robot.step()
        ed.callback(DT)
        frames += 1
    trace = None
    if os.path.exists(cfg["trace_path"]):
        with open(cfg["trace_path"], encoding="utf-8") as f:
            trace = json.load(f)
    return trace, robot, ed, ns


class Session(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = sys.modules.get("unreal")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self.saved is None:
            sys.modules.pop("unreal", None)
        else:
            sys.modules["unreal"] = self.saved

    def test_a_run_from_gate_to_trace(self):
        trace, robot, ed, ns = run_session(self.tmp, "RAMP5", "on")
        self.assertIsNone(trace["error"])
        self.assertEqual(ed.loaded, "/Game/Maps/Level/Map_Level_RAMP5_URL")
        self.assertEqual(trace["kind"], "course")
        self.assertEqual(trace["clock"], "physics")
        self.assertEqual(trace["setup_done"], {"stance": "outdoor"})
        gate = trace["gate"]
        self.assertAlmostEqual(gate["t"], course.GATE_AT_S, delta=DT)
        self.assertTrue(gate["steady"]["steady"])
        self.assertAlmostEqual(gate["rider_zero"][0], 1.5, places=3)  # the seat's mount, taken at the gate
        self.assertAlmostEqual(trace["go_t"], gate["t"] + course.SETTLE_S, places=6)
        self.assertEqual([(e["do"], e["ok"]) for e in trace["events"]], [("pref", True), ("assist", True)])
        self.assertAlmostEqual(trace["events"][1]["t"], gate["t"], places=6)  # armed on the gate's frame
        self.assertTrue(trace["go"]["level_ready"])
        self.assertEqual(trace["end"]["why"], "end line")
        self.assertGreaterEqual(trace["end"]["d"], trace["cfg"]["plan"]["end"]["d"])
        self.assertEqual(trace["end_why"], "ended")
        self.assertEqual((robot.fwd, robot.turn), (0.0, 0.0))  # the stick let go
        self.assertAlmostEqual(trace["samples"][-1]["t"], trace["end"]["t"] + course.POST_S, delta=2 * DT)
        self.assertAlmostEqual(trace["samples"][0]["t"], course.GATE_AT_S - ns["TRACE_LEAD_S"], delta=DT)
        s = next(x for x in trace["samples"] if x["t"] > trace["go_t"] + 2.0)
        for key in ("chassis", "seat", "wheels", "pref", "stick", "steer", "level", "mode", "cmd", "ground"):
            self.assertIn(key, s)
        self.assertEqual(s["stick"][0], 1.0)
        self.assertEqual(s["mode"], "differential")
        self.assertEqual(trace["locked_frame_s_set"], 0.0625)
        self.assertEqual(trace["locked_frame_s_end"], 0.0625)
        # No stick before go.
        self.assertTrue(all(x["stick"] == [0.0, 0.0] for x in trace["samples"] if x["t"] < trace["go_t"] - 1e-6))
        # And `end` puts the editor back as it was.
        ns["op_end"]()
        self.assertEqual(ed.cvars["urlab.LockedFrameSeconds"], 0.0)
        self.assertEqual(ed.cvars["t.MaxFPS"], 0.0)
        self.assertEqual(ed.console_robot, "")
        self.assertEqual((ed.start.loc.x, ed.start.rot), (1.0, "rot0"))  # the PlayerStart back where it was

    def test_the_start_is_placed(self):
        ed = Editor()
        ns = ed.load_runner()
        plan = course.plan("PARK", start="pad_grade", level="off", variant="parked")
        placed = ns["place_course_start"](plan["start"])
        self.assertAlmostEqual(placed["xyz"][0], plan["start"]["xyz"][0])
        self.assertEqual(ed.start.rot[0], "rot")
        self.assertAlmostEqual(math.degrees(math.asin(ed.start.rot[3])), 6.0, places=4)  # lying on the 6 deg pad
        self.assertTrue(ns["restore_start"]())
        self.assertEqual(ed.start.loc.x, 1.0)

    def test_on_and_off_cover_the_same_ground_and_score(self):
        off, _, _, _ = run_session(self.tmp, "TRANSITIONS", "off")
        on, _, _, _ = run_session(self.tmp, "TRANSITIONS", "on")
        f_off, f_on = lm.figures(off, PROFILE["level"]), lm.figures(on, PROFILE["level"])
        self.assertEqual([s["name"] for s in f_on["segments"]], ["in", "up", "top", "fall_left", "fall_right", "down_cross", "out"])
        by = {s["name"]: s for s in f_off["segments"]}
        self.assertAlmostEqual(by["up"]["rider_residual_deg"], 5.0, delta=0.1)
        self.assertAlmostEqual(by["fall_left"]["rider_mean_deg"][1], 4.0, delta=0.1)
        for s in f_on["segments"]:
            self.assertLess(s["rider_residual_deg"], 0.1, s["name"])
        # The hold kept both on the path, against the cross slope's pull, and its effort is in the figures.
        for f in (f_off, f_on):
            self.assertLess(abs(f["overall"]["lateral_peak_cm"]), 25.0)
            self.assertGreater(f["overall"]["steer_abs_mean"], 0.005)
        left = by["fall_left"]
        self.assertLess(left["steer_mean"], -0.01)  # pulled clockwise there: held back the other way
        p = lm.pair(f_on, f_off)
        self.assertLess(p["rejection_slopes_max"], 0.3)
        self.assertGreater(p["speed_kept"], 0.95)

    def test_the_hold_brings_a_yawed_start_back(self):
        trace, _, _, _ = run_session(self.tmp, "FLAT", "off", start="yaw5")
        f = lm.figures(trace, PROFILE["level"])
        s0 = next(x for x in trace["samples"] if x["t"] >= trace["go_t"])
        self.assertAlmostEqual(s0["steer"]["yaw_err"], 5.0, places=3)
        self.assertLess(s0["stick"][1], 0.0)  # turned back toward the path at once
        self.assertLess(abs(f["overall"]["yaw_end_deg"]), 0.5)
        self.assertLess(abs(f["overall"]["lateral_end_cm"]), 5.0)

    def test_without_the_hold_the_drift_shows(self):
        trace, _, _, _ = run_session(self.tmp, "CROSS6", "off", hold={"on": False})
        self.assertTrue(all(x["stick"][1] == 0.0 for x in trace["samples"]))
        f = lm.figures(trace, PROFILE["level"])
        self.assertGreater(abs(f["overall"]["yaw_change_deg"]), 5.0)  # the raw tendency, nothing hiding it
        held, _, _, _ = run_session(self.tmp, "CROSS6", "off")
        self.assertLess(abs(lm.figures(held, PROFILE["level"])["overall"]["yaw_change_deg"]), abs(f["overall"]["yaw_change_deg"]))

    def test_leaving_the_lane_ends_the_run(self):
        trace, robot, _, _ = run_session(self.tmp, "RAMP5", "off", start="yaw5", hold={"on": False},
                                         robot_kw={"pull_per_deg": 0.0})
        self.assertEqual(trace["end"]["why"], "left the lane")
        self.assertLess(abs(robot.y), lt.layout("RAMP5").half)  # stopped before the edge

    def test_a_robot_without_the_assist(self):
        trace, _, _, _ = run_session(self.tmp, "RAMP5", "on", robot_kw={"has_level": False})
        self.assertEqual([(e["do"], e["ok"]) for e in trace["events"]], [("pref", True), ("assist", False)])  # a zero preference: nothing to set
        self.assertNotIn("level", trace["samples"][5])
        self.assertFalse(trace["go"]["level_ready"])
        self.assertEqual(trace["end"]["why"], "end line")  # it still drives the course: a baseline

    def test_events_on_the_way(self):
        trace, robot, _, _ = run_session(self.tmp, "RAMP5", "on", variant="mode")
        self.assertEqual([e["label"] for e in trace["events"]],
                         ["preference +0, +0", "assist on", "stop", "mode holonomic", "mode differential", "go"])
        stop, m1, m2, go = trace["events"][2:]
        self.assertAlmostEqual(m1["t"] - stop["t"], 1.5, delta=DT)
        self.assertAlmostEqual(m2["t"] - m1["t"], course.MODE_STAY_S, delta=DT)
        self.assertAlmostEqual(go["t"] - m2["t"], course.MODE_STAY_S, delta=DT)
        standing = [x for x in trace["samples"] if stop["t"] + 1.0 < x["t"] < go["t"]]
        self.assertTrue(all(x["stick"] == [0.0, 0.0] for x in standing))
        self.assertAlmostEqual(standing[0]["chassis"]["xyz"][0], standing[-1]["chassis"]["xyz"][0], places=3)
        self.assertEqual({x["mode"] for x in standing if m1["t"] < x["t"] < m2["t"]}, {"holonomic"})
        self.assertEqual(trace["end"]["why"], "end line")
        f = lm.figures(trace, PROFILE["level"])
        self.assertEqual(f["overall"]["stops"], 0)  # the stop was asked for
        labels = [t["label"] for t in f["transitions"] if t["kind"] == "event"]
        self.assertEqual(labels, ["assist on", "stop", "mode holonomic", "mode differential", "go", "stop at the end"])

    def test_a_distance_event_waits_for_go(self):
        # An event by distance fires on the way, never while the robot settles before go (it stands at d = 0 then).
        ev = [{"t": -course.SETTLE_S, "do": "assist", "value": 1, "label": "assist on"},
              {"d": -50.0, "do": "set", "id": "x.y", "value": 1.0, "label": "behind the start"},
              {"d": 300.0, "do": "pref", "pitch": 2.0, "roll": 0.0, "label": "preference +2, +0"}]
        trace, robot, _, _ = run_session(self.tmp, "FLAT", "on", events=ev)
        by = {e["label"]: e for e in trace["events"]}
        self.assertAlmostEqual(by["assist on"]["t_rel"], -course.SETTLE_S, places=6)
        self.assertAlmostEqual(by["behind the start"]["t_rel"], 0.0, places=6)  # on go's own frame
        self.assertGreaterEqual(by["preference +2, +0"]["d"], 300.0)
        self.assertLess(by["preference +2, +0"]["d"], 300.0 + 60.0 * DT + 0.5)
        after = next(x for x in trace["samples"] if x["t"] >= by["preference +2, +0"]["t"])
        self.assertEqual(after["pref"], [2.0, 0.0])  # the sample of the frame it fired on already carries it

    def test_parked(self):
        trace, robot, _, _ = run_session(self.tmp, "PARK", "on", start="pad_cross", variant="parked")
        self.assertEqual(trace["end"]["why"], "end time")
        self.assertAlmostEqual(trace["end"]["t"] - trace["go_t"], course.PARK_HOLD_S + course.PARK_TAIL_S, delta=DT)
        self.assertTrue(all(x["stick"] == [0.0, 0.0] for x in trace["samples"]))
        f = lm.figures(trace, PROFILE["level"])
        self.assertEqual(f["parked"]["drift_cm"], 0.0)
        on = f["transitions"][0]
        self.assertEqual(on["label"], "assist on")
        self.assertAlmostEqual(on["rider_start_deg"], 6.0, delta=0.05)

    def test_a_timeout_writes_the_trace(self):
        trace, _, _, _ = run_session(self.tmp, "RAMP5", "off", robot_kw={"pull_per_deg": 0.0}, stick=0.01)
        self.assertEqual(trace["end"]["why"], "timeout")
        self.assertEqual(trace["end_why"], "timeout")

    def test_a_bad_plan_is_refused_before_pie(self):
        ed = Editor()
        ns = ed.load_runner()
        plan = course.plan("RAMP5", level="off")
        plan["events"] = [{"do": "fly", "t": 0.0}]
        ed.pending_world = types.SimpleNamespace(robot=None)
        with self.assertRaises(ValueError):
            ns["op_begin_course"]({"robot_id": ROBOT_ID, "plan": plan})
        self.assertIsNone(ed.game_world)

    def test_a_crossing_session_is_untouched(self):
        # The curb crossing's own step still runs when the session is not a course.
        ed = Editor()
        ns = ed.load_runner()
        self.assertIn("step", ns)
        self.assertIn("op_begin", ns)
        self.assertEqual(ns["op_status"](), {"stage": None})


class Pipeline(unittest.TestCase):
    """run_level.py's rows, the history and the report, from traces a session wrote."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = sys.modules.get("unreal")
        import run_level
        self.rl = run_level
        history.LEVEL_HISTORIES.clear()
        self.hist = os.path.join(self.tmp, "level_history.jsonl")
        history.register_level("testbot", self.hist, PROFILE["level"]["standard"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        history.LEVEL_HISTORIES.clear()
        if self.saved is None:
            sys.modules.pop("unreal", None)
        else:
            sys.modules["unreal"] = self.saved

    def run_dir(self, cases):
        d = os.path.join(self.tmp, "run")
        os.makedirs(d, exist_ok=True)
        rows = []
        for course_id, kw in cases:
            for level in ("off", "on"):
                trace, _, _, _ = run_session(d, course_id, level, **kw)
                plan = trace["cfg"]["plan"]
                case = {"course": course_id, "dir": plan["dir"], "start": plan["start"]["name"], "variant": plan["variant"],
                        "pref": tuple(plan["pref"]), "stick": plan["stick"], "hold": plan["hold"]["on"]}
                row = self.rl.row_of(PROFILE, case, level, trace, "2026-11-23T12:00:00+00:00", trace["cfg"]["token"])
                row["rep"] = 1
                rows.append(row)
        self.rl.finish_rows(PROFILE, rows)
        self.rl.write_results(d, rows)
        history.write_run_side_file(d, {"sim": {"sha": "abc", "dirty": False}}, {"argv": ["run_level.py", "--out", d],
                                                                               "started": "2026-11-23T12:00:00+00:00"})
        return d, rows

    def test_rows_pair_score_history_and_report(self):
        d, rows = self.run_dir([("RAMP5", {}), ("RAMP5", {"variant": "toggle"}), ("PARK", {"start": "pad_grade", "variant": "parked"})])
        off, on = rows[0], rows[1]
        self.assertEqual((off["level"], on["level"]), ("off", "on"))
        self.assertIsNone(off["outcome"]["met"])  # a baseline
        self.assertEqual(off["outcome"]["expect"], "pass")
        self.assertTrue(on["outcome"]["met"], on["outcome"])
        self.assertLess(on["pair"]["rejection_slopes_max"], 0.3)
        self.assertEqual(on["settings"]["locked_frame_s"], 0.0625)
        self.assertTrue(on["settings"]["steady"])
        self.assertEqual(on["settings"]["robot"], {"stance": "outdoor"})
        self.assertEqual(on["trace"], on["case"] + ".trace.json")
        self.assertEqual(rows[3]["outcome"]["expect"], "rates")
        self.assertTrue(os.path.exists(os.path.join(d, "level_summary.md")))
        # The history: one record per run, the on record with its pair; added again, replaced not doubled.
        self.assertEqual(history.add_level_runs([d], quiet=True), 6)
        self.assertEqual(history.add_level_runs([d], quiet=True), 6)
        recs = history.read_history(self.hist)
        self.assertEqual(len(recs), 6)
        r = next(x for x in recs if x["level"] == "on" and x["variant"] == "drive")
        self.assertEqual((r["group"], r["schema"], r["robot"], r["course"], r["dir"], r["start"]), ("level", 1, "testbot", "RAMP5", "fwd", "centre"))
        self.assertTrue(r["settings"]["standard"])
        self.assertTrue(r["hold"])
        self.assertIsNotNone(r["pair"]["rejection"])
        self.assertEqual(r["code"], {"ran_on": {"sim": {"sha": "abc", "dirty": False}}})
        self.assertEqual(len({history.level_key(x) for x in recs}), 6)
        self.assertFalse(os.path.isabs(r["run"]["dir"]))
        # The report: a page with a figure per case, each figure a well-formed SVG of its own too.
        import level_report
        page = level_report.write(d)
        with open(page, encoding="utf-8") as fh:
            html = fh.read()
        self.assertEqual(html.count("<svg"), 3)
        self.assertIn("rejection", html)
        self.assertIn("Transitions", html)
        svgs = sorted(os.listdir(os.path.join(d, "figures")))
        self.assertEqual(len(svgs), 3)
        for name in svgs:
            root = ET.parse(os.path.join(d, "figures", name)).getroot()
            self.assertTrue(root.tag.endswith("svg"))
            paths = [e for e in root.iter() if e.tag.endswith("path")]
            self.assertGreaterEqual(len(paths), 10)  # the ground, the preference, rider and chassis on and off, ...
        self.assertLess(os.path.getsize(page), 3_000_000)
        hp = level_report.history_page(recs, os.path.join(self.tmp, "history.html"))
        with open(hp, encoding="utf-8") as fh:
            self.assertIn("RAMP5 fwd centre drive", fh.read())
        # And the rows can be made again from the traces.
        again = self.rl.rescore.__globals__["robots"]
        saved = again.find
        again.find = lambda words: PROFILE
        try:
            new = self.rl.rescore(d)
        finally:
            again.find = saved
        self.assertEqual([x["outcome"].get("met") for x in new], [x["outcome"].get("met") for x in rows])
        self.assertEqual(new[1]["figures"]["overall"]["rider_rms_deg"], on["figures"]["overall"]["rider_rms_deg"])

    def test_an_on_run_the_robot_refused_fails(self):
        d = os.path.join(self.tmp, "r2")
        os.makedirs(d)
        trace, _, _, _ = run_session(d, "RAMP5", "on", robot_kw={"has_level": False})
        case = {"course": "RAMP5", "dir": "fwd", "start": "centre", "variant": "drive", "pref": (0.0, 0.0), "stick": 1.0, "hold": True}
        row = self.rl.row_of(PROFILE, case, "on", trace, None, "x")
        row["rep"] = 1
        self.rl.finish_rows(PROFILE, [row])
        self.assertFalse(row["outcome"]["met"])
        self.assertIn("did not take", row["outcome"]["why"])

    def test_a_public_history_takes_no_private_line(self):
        history.register_level("gen2", self.hist, lambda r: True, public=True)
        d = os.path.join(self.tmp, "r3")
        os.makedirs(d)
        row = {"group": "level", "history_robot": "gen2", "robot_id": "x", "course": "FLAT", "dir": "fwd", "start": "centre", "variant": "drive",
               "level": "off", "pref": [0, 0], "stick": 1.0, "hold": {"on": True}, "outcome": {"end": "end line"}, "figures": {}}
        with open(os.path.join(d, history.LEVEL_RESULTS), "w", encoding="utf-8") as f:
            json.dump([row], f)
        with self.assertRaises(ValueError):
            history.add_level_runs([d], quiet=True)
        self.assertFalse(os.path.exists(self.hist))

    def test_an_error_row_is_not_recorded(self):
        d = os.path.join(self.tmp, "r4")
        os.makedirs(d)
        case = {"course": "FLAT", "dir": "fwd", "start": "centre", "variant": "drive", "pref": (0.0, 0.0), "stick": 1.0, "hold": True}
        with open(os.path.join(d, history.LEVEL_RESULTS), "w", encoding="utf-8") as f:
            json.dump([self.rl.error_row(PROFILE, case, "on", "no editor")], f)
        self.assertEqual(history.add_level_runs([d], quiet=True), 0)

    def test_cases(self):
        args = types.SimpleNamespace(courses="RAMP5,CROWN", dirs="fwd", variants="drive,mode", pref=["0,0", "3,-2"], stick=None,
                                     hold="both", starts="centre,cross20")
        cases = self.rl.cases_of(args, PROFILE)
        # RAMP5 has no cross20 start: 1 start x 2 variants x 2 prefs x 2 holds; CROWN has both starts.
        self.assertEqual(len([c for c in cases if c["course"] == "RAMP5"]), 8)
        self.assertEqual(len([c for c in cases if c["course"] == "CROWN"]), 16)
        self.assertEqual(self.rl.parse_pref("3, -2"), (3.0, -2.0))
        with self.assertRaises(ValueError):
            self.rl.parse_pref("3")
        with self.assertRaises(ValueError):
            self.rl.cases_of(types.SimpleNamespace(courses="NOPE", dirs="fwd", variants="drive", pref=None, stick=None, hold="on",
                                                   starts="centre"), PROFILE)


if __name__ == "__main__":
    unittest.main()
