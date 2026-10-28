import sys, json, numpy as np, mujoco
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from traj import ARM, targets, T_END
m = mujoco.MjModel.from_xml_path(sys.argv[1]); d = mujoco.MjData(m)
aid = {mujoco.mj_id2name(m, 19, a): a for a in range(m.nu)}
jq = lambda n: d.qpos[m.jnt_qposadr[mujoco.mj_name2id(m, 3, n)]]
out = []; nxt = 0.0
eq = [e for e in range(m.neq) if m.eq_type[e] == mujoco.mjtEq.mjEQ_CONNECT]
while d.time < T_END:
    q, g = targets(d.time)
    for j in ARM: d.ctrl[aid[j]] = q[j]
    d.ctrl[aid["2f85_fingers_actuator"]] = g
    mujoco.mj_step(m, d)
    if d.time >= nxt:
        gap = []
        for e in eq:
            b1, b2 = m.eq_obj1id[e], m.eq_obj2id[e]
            p1 = d.xmat[b1].reshape(3, 3) @ m.eq_data[e][:3] + d.xpos[b1]; p2 = d.xmat[b2].reshape(3, 3) @ m.eq_data[e][3:6] + d.xpos[b2]
            gap.append(float(np.linalg.norm(p1 - p2) * 100))
        out.append({"t": round(d.time, 4), "q": {j: float(jq(j)) for j in ARM + ["2f85_right_driver_joint", "2f85_left_driver_joint", "2f85_right_follower_joint"]},
                    "target": q, "grip": g, "loop_gap_cm": max(gap)})
        nxt += 1.0 / 30
json.dump(out, open(sys.argv[2], "w"))
last = out[-1]; mid = [o for o in out if abs(o["t"] - 6.0) < 0.02][0]
print("t=6.0", {k: round(v, 4) for k, v in mid["q"].items()}, "gap", mid["loop_gap_cm"])
