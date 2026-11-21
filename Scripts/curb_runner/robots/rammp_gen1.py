"""RAMMP Gen1 on the curb runner (see robots/__init__.py for what a profile holds).

Its curb controller is URammsRammpGen1CurbController (RammsCore). Standard runs: the Blended style (it rolls through a
crossing, as the real robot does), the outdoor stance (front arm -14 deg: the front omni wheels up; elevators 9 deg),
the rider's stick held at 1 (the controller goes on only while it is held; its speed does not scale with it), asked for
at rest 5 s into the run, at the runner's 16 fps.
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))

STANDARD_MAX_FPS = 16.0
FRAME_MS = 1000.0 / STANDARD_MAX_FPS
SETUP = {
    "style": 1,  # curb.style: 1 Blended, 0 Stepped
    "stance": {"lift.front_caster_swing_arm": -14.0, "lift.motor_swing_arm_l": 9.0, "lift.motor_swing_arm_r": 9.0},
    "stick": 1.0,
}
# The maps inside its limits, and what the others must do: it refuses a step taller than its Config.MaxStepCm (17 cm)
# and an edge more than Config.MaxApproachDeg off square (which, near the edge of its scan, it may report as a step
# that does not run straight across its path).
PASS = ("S0", "S4")
REFUSE = {"S8": "more than 17", "A15": "off square|does not run straight across", "A30": "off square|does not run straight across",
          "A30N": "off square|does not run straight across", "R_A40": "off square|does not run straight across"}


def expect(sid, direction):
    if sid in PASS:
        return "pass"
    if sid in REFUSE and direction == "up":
        return "refuse:" + REFUSE[sid]
    return "explore"


def standard(row):
    """Run at the standard settings: the 16 fps cap with frames near it, the standard setup and start, asked for at
    rest on time, no console variables of its own."""
    s = row.get("settings") or {}
    if s.get("cvars") or s.get("max_fps") != STANDARD_MAX_FPS:
        return False
    frame = s.get("frame_ms")
    if frame is None or abs(frame - FRAME_MS) > 0.1 * FRAME_MS:
        return False
    robot = s.get("robot") or {}
    if robot.get("style") != SETUP["style"] or robot.get("stance") != SETUP["stance"] or robot.get("stick") != SETUP["stick"]:
        return False
    if row.get("start") != "standing":
        return False
    if row.get("dir") == "up" and robot.get("start_offset_cm") != PROFILE["start_offset_cm"]:
        return False
    return bool(s.get("steady")) and s.get("ask_sim_s") == 5.0 and (s.get("late_s") or 0.0) <= FRAME_MS / 1000.0


def checks(row):
    """Gen1's own: every lift back where it was at the ask (0.5 deg, 0.5 cm), as run_rammp_gen1_curb.sh checks."""
    c = row.get("controller") or {}
    return [] if c.get("lifts_back", True) else ["lifts back"]


PROFILE = {
    "robot_id": "rammp_gen1",
    "aliases": ["Gen1", "RammpGen1"],
    "name": "RAMMP Gen1",
    "history_robot": "gen1",
    "history_file": os.path.join(ROOT, "Docs", "curb-performance", "gen1_history.jsonl"),
    "history_public": True,
    "editor": "rammp_gen1_editor.py",
    # The adapter's wheel order: the controller's Config bodies, radii from its Config geometry.
    "wheels": [
        {"name": "front_omni_l", "radius_cm": 7.66, "powered": True},
        {"name": "front_omni_r", "radius_cm": 7.66, "powered": True},
        {"name": "drive_wheel_l", "radius_cm": 18.4, "powered": True},
        {"name": "drive_wheel_r", "radius_cm": 18.4, "powered": True},
        {"name": "rear_omni_l", "radius_cm": 10.11, "powered": False},
        {"name": "rear_omni_r", "radius_cm": 10.11, "powered": False},
    ],
    "rider_body": "rider",
    # From the map's PlayerStart its front hubs are about 153 cm from the edge, past its 150 cm scan (a probe on
    # 2026-11-21: refused at the spawn, accepted 13 cm on).
    "start_offset_cm": 20.0,
    "descent_start": "top",
    "setup": SETUP,
    "scenarios": list(PASS),
    "max_fps": STANDARD_MAX_FPS,
    "expect": expect,
    "standard": standard,
    "checks": checks,
}
