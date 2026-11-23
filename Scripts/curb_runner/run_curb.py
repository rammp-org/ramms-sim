#!/usr/bin/env python3
"""Run a robot's curb crossings on the public curb maps, measure them the same way for every robot, and record them.

    python -I Scripts/curb_runner/run_curb.py --robot rammp_gen1 [--scenarios S0,S4] [--dirs up,down] [--repeat N]
        [--out DIR] [--max-fps 16] [--no-history | --history FILE] [--history-label TEXT] [--list]
    python -I Scripts/curb_runner/run_curb.py --rescore DIR [--no-history]   # its rows again from its traces

Needs an editor of this project running (Scripts/editor_remote_exec.py; $RAMMS_EDITOR_REMOTE_PORT picks one). For each
crossing it ends any PIE, sends runner_op.py's `begin` (the map, the robot's start, the robot, the frame-rate cap, the
crossing session), waits for the session to finish, ends PIE, and reads the trace the session wrote: measures.py makes
its shared figures, scoring.py scores it against the robot's expectation (its profile in robots/), and the row goes to
<out>/results.json (rep<k>/ with --repeat) beside the trace. A summary.md lists the crossings; history.py records the
run in the robot's history (its profile's history_file) unless --no-history.

A climb starts at rest on the near road (the map's PlayerStart, start_offset_cm ahead), a descent on the sidewalk
(curb_terrain's top start); each is asked for on the frame nearest 5 s of simulated time once the robot is at rest.
Exit status: 1 when a crossing did not meet its expectation (or did not run), else 0. Only the standard library.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "Scripts", "curb_maps"))
import curb_terrain as ct  # noqa: E402
import history  # noqa: E402
import measures  # noqa: E402
import robots  # noqa: E402
import scoring  # noqa: E402

EXEC = os.path.join(ROOT, "Scripts", "editor_remote_exec.py")
OP = os.path.join(HERE, "runner_op.py")
TAG = "CURBRUN"
ASK_SIM_S = 5.0
SETUP_AT_S = 1.0
POST_S = 2.0
TIMEOUT_SIM_S = 90.0
TIMEOUT_WALL_S = 900.0
LIFT_RAD = 0.5 * 3.14159265 / 180.0  # a lift back within half a degree ...
LIFT_CM = 0.5  # ... or half a centimetre (the translators)


OP_TRIES = 3  # a remote call the editor missed (busy starting PIE: discovery gives up) is tried again
OP_RETRY_S = 2.0


def op(words, timeout=180, tries=OP_TRIES):
    """Run runner_op.py in the editor with `words` (its own namespace each call: runpy) and return its reply; a call
    with no reply is tried again (tries in all)."""
    code = ("import unreal, runpy; unreal._curb_runner_op = %r; _r = runpy.run_path(%r, run_name='__curb_runner__')" % (words, OP))
    for k in range(tries):
        try:
            r = subprocess.run([sys.executable, "-I", EXEC, "--code", code], capture_output=True, text=True, timeout=timeout)
            lines = [l.split(TAG + " ", 1)[1] for l in (r.stdout + r.stderr).splitlines() if (TAG + " ") in l]
            why = "" if lines else (r.stdout[-2000:] + r.stderr[-2000:])
        except subprocess.TimeoutExpired:
            lines, why = [], "timed out after %d s" % timeout
        if lines:
            break
        if k < tries - 1:
            time.sleep(OP_RETRY_S)
    if not lines:
        raise RuntimeError("%s: no reply from the editor\n%s" % (words.split()[0], why))
    d = json.loads(lines[-1])
    if not d.get("ok"):
        raise RuntimeError("%s: %s" % (words.split()[0], d.get("error")))
    return d


def lifts_back(at_ask, at_end):
    """Every lift where it was at the ask: angles within LIFT_RAD, translators (cm) within LIFT_CM."""
    if not at_ask or not at_end:
        return None
    for k, v in at_ask.items():
        if k not in at_end:
            continue
        tol = LIFT_CM if k.startswith("translator") else LIFT_RAD
        if abs(at_end[k] - v) > tol:
            return False
    return True


def frame_stats(samples):
    steps = sorted(b["t"] - a["t"] for a, b in zip(samples, samples[1:]) if b["t"] > a["t"])
    if not steps:
        return None, None, None
    return (round(steps[len(steps) // 2] * 1000.0, 1), round(steps[-1] * 1000.0, 1),
            round(steps[min(len(steps) - 1, int(len(steps) * 0.99))] * 1000.0, 1))


def row_of(prof, sid, direction, trace, expect, start, ran_at):
    """A results.json row from a crossing's trace."""
    samples = trace.get("samples") or []
    ask = trace.get("ask") or {}
    end = trace.get("end") or {}
    layout = ct.Layout(ct.BY_ID[sid])
    frame = measures.Frame(layout, direction)
    cfg = trace.get("cfg") or {}
    wheels = cfg.get("wheels") or prof["wheels"]  # the order the samples were taken in
    if trace.get("error") and not end:
        # The session failed (PIE did not start, another robot, an adapter call raised): not a crossing.
        return error_row(prof, sid, direction, expect, "the session: %s" % trace["error"])
    locked = trace.get("locked_frame_s_set") or 0.0
    if locked and "locked_frame_s_end" in trace and trace["locked_frame_s_end"] != locked:
        # URLab turned the lock off (a batch stalled) or something else changed it: the run is not a locked one.
        return error_row(prof, sid, direction, expect, "the frame lock (urlab.LockedFrameSeconds %s) did not hold to "
                         "the end (%s)" % (locked, trace.get("locked_frame_s_end")))
    phase = end.get("phase") or ("REFUSED" if trace.get("refused") else "TIMEOUT")
    shared = (measures.shared_figures(samples, wheels, frame, ask["t"]) if ask.get("t") is not None and ask.get("accepted")
              else None)
    rider = None
    if shared and trace.get("imu") and not trace.get("imu_dropped"):
        ev = shared["events"]
        # A physics-clock trace's samples and the IMU's carry one clock: nothing to line up. (imu_t is the newest
        # sample of a batch still being stepped as the session's callback ran, so its median turns on the wall clock.)
        # Only a world-clock trace (no `clock`, or "world") needs the estimate.
        off = 0.0 if trace.get("clock") == "physics" else measures.imu_clock_offset(samples)
        if off is not None:
            rider = measures.rider_figures(trace["imu"], ev.get("t0"), ev.get("t_last_down") or ev.get("t_end"), offset=off)
    rider_why = rider_why_of(trace, cfg.get("rider_body") or prof.get("rider_body"), rider) if shared else None
    controller = dict(end.get("stats") or {})
    controller["step_found"] = end.get("step_found")
    controller["lifts_back"] = lifts_back(ask.get("lifts"), end.get("lifts"))
    fmed, fmax, fp99 = frame_stats(samples)
    rate = trace.get("imu_rate_hz")
    setup = dict(cfg["setup"]) if isinstance(cfg.get("setup"), dict) else dict(prof.get("setup") or {})
    if cfg.get("stick") is not None:
        setup["stick"] = cfg["stick"]
    row = {
        "robot_id": prof["robot_id"], "history_robot": prof.get("history_robot"), "scenario": sid, "dir": direction,
        "start": "standing", "descent_start": (cfg.get("start") if direction == "down" else None), "ran_at": ran_at,
        "settings": {"max_fps": trace.get("max_fps_set", cfg.get("max_fps")), "frame_ms": fmed, "frame_max_ms": fmax, "frame_p99_ms": fp99,
                     "physics_step_ms": round(1000.0 / rate, 3) if rate else None, "maps": "public",
                     "ask_sim_s": cfg.get("ask_sim_s"), "steady": bool((ask.get("steady") or {}).get("steady")),
                     "clock": trace.get("clock"), "locked_frame_s": trace.get("locked_frame_s_set") or None,
                     "plan_in_step": bool(trace.get("plan_in_step_set")) or None,
                     "late_s": ask.get("late_s"), "cvars": None,
                     "robot": {**setup, "start_offset_cm": cfg.get("start_offset_cm") if direction == "up" else None,
                               "start": start, "start_past_cm": (trace.get("start_placed") or {}).get("past_cm")}},
        "outcome": {"phase": phase, "status": end.get("status"), "why": trace.get("refused") or (trace.get("error") or None),
                    "expect": expect},
        "shared": shared, "rider": rider, "rider_why": rider_why, "controller": controller,
        "trace": None,
    }
    sc = scoring.score(row, expect, frame.step_range, prof.get("checks"))
    row["outcome"].update(sc)
    return row


