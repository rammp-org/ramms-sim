"""Whether a crossing passed, and met what it was expected to do: the same checks for every robot, plus the robot's own
(its profile's checks(row)). Only the standard library.

Expectations (a profile's expect(scenario, dir)):
  pass             it crosses: every check below passes
  refuse:<regex>   it refuses the crossing, in words the regex finds in the controller's reason
  explore          run and recorded, not scored (met is None)

The shared checks of a crossing that ran:
  done        it ended Done
  across      every wheel it stood on at the ask came down past the edge (measures: shared.across)
  step        the step the controller found is the map's, within STEP_TOL_CM of the range across its tracks
  level       its final pitch and roll (at Done) are within FINAL_LEVEL_DEG of how it stood at the ask, less what the
              two surfaces' slopes explain (measures: final_pitch_change_deg / final_roll_change_deg)
  landing     every wheel came down at least LANDING_MIN_R radii past the edge
  upright     its chassis never leaned past UPRIGHT_DEG
"""

import re

STEP_TOL_CM = 1.5
FINAL_LEVEL_DEG = 1.5
LANDING_MIN_R = 0.3
UPRIGHT_DEG = 25.0


def shared_checks(row, step_range):
    o = row.get("outcome") or {}
    sh = row.get("shared") or {}
    att = sh.get("attitude") or {}
    failed = []
    if o.get("phase") != "DONE":
        failed.append("done")
    if not sh.get("across"):
        failed.append("across")
    found = (row.get("controller") or {}).get("step_found")
    if not found or step_range is None or not (min(step_range) - STEP_TOL_CM <= found[0] <= max(step_range) + STEP_TOL_CM):
        failed.append("step")
    fp, fr = att.get("final_pitch_change_deg"), att.get("final_roll_change_deg")
    if fp is None or fr is None or abs(fp) > FINAL_LEVEL_DEG or abs(fr) > FINAL_LEVEL_DEG:
        failed.append("level")
    lr = (sh.get("landing") or {}).get("min_r")
    if lr is None or lr < LANDING_MIN_R:
        failed.append("landing")
    if (att.get("max_chassis_incl_to_done_deg", att.get("max_chassis_incl_deg")) or 0.0) > UPRIGHT_DEG:
        failed.append("upright")
    return failed


def score(row, expect, step_range, robot_checks=None):
    """{"pass", "met", "failed"} for a row (run_curb.py's), its expectation and the map's step range."""
    o = row.get("outcome") or {}
    if expect.startswith("refuse:"):
        refused = o.get("phase") == "REFUSED"
        ok = refused and re.search(expect[len("refuse:"):], o.get("why") or "") is not None
        return {"pass": None, "met": bool(ok), "failed": [] if ok else (["refused otherwise"] if refused else ["not refused"])}
    if o.get("phase") == "REFUSED":
        return {"pass": False, "met": False if expect == "pass" else None, "failed": ["refused"]}
    failed = shared_checks(row, step_range)
    if robot_checks:
        failed += [c for c in robot_checks(row) if c not in failed]
    passed = not failed
    return {"pass": passed, "met": passed if expect == "pass" else None, "failed": failed}
