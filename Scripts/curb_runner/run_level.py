#!/usr/bin/env python3
"""Run a robot over the level-assist course maps, with the assist on and off, measure every run the same way for every
robot, score it, record it and show it.

    python -I Scripts/curb_runner/run_level.py --robot rammp_gen1 --courses RAMP5,TRANSITIONS [--level off,on]
        [--pref "0,0" --pref "3,-2"] [--starts centre,left20] [--dirs fwd,rev] [--variants drive,toggle]
        [--stick 0.5] [--hold on|off|both] [--repeat N] [--locked-frame-s 0.0625] [--max-fps 30] [--imu]
        [--out DIR] [--no-history | --history FILE] [--history-label TEXT] [--no-report]
    python -I Scripts/curb_runner/run_level.py --rescore DIR [--no-history]   # its rows again from its traces
    python -I Scripts/curb_runner/run_level.py --list

Needs an editor of this project running (Scripts/editor_remote_exec.py; $RAMMS_EDITOR_REMOTE_PORT picks one) and the
course maps built (Scripts/level_maps/make_level_maps.py). A case is a course, a direction, a start, a variant (what
happens on the way: course.py), a preference, a stick and the hold on or off; it is run once with the assist off and
once with it on, so the two cover the same ground. Each run is one PIE session (runner_op.py's begin_course); its
trace goes to <out>/<case>.trace.json, its row to <out>/level_results.json (rep<k>/ with --repeat), with
level_summary.md beside it. level_measures.py makes the figures, pairs the on run with its off run and scores the on
run against the robot's criteria (its profile's `level`). history.py records the runs in the robot's level history
unless --no-history; level_report.py writes <out>/level_report.html (the figures and the tables) unless --no-report.

The preference (--pref "pitch,roll", degrees, repeatable) is set in both runs; the assist-off run is scored against
the same preference. Exit status: 1 when an assist-on run did not meet its expectation (or a run did not run), else 0.
Only the standard library.
"""

import argparse
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import course  # noqa: E402
import history  # noqa: E402
import level_measures as lm  # noqa: E402
import robots  # noqa: E402

lt = course.lt
TIMEOUT_WALL_S = 1800.0
LOCKED_MAX_FPS = 30.0  # a locked run's physics per frame is fixed: the frame rate only sets how fast it runs


def op(words, timeout=180):
    import run_curb
    return run_curb.op(words, timeout)


def parse_pref(text):
    parts = [p for p in str(text).replace(" ", "").split(",") if p != ""]
    if len(parts) != 2:
        raise ValueError('a preference is "pitch,roll" in degrees, not %r' % text)
    return (float(parts[0]), float(parts[1]))


def cases_of(args, prof):
    """The cases asked for, in the order they run: [{"course", "dir", "start", "variant", "pref", "stick", "hold"}]."""
    lv = prof.get("level") or {}
    courses = [c for c in (args.courses.split(",") if args.courses else lv.get("courses") or ["FLAT"]) if c]
    unknown = [c for c in courses if c not in lt.BY_ID]
    if unknown:
        raise ValueError("unknown courses: %s (there are %s)" % (", ".join(unknown), ", ".join(c.id for c in lt.COURSES)))
    dirs = [d for d in args.dirs.split(",") if d]
    if not dirs or any(d not in lt.DIRECTIONS for d in dirs):
        raise ValueError("--dirs takes %s, not %s" % (",".join(lt.DIRECTIONS), args.dirs))
    variants = [v for v in args.variants.split(",") if v]
    if any(v not in course.VARIANTS for v in variants):
        raise ValueError("--variants takes %s, not %s" % (",".join(course.VARIANTS), args.variants))
    prefs = [parse_pref(p) for p in (args.pref or ["0,0"])]
    sticks = [float(x) for x in args.stick.split(",")] if args.stick else [float(lv.get("stick", 1.0))]
    holds = {"on": [True], "off": [False], "both": [True, False]}[args.hold]
    gains = {}
    for item in [x for x in (getattr(args, "hold_gains", None) or "").split(",") if x]:
        k, _, v = item.partition("=")
        if k not in ("k_yaw", "k_xt", "k_rate", "deadzone", "max_turn", "turn_sign"):
            raise ValueError("--hold-gains takes k_yaw, k_xt, k_rate, deadzone, max_turn, turn_sign, not %r" % k)
        gains[k] = float(v)
    starts = [s for s in args.starts.split(",") if s]
    out, skipped = [], []
    for cid in courses:
        for d in dirs:
            for st in starts:
                if st not in lt.BY_ID[cid].starts:
                    skipped.append("%s has no start %s" % (cid, st))
                    continue
                for v in variants:
                    if v == "mode" and not lv.get("alt_mode"):
                        skipped.append("%s has no other drive mode to switch to" % prof["robot_id"])
                        continue
                    for pref in prefs:
                        for stick in sticks:
                            for hold in holds:
                                out.append({"course": cid, "dir": d, "start": st, "variant": v, "pref": pref, "stick": stick, "hold": hold,
                                            "hold_gains": gains})
    for why in sorted(set(skipped)):
        print("  (left out: %s)" % why)
    return out