def rider_why_of(trace, rider_body, rider):
    """Why a measured crossing of a robot with a rider body has no rider figures (None when it has them, or has no
    rider body): without it a run whose IMU could not be read at all (a rider body the physics does not know, no IMU
    track) looks the same as one that lost a sample."""
    if rider is not None or not rider_body:
        return None
    err = trace.get("imu_error")  # the bridge's reply: words, or the whole reply when it gave none
    if err:
        return "the IMU read failed: %s" % (err if isinstance(err, str) else json.dumps(err, sort_keys=True))
    if trace.get("imu_dropped"):
        return "the IMU lost %d sample(s)" % trace["imu_dropped"]
    if not trace.get("imu"):
        return "no IMU samples in the trace"
    return "no IMU samples in the crossing's span"


def error_row(prof, sid, direction, expect, why):
    """A crossing that did not run: never recorded in a history (its why starts "error:"), always counted as a
    failure in the exit status, whatever was expected."""
    return {"robot_id": prof["robot_id"], "history_robot": prof.get("history_robot"), "scenario": sid, "dir": direction,
            "outcome": {"phase": "ERROR", "met": False, "pass": False, "why": "error: %s" % why, "expect": expect,
                        "failed": ["not run"]}}


def summary_line(r):
    sh = r.get("shared") or {}
    t = sh.get("times") or {}
    o = r["outcome"]
    sp = sh.get("speed") or {}
    att = sh.get("attitude") or {}

    def f(x, nd=2):
        return "-" if x is None else ("%.*f" % (nd, x))
    return ("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
        r["scenario"], r["dir"], o.get("expect"), o["phase"], {True: "yes", False: "no", None: "-"}[o.get("met")],
        ", ".join(o.get("failed") or []) or "-", f(t.get("edge_to_last_down_s")), f(t.get("edge_to_done_s")),
        f(t.get("edge_to_rest_s")), f(sp.get("v_min_cm_s")), f(att.get("max_seat_incl_deg")),
        (o.get("why") or o.get("status") or "").replace("|", "/")[:80]))


