"""The curb runner's operations inside the editor (run_curb.py sends them; Scripts/pie_tests/common.py's op pattern).

    begin <json>   open the scenario's public curb map, place the robot's start, choose the robot (ramms.Robot), cap
                   the frame rate, begin PIE and arm the crossing session (below); json: robot_id, adapter (the
                   editor-side adapter file), wheels, rider_body, scenario ("Flat" or a curb_terrain id), dir,
                   start ("climb" | "top"), start_offset_cm, setup, setup_at_s, ask_sim_s, stick, max_fps,
                   locked_frame_s (urlab.LockedFrameSeconds for the session; 0 off; above 0, plans are waited for
                   where they are asked, Ramms.Curb.PlanInStep), post_s, timeout_sim_s,
                   timeout_wall_s, trace_path
    begin_course <json>  a level-assist course run instead of a crossing (course.py's plan; see "The course
                   session" below): open the course's map, place the start, choose the robot, begin PIE and arm the
                   session; json: robot_id, adapter, wheels, rider_body, imu, setup, plan, max_fps, locked_frame_s,
                   timeout_wall_s, trace_path, token
    status         the session's stage and what it has seen: {"stage", "sim", "phase", "status", "error", "finished"}
    end            end PIE, stop the session, release the stick, put back the PlayerStart, t.MaxFPS and ramms.Robot
    probe          the robot as the adapter reads it now (chassis, wheels and their gaps, phase, status)

The session runs in the editor's own tick (a Slate post-tick callback), so nothing it times waits on a remote call, and
by the physics' own clock (the adapter's sim_time: the robot base's simulation time, what the controller reads) -- with
frame-locked stepping on (urlab.LockedFrameSeconds) the physics and the world's clock part company:
  - once the robot is there: its adapter's prepare(setup) at setup_at_s of simulated time;
  - from ask_sim_s - STEADY_LEAD_S: the steady gate (the chassis within STEADY_CM and STEADY_DEG over STEADY_WINDOW_S,
    no powered wheel faster than STEADY_RAD_S); the ask on the frame nearest ask_sim_s once steady (at most
    STEADY_MAX_WAIT_S later, then anyway, flagged unsteady);
  - after an accepted ask: the rider's stick held (`stick`) on every frame the crossing is under way (its planning
    included), let go on the first frame it has ended (the drive mode it hands back to never sees it);
  - a trace sample every frame from TRACE_LEAD_S before the ask (measures.py's sample format), and every physics step's
    IMU sample of the rider's body (URammsSensingBridge.ReadImuSamplesJson);
  - post_s after the end (or a refusal), or at a timeout (aborted then): the trace written to trace_path, finished.
"""

import importlib
import json
import math
import os
import sys
import time

import unreal

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None
TAG = "CURBRUN"
VAR = "_curb_runner_op"

STEADY_WINDOW_S = 0.5
STEADY_CM = 0.25
STEADY_DEG = 0.1
STEADY_RAD_S = 0.5
STEADY_MAX_WAIT_S = 5.0
STEADY_LEAD_S = 1.0
TRACE_LEAD_S = 1.0
ROBOT_WAIT_SIM_S = 5.0  # PIE without a robot the adapter knows this long: an error, not a wait
LOCK_CVAR = "urlab.LockedFrameSeconds"  # frame-locked stepping (URLab): 0 off
# With a fixed lock, a plan the robot's controller asks for is waited for where it is asked (RammsCore's curb planner;
# a robot without one ignores it): taken on the same frame in every run, so a locked run repeats exactly.
PLAN_CVAR = "Ramms.Curb.PlanInStep"
TERMINAL = ("DONE", "FAULTED", "ABORTED")

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def here():
    return HERE or os.path.join(unreal.Paths.project_dir(), "Scripts", "curb_runner")


def out(d):
    print(TAG + " " + json.dumps(d))


def terrain():
    """curb_terrain, reloaded: the editor outlives edits to it."""
    p = os.path.normpath(os.path.join(here(), "..", "curb_maps"))
    if p not in sys.path:
        sys.path.insert(0, p)
    import curb_terrain
    return importlib.reload(curb_terrain)


def load_adapter(path):
    """The adapter module at path, compiled once per version of the file (by mtime)."""
    key = (path, os.path.getmtime(path))
    cache = getattr(unreal, "_curb_runner_adapters", None) or {}
    mod = cache.get(path)
    if mod is None or mod.get("__key__") != key:
        with open(path, encoding="utf-8") as f:
            code = compile(f.read(), path, "exec")
        mod = {"__name__": "curb_robot_editor", "__file__": path, "__key__": key}
        exec(code, mod)
        cache[path] = mod
        unreal._curb_runner_adapters = cache
    return mod


def world():
    return ues.get_game_world()


def sim_time(w):
    return unreal.GameplayStatics.get_time_seconds(w)


def stop_session():
    h = getattr(unreal, "_curb_runner_handle", None)
    if h is not None:
        unreal.unregister_slate_post_tick_callback(h)
        unreal._curb_runner_handle = None


def session():
    return getattr(unreal, "_curb_runner_session", None)