def plan_of(prof, case, level):
    lv = prof.get("level") or {}
    hold = dict(lv.get("hold") or {})
    hold.update(case.get("hold_gains") or {})
    hold["on"] = bool(case["hold"])
    scale = abs(case["stick"]) / max(1e-6, abs(lv.get("stick", 1.0)))
    return course.plan(case["course"], case["dir"], case["start"], level, case["pref"], case["stick"], case["variant"], hold=hold,
                       speed_cm_s=max(5.0, lv.get("speed_cm_s", 60.0) * scale), alt_mode=lv.get("alt_mode"))


def run_case(prof, case, level, out_dir, max_fps, locked_frame_s, imu):
    """One PIE session; returns (the trace, when it ran, the case's name)."""
    lv = prof.get("level") or {}
    plan = plan_of(prof, case, level)
    name = course.case_name(case["course"], case["dir"], case["start"], case["variant"], level, case["pref"], case["stick"], case["hold"])
    trace_path = os.path.join(out_dir, name + ".trace.json")
    ran_at = history.now_utc()
    cfg = {"robot_id": prof["robot_id"], "adapter": prof["editor"], "wheels": prof["wheels"], "rider_body": prof.get("rider_body"),
           "imu": bool(imu), "setup": lv.get("setup") if lv.get("setup") is not None else (prof.get("setup") or {}),
           "level_setup": lv.get("setup") or {}, "plan": plan, "max_fps": max_fps, "locked_frame_s": locked_frame_s,
           "timeout_wall_s": TIMEOUT_WALL_S, "trace_path": trace_path, "token": "%s %s %s" % (ran_at, name, os.getpid())}
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
            op("begin_course " + json.dumps(cfg))
        except RuntimeError as exc:
            if "PIE was running" not in str(exc):
                raise
            time.sleep(5.0)  # the last PIE was still ending
            op("begin_course " + json.dumps(cfg))
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
    return trace, ran_at, name


