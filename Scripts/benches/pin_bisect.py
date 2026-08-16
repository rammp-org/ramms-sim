"""Disable one closure at a time; find which one jams each caster chain."""
import re
import numpy as np
import mujoco
import os

BASE = open(r"C:\Users\waemf\data\Ramms\mujoco\mebot\mebot_gen3_scene.xml",
            encoding="utf-8").read()
os.chdir(r"C:\Users\waemf\data\Ramms\mujoco\mebot")

def articulation(xml, act, joint):
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    dt = model.opt.timestep
    for _ in range(int(3 / dt)):
        mujoco.mj_step(model, data)
    aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, act)
    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
    rid = model.actuator_trnid[aid][0]
    q0 = float(data.qpos[model.jnt_qposadr[jid]])
    data.ctrl[aid] = -0.06
    for _ in range(int(4 / dt)):
        mujoco.mj_step(model, data)
    q1 = float(data.qpos[model.jnt_qposadr[jid]])
    rod = float(data.qpos[model.jnt_qposadr[rid]])
    return abs(q1 - q0), rod

cons = re.findall(r'<connect[^>]*/>', BASE)
for act, joint, side in (("rear_caster_motor_rod", "rear_caster_swing_arm", "rear"),
                         ("front_caster_motor_rod", "front_caster_swing_arm", "front")):
    art0, rod0 = articulation(BASE, act, joint)
    print("%s BASELINE art=%.3f rodq=%.4f" % (side, art0, rod0))
    for c in cons:
        if side not in c:
            continue
        label = re.search(r'body1="([^"]+)" body2="([^"]+)"', c)
        name = "%s__%s" % (label.group(1), label.group(2)) if label else c[:50]
        art, rod = articulation(BASE.replace(c, ""), act, joint)
        print("  minus %-58s art=%.3f rodq=%.4f %s"
              % (name[:58], art, rod, "<<< FREES IT" if art > art0 * 3 + 0.05 else ""))