def player_start():
    starts = [a for a in eas.get_all_level_actors() if a.get_class().get_name() == "PlayerStart"]
    if len(starts) != 1:
        raise RuntimeError("expected one PlayerStart in the level, found %d" % len(starts))
    return starts[0]


def restore_start():
    moved = getattr(unreal, "_curb_runner_moved_start", None)
    if not moved:
        return False
    unreal._curb_runner_moved_start = None
    path, loc, rot = moved
    w = ues.get_editor_world()
    if w is None or w.get_path_name() != path:
        return False
    try:
        start = player_start()
    except RuntimeError:
        return False
    start.set_actor_location(loc, False, False)
    start.set_actor_rotation(rot, False)
    return True


def place_start(ct, cfg):
    """Move the PlayerStart (the editor's copy of the level, which PIE duplicates; never saved, put back by `end`): a
    climb's start_offset_cm ahead along its heading, on the surface; a descent's on the sidewalk (top_start_pose)."""
    start = player_start()
    unreal._curb_runner_moved_start = (ues.get_editor_world().get_path_name(), start.get_actor_location(),
                                       start.get_actor_rotation())
    if cfg["start"] == "top":
        # Where a descent from the sidewalk starts (curb_terrain: nearer the near edge on a sidewalk falling toward
        # the far one, where the robots rolled over the far edge before the crossing began).
        L = ct.Layout(ct.BY_ID[cfg["scenario"]])
        past = L.top_cross_past()
        loc, x_axis, z_axis = L.top_start_pose(past)
        start.set_actor_location(unreal.Vector(*loc), False, False)
        start.set_actor_rotation(unreal.MathLibrary.make_rot_from_xz(unreal.Vector(*x_axis), unreal.Vector(*z_axis)), False)
        return {"xyz": list(loc), "kind": "top", "past_cm": past}
    off = float(cfg.get("start_offset_cm") or 0.0)
    loc = start.get_actor_location()
    if off:
        f = start.get_actor_forward_vector()
        x, y = loc.x + f.x * off, loc.y + f.y * off
        if cfg["scenario"] != ct.FLAT and cfg["scenario"] in ct.BY_ID:
            z = ct.Layout(ct.BY_ID[cfg["scenario"]]).planes["near"].z(x, y) + ct.START_ABOVE_SURFACE
        else:
            z = loc.z
        start.set_actor_location(unreal.Vector(x, y, z), False, False)
        loc = start.get_actor_location()
    return {"xyz": [loc.x, loc.y, loc.z], "kind": "climb", "offset_cm": off}


def console(cmd):
    unreal.SystemLibrary.execute_console_command(None, cmd)


def cvar_float(name):
    try:
        return unreal.SystemLibrary.get_console_variable_float_value(name)
    except Exception:  # noqa: BLE001
        return None


# --- the session ----------------------------------------------------------------------------------------------------

class Steady(object):
    def __init__(self):
        self.window = []

    def step(self, t, chassis, rates):
        self.window.append((t, chassis["xyz"], (chassis["pitch"], chassis["roll"]), max([abs(r) for r in rates] or [0.0])))
        while len(self.window) > 2 and t - self.window[1][0] >= STEADY_WINDOW_S:
            self.window.pop(0)
        return self.measure()

    def measure(self):
        w = self.window
        if len(w) < 2:
            return {"steady": False, "span_s": 0.0}
        x0, a0 = w[0][1], w[0][2]
        moved = max(math.hypot(s[1][0] - x0[0], s[1][1] - x0[1]) for s in w)
        turned = max(max(abs(s[2][0] - a0[0]), abs(s[2][1] - a0[1])) for s in w)
        rate = max(s[3] for s in w)
        span = w[-1][0] - w[0][0]
        return {"steady": span >= STEADY_WINDOW_S - 1e-6 and moved <= STEADY_CM and turned <= STEADY_DEG and rate <= STEADY_RAD_S,
                "span_s": round(span, 3), "moved_cm": round(moved, 3), "att_change_deg": round(turned, 3),
                "wheel_rate_max": round(rate, 3)}


def finish(s, why):
    """Write the trace and end the session (PIE stays up; `end` ends it)."""
    if s.get("finished"):
        return
    try:
        if s.get("adapter") is not None:
            s["adapter"].release_stick()
    except Exception:  # noqa: BLE001
        pass
    s["finished"] = True
    s["stage"] = "finished"
    s["end_why"] = why
    # URLab sets the lock's variable back to 0 if a batch stalls: a run whose lock did not hold to the end says so.
    s["locked_frame_s_end"] = cvar_float(LOCK_CVAR)
    rec = {k: s.get(k) for k in ("cfg", "start_placed", "robot_active", "robot_source", "setup_done", "setup_t", "ask",
                                 "refused", "end", "end_why", "imu_dropped", "imu_error", "imu_rate_hz", "frames", "error",
                                 "max_fps_set", "first_t", "clock", "locked_frame_s_set", "locked_frame_s_end",
                                 "plan_in_step_set")}
    rec["samples"] = s["samples"]
    rec["imu"] = s["imu"]
    path = s["cfg"]["trace_path"]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        s["error"] = "writing the trace: %s" % exc
    stop_session()


