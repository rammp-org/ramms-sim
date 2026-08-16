"""Strict per-motor bench v2: correct downstream mapping (user topology),
BOTH stroke directions, pass if EITHER direction articulates >= threshold
with bounded base motion."""
import numpy as np
import mujoco
import os

os.chdir(r"C:\Users\waemf\data\Ramms\mujoco\mebot")
model = mujoco.MjModel.from_xml_path("mebot_gen3_scene.xml")

TESTS = [
    ("front_caster_motor_rod", "front_caster_swing_arm", 0.15),
    ("rear_caster_motor_rod", "rear_caster_suspension_arm", 0.15),
    ("motor_elevator_rod_l", "motor_swing_arm_l", 0.15),
    ("motor_elevator_rod_r", "motor_swing_arm_r", 0.15),
]

def stroke(act, joint, ctrl):
    data = mujoco.MjData(model)
    dt = model.opt.timestep
    for _ in range(int(3 / dt)):
        mujoco.mj_step(model, data)
    aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, act)
    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
    bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "mebot")
    rid = model.actuator_trnid[aid][0]
    q0 = float(data.qpos[model.jnt_qposadr[jid]])
    p0 = data.xpos[bid].copy()
    data.ctrl[aid] = ctrl
    for _ in range(int(4 / dt)):
        mujoco.mj_step(model, data)
    q1 = float(data.qpos[model.jnt_qposadr[jid]])
    rod = float(data.qpos[model.jnt_qposadr[rid]])
    slide = float(np.linalg.norm((data.xpos[bid] - p0)[:2])) * 100
    return abs(q1 - q0), rod, slide

for act, joint, need in TESTS:
    for ctrl in (-0.06, +0.06):
        art, rod, slide = stroke(act, joint, ctrl)
        ok = art >= need and slide <= 10
        print("%-4s %-24s ctrl=%+0.2f art=%.3f rad (need %.2f) rod=%+.4f slide=%.1f cm"
              % ("PASS" if ok else "FAIL", act, ctrl, art, need, rod, slide))
