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
#
# THREE POINTS. This robot's roll is made by its two elevators alone: with any roll corrected it stands on both drive
# wheels and ONE rear omni wheel. Two of the checks below were written for a robot on four wheels and are held here to
# what three points can do:
#   margin_under_off_cm  was 1.0. Standing or at a crawl with roll corrected the bearing triangle is 2.2 to 3.2 cm
#                        tighter than the four-wheel stance on the same cross slope (measured, 2026-11-24; never less
#                        than 11 cm left, against the 3 cm of margin_cm), so "no more than 1 cm under the assist-off
#                        run" failed 18 of 56 runs for the stance itself. 3.5: the triangle's cost and no more.
#   at_reach_s           0.0 stays, and means the LEGS' reach: standing across exactly 6 deg the roll correction rests
#                        on its 6 deg limit and the status says so, which is the robot doing as authored, not a run
#                        out of reach. Courses whose cross fall is at that limit are not to be failed on it while the
#                        robot stands or crawls (the score has no such exception yet: read CROSS6's at-reach time with
#                        this in mind).
# The level assist carries roll on this robot up to a walk: all of it while the stick asks 60 cm/s or less (the standard
# stick, 0.5, asks 60), none of it once the stick asks 65 or more (Ramms.Level.ThreePointFullCmS / NoneCmS; all or none,
# never a part). So:
#   at the standard stick   the roll checks hold on a cross fall as on anything else (simulator, 2026-11-25: CROSS6 0.20
#                           deg RMS, CROSS2 0.06, CROWN 0.10 to 0.14, WARP 0.28, at the assist-off robot's pace).
#   at full stick           the rider's roll on a cross fall is the fall's own: steady_residual_deg, rider_rms_deg and
#                           rejection_max cannot pass there by design, and say nothing against the assist. The score
#                           does not yet tell that case apart; judge cross-fall segments driven at full stick by tilt
#                           rate, stops, floats and the yaw measures, not by the rider's roll. (The drive is held to 60
#                           cm/s for the 2 to 3 s the roll takes to walk out: the scale reads 0.5 there.)
#   a roll under 0.75 deg   is not corrected at all (and let go again under 0.5): on three points even that lifts a rear
#                           omni wheel. A robot straddling a crown rides up to 0.85 deg off, and steady_residual_deg can
#                           fail there for the dead band alone.
# In pitch a slope is levelled at any speed (the crest rule, which left part of a fast slope in the base, is off: it
# cost every ramp at full stick more than it saved at a crest). The price is a crest: over a break of twice 6 deg at
# full stick the levelled robot is thrown 9.4 deg where the robot switched off is thrown 8.0, and rider_peak_deg fails
# there; at the standard stick the same crest is 3.3 deg.
LEVEL_CRITERIA = {
    "steady_residual_deg": 0.5,  # the rider's error against the preference at the end of every constant segment
    "rider_rms_deg": 1.0,  # over the driven span
    "rider_peak_deg": 3.0,  # no seat mechanism: what the base leaves, the rider gets
    "tilt_rate_deg_s": 4.0,  # over 0.3 s
    "rejection_max": 0.3,  # the rider's error RMS on over off, on slopes of 3 deg or more
    "stops": 0,
    "speed_kept_slope": 0.8,  # mean speed on over off, on constant slopes ...
    "speed_kept_overall": 0.6,  # ... and over the run
    "at_reach_s": 0.0,  # the legs' reach; resting on the 6 deg roll limit standing across 6 deg is not this (see above)
    "margin_cm": 3.0,  # the centre of mass inside the bearing wheels' hull ...
    "margin_under_off_cm": 3.5,  # ... and no more than this under the assist-off run's (three points: see above)
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