def tick(dt):
    s = session()
    if s is None or s.get("finished"):
        stop_session()
        return
    course = s.get("kind") == "course"
    try:
        (step_course if course else step)(s)
    except Exception as exc:  # noqa: BLE001  (PIE ended under it, or an adapter call failed)
        s["error"] = "%s: %s" % (type(exc).__name__, exc)
        (finish_course if course else finish)(s, "error")


def step(s):
    cfg = s["cfg"]
    w = world()
    now_wall = time.time()
    if w is None:
        if s["stage"] != "wait_pie" or now_wall - s["started_wall"] > 120.0:
            raise RuntimeError("PIE is not running")
        return
    t = sim_time(w)
    if s.get("adapter") is None:
        # The robot PIE started, checked before looking for it: another robot, or the picker (no robot: an id that
        # matched nothing), ends the session at once rather than waiting for a controller that never comes.
        s["robot_active"] = unreal.RammsRobotBridge.get_active_robot_id()
        s["robot_source"] = unreal.RammsRobotBridge.get_active_robot_source()
        if s["robot_active"] and s["robot_active"] != cfg["robot_id"]:
            raise RuntimeError("PIE started robot %r (%s), not %s" % (s["robot_active"], s["robot_source"], cfg["robot_id"]))
        mod = load_adapter(cfg["adapter"])
        s["adapter"] = mod["find"](w, cfg["wheels"])
        if s["adapter"] is None:
            if t > ROBOT_WAIT_SIM_S or now_wall - s["started_wall"] > 120.0:
                raise RuntimeError("no robot the adapter knows in PIE after %.1f s (active robot %r: %s)" % (
                    t, s["robot_active"], s["robot_source"]))
            return
        if s["robot_active"] != cfg["robot_id"]:
            raise RuntimeError("PIE started robot %r (%s), not %s" % (s["robot_active"], s["robot_source"], cfg["robot_id"]))
    t = s["adapter"].sim_time() if hasattr(s["adapter"], "sim_time") else t
    if t < 0.0:
        return  # nothing published yet
    if s.get("first_t") is None:
        s["first_t"] = round(t, 4)
        s["clock"] = "physics" if hasattr(s["adapter"], "sim_time") else "world"
        s["actor_path"] = s["adapter"].pawn.get_path_name()
        s["stage"] = "setup"
    if s.get("last_t") is not None and t <= s["last_t"]:
        # The same physics state as the last frame (nothing stepped): nothing new to see or do -- but a physics that
        # never steps again still times out.
        if now_wall - s["started_wall"] > cfg["timeout_wall_s"]:
            if s.get("ask") and not s.get("end"):
                s["adapter"].abort()
            s["end"] = s.get("end") or {"t": round(t, 4), "phase": "TIMEOUT", "status": s["adapter"].status()}
            finish(s, "timeout")
        return
    a = s["adapter"]
    frame_dt = t - s["last_t"] if s.get("last_t") is not None else None
    s["last_t"] = t
    s["frames"] = s.get("frames", 0) + 1

    if t - s["first_t"] > cfg["timeout_sim_s"] or now_wall - s["started_wall"] > cfg["timeout_wall_s"]:
        if s.get("ask") and not s.get("end"):
            a.abort()
        s["end"] = s.get("end") or {"t": round(t, 4), "phase": "TIMEOUT", "status": a.status()}
        finish(s, "timeout")
        return

    if s.get("setup_done") is None and t >= cfg["setup_at_s"]:
        s["setup_done"] = a.prepare(cfg.get("setup") or {})
        s["setup_t"] = round(t, 4)

    ask_t = cfg["ask_sim_s"]
    tracing = t >= ask_t - TRACE_LEAD_S
    chassis = a.chassis()
    generic, raw = a.phase()
    if tracing:
        if s.get("imu_next") is None:
            s["imu_next"] = imu_read(s, -1)
        else:
            s["imu_next"] = imu_read(s, s["imu_next"])
        # imu_t: the physics' own clock (the IMU samples' sim_time), which starts later than the world's: the
        # newest IMU sample read this frame, so a world-clock trace's two clocks can be lined up
        # (measures.imu_clock_offset; a physics-clock trace needs none, run_curb.row_of).
        sample = {"t": round(t, 5), "wall": round(now_wall, 3), "imu_t": s.get("imu_last_t"), "phase": generic, "raw": raw,
                  "chassis": rnd_pose(chassis),
                  "wheels": [[round(x, 3) for x in h] if h else None for h in a.wheel_hubs()]}
        seat = a.seat()
        if seat:
            sample["seat"] = {k: round(v, 4) for k, v in seat.items()}
        st = a.status()
        if st != s.get("last_status"):
            sample["status"] = st
            s["last_status"] = st
        s["samples"].append(sample)

    if s.get("ask") is None:
        if t < ask_t - STEADY_LEAD_S:
            return
        m = s["steady"].step(t, chassis, a.wheel_rates())
        due = t >= ask_t or (frame_dt and t < ask_t <= t + frame_dt and (t + frame_dt - ask_t) > (ask_t - t))
        if not due:
            return
        if not m["steady"] and t < ask_t + STEADY_MAX_WAIT_S:
            return
        s["lifts_at_ask"] = a.lifts()
        ok, words = a.negotiate()
        s["ask"] = {"t": round(t, 5), "asked_for": ask_t, "late_s": round(max(0.0, t - ask_t), 4), "steady": m,
                    "frame_dt": round(frame_dt, 5) if frame_dt else None, "accepted": ok, "words": words,
                    "chassis": rnd_pose(chassis), "lifts": s["lifts_at_ask"]}
        s["stage"] = "crossing" if ok else "refused"
        if not ok:
            s["refused"] = words
            s["end"] = {"t": round(t, 4), "phase": "REFUSED", "status": words}
            s["post_until"] = t + min(cfg["post_s"], 0.5)
        return

    if s.get("end") is None:
        if generic in TERMINAL:
            a.release_stick()
            s["end"] = {"t": round(t, 5), "phase": generic, "raw": raw, "status": a.status(), "stats": a.stats(),
                        "step_found": a.step_found(), "lifts": a.lifts()}
            s["post_until"] = t + cfg["post_s"]
            s["stage"] = "post"
        elif generic != "IDLE":
            a.hold_stick(cfg.get("stick", 1.0))
        return

    if t >= s["post_until"]:
        s["end"]["stats_post"] = a.stats()
        finish(s, "ended")


