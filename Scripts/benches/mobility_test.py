"""Kinematic mobility: no gravity, springs stripped, direct torque on the
suspension arm — a mobile loop swings freely; mobility<=0 stays rigid."""
import re
import numpy as np
import mujoco
import os

xml = open(r"C:\Users\waemf\data\Ramms\mujoco\mebot\mebot_gen3_scene.xml",
           encoding="utf-8").read()
xml = re.sub(r'stiffness="[0-9.]+"', 'stiffness="0"', xml)
xml = re.sub(r'damping="[0-9.]+"', 'damping="0.5"', xml)
xml = re.sub(r'frictionloss="[0-9.]+"', 'frictionloss="0"', xml)
xml = xml.replace('<option ', '<option gravity="0 0 0" ')
os.chdir(r"C:\Users\waemf\data\Ramms\mujoco\mebot")
model = mujoco.MjModel.from_xml_string(xml)
data = mujoco.MjData(model)
dt = model.opt.timestep
for side, joint in (("rear", "rear_caster_suspension_arm"),
                    ("front", "front_caster_swing_arm")):
    mujoco.mj_resetData(model, data)
    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
    dadr = model.jnt_dofadr[jid]
    q0 = float(data.qpos[model.jnt_qposadr[jid]])
    for _ in range(int(2 / dt)):
        data.qfrc_applied[:] = 0
        data.qfrc_applied[dadr] = 30.0   # 30 N*m directly on the arm
        mujoco.mj_step(model, data)
    q1 = float(data.qpos[model.jnt_qposadr[jid]])
    print("%s %s: delta=%.3f rad under 30 N*m  %s"
          % (side, joint, q1 - q0,
             "MOBILE" if abs(q1 - q0) > 0.1 else "RIGID/JAMMED"))
