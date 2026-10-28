"""Compile an MJCF with MuJoCo and write what a Chaos build needs, in Unreal's frame (cm, Y flipped):
bodies (pose at qpos0, mass, inertia, convex hull of collision geoms in the body frame), joints (anchor, axis,
range, damping, armature), position-servo actuators, connect equalities."""
import json, sys
import numpy as np, mujoco
from scipy.spatial import ConvexHull

S = np.array([1.0, -1.0, 1.0])
def ue_pos(p): return (np.asarray(p) * S * 100.0).tolist()
def ue_quat(q): w, x, y, z = q; return [w, -x, y, -z]
def ue_axis(a): return (-np.asarray(a) * S).tolist()   # pseudovector: keeps the joint coordinate's sign

def geom_points(m, g):
    t = int(m.geom_type[g]); s = m.geom_size[g]   # int(): numpy ints don't match the enum in a tuple test
    if t == mujoco.mjtGeom.mjGEOM_MESH:
        mid = m.geom_dataid[g]; a, n = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
        return m.mesh_vert[a:a + n].astype(float)
    if t == mujoco.mjtGeom.mjGEOM_BOX:
        return np.array([[sx, sy, sz] for sx in (-s[0], s[0]) for sy in (-s[1], s[1]) for sz in (-s[2], s[2])])
    if t == mujoco.mjtGeom.mjGEOM_SPHERE:
        u = np.random.RandomState(0).normal(size=(64, 3)); return s[0] * u / np.linalg.norm(u, axis=1, keepdims=True)
    if t in (int(mujoco.mjtGeom.mjGEOM_CAPSULE), int(mujoco.mjtGeom.mjGEOM_CYLINDER)):
        ang = np.linspace(0, 2 * np.pi, 24, endpoint=False); ring = np.c_[s[0] * np.cos(ang), s[0] * np.sin(ang)]
        pts = [np.c_[ring, np.full(24, z)] for z in (-s[1], s[1])]
        if t == mujoco.mjtGeom.mjGEOM_CAPSULE: pts += [np.array([[0, 0, -s[1] - s[0]], [0, 0, s[1] + s[0]]])]
        return np.vstack(pts)
    return None