def rnd_pose(c):
    return {"xyz": [round(x, 3) for x in c["xyz"]], "pitch": round(c["pitch"], 4), "yaw": round(c["yaw"], 4),
            "roll": round(c["roll"], 4)}


def imu_read(s, since):
    body = s["cfg"].get("rider_body")
    if not body:
        return since
    r = json.loads(unreal.RammsSensingBridge.read_imu_samples_json(s["actor_path"], body, json.dumps({"since": since})))
    if not r.get("ok"):
        s["imu_error"] = r.get("error") or r
        return since
    s["imu_dropped"] = (s.get("imu_dropped") or 0) + int(r.get("dropped") or 0)
    if r.get("rate_hz"):
        s["imu_rate_hz"] = r["rate_hz"]
    for x in r.get("samples") or []:
        s["imu"].append({"seq": x.get("seq"), "sim_time": x.get("sim_time"),
                         "linear_acceleration": x.get("linear_acceleration"), "orientation": x.get("orientation")})
        s["imu_last_t"] = x.get("sim_time")
    return r.get("next", since)


# --- the ops --------------------------------------------------------------------------------------------------------

def op_begin(cfg):
    if world() is not None:
        les.editor_request_end_play()
        raise RuntimeError("PIE was running -- ended it; begin again")
    if not unreal.Paths.get_project_file_path().replace("\\", "/").endswith("/Ramms.uproject"):
        raise RuntimeError("not the Ramms project's editor")
    stop_session()
    restore_start()
    ct = terrain()
    sid = None if cfg["scenario"] in (None, "", ct.FLAT) else cfg["scenario"]
    path = ct.map_path(sid)
    if not les.load_level(path):
        raise RuntimeError("could not load %s" % path)
    placed = place_start(ct, cfg)
    if getattr(unreal, "_curb_runner_saved", None) is None:
        unreal._curb_runner_saved = {"t.MaxFPS": cvar_float("t.MaxFPS"), "robot": unreal.RammsRobotCatalog.get_console_robot(),
                                     LOCK_CVAR: cvar_float(LOCK_CVAR), PLAN_CVAR: cvar_float(PLAN_CVAR)}
    if cfg.get("max_fps") is not None:
        console("t.MaxFPS %s" % cfg["max_fps"])  # 0: uncapped
    console("%s %s" % (LOCK_CVAR, float(cfg.get("locked_frame_s") or 0.0)))
    # (Pinned either way, as the lock is: a 1 left behind by hand or by a run that was killed would hold an unlocked
    # run's frames for its plans while its physics ran on.)
    console("%s %d" % (PLAN_CVAR, 1 if float(cfg.get("locked_frame_s") or 0.0) > 0.0 else 0))
    unreal.RammsRobotCatalog.set_console_robot(cfg["robot_id"])
    unreal._curb_runner_session = {"cfg": cfg, "stage": "wait_pie", "samples": [], "imu": [], "steady": Steady(),
                                   "started_wall": time.time(), "start_placed": placed, "finished": False,
                                   "max_fps_set": cvar_float("t.MaxFPS"), "locked_frame_s_set": cvar_float(LOCK_CVAR),
                                   "plan_in_step_set": cvar_float(PLAN_CVAR)}
    les.editor_request_begin_play()
    unreal._curb_runner_handle = unreal.register_slate_post_tick_callback(tick)
    return {"map": path, "start": placed}


