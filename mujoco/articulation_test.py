"""Open and close an articulated SimReady appliance with the MuJoCo Gen3 + 2F-85.

Composes gen3_2f85/gen3_2f85_fixed.xml (the arm on a 0.75 m pedestal, with the
gravity compensation the Gen3's own controller provides) and an MJCF written by
RammsWorldGen's Tools/simready_mjcf.py, then runs

  approach -> reach -> grasp -> open (the joint swept along a minimum-jerk path,
  the grasp frame moving with the door or drawer) -> close (swept back, still
  holding) -> release -> retreat -> [push: close the rest with the closed gripper]

The arm runs damped-least-squares IK on the 2f85_pinch site, the control law of
ik_test.py and of RammsMjEndEffectorController. Writes <out>.json (the result and
a 50 Hz log, including the pinch targets that Scripts/pie_tests/simready_door
replays in Unreal), <out>.mp4 (needs an offscreen GL: MUJOCO_GL=egl or osmesa
on Linux) and <out>_plot.png.

Grasps (one of):
  --handle GEOM          a bar collider (capsule or cylinder): pinched across its
                         axis, approaching against the appliance front (--front)
  --grasp-local x y z --approach-local x y z --close-local x y z
                         a point and gripper axes in the moving body's frame (e.g.
                         the free edge of a microwave door)

The appliance is placed by --app-pos / --app-yaw (MuJoCo world; the arm's base is
at the origin facing +x), on a counter with --table.

  # ForgeCAD refrigerator, left door: grasp the bar handle, open to 80 degrees, close.
  python mujoco/articulation_test.py --model D:/simready/mjcf/sr_fc_refrigerator/sr_fc_refrigerator.xml \
      --joint door_1 --handle col_handle_002 --grip-z 1.08 --depth -0.01 --yaw-follow 0.5 \
      --open 80 --app-pos 1.168 0.053 0 --out fridge_door

  # ForgeCAD microwave on a 0.85 m counter: door ajar at 25 degrees (as after the release
  # button), pinch its free edge, open to 85, bring it back, let go, push it shut.
  python mujoco/articulation_test.py --model D:/simready/mjcf/sr_fc_microwave_oven/sr_fc_microwave_oven.xml \
      --joint door --start 25 --open 85 --close-to 12 --grasp-local 0.345 -0.004 0.12 \
      --approach-local -1 0 0 --close-local 0 1 0 --yaw-follow 0.8 --push 0.27 -0.02 0.12 0 1 0 \
      --app-pos 1.022 0.068 0 --table 0.3 0.25 0.85 --cam 0.75 0.1 1.0 1.8 25 -28 --out microwave_door

--yaw-follow is the fraction of the door's rotation the hand turns with (a bar
turns in the grip); below 1 it keeps the wrist (joint 6) inside its limits.
AT_TRACE=1 prints the joint, the tracking error, contact and arm joints at limits.
"""
import argparse
import json
import math
import os

import numpy as np
import mujoco as mj

HERE = os.path.dirname(os.path.abspath(__file__))
ARM = 7
ARM_HOME = [0.0, 0.26179939, 3.14159265, -2.26892803, 0.0, 0.95993109, 1.57079633]
DAMP = 0.05
GAIN = 0.6


def compose(robot_xml, app_xml, app_pos, app_yaw, base_z, table=None, prefix="app_"):
    spec = mj.MjSpec.from_file(robot_xml)
    spec.option.timestep = 0.002
    spec.visual.global_.offwidth = 1280
    spec.visual.global_.offheight = 720
    spec.visual.headlight.ambient = [0.35, 0.35, 0.35]
    spec.visual.headlight.diffuse = [0.45, 0.45, 0.45]
    wb = spec.worldbody
    base = spec.body("base_link")
    base.pos = [0, 0, base_z]
    # The Gen3's own controller compensates gravity; Menagerie's PD actuators do not.
    stack = [base]
    while stack:
        b = stack.pop()
        b.gravcomp = 1.0
        stack.extend(b.bodies)
    wb.add_geom(type=mj.mjtGeom.mjGEOM_PLANE, size=[4, 4, 0.1], rgba=[0.82, 0.8, 0.76, 1], name="floor")
    wb.add_geom(type=mj.mjtGeom.mjGEOM_BOX, size=[0.12, 0.12, base_z / 2], pos=[0, 0, base_z / 2],
                rgba=[0.25, 0.27, 0.3, 1], name="pedestal")
    wb.add_light(pos=[0.5, -1.0, 3.0], dir=[0, 0.3, -1], diffuse=[0.7, 0.7, 0.7], castshadow=True)
    wb.add_light(pos=[-1.5, 1.0, 2.5], dir=[0.5, -0.3, -1], diffuse=[0.35, 0.35, 0.35], castshadow=False)
    if table:  # half sizes x y, height: a counter under the appliance
        hx, hy, h = table
        wb.add_geom(type=mj.mjtGeom.mjGEOM_BOX, size=[hx, hy, h / 2], pos=[app_pos[0], app_pos[1], h / 2],
                    rgba=[0.55, 0.45, 0.35, 1], name="counter")
        app_pos = [app_pos[0], app_pos[1], app_pos[2] + h]
    app = mj.MjSpec.from_file(app_xml)
    d = os.path.dirname(os.path.abspath(app_xml))
    for mesh in app.meshes:
        mesh.file = os.path.join(d, mesh.file)
    for tex in app.textures:
        if tex.file:
            tex.file = os.path.join(d, tex.file)
    q = np.zeros(4)
    mj.mju_euler2Quat(q, [0, 0, math.radians(app_yaw)], "xyz")
    frame = wb.add_frame(pos=app_pos, quat=q)
    spec.attach(app, prefix=prefix, frame=frame)
    return spec


