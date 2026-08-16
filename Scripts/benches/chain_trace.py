"""Trace per-joint motion through the caster chains during a rod stroke."""
import sys
import numpy as np
import mujoco
import os

os.chdir(r"C:\Users\waemf\data\Ramms\mujoco\mebot")
model = mujoco.MjModel.from_xml_path("mebot_gen3_scene.xml")

CHAINS = {
    "rear_caster_motor_rod": [
        "rear_caster_motor", "rear_caster_motor_rod",
        "rear_caster_suspension_arm", "rear_caster_aux_linkage",
        "rear_caster_motor_dampener_pivot", "rear_caster_dampener",
        "rear_caster_dampener_rod", "rear_caster_swing_arm",
    ],
    "front_caster_motor_rod": [
        "front_caster_motor", "front_caster_motor_rod",
        "front_caster_linkage", "front_caster_linkage_arm",
        "front_caster_linkage_aux", "front_caster_linkage_aux_arm",
        "front_caster_swing_arm",
    ],
}

for act_name, chain in CHAINS.items():
    data = mujoco.MjData(model)
    dt = model.opt.timestep
    for _ in range(int(4 / dt)):
        mujoco.mj_step(model, data)
    aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, act_name)
    def snap():
        out = {}
        for jn in chain:
            j = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, jn)
            if j < 0:
                out[jn] = None
            else:
                out[jn] = float(data.qpos[model.jnt_qposadr[j]])
        return out
    q0 = snap()
    data.ctrl[aid] = -0.06
    for _ in range(int(5 / dt)):
        mujoco.mj_step(model, data)
    q1 = snap()
    print("=== %s (ctrl -0.06) ===" % act_name)
    for jn in chain:
        if q0[jn] is None:
            print("  %-36s MISSING JOINT" % jn)
        else:
            print("  %-36s delta=%+.4f  (%.4f -> %.4f)"
                  % (jn, q1[jn] - q0[jn], q0[jn], q1[jn]))