def op_status():
    s = session()
    if s is None:
        return {"stage": None}
    w = world()
    d = {"stage": s.get("stage"), "finished": bool(s.get("finished")), "error": s.get("error"),
         "sim": round(sim_time(w), 3) if w else None, "ask": s.get("ask"), "end": s.get("end"), "frames": s.get("frames"),
         "imu_error": s.get("imu_error")}
    if s.get("kind") == "course":
        d.update({"kind": "course", "gate_t": (s.get("gate") or {}).get("t"), "go_t": s.get("go_t"), "d": s.get("d_now"),
                  "events": len(s.get("events") or [])})
        return d
    a = s.get("adapter")
    if a is not None and w is not None and not s.get("finished"):
        try:
            d["phase"], d["raw"] = a.phase()
            d["status"] = a.status()
        except Exception:  # noqa: BLE001
            pass
    return d


def op_end():
    s = session()
    stop_session()
    if s is not None and s.get("adapter") is not None:
        for release in ("release_stick", "release_drive"):
            try:
                getattr(s["adapter"], release)()
            except Exception:  # noqa: BLE001  (an adapter without it, or PIE already gone)
                pass
    if world() is not None:
        les.editor_request_end_play()
    saved = getattr(unreal, "_curb_runner_saved", None)
    if saved:
        if saved.get("t.MaxFPS") is not None:
            console("t.MaxFPS %s" % saved["t.MaxFPS"])
        if saved.get(LOCK_CVAR) is not None:
            console("%s %s" % (LOCK_CVAR, saved[LOCK_CVAR]))
        if saved.get(PLAN_CVAR) is not None:
            console("%s %d" % (PLAN_CVAR, int(saved[PLAN_CVAR])))
        unreal.RammsRobotCatalog.set_console_robot(saved.get("robot") or "")
        unreal._curb_runner_saved = None
    unreal._curb_runner_session = None
    return {"ended": True, "start_restored": restore_start()}


def op_probe(cfg):
    w = world()
    if w is None:
        raise RuntimeError("PIE is not running")
    a = load_adapter(cfg["adapter"])["find"](w, cfg["wheels"])
    if a is None:
        raise RuntimeError("no robot the adapter knows in PIE")
    ct = terrain()
    hubs = a.wheel_hubs()
    gaps = []
    for wh, h in zip(cfg["wheels"], hubs):
        surf = ct.Layout(ct.BY_ID[cfg["scenario"]]).surface_z(h[0], h[1]) if cfg.get("scenario") in ct.BY_ID else None
        gaps.append({"wheel": wh["name"], "hub": [round(x, 2) for x in h],
                     "gap_cm": round(h[2] - wh["radius_cm"] - surf, 2) if surf is not None else None})
    g, raw = a.phase()
    return {"sim": round(sim_time(w), 3), "chassis": rnd_pose(a.chassis()), "seat": a.seat(), "wheels": gaps,
            "phase": g, "raw": raw, "status": a.status(), "rates": a.wheel_rates(), "lifts": a.lifts(),
            "robot": unreal.RammsRobotBridge.get_active_robot_id()}


# --- the course session (level assist) ----------------------------------------------------------------------------
#
# A course run by the physics' own clock (course.py documents the timeline and the events):
#   - once the robot is there: its adapter's prepare(setup) at the plan's setup_at_s;
#   - from gate_at_s: the steady gate (as a crossing's); once it passes, the run's zero is taken (the seat against the
#     chassis, the lifts, the level controls) and "go" is set settle_s later;
#   - every frame from the gate: the events that are due fire (the assist, the preference, a mode switch, a stop, a
#     go), in the frame after the robot's state was read;
#   - from go: the stick held on every frame (the adapter's drive: drive.forward / drive.turn, source Script, in
#     whatever drive mode is active), drive.turn from the hold (course.steer) -- recorded, with the cross-track and
#     heading errors, in every sample;
#   - a sample every frame from TRACE_LEAD_S before the gate: measures.py's, and the level controls, the preference
#     asked for, the stick, the active mode, each levelled motor's baseline, offset and joint, the ground support;
#   - the end: the reference point past the end line (or the end time of a run that stays where it is), the robot at
#     the lane's side (ended there, said so), or a timeout; post_s later the trace is written.

LEVEL_READY = (1, 2)  # level.state Active or Holding


def course_module():
    """course.py (the schedule, the hold), reloaded: the editor outlives edits to it."""
    p = here()
    if p not in sys.path:
        sys.path.insert(0, p)
    import course
    return importlib.reload(course)


def place_course_start(st):
    """The PlayerStart at a course start's pose (the editor's copy of the level; never saved, put back by `end`)."""
    start = player_start()
    unreal._curb_runner_moved_start = (ues.get_editor_world().get_path_name(), start.get_actor_location(),
                                       start.get_actor_rotation())
    start.set_actor_location(unreal.Vector(*st["xyz"]), False, False)
    start.set_actor_rotation(unreal.MathLibrary.make_rot_from_xz(unreal.Vector(*st["x_axis"]), unreal.Vector(*st["z_axis"])), False)
    loc = start.get_actor_location()
    return {"xyz": [loc.x, loc.y, loc.z], "kind": "course", "name": st.get("name"), "dir": st.get("dir")}


