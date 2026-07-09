"""
Headless validation of end-effector IK control for the combined Gen3 + 2F-85.

Damped-least-squares IK on the gripper 'pinch' site: holds the home orientation,
moves the EE target to the cube, grasps, and lifts. This is the same control law a
URLab MjArticulationController would run on the physics thread, so if it grasps+lifts
here, EE teleop will work in-engine.

Run:  .mjtools/Scripts/python.exe mujoco/ik_test.py
"""
import numpy as np
import mujoco as mj

SCENE = r"C:/Users/waemf/data/Ramms/mujoco/gen3_2f85/gen3_2f85_scene.xml"
ARM_DOFS = 7          # joint_1..7 are the first 7 dofs
DAMP = 0.08           # DLS damping
STEP_GAIN = 0.6       # fraction of IK delta applied per control update


def name2id(m, typ, name):
    return mj.mj_name2id(m, typ, name)


def ee_site_id(m):
    for cand in ("2f85_pinch", "pinch", "pinch_site"):
        i = name2id(m, mj.mjtObj.mjOBJ_SITE, cand)
        if i >= 0:
            return i, cand
    raise SystemExit("no pinch site found")


def quat_err(target_q, cur_q):
    """3-vector orientation error (cur -> target) in world frame."""
    neg = np.zeros(4); err = np.zeros(4); cur_inv = np.zeros(4)
    mj.mju_negQuat(cur_inv, cur_q)
    mj.mju_mulQuat(err, target_q, cur_inv)
    res = np.zeros(3)
    mj.mju_quat2Vel(res, err, 1.0)
    return res


def main():
    m = mj.MjModel.from_xml_path(SCENE)
    d = mj.MjData(m)
    # Set the arm to its home pose directly (the keyframe would zero the object freejoint here).
    arm_home = [0.0, 0.26179939, 3.14159265, -2.26892803, 0.0, 0.95993109, 1.57079633]
    d.qpos[:ARM_DOFS] = arm_home
    d.ctrl[:ARM_DOFS] = arm_home
    mj.mj_forward(m, d)

    sid, sname = ee_site_id(m)
    grip_act = name2id(m, mj.mjtObj.mjOBJ_ACTUATOR, "2f85_fingers_actuator")
    obj_bid = name2id(m, mj.mjtObj.mjOBJ_BODY, "object")
    print(f"EE site={sname} grip_act={grip_act} obj_body={obj_bid}")

    # Hold the home EE orientation throughout (pure translation teleop).
    home_quat = np.zeros(4)
    mj.mju_mat2Quat(home_quat, d.site_xmat[sid])
    ee0 = d.site_xpos[sid].copy()
    cube0 = d.xpos[obj_bid].copy()
    print(f"EE home pos={ee0.round(3)}  cube pos={cube0.round(3)}")

    jacp = np.zeros((3, m.nv)); jacr = np.zeros((3, m.nv))

    def ik_to(target_pos, grip_ctrl, n_steps):
        for _ in range(n_steps):
            mj.mj_jacSite(m, d, jacp, jacr, sid)
            J = np.vstack([jacp[:, :ARM_DOFS], jacr[:, :ARM_DOFS]])  # 6 x 7
            cur_q = np.zeros(4); mj.mju_mat2Quat(cur_q, d.site_xmat[sid])
            err = np.concatenate([target_pos - d.site_xpos[sid], quat_err(home_quat, cur_q)])
            dq = J.T @ np.linalg.solve(J @ J.T + (DAMP ** 2) * np.eye(6), err)
            d.ctrl[:ARM_DOFS] = d.qpos[:ARM_DOFS] + STEP_GAIN * dq
            d.ctrl[grip_act] = grip_ctrl
            mj.mj_step(m, d)

    # Pre-grasp above cube -> descend -> close -> lift
    above = cube0 + np.array([0, 0, 0.12])
    at = cube0 + np.array([0, 0, 0.0])
    ik_to(above, 0.0, 600)
    ee_above = d.site_xpos[sid].copy()
    ik_to(at, 0.0, 600)
    ee_at = d.site_xpos[sid].copy()
    ik_to(at, 255.0, 400)            # close on cube
    cube_grasped = d.xpos[obj_bid].copy()
    ik_to(above + np.array([0, 0, 0.08]), 255.0, 800)  # lift
    cube_lifted = d.xpos[obj_bid].copy()

    print(f"EE reached above: {ee_above.round(3)}  (target {above.round(3)})")
    print(f"EE reached at:    {ee_at.round(3)}  (target {at.round(3)})")
    print(f"cube z: start={cube0[2]:.3f} grasped={cube_grasped[2]:.3f} lifted={cube_lifted[2]:.3f}")
    rise = cube_lifted[2] - cube_grasped[2]
    print("VERDICT:", "GRASP+LIFT OK (cube rose %.3f m)" % rise if rise > 0.05 else "FAILED (cube rose %.3f m)" % rise)


if __name__ == "__main__":
    main()