def main(path, out):
    m = mujoco.MjModel.from_xml_path(path); d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    bodies = []
    for b in range(1, m.nbody):
        name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b)
        R = d.xmat[b].reshape(3, 3); p = d.xpos[b]
        pts = []
        for g in range(m.ngeom):
            if m.geom_bodyid[g] != b or not (m.geom_contype[g] or m.geom_conaffinity[g]): continue
            gp = geom_points(m, g)
            if gp is None: continue
            gw = gp @ d.geom_xmat[g].reshape(3, 3).T + d.geom_xpos[g]          # world, MuJoCo frame
            pts.append((gw - p) @ R)                                           # body frame
        hull = None
        moving = any(m.jnt_bodyid[j] == b for j in range(m.njnt))
        if not pts and moving:   # a moving body with no collision geom still needs a Chaos body: a 1 cm cube at its centre of mass
            pts = [(np.array([[x, y, z] for x in (-.005, .005) for y in (-.005, .005) for z in (-.005, .005)]) + m.body_ipos[b])]
        if pts:
            P = np.vstack(pts) * S * 100.0                                     # body frame, UE cm
            h = ConvexHull(P)
            idx = sorted(set(h.simplices.ravel())); remap = {v: i for i, v in enumerate(idx)}
            faces = []
            for f, eq in zip(h.simplices, h.equations):                       # wind outward
                a, bb, c = P[f]
                if np.dot(np.cross(bb - a, c - a), eq[:3]) < 0: f = f[::-1]
                faces.append([remap[i] for i in f])
            hull = {"verts": np.round(P[idx], 4).tolist(), "faces": faces}
        bodies.append({"name": name, "parent": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.body_parentid[b]),
                       "pos": ue_pos(p), "quat": ue_quat(d.xquat[b]), "mass": float(m.body_mass[b]),
                       "inertia": m.body_inertia[b].tolist(), "hull": hull,
                       "free": any(m.jnt_type[j] == 0 for j in range(m.njnt) if m.jnt_bodyid[j] == b)})
    joints = []
    for j in range(m.njnt):
        if m.jnt_type[j] == 0: continue
        b = m.jnt_bodyid[j]; dof = m.jnt_dofadr[j]
        joints.append({"name": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j), "type": ["free", "ball", "slide", "hinge"][m.jnt_type[j]],
                       "child": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b), "parent": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, m.body_parentid[b]),
                       "anchor": ue_pos(d.xanchor[j]), "axis": (ue_axis(d.xaxis[j]) if m.jnt_type[j] == 3 else (np.asarray(d.xaxis[j]) * S).tolist()),   # a slide's axis is a true vector
                       "range": m.jnt_range[j].tolist() if m.jnt_limited[j] else None,
                       "stiffness": float(m.jnt_stiffness[j]), "springref": float(m.qpos_spring[m.jnt_qposadr[j]]),
                       "damping": float(m.dof_damping[dof]), "armature": float(m.dof_armature[dof]), "frictionloss": float(m.dof_frictionloss[dof])})
    acts = []
    for a in range(m.nu):
        g, bp = m.actuator_gainprm[a], m.actuator_biasprm[a]
        e = {"name": mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, a), "gain": float(g[0]), "kp": float(-bp[1]), "kv": float(-bp[2]),
             "forcerange": m.actuator_forcerange[a].tolist() if m.actuator_forcelimited[a] else None, "ctrlrange": m.actuator_ctrlrange[a].tolist()}
        if m.actuator_trntype[a] == mujoco.mjtTrn.mjTRN_JOINT:
            e["joints"] = [[mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, m.actuator_trnid[a][0]), float(m.actuator_gear[a][0])]]
        elif m.actuator_trntype[a] == mujoco.mjtTrn.mjTRN_TENDON:
            t = m.actuator_trnid[a][0]; e["tendon"] = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_TENDON, t)
            e["joints"] = [[mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, m.wrap_objid[w]), float(m.wrap_prm[w])] for w in range(m.tendon_adr[t], m.tendon_adr[t] + m.tendon_num[t])]
        e["kind"] = "servo" if e["kp"] > 0 else "motor"
        acts.append(e)
    eqs = []
    for e in range(m.neq):
        b1, b2 = m.eq_obj1id[e], m.eq_obj2id[e]
        if m.eq_type[e] == mujoco.mjtEq.mjEQ_CONNECT:
            anchor_w = d.xmat[b1].reshape(3, 3) @ m.eq_data[e][:3] + d.xpos[b1]
            eqs.append({"type": "connect", "body1": mujoco.mj_id2name(m, 1, b1), "body2": mujoco.mj_id2name(m, 1, b2), "anchor": ue_pos(anchor_w)})
        elif m.eq_type[e] == mujoco.mjtEq.mjEQ_JOINT:
            eqs.append({"type": "joint", "joint1": mujoco.mj_id2name(m, 3, b1), "joint2": mujoco.mj_id2name(m, 3, b2)})
        elif m.eq_type[e] == mujoco.mjtEq.mjEQ_WELD:
            eqs.append({"type": "weld", "body1": mujoco.mj_id2name(m, 1, b1), "body2": mujoco.mj_id2name(m, 1, b2)})
    excl = [[mujoco.mj_id2name(m, 1, m.exclude_signature[k] >> 16), mujoco.mj_id2name(m, 1, m.exclude_signature[k] & 0xFFFF)] for k in range(m.nexclude)]
    keys = {mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_KEY, k): m.key_ctrl[k].tolist() for k in range(m.nkey)}
    json.dump({"source": path, "keys": keys, "timestep": m.opt.timestep, "bodies": bodies, "joints": joints, "actuators": acts, "equality": eqs, "exclude": excl}, open(out, "w"), indent=1)
    print("bodies", len(bodies), "joints", len(joints), "acts", len(acts), "eq", len(eqs), "hull verts", sum(len(b["hull"]["verts"]) for b in bodies if b["hull"]))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