def write_results(d, rows):
    os.makedirs(d, exist_ok=True)
    history.write_atomically(os.path.join(d, "results.json"), lambda f: f.write(json.dumps(rows, indent=1) + "\n"))
    lines = ["# Curb crossings", "",
             "| scenario | dir | expect | end | met | failed | edge to last down s | edge to Done s | edge to rest s | "
             "v_min cm/s | seat incl deg | why / status |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"] + [summary_line(r) for r in rows]
    met = sum(1 for r in rows if r["outcome"].get("met"))
    scored = sum(1 for r in rows if r["outcome"].get("met") is not None)
    lines += ["", "%d of %d scored crossings met their expectation (%d run)." % (met, scored, len(rows))]
    history.write_atomically(os.path.join(d, "summary.md"), lambda f: f.write("\n".join(lines) + "\n"))


def run_one(prof, sid, direction, out_dir, max_fps, locked_frame_s=0.0):
    start = "top" if direction == "down" and prof.get("descent_start", "top") == "top" else "climb"
    trace_path = os.path.join(out_dir, "%s_%s.trace.json" % (sid, direction))
    cfg = {"robot_id": prof["robot_id"], "adapter": prof["editor"], "wheels": prof["wheels"], "rider_body": prof.get("rider_body"),
           "scenario": sid, "dir": direction, "start": start,
           "start_offset_cm": prof.get("start_offset_cm", 0.0) if start == "climb" else 0.0,
           "setup": prof.get("setup") or {}, "setup_at_s": SETUP_AT_S, "ask_sim_s": ASK_SIM_S,
           "stick": (prof.get("setup") or {}).get("stick", 1.0), "max_fps": max_fps, "locked_frame_s": locked_frame_s,
           "post_s": POST_S,
           "timeout_sim_s": TIMEOUT_SIM_S, "timeout_wall_s": TIMEOUT_WALL_S, "trace_path": trace_path}
    ran_at = history.now_utc()
    cfg["token"] = "%s %s %s %s" % (ran_at, sid, direction, os.getpid())  # the trace read must be this session's
    for p in (trace_path, trace_path + ".tmp"):
        if os.path.exists(p):
            os.remove(p)
    try:
        op("end")
    except RuntimeError:
        pass
    time.sleep(3.0)
    st = {}
    try:
        try:
            op("begin " + json.dumps(cfg))
        except RuntimeError as exc:
            if "PIE was running" not in str(exc):
                raise
            time.sleep(5.0)  # the last PIE was still ending
            op("begin " + json.dumps(cfg))
        deadline = time.monotonic() + TIMEOUT_WALL_S + 120.0
        misses = 0
        while time.monotonic() < deadline:
            time.sleep(1.0)
            try:
                st = op("status")
                misses = 0
            except RuntimeError:
                misses += 1  # the editor busy: the session goes on in it
                if misses >= 10:
                    raise
                continue
            if st.get("finished") or st.get("stage") is None:
                break
    finally:
        try:
            op("end")
        except RuntimeError as exc:
            print("  (ending PIE: %s)" % str(exc).splitlines()[0])
    if not os.path.exists(trace_path):
        raise RuntimeError("no trace written (%s)" % (st.get("error") or st.get("stage")))
    with open(trace_path, encoding="utf-8") as f:
        trace = json.load(f)
    if (trace.get("cfg") or {}).get("token") != cfg["token"]:
        raise RuntimeError("the trace at %s is not this session's" % trace_path)
    if trace.get("error"):
        print("  (the session: %s)" % trace["error"])
    expect = prof["expect"](sid, direction)
    row = row_of(prof, sid, direction, trace, expect, start, ran_at)
    row["trace"] = os.path.basename(trace_path)
    if row.get("rider_why"):
        print("  (no rider figures: %s)" % row["rider_why"])
    return row


