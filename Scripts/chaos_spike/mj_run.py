"""MuJoCo reference: run a traj.py schedule on an MJCF and record every joint, the free body's pose (Unreal
frame, cm) and the connect-loop gaps.   python mj_run.py model.xml chaos.json <schedule> out.json [box]"""
import sys, os, json, math, numpy as np, mujoco
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import traj
xml, jpath, name, out = sys.argv[1:5]
J = json.load(open(jpath)); sched = traj.SCHEDULES[name]
spec = mujoco.MjSpec.from_file(xml)
if len(sys.argv) > 5 and sys.argv[5] == "box":
    B = traj.BOX; b = spec.worldbody.add_body(name="box", pos=[B["pos_ue"][0] / 100, -B["pos_ue"][1] / 100, B["pos_ue"][2] / 100])
    b.add_freejoint(); b.add_geom(type=mujoco.mjtGeom.mjGEOM_BOX, size=[h / 100 for h in B["half_cm"]], mass=B["mass"])
m = spec.compile(); d = mujoco.MjData(m)
aid = {mujoco.mj_id2name(m, 19, a): a for a in range(m.nu)}
free = [j for j in range(m.njnt) if m.jnt_type[j] == 0 and mujoco.mj_id2name(m, 1, m.jnt_bodyid[j]) != "box"]
rec = []; nxt = 0.0
while d.time < sched.end:
    c = sched(d.time, J); d.qfrc_applied[:] = 0
    for k, v in c.items():
        if k in aid: d.ctrl[aid[k]] = v
    for jn, f in c.get("__qfrc__", {}).items():
        d.qfrc_applied[m.jnt_dofadr[mujoco.mj_name2id(m, 3, jn)]] = f
    mujoco.mj_step(m, d)
    if d.time >= nxt:
        r = {"t": d.time, "q": {mujoco.mj_id2name(m, 3, j): float(d.qpos[m.jnt_qposadr[j]]) for j in range(m.njnt) if m.jnt_type[j] in (2, 3)}}
        if free:
            a = m.jnt_qposadr[free[0]]; p = d.qpos[a:a + 3]; w, x, y, z = d.qpos[a + 3:a + 7]
            r["base"] = [p[0] * 100, -p[1] * 100, p[2] * 100]
            r["rpy"] = [math.degrees(math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))), math.degrees(math.asin(max(-1, min(1, 2 * (w * y - z * x))))), math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))]
        rec.append(r); nxt += 1.0 / 30
json.dump(rec, open(out, "w"))
print("frames", len(rec), "last base", [round(v, 2) for v in rec[-1].get("base", [])], "rpy", [round(v, 2) for v in rec[-1].get("rpy", [])])