def level_att(pose):
    """(pitch, roll with the right side up) of an adapter's {"pitch", "roll"} (a UE rotator's), as level_measures.att."""
    p, r = pose.get("pitch", 0.0), pose.get("roll", 0.0)
    return (p, math.degrees(math.asin(max(-1.0, min(1.0, -math.sin(math.radians(r)) * math.cos(math.radians(p)))))))


def opt(adapter, name, *args):
    """An adapter method a robot may not have: its answer, or None."""
    f = getattr(adapter, name, None)
    return f(*args) if f is not None else None


def fire_event(s, a, e, t, d):
    do = e["do"]
    ok = True
    if do == "assist":
        ok = bool(opt(a, "set_control", "level.assist", float(e["value"])))
    elif do == "pref":
        s["pref"] = [float(e["pitch"]), float(e["roll"])]
        if not any(s["pref"]) and opt(a, "level") is None:
            ok = True  # a robot without the assist has no preference to set, and zero is what it is scored against
        else:
            ok = bool(opt(a, "set_control", "level.pref.pitch", s["pref"][0])) and bool(opt(a, "set_control", "level.pref.roll", s["pref"][1]))
    elif do == "mode":
        ok = bool(opt(a, "set_mode", e["id"]))
    elif do == "stop":
        s["stopped"] = True
        a.release_drive()
    elif do == "go":
        s["stopped"] = False
    elif do == "stick":
        s["stick"] = float(e["value"])
    elif do == "set":
        ok = bool(opt(a, "set_control", e["id"], float(e["value"])))
    rec = dict(e)
    rec.update({"t": round(t, 5), "t_rel": round(t - s["go_t"], 5), "d": round(d, 2), "ok": ok})
    s["events"].append(rec)
    return rec


def finish_course(s, why):
    """Write the trace and end the session (PIE stays up; `end` ends it)."""
    if s.get("finished"):
        return
    try:
        if s.get("adapter") is not None:
            s["adapter"].release_drive()
    except Exception:  # noqa: BLE001
        pass
    s["finished"] = True
    s["stage"] = "finished"
    s["end_why"] = why
    s["locked_frame_s_end"] = cvar_float(LOCK_CVAR)
    rec = {k: s.get(k) for k in ("cfg", "kind", "start_placed", "robot_active", "robot_source", "setup_done", "setup_t", "gate",
                                 "go_t", "go", "end", "end_why", "events", "imu_dropped", "imu_error", "imu_rate_hz", "frames",
                                 "error", "max_fps_set", "first_t", "clock", "locked_frame_s_set", "locked_frame_s_end",
                                 "plan_in_step_set")}
    rec["samples"] = s["samples"]
    rec["imu"] = s["imu"]
    path = s["cfg"]["trace_path"]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001
        s["error"] = "writing the trace: %s" % exc
    stop_session()


