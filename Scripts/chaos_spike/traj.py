"""Shared target schedule (radians for arm joints, 0..255 for the gripper) for the MuJoCo reference and the Chaos run."""
ARM = ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6", "joint_7"]
POSE = {"joint_1": 0.6, "joint_2": 0.9, "joint_3": 0.0, "joint_4": 1.6, "joint_5": 0.0, "joint_6": 0.6, "joint_7": 0.8}
T_END = 9.0
def targets(t):
    s = min(max((t - 1.0) / 2.0, 0.0), 1.0)          # 1-3 s: ramp out
    r = min(max((t - 7.0) / 1.5, 0.0), 1.0)          # 7-8.5 s: ramp back
    k = s * (1.0 - r)
    q = {j: k * POSE[j] for j in ARM}
    grip = 255.0 if 4.0 <= t < 6.5 else 0.0          # close 4-6.5 s
    return q, grip

# Grasp hold: a 3x3x5 cm, 50 g box stands on the gripper base between the open fingers; close, then tip the
# gripper over (joint_4, joint_6) so gravity pulls the box across the pads, and hold.
GRASP_POSE = {"joint_1": 0.0, "joint_2": 0.6, "joint_3": 0.0, "joint_4": 1.9, "joint_5": 0.0, "joint_6": 1.4, "joint_7": 0.0}
GRASP_END = 8.0
BOX = {"pos_ue": (0.0, 2.49, 131.4), "half_cm": (1.5, 1.5, 2.5), "mass": 0.05}
def targets_grasp(t):
    s = min(max((t - 3.0) / 2.0, 0.0), 1.0)
    q = {j: s * GRASP_POSE[j] for j in ARM}
    grip = 255.0 if t >= 1.0 else 0.0
    return q, grip
