"""The robots the curb runner can run: one profile module per robot, found by discovery.

A profile is a module that defines PROFILE, a dict:

    robot_id         the robot definition's id the map starts (ramms.Robot), e.g. "rammp_gen1"
    aliases          other names it answers to on the command line
    name             as shown, e.g. "RAMMP Gen1"
    history_robot    its history's robot name ("gen1"); history_file: the JSON Lines file its records go to;
                     history_public: whether that file is in a public repository (provenance is then kept public)
    editor           the editor-side adapter file (run inside the editor by runner_op.py), next to the profile
    wheels           [{"name", "radius_cm", "powered", "axle": [x, y, z] chassis frame (default +Y)}], the adapter's
                     wheel order
    start_offset_cm  how far ahead of the map's PlayerStart (along its heading) the robot starts a climb
    descent_start    "top": a descent starts on the sidewalk (curb_terrain.Layout.top_start_pose)
    setup            the robot's standard setup, given to the adapter's prepare() (its own words)
    scenarios        the maps it runs by default
    expect(sid, dir) -> "pass" | "refuse:<regex>" | "explore": what a crossing should do
    standard(row)    -> bool: the row ran at the robot's standard settings
    checks(row)      -> [failed check names] (optional): the robot's own pass checks, beside the shared ones

Discovery, in order (a later profile with the same robot_id replaces an earlier one):
  1. Scripts/curb_runner/robots/*.py (not *_editor.py);
  2. Plugins/*/Scripts/curb_runner_robots/*.py: a plugin's own robots, found only while it is checked out;
  3. the files and folders in $RAMMS_CURB_ROBOTS (os.pathsep-separated): your own.
Only the standard library.
"""

import glob
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
ENV = "RAMMS_CURB_ROBOTS"

_PROFILES = {}
_LOADED = False


def _candidates():
    out = [p for p in sorted(glob.glob(os.path.join(HERE, "*.py"))) if not p.endswith(("__init__.py", "_editor.py"))]
    out += sorted(p for p in glob.glob(os.path.join(ROOT, "Plugins", "*", "Scripts", "curb_runner_robots", "*.py"))
                  if not p.endswith(("__init__.py", "_editor.py")))
    for entry in [e for e in os.environ.get(ENV, "").split(os.pathsep) if e.strip()]:
        if os.path.isdir(entry):
            out += sorted(p for p in glob.glob(os.path.join(entry, "*.py")) if not p.endswith(("__init__.py", "_editor.py")))
        elif os.path.isfile(entry):
            out.append(entry)
    return out


def _load(path):
    name = "curb_robot_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    prof = getattr(mod, "PROFILE", None)
    if not isinstance(prof, dict) or not prof.get("robot_id"):
        return None
    prof = dict(prof)
    prof["_file"] = os.path.abspath(path)
    if prof.get("editor") and not os.path.isabs(prof["editor"]):
        prof["editor"] = os.path.join(os.path.dirname(prof["_file"]), prof["editor"])
    return prof


def load_all():
    global _LOADED
    if _LOADED:
        return _PROFILES
    for p in _candidates():
        try:
            prof = _load(p)
        except Exception as exc:  # one broken profile must not hide the others
            print("curb runner: robot profile %s did not load: %s" % (p, exc))
            continue
        if prof:
            _PROFILES[prof["robot_id"]] = prof
    _LOADED = True
    return _PROFILES


def find(words):
    """The profile whose robot_id, alias, name or history robot is `words` (any case), or None."""
    w = str(words or "").strip().lower()
    for prof in load_all().values():
        names = [prof["robot_id"], prof.get("name", ""), prof.get("history_robot", "")] + list(prof.get("aliases") or [])
        if w in (n.lower() for n in names if n):
            return prof
    return None


def by_history_robot(name):
    for prof in load_all().values():
        if prof.get("history_robot") == name:
            return prof
    return None
