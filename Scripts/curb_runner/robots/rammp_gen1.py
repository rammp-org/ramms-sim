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
    if s.get("locked_frame_s"):
        return False  # frame-locked stepping (urlab.LockedFrameSeconds): a series of its own until it is the standard
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


# --- level-assist courses (run_level.py; level_measures.score reads `criteria`) ---------------------------------------
# What a run with the assist on must do, per the level plan's pass criteria (its section I): Gen1's values are public.
LEVEL_CRITERIA = {
    "steady_residual_deg": 0.5,  # the rider's error against the preference at the end of every constant segment
    "rider_rms_deg": 1.0,  # over the driven span
    "rider_peak_deg": 3.0,  # no seat mechanism: what the base leaves, the rider gets
    "tilt_rate_deg_s": 4.0,  # over 0.3 s
    "rejection_max": 0.3,  # the rider's error RMS on over off, on slopes of 3 deg or more
    "stops": 0,
    "speed_kept_slope": 0.8,  # mean speed on over off, on constant slopes ...
    "speed_kept_overall": 0.6,  # ... and over the run
    "at_reach_s": 0.0,
    "margin_cm": 3.0,  # the centre of mass inside the bearing wheels' hull ...
    "margin_under_off_cm": 1.0,  # ... and no more than this under the assist-off run's
    "drive_share_under_off": 0.02,  # the drive wheels' least share of the load: not below the off run's (by more than this)
    "float_s": 0.2,  # no drive wheel off the ground longer
    "level_after_flat_deg": 0.5,  # 3 s after the last seam back onto the flat
    "flat_rms_over_off_deg": 0.2,  # FLAT: on within this of off
    "flat_leg_travel_rms_cm": 0.2,  # FLAT: no hunting
    # Past the legs' reach (about 7 deg nose up at the outdoor stance): the tilt bounded by the ground less the reach.
    "past_reach": {"reach_deg": 7.0, "tilt_over_deg": 0.5, "rate_deg_s": 3.5, "speed_floor": 0.25},
    "parked": {"drift_cm": 1.0, "cmd_changes": 0, "toggle_rate_deg_s": 3.5, "mode_switch_deg": None},
}
LEVEL_COURSES = ["FLAT", "RAMP5", "CROSS2", "CROSS6", "BREAK6", "STEEPEN", "WARP", "CROWN", "FOLD", "COMBO", "TRANSITIONS"]
LEVEL_LOCKED_FRAME_S = 0.0625  # the standard series is frame-locked: a levelling run has no planner to wait for
LEVEL_STICK = 0.5  # about 60 of its 120 cm/s


def level_expect(course_id, direction, start, variant):
    """What an assist-on run should do (level_measures.score): its roll is capped at 6 deg and its nose-up reach is
    about 7, so the 8 deg ramp is past its reach and the 12 deg one is only explored."""
    if variant == "parked":
        return "parked"
    if variant in ("toggle", "pref_step", "mode"):
        return "rates"
    if course_id == "RAMP12":
        return "explore"
    if course_id == "RAMP8":
        return "past_reach"
    return "pass"


def level_standard(row):
    """A course run at the standard settings: frame-locked at 1/16 s, the standard setup and stick, the hold on,
    steady at the gate, no console variables of its own."""
    s = row.get("settings") or {}
    if s.get("cvars") or s.get("locked_frame_s") != LEVEL_LOCKED_FRAME_S:
        return False
    robot = s.get("robot") or {}
    if robot.get("style") != SETUP["style"] or robot.get("stance") != SETUP["stance"]:
        return False
    return bool(s.get("steady")) and row.get("stick") in (LEVEL_STICK, 0.0) and bool((row.get("hold") or {}).get("on"))


LEVEL = {
    "stick": LEVEL_STICK,
    "speed_cm_s": 60.0,  # what that stick gives, for a run's timeout only
    "locked_frame_s": LEVEL_LOCKED_FRAME_S,
    "setup": {"style": SETUP["style"], "stance": SETUP["stance"]},
    # The outdoor stance stands on the drive wheels and the rear omni wheels; the front ones are held up.
    "support_wheels": ["drive_wheel_l", "drive_wheel_r", "rear_omni_l", "rear_omni_r"],
    "drive_wheels": ["drive_wheel_l", "drive_wheel_r"],
    "rider_offset_deg": None,  # the seat against the chassis, taken at each run's steady gate
    "alt_mode": None,  # (the mode it drives in, its other one), for the variants that switch
    # As tuned in the editor (FLAT from the yaw5 start, 2026-11-24). The differential drive takes nothing under its
    # 0.05 stick dead zone and rescales the rest: with the plain gains the hold's small turns never reached the
    # wheels and the robot wove +-20 cm / +-4 deg about its path. The dead zone is carried; the gains are low and the
    # rate term small because the heading answers the stick late (the wheels' speed loops against the robot's yaw
    # inertia): a yawed start is back within 1.5 deg in 5 s without a second swing.
    "hold": {"k_yaw": 0.02, "k_xt": 0.002, "k_rate": 0.02, "deadzone": 0.05},
    "courses": LEVEL_COURSES,
    "criteria": LEVEL_CRITERIA,
    "expect": level_expect,
    "standard": level_standard,
    "history_file": os.path.join(ROOT, "Docs", "level-performance", "gen1_level_history.jsonl"),
}

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
    "level": LEVEL,
}