def step_course(s):
    cfg = s["cfg"]
    plan = cfg["plan"]
    w = world()
    now_wall = time.time()
    if w is None:
        if s["stage"] != "wait_pie" or now_wall - s["started_wall"] > 120.0:
            raise RuntimeError("PIE is not running")
        return
    t = sim_time(w)
    if s.get("adapter") is None:
        s["robot_active"] = unreal.RammsRobotBridge.get_active_robot_id()
        s["robot_source"] = unreal.RammsRobotBridge.get_active_robot_source()
        if s["robot_active"] and s["robot_active"] != cfg["robot_id"]:
            raise RuntimeError("PIE started robot %r (%s), not %s" % (s["robot_active"], s["robot_source"], cfg["robot_id"]))
        mod = load_adapter(cfg["adapter"])
        s["adapter"] = mod["find"](w, cfg["wheels"])
        if s["adapter"] is None:
            if t > ROBOT_WAIT_SIM_S or now_wall - s["started_wall"] > 120.0:
                raise RuntimeError("no robot the adapter knows in PIE after %.1f s (active robot %r: %s)" % (
                    t, s["robot_active"], s["robot_source"]))
            return
        if s["robot_active"] != cfg["robot_id"]:
            raise RuntimeError("PIE started robot %r (%s), not %s" % (s["robot_active"], s["robot_source"], cfg["robot_id"]))
        missing = [m for m in ("drive", "release_drive") if not hasattr(s["adapter"], m)]
        if missing:
            raise RuntimeError("the robot's adapter cannot run a course: it has no %s" % ", ".join(missing))
    a = s["adapter"]
    t = a.sim_time() if hasattr(a, "sim_time") else t
    if t < 0.0:
        return  # nothing published yet
    if s.get("first_t") is None:
        s["first_t"] = round(t, 4)
        s["clock"] = "physics" if hasattr(a, "sim_time") else "world"
        s["actor_path"] = a.pawn.get_path_name()
        s["stage"] = "setup"
    timed_out = t - s["first_t"] > plan["timeout_sim_s"] or now_wall - s["started_wall"] > cfg["timeout_wall_s"]
    if s.get("last_t") is not None and t <= s["last_t"]:
        # The same physics state as the last frame: nothing new to see, but the stick stays held, and a physics that
        # never steps again still times out.
        if s.get("held"):
            a.drive(*s["held"])
        if timed_out:
            s["end"] = s.get("end") or {"t": round(t, 4), "why": "timeout"}
            finish_course(s, "timeout")
        return
    frame_dt = t - s["last_t"] if s.get("last_t") is not None else None
    s["last_t"] = t
    s["frames"] = s.get("frames", 0) + 1
    if timed_out:
        s["end"] = s.get("end") or {"t": round(t, 4), "why": "timeout", "d": s.get("d_now")}
        finish_course(s, "timeout")
        return

    if s.get("setup_done") is None and t >= plan["setup_at_s"]:
        s["setup_done"] = a.prepare(cfg.get("setup") or {})
        extra = opt(a, "prepare_level", cfg.get("level_setup") or {})
        if extra:
            s["setup_done"] = dict(s["setup_done"] or {}, **extra)
        s["setup_t"] = round(t, 4)

    # The robot as this frame finds it.
    chassis = a.chassis()
    seat = a.seat()
    c = s["course"]
    d, xt, yaw_err = c.path_coords(plan["path"]["origin"], plan["path"]["yaw"], chassis["xyz"][0], chassis["xyz"][1], chassis["yaw"])
    s["d_now"] = round(d, 1)
    # The heading's own rate (deg/s), for the hold's damping: from the frame before, smoothed over YAW_RATE_TAU_S (a
    # drive's torque ripple shows in the frame-to-frame heading, and would be handed back as stick).
    yaw_rate = s.get("yaw_rate", 0.0)
    if frame_dt and s.get("yaw_err_last") is not None:
        yaw_rate += (c.wrap180(yaw_err - s["yaw_err_last"]) / frame_dt - yaw_rate) * min(1.0, frame_dt / c.YAW_RATE_TAU_S)
    s["yaw_rate"] = yaw_rate
    s["yaw_err_last"] = yaw_err
    gate_at = plan["gate_at_s"]

    if s.get("gate") is None:
        if t >= gate_at - STEADY_LEAD_S:
            m = s["steady"].step(t, chassis, a.wheel_rates())
            if t >= gate_at and (m["steady"] or t >= gate_at + STEADY_MAX_WAIT_S):
                ca, sa = level_att(chassis), (level_att(seat) if seat else None)
                s["gate"] = {"t": round(t, 5), "asked_for": gate_at, "steady": m, "frame_dt": round(frame_dt, 5) if frame_dt else None,
                             "chassis": rnd_pose(chassis), "seat": {k: round(v, 4) for k, v in seat.items()} if seat else None,
                             "rider_zero": [round(sa[0] - ca[0], 4), round(sa[1] - ca[1], 4)] if sa else None,
                             "lifts": a.lifts(), "level": opt(a, "level"), "mode": opt(a, "mode")}
                s["go_t"] = t + plan["settle_s"]
                s["stage"] = "settle"

    # The events due, fired after the robot was read: the sample below shows the state they found.
    fired = []
    t_rel = (t - s["go_t"]) if s.get("gate") is not None else None
    if t_rel is not None and s.get("end") is None:
        for e in s["schedule"].due(t_rel, d if t_rel >= 0.0 else None):
            fired.append(fire_event(s, a, e, t, d))

    driving = t_rel is not None and t_rel >= 0.0 and s.get("end") is None
    stick, turn = 0.0, 0.0
    if driving:
        if s.get("go") is None:
            lv = opt(a, "level")
            s["go"] = {"t": round(t, 5), "level": lv, "mode": opt(a, "mode"), "chassis": rnd_pose(chassis),
                       "level_ready": bool(lv) and int(lv.get("state") or 0) in LEVEL_READY}
            s["stage"] = "drive"
        if not s["stopped"]:
            stick = s["stick"]
            turn = c.steer(plan["hold"], xt, yaw_err, stick, yaw_rate)
            a.drive(stick, turn)
            s["held"] = (stick, turn)
        else:
            s["held"] = None

    if t >= gate_at - TRACE_LEAD_S:
        if cfg.get("imu") and cfg.get("rider_body"):
            s["imu_next"] = imu_read(s, -1 if s.get("imu_next") is None else s["imu_next"])
        sample = {"t": round(t, 5), "wall": round(now_wall, 3), "chassis": rnd_pose(chassis),
                  "wheels": [[round(x, 3) for x in h] if h else None for h in a.wheel_hubs()],
                  "pref": list(s["pref"]), "stick": [round(stick, 4), round(turn, 4)],
                  "steer": {"xt": round(xt, 3), "yaw_err": round(yaw_err, 4), "yaw_rate": round(yaw_rate, 4)}}
        if seat:
            sample["seat"] = {k: round(v, 4) for k, v in seat.items()}
        lv = opt(a, "level")
        if lv:
            words = lv.pop("status", None)
            sample["level"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in lv.items()}
            if words != s.get("last_status"):
                sample["level"]["status"] = words
                s["last_status"] = words
        mode = opt(a, "mode")
        if mode is not None:
            sample["mode"] = mode
        cmd = opt(a, "commands")
        if cmd:
            sample["cmd"] = {k: [None if x is None else round(x, 6) for x in v] for k, v in cmd.items()}
        ground = opt(a, "ground")
        if ground:
            sample["ground"] = ground
        if fired:
            sample["ev"] = [e.get("label") or e["do"] for e in fired]
        s["samples"].append(sample)

    if driving:
        end, why = plan["end"], None
        if "d" in end and d >= end["d"]:
            why = "end line"
        elif "t" in end and t_rel >= end["t"]:
            why = "end time"
        elif abs(chassis["xyz"][1]) > plan["lane_half"] - c.LANE_GUARD_CM:
            why = "left the lane"
        if why:
            a.release_drive()
            s["held"] = None
            s["end"] = {"t": round(t, 5), "why": why, "d": round(d, 2), "xt": round(xt, 2), "chassis": rnd_pose(chassis),
                        "lifts": a.lifts(), "level": opt(a, "level"), "pending": [e.get("label") or e["do"] for e in s["schedule"].pending()]}
            s["post_until"] = t + plan["post_s"]
            s["stage"] = "post"
    elif s.get("end") is not None and t >= s["post_until"]:
        finish_course(s, "ended")