def frame_stats(samples):
    steps = sorted(b["t"] - a["t"] for a, b in zip(samples, samples[1:]) if b["t"] > a["t"])
    if not steps:
        return None, None, None
    return (round(steps[len(steps) // 2] * 1000.0, 1), round(steps[-1] * 1000.0, 1),
            round(steps[min(len(steps) - 1, int(len(steps) * 0.99))] * 1000.0, 1))


def error_row(prof, case, level, why, name=None):
    """A run that did not run: never recorded in a history (its why starts "error:"), always a failure."""
    return {"group": history.LEVEL_GROUP, "robot_id": prof["robot_id"], "history_robot": prof.get("history_robot"),
            "course": case["course"], "dir": case["dir"], "start": case["start"], "variant": case["variant"], "level": level,
            "pref": list(case["pref"]), "stick": case["stick"], "hold": {"on": bool(case["hold"])}, "case": name,
            "outcome": {"end": "ERROR", "met": False, "failed": ["not run"], "why": "error: %s" % why}}


def row_of(prof, case, level, trace, ran_at, name):
    """A level_results.json row from a run's trace (its pair figures and its score come later: finish_rows)."""
    lv = prof.get("level") or {}
    if trace.get("error") and not trace.get("end"):
        return error_row(prof, case, level, "the session: %s" % trace["error"], name)
    locked = trace.get("locked_frame_s_set") or 0.0
    if locked and "locked_frame_s_end" in trace and trace["locked_frame_s_end"] != locked:
        return error_row(prof, case, level, "the frame lock (urlab.LockedFrameSeconds %s) did not hold to the end (%s)"
                         % (locked, trace.get("locked_frame_s_end")), name)
    cfg = trace.get("cfg") or {}
    plan = cfg.get("plan") or {}
    samples = trace.get("samples") or []
    gate, go, end = trace.get("gate") or {}, trace.get("go") or {}, trace.get("end") or {}
    fig = lm.figures(trace, lv)
    fmed, fmax, fp99 = frame_stats(samples)
    refused = [e.get("label") or e.get("do") for e in trace.get("events") or [] if e.get("ok") is False]
    rider = None
    if trace.get("imu") and not trace.get("imu_dropped") and trace.get("go_t") is not None and end.get("t") is not None:
        rider = lm.rider_accel(trace["imu"], trace["go_t"], end["t"])
    why = None
    if trace.get("error"):
        why = "the session: %s" % trace["error"]
    elif fig.get("why"):
        why = fig["why"]
    elif refused:
        why = "the robot did not take: %s" % ", ".join(refused)
    return {
        "group": history.LEVEL_GROUP, "version": lm.LEVEL_VERSION, "robot_id": prof["robot_id"], "history_robot": prof.get("history_robot"),
        "course": case["course"], "dir": case["dir"], "start": case["start"], "variant": case["variant"], "level": level,
        "pref": list(case["pref"]), "stick": case["stick"], "hold": plan.get("hold") or {"on": bool(case["hold"])},
        "case": name, "ran_at": ran_at,
        "settings": {"max_fps": trace.get("max_fps_set", cfg.get("max_fps")), "frame_ms": fmed, "frame_max_ms": fmax, "frame_p99_ms": fp99,
                     "maps": "public", "clock": trace.get("clock"), "locked_frame_s": locked or None, "cvars": None,
                     "steady": bool((gate.get("steady") or {}).get("steady")), "gate_s": gate.get("t"), "go_s": trace.get("go_t"),
                     "level_ready": go.get("level_ready"), "mode": go.get("mode"), "imu": bool(cfg.get("imu")),
                     "robot": dict(cfg.get("setup") or {})},
        "outcome": {"end": end.get("why") or trace.get("end_why"), "why": why, "refused": refused or None},
        "figures": fig, "pair": None, "rider": rider, "trace": name + ".trace.json",
    }


def finish_rows(prof, rows):
    """Pair every assist-on row with the assist-off row of its case, and score it against the robot's criteria."""
    lv = prof.get("level") or {}
    expect = lv.get("expect") or (lambda *a: "explore")
    off = {course.pair_key(r): r for r in rows if r.get("level") == "off" and r.get("figures")}
    for r in rows:
        if not r.get("figures"):
            continue
        partner = off.get(course.pair_key(r)) if r["level"] == "on" else None
        r["pair"] = lm.pair(r["figures"], partner["figures"]) if partner else None
        sc = lm.score(r["figures"], r["pair"], lv.get("criteria"), expect(r["course"], r["dir"], r["start"], r["variant"]), r["level"])
        if r["level"] == "on" and (r["outcome"].get("refused") or r["outcome"].get("end") in ("timeout", "left the lane", "error")):
            if sc["expect"] != "explore":
                sc["met"] = False
                sc["failed"] = sorted(set(sc["failed"] + [r["outcome"].get("end") if not r["outcome"].get("refused") else "refused"]))
        r["outcome"].update(sc)
    return rows


def f(x, nd=2):
    return "-" if x is None else ("%.*f" % (nd, x))


def summary_line(r):
    o = r["outcome"]
    fig = (r.get("figures") or {}).get("overall") or {}
    segs = (r.get("figures") or {}).get("segments") or []
    p = r.get("pair") or {}
    res = max((s["rider_residual_deg"] for s in segs if s.get("complete")), default=None)
    return ("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
        r.get("case") or r["course"], r["level"], o.get("end"), o.get("expect") or "-",
        {True: "yes", False: "no", None: "-"}[o.get("met")], ", ".join(o.get("failed") or []) or "-",
        f(fig.get("rider_rms_deg")), f(fig.get("rider_peak_deg")), f(res), f(fig.get("rider_rate_deg_s")),
        f(p.get("rejection_slopes_max") if p.get("rejection_slopes_max") is not None else p.get("rejection")), f(p.get("speed_kept")),
        f(fig.get("reach_min")), f(fig.get("speed_scale_min")), f(fig.get("yaw_change_deg")), f(fig.get("steer_abs_mean"), 3),
        (o.get("why") or "").replace("|", "/")[:80]))


def write_results(d, rows):
    os.makedirs(d, exist_ok=True)
    history.write_atomically(os.path.join(d, history.LEVEL_RESULTS), lambda fh: fh.write(json.dumps(rows, indent=1) + "\n"))
    lines = ["# Level-assist course runs", "",
             "The rider's error is against the preference (deg). Rejection: the error's RMS with the assist on over off "
             "(the worst slope of 3 deg or more, else the whole run).", "",
             "| case | assist | end | expect | met | failed | rider RMS | rider peak | steady residual | tilt rate /0.3 s | "
             "rejection | speed kept | reach least | speed scale least | yaw change deg | steering effort | why |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"] + [summary_line(r) for r in rows]
    scored = [r for r in rows if r["outcome"].get("met") is not None]
    lines += ["", "%d of %d scored runs met their expectation (%d run)." % (sum(1 for r in scored if r["outcome"]["met"]), len(scored), len(rows))]
    history.write_atomically(os.path.join(d, "level_summary.md"), lambda fh: fh.write("\n".join(lines) + "\n"))


def rescore(run_dir):
    """Every row of a run folder made again from its trace (the measures, the criteria and the expectations as they
    are now); level_results.json and level_summary.md rewritten in place. Returns the rows."""
    out = []
    for rep, rows, path in history.run_rows(run_dir, history.LEVEL_RESULTS):
        d = os.path.dirname(path)
        new, prof = [], None
        for r in rows:
            prof = robots.find(r.get("robot_id") or "") or prof
            tp = os.path.join(d, r.get("trace") or "")
            if prof is None or not r.get("trace") or not os.path.exists(tp):
                new.append(r)  # an error row, or a robot not here: kept as it was
                continue
            with open(tp, encoding="utf-8") as fh:
                trace = json.load(fh)
            case = {"course": r["course"], "dir": r["dir"], "start": r["start"], "variant": r["variant"], "pref": tuple(r["pref"]),
                    "stick": r["stick"], "hold": bool((r.get("hold") or {}).get("on"))}
            row = row_of(prof, case, r["level"], trace, r.get("ran_at"), r.get("case"))
            row["rep"] = rep
            new.append(row)
        if prof is not None:
            finish_rows(prof, [r for r in new if r.get("figures")])
        write_results(d, new)
        out += new
    return out


def report(out):
    try:
        import level_report
        path = level_report.write(out)
        print("report: %s" % path)
    except Exception as exc:  # noqa: BLE001  (the runs are kept whatever the report does)
        print("no report: %s: %s" % (type(exc).__name__, exc))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--robot", help="a robot's id or alias (robots/)")
    ap.add_argument("--courses", default=None, help="comma-separated level_terrain ids (default: the robot's)")
    ap.add_argument("--level", default="off,on", help="off,on (default: both, the off run first)")
    ap.add_argument("--pref", action="append", default=None, metavar="P,R",
                    help='the rider\'s preferred tilt "pitch,roll" in degrees (repeatable; default "0,0")')
    ap.add_argument("--starts", default="centre", help="comma-separated start names (a course without one leaves it out)")
    ap.add_argument("--dirs", default="fwd,rev")
    ap.add_argument("--variants", default="drive", help="comma-separated: %s" % ", ".join(course.VARIANTS))
    ap.add_argument("--stick", default=None, help="the stick's value(s), comma-separated (default: the robot's standard)")
    ap.add_argument("--hold", default="on", choices=("on", "off", "both"), help="the heading and cross-track hold")
    ap.add_argument("--hold-gains", default=None, metavar="K=V,...",
                    help="the hold's gains for this run, over the robot's (k_yaw, k_xt, k_rate, deadzone, max_turn, turn_sign): for tuning it")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--locked-frame-s", type=float, default=None, metavar="S",
                    help="frame-locked stepping (urlab.LockedFrameSeconds); default: the robot's standard; 0 off")
    ap.add_argument("--max-fps", type=float, default=None, help="the frame-rate cap (default: %g locked, else the robot's)" % LOCKED_MAX_FPS)
    ap.add_argument("--imu", action="store_true", help="keep every physics step's IMU sample of the rider (a large trace)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--history", default=None, help="record in this file instead of the robot's level history")
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--history-label", default=None)
    ap.add_argument("--no-report", action="store_true")
    ap.add_argument("--list", action="store_true", help="the courses and the robots there are, and exit")
    ap.add_argument("--rescore", default=None, metavar="DIR", help="make a run folder's rows again from its traces")
    ap.add_argument("--overwrite", action="store_true", help="run into an --out folder that holds an earlier run")
    args = ap.parse_args()
    if args.rescore:
        rows = rescore(args.rescore)
        for r in rows:
            print("  " + summary_line(r))
        if not args.no_history:
            history.add_level_runs([args.rescore], args.history, args.history_label)
        if not args.no_report:
            report(args.rescore)
        return 1 if any(r["outcome"].get("met") is False for r in rows) else 0
    if args.list or not args.robot:
        for c in lt.COURSES:
            print("%-12s %s (starts: %s)" % (c.id, c.title, ", ".join(sorted(c.starts))))
        for p in robots.load_all().values():
            lv = p.get("level")
            print("%-12s %-14s %s" % (p["robot_id"], p.get("name", ""),
                                      "level history %s" % history.rel_path(lv["history_file"]) if lv and lv.get("history_file")
                                      else "no level profile"))
        return 0
    prof = robots.find(args.robot)
    if prof is None:
        print("no robot profile answers to %r (--list)" % args.robot)
        return 2
    if not prof.get("level"):
        print("%s has no level profile (its robot profile's `level`)" % prof["robot_id"])
        return 2
    lv = prof["level"]
    levels = [x for x in args.level.split(",") if x]
    if not levels or any(x not in course.LEVELS for x in levels):
        print("--level takes off,on, not %s" % args.level)
        return 2
    levels = sorted(levels, key=lambda x: x != "off")  # the off run first
    try:
        cases = cases_of(args, prof)
        for c in cases:
            for level in levels:
                plan_of(prof, c, level)  # a case that cannot be planned is refused before anything runs
    except ValueError as exc:
        print(exc)
        return 2
    if not cases:
        print("no case to run")
        return 2
    locked = lv.get("locked_frame_s", 0.0) if args.locked_frame_s is None else args.locked_frame_s
    max_fps = args.max_fps if args.max_fps is not None else (LOCKED_MAX_FPS if locked and locked > 0 else prof.get("max_fps"))
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out = os.path.abspath(args.out or os.path.join(history.DEFAULT_OUT, "level-runs", "%s-%s" % (stamp, prof["robot_id"])))
    if history.run_rows(out, history.LEVEL_RESULTS) and not args.overwrite:
        print("%s holds an earlier run's results: another --out, or --overwrite" % out)
        return 2
    for rep, _, path in history.run_rows(out, history.LEVEL_RESULTS):
        os.remove(path)
    os.makedirs(out, exist_ok=True)
    history.register_level_profiles()
    ran_on = history.code_state((history.LEVEL_HISTORIES.get(prof.get("history_robot")) or {}).get("repos") or history.PUBLIC_REPOS)
    meta = {"argv": [os.path.relpath(__file__, ROOT).replace("\\", "/")] + sys.argv[1:], "started": history.now_utc(),
            "robot_id": prof["robot_id"], "editors": 1, "label": args.history_label}
    history.write_atomically(os.path.join(out, "run.json"), lambda fh: fh.write(json.dumps(meta, indent=1) + "\n"))
    history.write_run_side_file(out, ran_on, meta)
    all_rows = []
    stopped = False  # a file named STOP in the run's folder ends the run after the case in hand (runner_op.stop_asked)
    try:
        for rep in range(1, args.repeat + 1):
            d = os.path.join(out, "rep%d" % rep) if args.repeat > 1 else out
            rows = []
            for c in cases:
                for level in levels:
                    name = course.case_name(c["course"], c["dir"], c["start"], c["variant"], level, c["pref"], c["stick"], c["hold"])
                    if os.path.exists(os.path.join(out, "STOP")):
                        if not stopped:
                            print("stopped: %s is there; the cases left are not run" % os.path.join(out, "STOP"), flush=True)
                        stopped = True
                        continue
                    print("[%s %s%s]" % (prof["robot_id"], name, " rep %d" % rep if args.repeat > 1 else ""), flush=True)
                    try:
                        trace, ran_at, name = run_case(prof, c, level, d, max_fps, locked, args.imu)
                        if trace.get("error"):
                            print("  (the session: %s)" % trace["error"])
                        row = row_of(prof, c, level, trace, ran_at, name)
                    except Exception as exc:  # one broken run must not lose the others
                        row = error_row(prof, c, level, str(exc).splitlines()[0] if str(exc) else type(exc).__name__, name)
                    row["rep"] = rep
                    rows.append(row)
                    all_rows.append(row)
                    finish_rows(prof, [r for r in rows if r.get("figures")])
                    print("  " + summary_line(row), flush=True)
                    write_results(d, rows)
    finally:
        try:
            op("end")  # PIE, t.MaxFPS, ramms.Robot and the PlayerStart back, however the run ended
        except Exception:  # noqa: BLE001
            pass
    if not args.no_history:
        history.add_level_runs([out], args.history, args.history_label)
    if not args.no_report:
        report(out)
    print("results in %s" % out)
    if not all_rows:
        print("no run ran")
        return 1
    return 1 if any(r["outcome"].get("met") is False for r in all_rows) else 0


if __name__ == "__main__":
    sys.exit(main())
