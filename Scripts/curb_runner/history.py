#!/usr/bin/env python3
"""The curb crossings' performance history: one JSON record per crossing in a robot's JSON Lines file, so that its
crossings can be tracked and plotted over time, and compared with another robot's run the same way.

    python -I Scripts/curb_runner/history.py add RUN [RUN ...] [--history FILE] [--label TEXT]
    python -I Scripts/curb_runner/history.py csv --history FILE [--out FILE.csv]
    python -I Scripts/curb_runner/history.py plot --history FILE [--history FILE ...] [--robot NAME] [--out FILE.html] [--all]
    python -I Scripts/curb_runner/history.py list --history FILE

Each RUN is a run_curb.py --out folder (results.json, or rep<k>/results.json, with the traces beside them); the runner
records every run itself as it ends. A record (schema 3; Docs/curb-performance/README.md describes every field):

    identity   schema, robot (the history's robot name), robot_id, scenario, dir, start, descent_start, rep, ran_at, label
    run        dir (relative to the project), started, argv, editors
    code       the commit of each public repository and whether its tracked files differed (ran_on); when the
               editor's plugin binaries were built
    settings   standard (the robot's standard settings), max_fps, frame_ms / frame_max_ms / frame_p99_ms, physics_step_ms,
               maps, ask_sim_s, steady, late_s, cvars, robot (its setup: style, stance, stick, start_offset_cm)
    outcome    phase, pass, met, expect, failed, status, why
    shared     measures.py's events, times and figures: the same definitions for every robot (shared.version)
    rider      the rider's acceleration (measures.rider_figures), or null
    controller the robot's own measurements as its controller reports them (never compared across robots)

Robots register their history here (register()): a robot's profile (robots/) gives its file and its standard. A file
in a public repository keeps public provenance only: the public repositories' commits, paths relative to the project,
nothing of an optional private plugin. Only the standard library.
"""

import argparse
import csv
import datetime
import glob
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
if HERE not in sys.path:
    sys.path.insert(0, HERE)  # history_plot, robots (python -I leaves the script's folder off the path)
DEFAULT_OUT = os.path.join(ROOT, "Saved", "CurbHistory")
SCHEMA = 3
RUN_SIDE_FILE = "history_run.json"


def optional_submodules(root=ROOT):
    """The submodules .gitmodules marks `update = none`: optional ones a public checkout may not have (a private
    plugin), whose state a public record never carries."""
    out, path, skip = [], None, False
    try:
        with open(os.path.join(root, ".gitmodules"), encoding="utf-8") as f:
            lines = f.read().splitlines() + ["[end]"]
    except OSError:
        return out
    for line in lines:
        t = line.strip()
        if t.startswith("["):
            if path and skip:
                out.append(path)
            path, skip = None, False
        elif t.startswith("path"):
            path = t.split("=", 1)[1].strip()
        elif t.replace(" ", "") == "update=none":
            skip = True
    return out


# The public repositories a crossing's code comes from (the superproject first), and what their dirty check leaves out:
# in the superproject the plugins' own changes (each plugin's entry has them; a moved submodule pointer still counts),
# the history itself, and the optional submodules (never named in a public record).
PUBLIC_REPOS = (("sim", ".", ["--ignore-submodules=dirty", "--", ".", ":(exclude)Docs/curb-performance"]
                 + [":(exclude)" + p for p in optional_submodules()]),
                ("core", "Plugins/RammsCore", []),
                ("mujoco", "Plugins/RammsMujocoSupport", []),
                ("urlab", "Plugins/unreal-robotics-lab", []))
BUILT = (("core", "Plugins/RammsCore/Binaries/Win64/UnrealEditor-RammsCore.dll"),
         ("mujoco", "Plugins/RammsMujocoSupport/Binaries/Win64/UnrealEditor-RammsMujocoSupport.dll"))

# name -> {"file", "public", "standard": fn(row) -> bool, "repos", "record": fn or None (the default record)}
HISTORIES = {}