def stop_asked(trace_path):
    """A file named STOP in a run's folder (or the one above a rep<k>/) asks the run to end: the session in PIE
    finishes, and no other is begun. The way to end a long run without killing its runner or its editor."""
    d = os.path.dirname(trace_path or "")
    for p in (os.path.join(d, "STOP"), os.path.join(os.path.dirname(d), "STOP")) if d else ():
        if os.path.exists(p):
            return p
    return None


def op_begin_course(cfg):
    stop = stop_asked(cfg.get("trace_path"))
    if stop:
        raise RuntimeError("stopped: %s is there (remove it to run here again)" % stop)
    if world() is not None:
        les.editor_request_end_play()
        raise RuntimeError("PIE was running -- ended it; begin again")
    if not unreal.Paths.get_project_file_path().replace("\\", "/").endswith("/Ramms.uproject"):
        raise RuntimeError("not the Ramms project's editor")
    stop_session()
    restore_start()
    plan = cfg["plan"]
    c = course_module()
    schedule = c.Schedule(plan["events"], plan["settle_s"])  # a bad event list is refused before PIE starts
    if not les.load_level(plan["map"]):
        raise RuntimeError("could not load %s (build the course maps: Scripts/level_maps/make_level_maps.py)" % plan["map"])
    placed = place_course_start(plan["start"])
    if getattr(unreal, "_curb_runner_saved", None) is None:
        unreal._curb_runner_saved = {"t.MaxFPS": cvar_float("t.MaxFPS"), "robot": unreal.RammsRobotCatalog.get_console_robot(),
                                     LOCK_CVAR: cvar_float(LOCK_CVAR), PLAN_CVAR: cvar_float(PLAN_CVAR)}
    if cfg.get("max_fps") is not None:
        console("t.MaxFPS %s" % cfg["max_fps"])  # 0: uncapped
    console("%s %s" % (LOCK_CVAR, float(cfg.get("locked_frame_s") or 0.0)))
    console("%s %d" % (PLAN_CVAR, 1 if float(cfg.get("locked_frame_s") or 0.0) > 0.0 else 0))  # pinned either way, as a crossing's
    unreal.RammsRobotCatalog.set_console_robot(cfg["robot_id"])
    unreal._curb_runner_session = {"kind": "course", "cfg": cfg, "stage": "wait_pie", "samples": [], "imu": [], "events": [],
                                   "steady": Steady(), "course": c, "schedule": schedule, "stick": float(plan.get("stick") or 0.0),
                                   "stopped": False, "held": None, "pref": [0.0, 0.0],
                                   "started_wall": time.time(), "start_placed": placed, "finished": False,
                                   "max_fps_set": cvar_float("t.MaxFPS"), "locked_frame_s_set": cvar_float(LOCK_CVAR),
                                   "plan_in_step_set": cvar_float(PLAN_CVAR)}
    les.editor_request_begin_play()
    unreal._curb_runner_handle = unreal.register_slate_post_tick_callback(tick)
    return {"map": plan["map"], "start": placed}


def main():
    words = getattr(unreal, VAR, "status")
    if hasattr(unreal, VAR):
        delattr(unreal, VAR)
    parts = words.split(None, 1)
    op = parts[0]
    arg = json.loads(parts[1]) if len(parts) > 1 and parts[1].strip().startswith("{") else None
    try:
        if op == "begin":
            out({"ok": True, **op_begin(arg)})
        elif op == "begin_course":
            out({"ok": True, **op_begin_course(arg)})
        elif op == "status":
            out({"ok": True, **op_status()})
        elif op == "end":
            out({"ok": True, **op_end()})
        elif op == "probe":
            out({"ok": True, **op_probe(arg)})
        else:
            raise RuntimeError("unknown op %r" % op)
    except Exception as exc:  # noqa: BLE001
        out({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})


main()