def quat_err(target_q, cur_q):
    inv = np.zeros(4); err = np.zeros(4); res = np.zeros(3)
    mj.mju_negQuat(inv, cur_q)
    mj.mju_mulQuat(err, target_q, inv)
    mj.mju_quat2Vel(res, err, 1.0)
    return res


def minjerk(s):
    s = min(max(s, 0.0), 1.0)
    return s ** 3 * (10 - 15 * s + 6 * s * s)


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--robot", default=os.path.join(HERE, "gen3_2f85", "gen3_2f85_fixed.xml"))
    ap.add_argument("--model", required=True)
    ap.add_argument("--joint", required=True, help="appliance joint to drive (unprefixed)")
    ap.add_argument("--handle", help="bar geom to grasp (unprefixed)")
    ap.add_argument("--grasp-local", type=float, nargs=3)
    ap.add_argument("--approach-local", type=float, nargs=3)
    ap.add_argument("--close-local", type=float, nargs=3)
    ap.add_argument("--open", type=float, required=True, help="opening to reach: degrees (hinge) or metres (slide)")
    ap.add_argument("--start", type=float, default=None, help="joint value to start from (e.g. a door left ajar)")
    ap.add_argument("--close-to", type=float, default=None, help="joint value to bring it back to while holding")
    ap.add_argument("--push", type=float, nargs=6, default=None,
                    help="push point and push direction in the moving body's frame: close the rest with a fist")
    ap.add_argument("--app-pos", type=float, nargs=3, default=[1.0, 0.0, 0.0])
    ap.add_argument("--app-yaw", type=float, default=-90.0)
    ap.add_argument("--table", type=float, nargs=3, default=None, help="counter half x, half y, height")
    ap.add_argument("--front", type=float, nargs=3, default=[0, -1, 0], help="appliance front normal, model frame")
    ap.add_argument("--base-z", type=float, default=0.75)
    ap.add_argument("--grip-z", type=float, default=None, help="grasp height on a vertical bar (world z)")
    ap.add_argument("--grip-along", type=float, default=0.0, help="grasp offset along a bar from its centre")
    ap.add_argument("--depth", type=float, default=0.0, help="pinch point past the grasp point along the approach")
    ap.add_argument("--yaw-follow", type=float, default=1.0,
                    help="fraction of a hinge's rotation the hand follows (a bar turns in the grip)")
    ap.add_argument("--move-time", type=float, default=6.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--video", type=int, default=1)
    ap.add_argument("--cam", type=float, nargs=6, default=[0.5, 0.05, 0.95, 2.4, 50, -24],
                    help="lookat xyz, distance, azimuth, elevation")
    a = ap.parse_args()

    spec = compose(a.robot, a.model, a.app_pos, a.app_yaw, a.base_z, a.table)
    m = spec.compile()
    d = mj.MjData(m)
    d.qpos[:ARM] = ARM_HOME
    d.ctrl[:ARM] = ARM_HOME
    jid = m.joint("app_" + a.joint).id
    jq = m.jnt_qposadr[jid]
    hinge = m.jnt_type[jid] == mj.mjtJoint.mjJNT_HINGE
    conv_in = math.radians if hinge else (lambda x: x)
    conv = math.degrees if hinge else (lambda x: x)
    lo, hi = m.jnt_range[jid]
    q_closed = float(m.qpos0[jq])
    if a.start is not None:
        d.qpos[jq] = conv_in(a.start)
    mj.mj_forward(m, d)

    sid = m.site("2f85_pinch").id
    grip = m.actuator("2f85_fingers_actuator").id
    bid = m.jnt_bodyid[jid]
    target_open = float(np.clip(conv_in(a.open), lo, hi))
    q_start = float(d.qpos[jq])
    q_back = conv_in(a.close_to) if a.close_to is not None else q_closed

    Rb = d.xmat[bid].reshape(3, 3).copy()
    pb = d.xpos[bid].copy()
    contact_geoms = set()
    if a.handle:
        gid = m.geom("app_" + a.handle).id
        contact_geoms.add(gid)
        q = np.zeros(4)
        mj.mju_euler2Quat(q, [0, 0, math.radians(a.app_yaw)], "xyz")
        R_app = np.zeros(9); mj.mju_quat2Mat(R_app, q); R_app = R_app.reshape(3, 3)
        approach = unit(-(R_app @ np.array(a.front, float)))
        bar = d.geom_xmat[gid].reshape(3, 3)[:, 2].copy()
        centre = d.geom_xpos[gid].copy()
        if a.grip_z is not None and abs(bar[2]) > 0.7:
            centre = centre + bar * ((a.grip_z - centre[2]) / bar[2])
        centre = centre + bar * a.grip_along
        y_ax = unit(np.cross(bar, approach))
    else:
        centre = pb + Rb @ np.array(a.grasp_local)
        approach = unit(Rb @ np.array(a.approach_local))
        y_ax = unit(Rb @ np.array(a.close_local))
        y_ax = unit(y_ax - approach * np.dot(y_ax, approach))
        contact_geoms = {g for g in range(m.ngeom) if m.geom_bodyid[g] == bid}
    x_ax = np.cross(y_ax, approach)
    R_grasp = np.column_stack([x_ax, y_ax, approach])
    p_loc = Rb.T @ (centre - pb)
    R_loc = Rb.T @ R_grasp
    anchor = d.xanchor[jid].copy()
    axis = d.xaxis[jid].copy()

    def rot(ang):
        qq = np.zeros(4); mj.mju_axisAngle2Quat(qq, axis, ang)
        R = np.zeros(9); mj.mju_quat2Mat(R, qq); return R.reshape(3, 3)

    def body_target(val, p_l, R_l, follow, depth):
        """Pose of a frame fixed to the moving body (p_l, R_l in the start pose) with the joint at val."""
        dv = val - q_start
        if hinge:
            p = anchor + rot(dv) @ (pb + Rb @ p_l - anchor)
            Rg = rot(follow * dv) @ Rb @ R_l
        else:
            p = pb + Rb @ p_l + axis * dv
            Rg = Rb @ R_l
        p = p + Rg[:, 2] * depth
        qg = np.zeros(4); mj.mju_mat2Quat(qg, Rg.ravel())
        return p, qg

    def grasp_target(val):
        return body_target(val, p_loc, R_loc, a.yaw_follow, a.depth)

    jacp = np.zeros((3, m.nv)); jacr = np.zeros((3, m.nv))
    log = {"t": [], "q": [], "q_des": [], "ee_err": [], "grip": [], "phase": [], "contact": [], "ctrl": [],
           "target": []}
    frames = []
    renderer = None
    if a.video:
        renderer = mj.Renderer(m, 540, 960)
        cam = mj.MjvCamera()
        cam.lookat[:] = a.cam[:3]; cam.distance = a.cam[3]; cam.azimuth = a.cam[4]; cam.elevation = a.cam[5]
        vopt = mj.MjvOption()
    fps_every = int(round(1 / 30 / m.opt.timestep))
    pad_bodies = {m.body("2f85_right_pad").id, m.body("2f85_left_pad").id}
    state = {"step": 0}

    def in_contact():
        for c in d.contact[:d.ncon]:
            b1, b2 = m.geom_bodyid[c.geom1], m.geom_bodyid[c.geom2]
            if (c.geom1 in contact_geoms and b2 in pad_bodies) or (c.geom2 in contact_geoms and b1 in pad_bodies):
                return True
        return False

    def step_to(p_t, q_t, grip_ctrl, phase, q_des):
        mj.mj_jacSite(m, d, jacp, jacr, sid)
        J = np.vstack([jacp[:, :ARM], jacr[:, :ARM]])
        cur = np.zeros(4); mj.mju_mat2Quat(cur, d.site_xmat[sid])
        err = np.concatenate([p_t - d.site_xpos[sid], quat_err(q_t, cur)])
        dq = J.T @ np.linalg.solve(J @ J.T + DAMP ** 2 * np.eye(6), err)
        dq = np.clip(dq, -0.05, 0.05)
        d.ctrl[:ARM] = d.qpos[:ARM] + GAIN * dq
        d.ctrl[grip] = grip_ctrl
        mj.mj_step(m, d)
        state["step"] += 1
        if state["step"] % 10 == 0:
            log["t"].append(round(d.time, 3)); log["q"].append(float(d.qpos[jq])); log["q_des"].append(float(q_des))
            log["ee_err"].append(float(np.linalg.norm(err[:3]))); log["grip"].append(float(d.ctrl[grip]))
            log["phase"].append(phase); log["contact"].append(in_contact())
            log["ctrl"].append([round(float(x), 6) for x in d.ctrl[:ARM]] + [float(d.ctrl[grip])])
            log["target"].append([round(float(x), 6) for x in list(p_t) + list(q_t)])
        if os.environ.get("AT_TRACE") and state["step"] % 250 == 0:
            lim = [i + 1 for i in range(ARM) if m.jnt_limited[i]
                   and min(abs(d.qpos[i] - m.jnt_range[i][0]), abs(d.qpos[i] - m.jnt_range[i][1])) < 0.05]
            print("%5.2fs %-8s q=%7.3f qd=%7.3f err=%.3f contact=%d limits=%s" % (
                d.time, phase, conv(d.qpos[jq]), conv(q_des), np.linalg.norm(err[:3]), in_contact(), lim))
        if renderer is not None and state["step"] % fps_every == 0:
            renderer.update_scene(d, cam, vopt)
            frames.append(renderer.render())

    def hold(p, qt, g, secs, phase, q_des):
        for _ in range(int(secs / m.opt.timestep)):
            step_to(p, qt, g, phase, q_des)

    def move(p0, p1, qt, g, secs, phase, q_des, q_from=None):
        """Straight-line move; with q_from, the orientation is slerped from it to qt."""
        n = int(secs / m.opt.timestep)
        for i in range(n):
            s = minjerk((i + 1) / n)
            q_s = qt
            if q_from is not None:
                q_s = slerp(q_from, qt, s)
            step_to(p0 + (p1 - p0) * s, q_s, g, phase, q_des)

    def sweep(target, v0, v1, secs, g, phase):
        n = int(secs / m.opt.timestep)
        for i in range(n):
            v = v0 + (v1 - v0) * minjerk((i + 1) / n)
            p, qt = target(v)
            step_to(p, qt, g, phase, v)
        p, qt = target(v1)
        hold(p, qt, g, 0.5, phase, v1)
        return float(d.qpos[jq])

    # Approach, reach, grasp.
    p_g, q_g = grasp_target(q_start)
    pre = p_g - unit(R_grasp[:, 2]) * 0.15
    q_home = np.zeros(4); mj.mju_mat2Quat(q_home, d.site_xmat[sid].copy())
    move(d.site_xpos[sid].copy(), pre, q_g, 0, 2.5, "approach", q_start, q_from=q_home)
    hold(pre, q_g, 0, 0.5, "approach", q_start)
    move(pre, p_g, q_g, 0, 1.5, "reach", q_start)
    hold(p_g, q_g, 0, 0.3, "reach", q_start)
    reach_err = float(np.linalg.norm(d.site_xpos[sid] - p_g))
    hold(p_g, q_g, 255, 1.0, "grasp", q_start)
    grasped = in_contact()

    opened = sweep(grasp_target, q_start, target_open, a.move_time, 255, "open")
    held_open = in_contact()
    back = sweep(grasp_target, target_open, q_back, a.move_time, 255, "close")
    p_c, q_c = grasp_target(q_back)
    hold(p_c, q_c, 0, 0.8, "release", q_back)
    away = p_c - unit(np.array(q_to_mat(q_c))[:, 2]) * 0.12
    move(p_c, away, q_c, 0, 1.2, "retreat", q_back)
    hold(away, q_c, 0, 0.3, "retreat", q_back)

    if a.push:
        # Close the rest with a fist: a frame on the face, pushing along push_dir.
        cur_v = float(d.qpos[jq])
        Rb_now = d.xmat[bid].reshape(3, 3).copy(); pb_now = d.xpos[bid].copy()
        pp_world = pb_now + Rb_now @ np.array(a.push[:3])
        pd_world = unit(Rb_now @ np.array(a.push[3:]))
        # Fist frame: approach along the push, fingers closing horizontally, x down (as at home).
        ref = unit(np.cross([0, 0, 1], pd_world)) if abs(pd_world[2]) < 0.9 else np.array([0, 1.0, 0])
        Rp = np.column_stack([np.cross(ref, pd_world), ref, pd_world])
        # Express in the start-pose body frame for body_target.
        dv = cur_v - q_start
        R0 = rot(-dv) if hinge else np.eye(3)
        pp0 = anchor + R0 @ (pp_world - anchor) if hinge else pp_world - axis * dv
        p_pl = Rb.T @ (pp0 - pb)
        R_pl = Rb.T @ (R0 @ Rp)

        def push_target(val):
            return body_target(val, p_pl, R_pl, 1.0, 0.0)

        p0, qp = push_target(cur_v)
        q_now = np.zeros(4); mj.mju_mat2Quat(q_now, d.site_xmat[sid].copy())
        move(d.site_xpos[sid].copy(), p0 - Rp[:, 2] * 0.06, qp, 255, 2.0, "push", cur_v, q_from=q_now)
        move(p0 - Rp[:, 2] * 0.06, p0, qp, 255, 0.8, "push", cur_v)
        sweep(push_target, cur_v, q_closed - (0.02 if hinge else 0.005) * np.sign(target_open - q_closed),
              2.5, 255, "push")
        p_e, q_e = push_target(q_closed)
        move(p_e, p_e - Rp[:, 2] * 0.12, q_e, 255, 1.0, "retreat", q_closed)
        hold(p_e - Rp[:, 2] * 0.12, q_e, 255, 0.5, "retreat", q_closed)
    final = float(d.qpos[jq])

    track = [abs(x - y) for x, y, ph in zip(log["q"], log["q_des"], log["phase"]) if ph == "open"]
    span = target_open - q_closed
    res = {
        "model": os.path.basename(a.model), "joint": a.joint, "grasp": a.handle or "local frame",
        "type": "hinge" if hinge else "slide", "unit": "deg" if hinge else "m",
        "start": conv(q_start), "target_open": conv(target_open), "reached_open": conv(opened),
        "brought_back_to": conv(back), "final": conv(final), "reach_error_m": round(reach_err, 4),
        "grasped": grasped, "held_at_open": held_open,
        "max_open_tracking_error": conv(max(track)) if track else None,
        "open_fraction": (opened - q_closed) / span if span else None,
        "closed_fraction": 1 - (final - q_closed) / span if span else None,
        "sim_seconds": round(d.time, 2),
        "scene": {"base_z": a.base_z, "app_pos": a.app_pos, "app_yaw": a.app_yaw, "table": a.table,
                  "start": a.start, "gravcomp": True, "timestep": m.opt.timestep, "log_dt": 10 * m.opt.timestep},
    }
    res["verdict"] = "PASS" if (res["open_fraction"] or 0) > 0.9 and (res["closed_fraction"] or 0) > 0.97 else "FAIL"
    print(json.dumps(res, indent=1))
    with open(a.out + ".json", "w") as f:
        json.dump({"result": res, "log": log}, f)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 3.2))
        t = np.array(log["t"])
        ax.plot(t, [conv(x) for x in log["q_des"]], "--", color="#8a8f98", lw=1.2, label="commanded")
        ax.plot(t, [conv(x) for x in log["q"]], color="#1f6feb", lw=1.8, label="%s (simulated)" % a.joint)
        c = np.array(log["contact"])
        ax.fill_between(t, 0, 1, where=c, transform=ax.get_xaxis_transform(), color="#1f6feb", alpha=0.07,
                        lw=0, label="gripper in contact")
        ax.set_xlabel("time (s)"); ax.set_ylabel("deg" if hinge else "m")
        ax.legend(loc="upper left", frameon=False, fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_title("%s / %s: %s" % (res["model"], a.joint, res["verdict"]), fontsize=10)
        fig.tight_layout(); fig.savefig(a.out + "_plot.png", dpi=110)
    except ImportError:
        pass
    if frames:
        import imageio
        imageio.mimwrite(a.out + ".mp4", frames, fps=30, quality=7, macro_block_size=4)
        print("video", a.out + ".mp4", len(frames), "frames")


def slerp(q0, q1, s):
    q0 = np.asarray(q0, float); q1 = np.asarray(q1, float)
    if np.dot(q0, q1) < 0:
        q1 = -q1
    dot = min(1.0, float(np.dot(q0, q1)))
    if dot > 0.9995:
        q = q0 + s * (q1 - q0)
    else:
        th = math.acos(dot)
        q = (math.sin((1 - s) * th) * q0 + math.sin(s * th) * q1) / math.sin(th)
    return q / np.linalg.norm(q)


def q_to_mat(q):
    R = np.zeros(9); mj.mju_quat2Mat(R, q); return R.reshape(3, 3)


if __name__ == "__main__":
    main()
