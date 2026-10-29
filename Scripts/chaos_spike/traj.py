"""Target schedules shared by the MuJoCo reference (mj_run.py) and the Chaos run (chaos_pie.py).
A schedule maps time (s) to {actuator name: ctrl}, in the MJCF's own ctrl units."""
ARM = ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6", "joint_7"]
GRIP = "2f85_fingers_actuator"

# Gen3 + 2F-85, arm tracking: out at 1-3 s, hold, back at 7-8.5 s; the gripper closes 4-6.5 s.
POSE = {"joint_1": 0.6, "joint_2": 0.9, "joint_3": 0.0, "joint_4": 1.6, "joint_5": 0.0, "joint_6": 0.6, "joint_7": 0.8}
def arm(t, J=None):
    s = min(max((t - 1.0) / 2.0, 0.0), 1.0); r = min(max((t - 7.0) / 1.5, 0.0), 1.0)
    c = {j: s * (1.0 - r) * POSE[j] for j in ARM}
    c[GRIP] = 255.0 if 4.0 <= t < 6.5 else 0.0
    return c
arm.end = 9.0

# Grasp hold: a 3x3x5 cm, 50 g box stands on the gripper base between the open fingers; close at 1 s,
# then tip the gripper over (joints 2, 4, 6) so gravity pulls the box across the pads.
GRASP_POSE = {"joint_1": 0.0, "joint_2": 0.6, "joint_3": 0.0, "joint_4": 1.9, "joint_5": 0.0, "joint_6": 1.4, "joint_7": 0.0}
BOX = {"pos_ue": (0.0, 2.49, 131.4), "half_cm": (1.5, 1.5, 2.5), "mass": 0.05}
def grasp(t, J=None):
    s = min(max((t - 3.0) / 2.0, 0.0), 1.0)
    c = {j: s * GRASP_POSE[j] for j in ARM}
    c[GRIP] = 255.0 if t >= 1.0 else 0.0
    return c
grasp.end = 8.0

# A base with keyframes (low / mid / full / tilt): settle, move through the stances by ramping the servo
# ctrls between keyframes, then drive straight with equal wheel torques. Needs the export's "keys".
BASE_STEPS = [(1.0, "mid"), (3.0, "full"), (5.0, "tilt"), (7.0, "mid")]   # ramp to key over 2 s starting at t
BASE_DRIVE = (9.5, 12.0, 8.0)   # wheel torque (ctrl) from t0 to t1
def base(t, J):
    names = [a["name"] for a in J["actuators"]]; keys = J["keys"]
    cur = [0.0] * len(names)
    for t0, k in BASE_STEPS:
        s = min(max((t - t0) / 2.0, 0.0), 1.0)
        cur = [a + s * (b - a) for a, b in zip(cur, keys[k])]
    c = {}
    for a, v in zip(J["actuators"], cur):
        if a["kind"] == "servo": c[a["name"]] = v
        else: c[a["name"]] = BASE_DRIVE[2] * float(BASE_SIDE.get(a["name"], 1.0)) if BASE_DRIVE[0] <= t < BASE_DRIVE[1] else 0.0
    return c
base.end = 13.0
BASE_SIDE = {}   # per-wheel sign, filled in by the caller when the two sides spin opposite ways
SCHEDULES = {"arm": arm, "grasp": grasp, "base": base}

# An articulated object (no actuators): push every joint open for 0.5 s with a generalized force scaled
# to its moving body's mass (1.2 N.m per kg on a hinge, 5 N per kg on a slide), then let it coast.
def obj(t, J):
    mass = {b["name"]: b["mass"] for b in J["bodies"]}
    if not (0.5 <= t < 1.0): return {}
    return {"__qfrc__": {j["name"]: (1.2 if j["type"] == "hinge" else 5.0) * max(mass.get(j["child"], 0.0), 0.05)
                         for j in J["joints"] if j["type"] in ("hinge", "slide")}}
obj.end = 4.0
SCHEDULES["object"] = obj

# Driving only: ramp to the mid stance, then the same equal wheel torques (isolates heading drift).
def _base_drive(t, J):
    names = [a["name"] for a in J["actuators"]]; mid = J["keys"]["mid"]; s = min(max(t / 2.0, 0.0), 1.0)
    c = {}
    for a, v in zip(J["actuators"], mid):
        c[a["name"]] = s * v if a["kind"] == "servo" else (BASE_DRIVE[2] if 3.0 <= t < 5.5 else 0.0)
    return c
_base_drive.end = 6.0
SCHEDULES["base_drive"] = _base_drive
def _base_drive_rev(t, J):
    c = _base_drive(t, J)
    return {k: (-v if J and any(a["name"] == k and a["kind"] == "motor" for a in J["actuators"]) else v) for k, v in c.items()}
_base_drive_rev.end = 6.0
SCHEDULES["base_drive_rev"] = _base_drive_rev
