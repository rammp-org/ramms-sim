import sys, json, numpy as np, mujoco
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from traj import ARM, targets_grasp, GRASP_END, BOX
spec = mujoco.MjSpec.from_file(sys.argv[1])
b = spec.worldbody.add_body(name="box", pos=[BOX["pos_ue"][0] / 100, -BOX["pos_ue"][1] / 100, BOX["pos_ue"][2] / 100])
b.add_freejoint()
b.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[h / 100 for h in BOX["half_cm"]], mass=BOX["mass"])
m = spec.compile(); d = mujoco.MjData(m)
aid = {mujoco.mj_id2name(m, 19, a): a for a in range(m.nu)}
bb = mujoco.mj_name2id(m, 1, "box"); br = mujoco.mj_name2id(m, 1, "bracelet_link")
mujoco.mj_forward(m, d)
rel0 = None; out = []; nxt = 0.0
while d.time < GRASP_END:
    q, g = targets_grasp(d.time)
    for j in ARM: d.ctrl[aid[j]] = q[j]
    d.ctrl[aid["2f85_fingers_actuator"]] = g
    mujoco.mj_step(m, d)
    if d.time >= nxt:
        rel = d.xmat[br].reshape(3, 3).T @ (d.xpos[bb] - d.xpos[br])
        if rel0 is None and d.time >= 2.9: rel0 = rel.copy()
        out.append({"t": d.time, "box_z_cm": d.xpos[bb][2] * 100, "slip_cm": float(np.linalg.norm(rel - rel0) * 100) if rel0 is not None else 0.0})
        nxt += 0.05
json.dump(out, open(sys.argv[2], "w"))
for tt in (2.9, 5.0, 6.5, 7.95):
    r = min(out, key=lambda r: abs(r["t"] - tt)); print("t=%.2f box_z=%.2f slip=%.3f cm" % (r["t"], r["box_z_cm"], r["slip_cm"]))