def rescore(run_dir):
    """Every row of a run folder made again from its trace (the measures, the scoring and the expectations as they are
    now); results.json and summary.md rewritten in place. Returns the rows."""
    out = []
    for rep, rows, path in history.run_rows(run_dir):
        d = os.path.dirname(path)
        new = []
        for r in rows:
            prof = robots.find(r.get("robot_id") or "")
            tp = os.path.join(d, r.get("trace") or "")
            if prof is None or not r.get("trace") or not os.path.exists(tp):
                new.append(r)  # an error row, or a robot not here: kept as it was
                continue
            with open(tp, encoding="utf-8") as f:
                trace = json.load(f)
            start = ((r.get("settings") or {}).get("robot") or {}).get("start") or ("top" if r["dir"] == "down" else "climb")
            row = row_of(prof, r["scenario"], r["dir"], trace, prof["expect"](r["scenario"], r["dir"]), start, r.get("ran_at"))
            row["trace"] = r["trace"]
            new.append(row)
        write_results(d, new)
        out += new
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--robot", required=False, help="a robot's id or alias (robots/)")
    ap.add_argument("--scenarios", default=None, help="comma-separated curb_terrain ids (default: the robot's)")
    ap.add_argument("--dirs", default="up,down")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-fps", type=float, default=None, help="the frame-rate cap (default: the robot's standard)")
    ap.add_argument("--locked-frame-s", type=float, default=0.0, metavar="S",
                    help="frame-locked stepping (urlab.LockedFrameSeconds): S of physics per frame, whatever the frame rate; "
                         "0 off; below 0 matched to the frame (real time, but not frame-rate independent)")
    ap.add_argument("--history", default=None, help="record in this file instead of the robot's history")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--history-label", default=None)
    ap.add_argument("--list", action="store_true", help="the robots there are, and exit")
    ap.add_argument("--rescore", default=None, metavar="DIR", help="make a run folder's rows again from its traces")
    ap.add_argument("--overwrite", action="store_true", help="run into an --out folder that holds an earlier run")
    args = ap.parse_args()
    if args.rescore:
        rows = rescore(args.rescore)
        for r in rows:
            print("  " + summary_line(r))
        if not args.no_history:
            history.register_profiles()
            history.add_runs([args.rescore], args.history, args.history_label)
        return 1 if any(r["outcome"].get("met") is False for r in rows) else 0
    if args.list or not args.robot:
        for p in robots.load_all().values():
            print("%-12s %-14s aliases %s; history %s" % (p["robot_id"], p.get("name", ""), ", ".join(p.get("aliases") or []),
                                                         history.rel_path(p.get("history_file")) if p.get("history_file") else "-"))
        return 0
    prof = robots.find(args.robot)
    if prof is None:
        print("no robot profile answers to %r (--list)" % args.robot)
        return 2
    scenarios = [s for s in (args.scenarios.split(",") if args.scenarios else prof.get("scenarios") or ["S0"]) if s]
    unknown = [s for s in scenarios if s not in ct.BY_ID]
    if unknown:
        print("unknown scenarios: %s" % ", ".join(unknown))
        return 2
    dirs = [d for d in args.dirs.split(",") if d]
    bad_dirs = [d for d in dirs if d not in ct.DIRECTIONS]
    if bad_dirs or not dirs:
        print("--dirs takes %s, not %s" % (",".join(ct.DIRECTIONS), args.dirs))
        return 2
    max_fps = args.max_fps if args.max_fps is not None else prof.get("max_fps")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out = os.path.abspath(args.out or os.path.join(history.DEFAULT_OUT, "runs", "%s-%s" % (stamp, prof["robot_id"])))
    if history.run_rows(out) and not args.overwrite:
        print("%s holds an earlier run's results: another --out, or --overwrite" % out)
        return 2
    for rep, _, path in history.run_rows(out):  # --overwrite: the earlier run's results go, not just some of them
        os.remove(path)
    os.makedirs(out, exist_ok=True)
    history.register_profiles()
    ran_on = history.code_state((history.HISTORIES.get(prof.get("history_robot")) or {}).get("repos") or history.PUBLIC_REPOS)
    meta = {"argv": [os.path.relpath(__file__, ROOT).replace("\\", "/")] + sys.argv[1:], "started": history.now_utc(),
            "robot_id": prof["robot_id"], "editors": 1, "label": args.history_label}
    history.write_atomically(os.path.join(out, "run.json"), lambda f: f.write(json.dumps(meta, indent=1) + "\n"))
    history.write_run_side_file(out, ran_on, meta)
    all_rows, bad = [], 0
    try:
        run_all(args, prof, scenarios, dirs, max_fps, out, all_rows)
    finally:
        try:
            op("end", tries=1)  # PIE, t.MaxFPS, ramms.Robot and the PlayerStart back, however the run ended
        except Exception:  # noqa: BLE001
            pass
    bad = sum(1 for r in all_rows if r["outcome"].get("met") is False)
    if not args.no_history:
        history.add_runs([out], args.history, args.history_label)
    print("results in %s" % out)
    if not all_rows:
        print("no crossing ran")
        return 1
    return 1 if bad else 0


def run_all(args, prof, scenarios, dirs, max_fps, out, all_rows):
    for rep in range(1, args.repeat + 1):
        d = os.path.join(out, "rep%d" % rep) if args.repeat > 1 else out
        rows = []
        for sid in scenarios:
            layout = ct.Layout(ct.BY_ID[sid])
            for direction in dirs:
                if direction not in layout.s.dirs:
                    continue
                print("[%s %s %s%s]" % (prof["robot_id"], sid, direction, " rep %d" % rep if args.repeat > 1 else ""), flush=True)
                try:
                    row = run_one(prof, sid, direction, d, max_fps, args.locked_frame_s)
                except Exception as exc:  # one broken crossing must not lose the others
                    row = error_row(prof, sid, direction, prof["expect"](sid, direction), str(exc).splitlines()[0])
                rows.append(row)
                all_rows.append(row)
                print("  " + summary_line(row), flush=True)
                write_results(d, rows)


if __name__ == "__main__":
    sys.exit(main())
