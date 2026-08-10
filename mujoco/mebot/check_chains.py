"""Transmission check for the mebot linkages: drives each rod servo and
prints which chain joints moved (>0.01). Run after every closure edit:

    Plugins/RammsNewtonPhysics/Scripts/.venv/Scripts/python.exe mujoco/mebot/check_chains.py

See doc/rammp_robot_pipeline.md "HOW-TO: author loop closures manually".
"""
import os

import mujoco

os.chdir(os.path.dirname(os.path.abspath(__file__)))
m = mujoco.MjModel.from_xml_path("mebot_scene.xml")
d = mujoco.MjData(m)
act = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i): i for i in range(m.nu)}
j = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, i): i for i in range(m.njnt)}
jp = lambda n: float(d.qpos[m.jnt_qposadr[j[n]]])

for _ in range(3000):
    mujoco.mj_step(m, d)

watch = [n for n in j if n and ("caster" in n or "elevator" in n or "swing" in n)]
base = {n: jp(n) for n in watch}
for rod in ("front_caster_motor_rod", "rear_caster_motor_rod",
            "motor_elevator_rod_l", "motor_elevator_rod_r"):
    for _ in range(1500):
        d.ctrl[:] = 0
        d.ctrl[act[rod]] = 0.08
        mujoco.mj_step(m, d)
    print("==", rod)
    for n in sorted(watch):
        delta = jp(n) - base[n]
        if abs(delta) > 0.01:
            print("   %-34s %+.3f" % (n, delta))
    base = {n: jp(n) for n in watch}
