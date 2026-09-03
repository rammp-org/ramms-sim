"""Full strict suite: per-motor articulation (correct downstream mapping,
BOTH directions, pass if either articulates — one direction is loaded),
rear swing-arm criterion (the wheel-carrier must rotate, strut stroke
bounded), rest jitter, drop test, lateral-whack impact stability
(guards the kp=6e5 rod servos against the historic pogo-stick ring)."""
import numpy as np
import mujoco
import os

os.chdir(os.path.join(os.path.dirname(__file__), "..", "..", "mujoco", "mebot"))
model = mujoco.MjModel.from_xml_path("mebot_gen3_scene.xml")

def jid(n): return mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, n)
def q(d, n): return float(d.qpos[model.jnt_qposadr[jid(n)]])

def settle(seconds=3.0):
    d = mujoco.MjData(model)
    for _ in range(int(seconds / model.opt.timestep)):
        mujoco.mj_step(model, d)
    return d

fails = 0

# --- per-motor articulation ---
TESTS = [
    ("front_caster_motor_rod", "front_caster_swing_arm", 0.15, None),
    ("rear_caster_motor_rod", "rear_caster_suspension_arm", 0.15, "rear_caster_swing_arm"),
    ("motor_elevator_rod_l", "motor_swing_arm_l", 0.15, None),
    ("motor_elevator_rod_r", "motor_swing_arm_r", 0.15, None),
]
bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "mebot")
for act, joint, need, extra in TESTS:
    best = None
    for ctrl in (-0.06, +0.06):
        d = settle()
        aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, act)
        q0, e0 = q(d, joint), (q(d, extra) if extra else 0.0)
        p0 = d.xpos[bid].copy()
        d.ctrl[aid] = ctrl
        for _ in range(int(4 / model.opt.timestep)):
            mujoco.mj_step(model, d)
        art = abs(q(d, joint) - q0)
        ext = abs(q(d, extra) - e0) if extra else 0.0
        slide = float(np.linalg.norm((d.xpos[bid] - p0)[:2])) * 100
        ring = float(np.sqrt(np.mean(d.qvel[6:] ** 2)))
        ok = art >= need and slide <= 10 and ring <= 0.15 and (extra is None or ext >= 0.10)
        row = (ok, ctrl, art, ext, slide, ring)
        if best is None or (row[0] and not best[0]) or (row[0] == best[0] and row[2] > best[2]):
            best = row
    ok, ctrl, art, ext, slide, ring = best
    fails += 0 if ok else 1
    msg = "" if extra is None else " swing=%.3f(need 0.10)" % ext
    print("%-4s %-24s best ctrl=%+0.2f art=%.3f (need %.2f)%s slide=%.1fcm ring=%.3f"
          % ("PASS" if ok else "FAIL", act, ctrl, art, need, msg, slide, ring))

# --- rest jitter ---
d = settle(6.0)
ring = float(np.sqrt(np.mean(d.qvel[6:] ** 2)))
ok = ring <= 0.02
fails += 0 if ok else 1
print("%-4s rest jitter qvel RMS=%.4f (need <=0.02)" % ("PASS" if ok else "FAIL", ring))

# --- drop test: spawn 10 cm higher, must settle upright without ringing ---
d = mujoco.MjData(model)
d.qpos[2] += 0.10
for _ in range(int(5 / model.opt.timestep)):
    mujoco.mj_step(model, d)
ring = float(np.sqrt(np.mean(d.qvel[6:] ** 2)))
upz = float(1 - 2 * (d.qpos[4] ** 2 + d.qpos[5] ** 2))  # z of body up-axis from quat
ok = ring <= 0.05 and upz >= 0.95
fails += 0 if ok else 1
print("%-4s drop 10cm: ring=%.4f (need <=0.05) upz=%.2f" % ("PASS" if ok else "FAIL", ring, upz))

# --- whack test: 1.5 m/s lateral velocity kick at rest ---
d = settle()
d.qvel[0:2] = [1.0, 1.1]
for _ in range(int(5 / model.opt.timestep)):
    mujoco.mj_step(model, d)
ring = float(np.sqrt(np.mean(d.qvel[6:] ** 2)))
upz = float(1 - 2 * (d.qpos[4] ** 2 + d.qpos[5] ** 2))
ok = ring <= 0.05 and upz >= 0.95
fails += 0 if ok else 1
print("%-4s whack 1.5m/s: ring=%.4f (need <=0.05) upz=%.2f" % ("PASS" if ok else "FAIL", ring, upz))

print("SUITE", "PASS" if fails == 0 else "FAIL(%d)" % fails)
