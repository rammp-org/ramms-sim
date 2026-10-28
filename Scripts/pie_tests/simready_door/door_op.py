"""PIE run of a door plan through RammsMjEndEffectorController (closed-loop DLS IK in URLab's MuJoCo); see
README.md. Follows the plan's pinch-site targets and grip on the sim clock: position through
SetTargetPosition, orientation through MoveTargetBy deltas, grip through SetGrip. Sets the appliance joint to the
plan's start value, records it every tick, takes HighResShots at the given plan times and ends PIE when the plan
is done. Runs from a slate tick, so it returns at once.

Globals: DO_PLAN (the plan .json), DO_JOINT (the appliance joint), DO_SHOTS (plan seconds), DO_OUT (the result
.json: rows of [sim_s, joint, planned joint, grip 0..255, commanded yaw deg], with the offline log beside them).
"""
import json, math, os, time, traceback
import unreal
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
plan = json.load(open(DO_PLAN))
LOG = plan["log"]; DT = plan["result"]["scene"]["log_dt"]; BASE_Z = plan["result"]["scene"]["base_z"]
T = LOG["t"]; TGT = LOG["target"]; GRIP = LOG["grip"]; QD = LOG["q_des"]; QS = LOG["q"]
for k in [k for k in list(globals()) if k == "DOP"]:
    globals().pop(k)
DOP = {"phase": "begin", "until": time.time() + 0.5, "rows": [], "err": None, "shots": list(DO_SHOTS), "yaw_cmd": 0.0,
       "t_start": time.time(), "q_cmd": list(TGT[0][3:])}   # the controller seeds its target from the home pose

def qmul(a, b):
    aw, ax, ay, az = a; bw, bx, by, bz = b
    return [aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw]

def qconj(q):
    return [q[0], -q[1], -q[2], -q[3]]

def qnorm(q):
    n = math.sqrt(sum(c * c for c in q)); return [c / n for c in q]

def qaxis(ax_, ang):
    s_ = math.sin(ang / 2); return [math.cos(ang / 2)] + [c * s_ for c in ax_]

def zyx(q):
    """q = qz(yaw) * qy(pitch) * qx(roll), in degrees (the order MoveTargetBy composes)."""
    w, x, y, z = q
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return [math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]

def finish(msg):
    DOP["done"] = msg
    out = {"msg": msg, "rows": DOP["rows"], "plan_t": T, "plan_q": QS, "plan_q_des": QD, "err": DOP["err"]}
    os.makedirs(os.path.dirname(os.path.abspath(DO_OUT)), exist_ok=True)
    json.dump(out, open(DO_OUT, "w"))
    unreal.log("simready_door: %s, %d rows -> %s" % (msg, len(DOP["rows"]), DO_OUT))
    try:
        unreal.unregister_slate_post_tick_callback(DOP["h"])
    except Exception:
        pass
    try:
        les.editor_request_end_play()
    except Exception:
        pass

def interp(t):
    i = t / DT
    i0 = int(max(0, min(len(T) - 1, math.floor(i))))
    i1 = min(len(T) - 1, i0 + 1)
    f = max(0.0, min(1.0, i - i0))
    p = [TGT[i0][k] * (1 - f) + TGT[i1][k] * f for k in range(3)]
    return p, TGT[i1][3:], GRIP[i1], QD[i1], i1

def tick(dt):
    now = time.time()
    if now < DOP["until"]:
        return
    try:
        ph = DOP["phase"]
        if ph == "begin":
            les.editor_request_begin_play(); DOP["phase"] = "find"; DOP["until"] = now + 4.0; return
        gw = ues.get_game_world()
        if gw is None:
            if now - DOP["t_start"] > 60: finish("no PIE world")
            return
        if ph == "find":
            arts = list(unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.MjArticulation))
            DOP["arm"] = [a for a in arts if "joint_1" in list(a.get_joint_names())][0]
            DOP["app"] = [a for a in arts if DO_JOINT in list(a.get_joint_names())][0]
            DOP["ctl"] = DOP["arm"].get_components_by_class(unreal.RammsMjEndEffectorController)[0]
            DOP["mgr"] = unreal.AMjManager.get_manager()
            if not DOP["mgr"].is_running():
                DOP["mgr"].set_paused(False)
            cams = [c for c in unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.CameraActor) if unreal.Name("door_cam") in c.tags]
            pc = unreal.GameplayStatics.get_player_controller(gw, 0)
            pawn = pc.get_controlled_pawn() if pc else None
            if pawn:
                pawn.destroy_actor()     # GameModeBase's DefaultPawn sphere; the view is the camera
            if cams:
                pc.set_view_target_with_blend(cams[0], 0.0)
            DOP["phase"] = "init"; return
        if ph == "init":
            start = plan["result"]["scene"].get("start")
            if start is not None and not DOP.get("started"):
                j = DOP["app"].get_joint(DO_JOINT)
                hinge = plan["result"]["type"] == "hinge"
                unreal.MjJointRuntime.set_position(j, math.radians(start) if hinge else start)
                DOP["started"] = True
                return
            if not DOP["ctl"].is_target_initialized():
                return
            DOP["t0"] = DOP["mgr"].get_sim_time(); DOP["phase"] = "run"; return
        if ph == "run":
            ts = DOP["mgr"].get_sim_time() - DOP["t0"]
            p, q, g, qd, i = interp(ts)
            # RammsMjEndEffectorController (bTrackBaseFrame) takes targets in the arm's base frame;
            # the base sits at (0, 0, base_z) in the plan's world with no rotation.
            DOP["ctl"].set_target_position(unreal.Vector(p[0], p[1], p[2] - BASE_Z))
            # Orientation: send the delta from the commanded to the planned orientation as a
            # base-frame rotation (MoveTargetBy pre-multiplies qz*qy*qx), and mirror it in q_cmd.
            qp = list(q)
            if qmul(qp, qconj(DOP["q_cmd"]))[0] < 0:
                qp = [-c for c in qp]
            dq = qnorm(qmul(qp, qconj(DOP["q_cmd"])))
            if 2 * math.degrees(math.acos(min(1.0, abs(dq[0])))) > 0.05:
                r, pt, yw = zyx(dq)
                DOP["ctl"].move_target_by(unreal.Vector(0, 0, 0), unreal.Rotator(roll=r, pitch=pt, yaw=yw), False)
                applied = qmul(qmul(qaxis([0, 0, 1], math.radians(yw)), qaxis([0, 1, 0], math.radians(pt))),
                               qaxis([1, 0, 0], math.radians(r)))
                DOP["q_cmd"] = qnorm(qmul(applied, DOP["q_cmd"]))
                DOP["yaw_cmd"] = zyx(DOP["q_cmd"])[2]
            DOP["ctl"].set_grip(g / 255.0)
            qa = DOP["app"].get_joint_angle(DO_JOINT)
            DOP["rows"].append([round(ts, 4), round(qa, 5), round(qd, 5), round(g, 1), round(DOP["yaw_cmd"], 2)])
            if DOP["shots"] and ts >= DOP["shots"][0]:
                DOP["shots"].pop(0)
                unreal.SystemLibrary.execute_console_command(gw, "HighResShot 1920x1080")
            if ts >= T[-1]:
                finish("ok")
    except Exception:
        DOP["err"] = traceback.format_exc()
        finish("error")

DOP["h"] = unreal.register_slate_post_tick_callback(tick)