def register(name, history_file, standard, public=True, repos=PUBLIC_REPOS, record_fn=None):
    """A robot's history: its file, its standard-settings predicate, whether the file is public (its lines then must
    pass Scripts/check_public_history.py's rules), the repositories its code state names, and its record builder."""
    HISTORIES[name] = {"file": history_file, "public": public, "standard": standard, "repos": repos, "record": record_fn}


def register_profiles():
    """Every robot profile with a history (robots/), registered. A profile whose history is not public may name more
    repositories (its `repos`: [(name, path from the project, extra git status arguments)]), the public ones first."""
    import robots
    for prof in robots.load_all().values():
        if prof.get("history_robot") and prof.get("history_file"):
            public = bool(prof.get("history_public", True))
            repos = PUBLIC_REPOS if public else PUBLIC_REPOS + tuple(tuple(r) for r in (prof.get("repos") or ()))
            register(prof["history_robot"], prof["history_file"], prof.get("standard") or (lambda row: False),
                     public=public, repos=repos)


# --- code ---------------------------------------------------------------------------------------------------------

def git(repo, *args, strip=True):
    try:
        r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip() if strip else r.stdout


def iso_utc(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat(timespec="seconds") if epoch else None


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def code_state(repos=PUBLIC_REPOS, root=ROOT):
    """Each repository's commit, branch and whether its tracked files differ from it (and up to 20 of them), and when
    the editor's plugin binaries were built (an editor runs what was built, which may be older than the checkout)."""
    state = {}
    for name, rel, extra in repos:
        repo = os.path.join(root, rel)
        sha = git(repo, "rev-parse", "HEAD")
        if not sha:
            continue
        changed = git(repo, "status", "--porcelain", "--untracked-files=no", *extra, strip=False) or ""
        state[name] = {"sha": sha[:12], "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
                       "dirty": bool(changed.strip()), "changed": [l[3:] for l in changed.splitlines() if l.strip()][:20]}
    built = {}
    for name, dll in BUILT:
        p = os.path.join(root, dll)
        if os.path.exists(p):
            built[name] = iso_utc(os.path.getmtime(p))
    if built:
        state["built"] = built
    return state


# --- paths kept public --------------------------------------------------------------------------------------------

def rel_path(p):
    """A path as the project-relative path a public record keeps: relative to the project when it is under it, else
    only its last part (an absolute path names this machine)."""
    if not p:
        return p
    a = os.path.abspath(str(p))
    try:
        rel = os.path.relpath(a, ROOT)
    except ValueError:  # another drive
        rel = None
    if rel is None or rel.startswith(".."):
        return os.path.basename(a.rstrip("\\/"))
    return rel.replace("\\", "/")


def is_abs(s):
    return os.path.isabs(s) or re.match(r"^[A-Za-z]:[\\/]", s) is not None or s.startswith(("/", "\\"))


def public_argv(argv):
    """argv with every path made project-relative (rel_path), an option's joined value (--out=PATH) too."""
    out = []
    for a in argv or []:
        s = str(a)
        if s.startswith("-") and "=" in s:
            k, v = s.split("=", 1)
            out.append(k + "=" + (rel_path(v) if is_abs(v) else v.replace("\\", "/")))
        elif is_abs(s):
            out.append(rel_path(s))
        else:
            out.append(s.replace("\\", "/"))
    return out


ABS_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\|/(?:Users|home)/)[^\s'\"<>|,;]*")


def public_text(text):
    """Free text (a status, a reason, a label) with any absolute path in it made project-relative."""
    if not isinstance(text, str):
        return text
    return ABS_PATH.sub(lambda m: rel_path(m.group(0)), text)


def public_rules():
    """Scripts/check_public_history.py's rules: what no line of a public history may carry."""
    p = os.path.join(ROOT, "Scripts", "check_public_history.py")
    ns = {"__name__": "check_public_history"}
    with open(p, encoding="utf-8") as f:
        exec(compile(f.read(), p, "exec"), ns)
    return ns["RULES"]


# --- reading a run --------------------------------------------------------------------------------------------------

def load_json(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def run_rows(run_dir):
    """(rep, rows, results path) for every results.json of a run: the top-level one, or rep<k>/results.json (a
    --repeat run); a folder that holds both (one run, then another with --repeat) gives the newer."""
    top = os.path.join(run_dir, "results.json")
    reps = []
    for p in glob.glob(os.path.join(run_dir, "rep*", "results.json")):
        m = re.fullmatch(r"rep(\d+)", os.path.basename(os.path.dirname(p)))
        if m:
            reps.append((int(m.group(1)), p))
    if os.path.exists(top) and (not reps or os.path.getmtime(top) >= max(os.path.getmtime(p) for _, p in reps)):
        if reps:
            print("curb history: %s holds both results.json and rep*/: the newer, results.json, counts" % rel_path(run_dir))
        return [(1, load_json(top) or [], top)]
    if reps and os.path.exists(top):
        print("curb history: %s holds both results.json and rep*/: the newer, rep*/, count" % rel_path(run_dir))
    return sorted(((rep, load_json(p) or [], p) for rep, p in reps), key=lambda x: x[0])


def run_id(run_dir):
    """A run folder's identity, the same however its path is typed (records of a folder added again replace its
    earlier ones; two folders with the same last name stay apart): a hash, not a path."""
    import hashlib
    return hashlib.sha1(os.path.normcase(os.path.realpath(run_dir)).encode("utf-8")).hexdigest()[:16]


def num(x, nd=3):
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, nd) if math.isfinite(v) else None


def not_a_crossing(row):
    """Rows for crossings that never ran: the runner's error rows (an editor that died), skipped ones."""
    if not isinstance(row, dict) or not row.get("scenario"):
        return True
    return bool(row.get("skipped")) or str((row.get("outcome") or {}).get("why") or "").startswith("error:")


def record(row, rep, results_path, run_dir, meta, code, label):
    """A run_curb.py row as a record (schema 3)."""
    meta = meta or {}
    h = HISTORIES.get(row.get("history_robot")) or {}
    s = dict(row.get("settings") or {})
    try:
        s["standard"] = bool(h.get("standard", lambda r: False)(row))
    except Exception:  # noqa: BLE001  (a standard predicate that does not know this row)
        s["standard"] = False
    o = row.get("outcome") or {}
    editors = meta.get("editors")
    return {
        "schema": SCHEMA,
        "robot": row.get("history_robot"),
        "robot_id": row.get("robot_id"),
        "scenario": row.get("scenario"),
        "dir": row.get("dir"),
        "start": row.get("start") or "standing",
        "descent_start": row.get("descent_start"),
        "rep": rep,
        "ran_at": row.get("ran_at") or meta.get("started"),
        "label": public_text(label),
        "run": {"id": run_id(run_dir), "dir": rel_path(run_dir), "started": meta.get("started"),
                "argv": public_argv(meta.get("argv")), "editors": (len(editors) if isinstance(editors, list) else editors) or None},
        "code": code,
        "settings": s,
        "outcome": {"phase": o.get("phase"), "pass": o.get("pass"), "met": o.get("met"), "expect": o.get("expect"),
                    "failed": sorted(set(o.get("failed") or [])) or None, "status": public_text(o.get("status")),
                    "why": public_text(o.get("why")) or None},
        "shared": row.get("shared"),
        "rider": row.get("rider"),
        "controller": row.get("controller"),
    }


# --- the history file -----------------------------------------------------------------------------------------------

class HistoryLock(object):
    """An exclusive lock on a history file (FILE.lock) around its read and write: two runs ending together each keep
    their records. A lock older than STALE_S (a recorder killed while holding it) is taken over."""
    STALE_S = 600.0

    def __init__(self, path, timeout=120.0):
        self.path = os.path.abspath(path) + ".lock"
        self.timeout = timeout
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.STALE_S:
                        os.remove(self.path)
                        continue
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError("the history is locked (%s)" % self.path)
                time.sleep(0.25)

    def __exit__(self, *exc):
        try:
            os.close(self.fd)
        finally:
            try:
                os.remove(self.path)
            except OSError:
                pass


def read_history(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    print("curb history: %s line %d is not a record, left out" % (path, n))
    return out


def replace_file(tmp, path, tries=10):
    """os.replace, retried: on Windows a reader holding the file open makes it fail for a moment."""
    for i in range(tries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.5)


def write_atomically(path, write):
    """write(f) into a temporary file beside path, then put it in path's place (never a half-written file)."""
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            write(f)
        replace_file(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_history(path, records):
    """The whole file, ordered by when each crossing ran."""
    records = sorted(records, key=lambda r: (r.get("ran_at") or "", r["run"]["dir"], r["rep"], r["scenario"], r["dir"]))
    write_atomically(path, lambda f: [f.write(json.dumps(r, separators=(",", ":")) + "\n") for r in records])


def write_run_side_file(run_dir, ran_on, meta):
    """The code a run ran on and its meta, in the run folder (history_run.json): a later `add` of it keeps them."""
    try:
        write_atomically(os.path.join(run_dir, RUN_SIDE_FILE),
                         lambda f: f.write(json.dumps({"ran_on": ran_on, "meta": meta}, indent=1) + "\n"))
    except OSError as e:
        print("curb history: could not write %s (%s)" % (RUN_SIDE_FILE, e))


def add_runs(run_dirs, history=None, label=None, quiet=False):
    """Record every crossing of run_dirs in its robot's history (or `history`), replacing all of each folder's earlier
    records there; returns how many were written. The code each ran on comes from the folder's history_run.json, else
    the checkout now (kept as `at_record`)."""
    if not HISTORIES:
        register_profiles()
    by_file, public_by_file = {}, {}
    for run_dir in run_dirs:
        side = load_json(os.path.join(run_dir, RUN_SIDE_FILE)) or {}
        meta = dict(side.get("meta") or {})
        meta.update(load_json(os.path.join(run_dir, "run.json")) or {})
        for rep, rows, path in run_rows(run_dir):
            for row in rows:
                if not_a_crossing(row):
                    continue
                h = HISTORIES.get(row.get("history_robot"))
                if h is None and history is None:
                    continue
                target = history or h["file"]
                repos = (h or {}).get("repos") or PUBLIC_REPOS
                code = {"ran_on": side["ran_on"]} if side.get("ran_on") else {"at_record": code_state(repos)}
                build = (h or {}).get("record") or record
                rec = build(row, rep, path, run_dir, meta, code, label or meta.get("label"))
                by_file.setdefault(target, {}).setdefault(rec["run"].get("id") or rec["run"]["dir"], []).append(rec)
                public_by_file[target] = (h or {}).get("public", True)
    n = 0
    for target, new in by_file.items():
        if public_by_file.get(target):
            # A public history takes no line its pre-commit hook would refuse.
            rules = public_rules()
            for recs in new.values():
                for rec in recs:
                    line = json.dumps(rec, separators=(",", ":"))
                    hit = next((what for rx, what in rules if rx.search(line)), None)
                    if hit:
                        raise ValueError("a record for the public history %s carries %s: not written" % (rel_path(target), hit))
        with HistoryLock(target):
            have = read_history(target)

            def key(r):
                return r["run"].get("id") or r["run"]["dir"]
            old_label = {}
            for r in have:
                if r.get("label"):
                    old_label.setdefault(key(r), r["label"])
            # A record from before run ids (none) is replaced by the same folder's new ones.
            new_dirs = {rec["run"]["dir"] for recs in new.values() for rec in recs}
            kept = [r for r in have if key(r) not in new and (r["run"].get("id") or r["run"]["dir"] not in new_dirs)]
            for d, recs in new.items():
                for rec in recs:
                    if not rec.get("label") and old_label.get(d):
                        rec["label"] = old_label[d]
                kept += recs
                n += len(recs)
            write_history(target, kept)
        if not quiet:
            print("curb history: %d crossing(s) recorded in %s (%d in all)" % (sum(len(v) for v in new.values()), rel_path(target), len(kept)))
    return n


# --- export -------------------------------------------------------------------------------------------------------

def flat(rec, prefix=""):
    out = {}
    for k, v in rec.items():
        name = prefix + k
        if isinstance(v, dict) and k not in ("code", "down", "stance"):
            out.update(flat(v, name + "."))
        elif isinstance(v, list):
            out[name] = ";".join("" if x is None else str(x) for x in v)
        elif isinstance(v, dict):
            out[name] = json.dumps(v, separators=(",", ":"))
        else:
            out[name] = v
    return out


def to_csv(records, out):
    rows = [flat(r) for r in records]
    cols = []
    for r in rows:
        for c in r:
            if c not in cols:
                cols.append(c)

    def write(f):
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    write_atomically(out, write)
    print("curb history: %d row(s) to %s" % (len(rows), out))


def code_label(rec):
    c = rec.get("code") or {}
    at = c.get("ran_on") or c.get("at_record") or {}
    core = at.get("core") or {}
    if core.get("sha"):
        dirty = any(v.get("dirty") for k, v in at.items() if isinstance(v, dict) and k != "built")
        return "%score %s%s" % ("" if c.get("ran_on") else "(at record) ", core["sha"][:7], "+" if dirty else "")
    return (c.get("ran_on_note") or {}).get("note") or "?"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="record a run's crossings")
    a.add_argument("runs", nargs="+")
    a.add_argument("--history", default=None, help="this file instead of each robot's own")
    a.add_argument("--label", default=None)
    c = sub.add_parser("csv", help="a history as one flat CSV")
    c.add_argument("--history", required=True)
    c.add_argument("--out", default=None)
    p = sub.add_parser("plot", help="an HTML page of histories' charts")
    p.add_argument("--history", action="append", required=True, help="a history file (more than one: their robots together)")
    p.add_argument("--robot", action="append", default=None, help="only this robot's records (repeatable)")
    p.add_argument("--out", default=None)
    p.add_argument("--all", action="store_true", help="every record, not only those at the standard settings")
    ls = sub.add_parser("list", help="the runs in a history")
    ls.add_argument("--history", required=True)
    args = ap.parse_args()
    if args.cmd == "add":
        register_profiles()
        add_runs(args.runs, args.history, args.label)
    elif args.cmd == "csv":
        stem = os.path.splitext(os.path.basename(args.history))[0]
        to_csv(read_history(args.history), args.out or os.path.join(DEFAULT_OUT, stem + ".csv"))
    elif args.cmd == "plot":
        import history_plot
        recs = [r for h in args.history for r in read_history(h)]
        if args.robot:
            recs = [r for r in recs if r.get("robot") in args.robot]
        stem = "_".join(os.path.splitext(os.path.basename(h))[0] for h in args.history)
        history_plot.write(recs, args.out or os.path.join(DEFAULT_OUT, stem + ".html"), standard_only=not args.all)
    elif args.cmd == "list":
        runs = {}
        for r in read_history(args.history):
            runs.setdefault(r["run"]["dir"], []).append(r)
        for d, rs in sorted(runs.items(), key=lambda kv: min(x.get("ran_at") or "" for x in kv[1])):
            met = sum(1 for x in rs if x["outcome"].get("met"))
            print("%s  %-60s %3d crossings, %3d met, %s%s" % (min(x.get("ran_at") or "" for x in rs)[:16], d, len(rs), met,
                                                        code_label(rs[0]), "  [%s]" % rs[0]["label"] if rs[0].get("label") else ""))


if __name__ == "__main__":
    main()
