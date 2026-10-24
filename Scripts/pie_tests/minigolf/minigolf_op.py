"""The mini-golf scenario inside the running ramms-sim editor: the Gen3 putting a free ball under MuJoCo, one op per call.
The host is run_minigolf.py; the level is made by make_minigolf_map.py. Each call prints one `MINIGOLF {...}` line.

The host leaves the op string on `unreal._minigolf_op` (it is consumed on read) and runs this file. Ops:

    start [map] / pie / stop         load the map and begin PIE / begin PIE on the open map / end PIE
    status                           manager state, sim time, tick rate, base and bracelet pose
    run                              unpause the manager (our map has no pawn to start it)
    arm                              actuator, joint and body names, joint positions (rad), base_link and bracelet_link pose
    pose                             bracelet_link relative to base_link (Unreal cm, base frame) and both world poses
    probe <q1..q7> <settle_s>        set the seven targets, wait settle_s of sim time, then pose (one call)
    goto <seconds> <q1..q7>          ramp the targets from the current joints to q over N s of sim time (smoothstep)
    play <stroke.json>|<f0>|<f1>|<out.json>
                                     play a 24 fps joint stroke (degrees) from frame f0 to f1 on the sim clock and record
                                     every tick (see below); `progress` reports it and the file is written at the end
                                     optional chair-assist fields: ...|<chair_v cm/s>|<fa>|<fb> slide the Gen3 actor along +x
                                     at that speed between frames fa and fb (6-frame smoothstep ramps, on the sim clock); needs
                                     the non-fixed Gen3 Blueprint, whose free base is welded to a mocap body that follows the actor
    progress                         samples so far, whether the play finished, the last frame
    speed <percent>                  set the physics engine's sim_speed_percent (finer control updates per sim second) and report
                                     whether the articulation is still bound
    sequence <spec.json>|<out.json>  one recording of several segments on the sim clock (see the op): play / goto / drive / settle
    kick <vx m/s> <seconds>          give the ball a velocity along +X by its free joint and sample it per tick
    kickresult                       the kick's samples, thinned, and the last one
    headbody                         the putter head's and the ball's body poses (checks both exist in the running sim)

Frames. Poses are reported in Unreal world centimetres with quaternions (x, y, z, w). MuJoCo is right-handed with metres and
quaternions (w, x, y, z); URLab mirrors Y between the two (positions (x, -y, z) / 100, quaternions (w, -x, y, -z)), and the
Body.get_world_position / get_world_rotation calls used here already return the Unreal side. Joint angles are the MJCF's own
radians; the stroke file is in degrees and converted on read, with no sign changes.

The arm is driven through the MJCF's <general> position servos (gainprm 2000 / 500, ctrl = target angle in radians).
"""
import json
import math
import time

import unreal

import common   # Scripts/pie_tests/common.py: the host puts its folder on sys.path

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
TAG = "MINIGOLF"
JOINTS = ["joint_%d" % i for i in range(1, 8)]


def world():
    w = ues.get_game_world()
    if w is None:
        raise RuntimeError("PIE is not running")
    return w


def arm(w):
    """The Gen3: the articulation that has joint_1 (the ball is an articulation too)."""
    arts = list(unreal.GameplayStatics.get_all_actors_of_class(w, unreal.MjArticulation))
    for a in arts:
        if "joint_1" in list(a.get_joint_names()):
            return a
    if not arts:
        raise RuntimeError("no articulation")
    return arts[0]


def ball_body(w):
    for a in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.MjArticulation):
        b = a.get_body("ball")
        if b is not None:
            return a, b
    return None, None


def body_xf(b):
    p, q = b.get_world_position(), b.get_world_rotation()
    return [round(p.x, 3), round(p.y, 3), round(p.z, 3), round(q.x, 6), round(q.y, 6), round(q.z, 6), round(q.w, 6)]


def vec3(v):
    return [round(v.x, 3), round(v.y, 3), round(v.z, 3)]


def quat(q):
    return [round(q.x, 6), round(q.y, 6), round(q.z, 6), round(q.w, 6)]


def pose_of(body):
    return {"pos": vec3(body.get_world_position()), "quat": quat(body.get_world_rotation())}


def rel_pose(a):
    """bracelet_link in base_link's frame (cm), plus both world poses."""
    base, brace = a.get_body("base_link"), a.get_body("bracelet_link")
    if base is None or brace is None:
        return {"bound": False}
    bp, bq = base.get_world_position(), base.get_world_rotation()
    d = brace.get_world_position() - bp
    local = bq.unrotate_vector(d)
    return {"bound": True, "base": pose_of(base), "bracelet": pose_of(brace), "bracelet_in_base": vec3(local),
            "joints": [round(unreal.MjJointRuntime.get_position(a.get_joint(j)), 4) for j in JOINTS]}


def set_ctrl(a, q):
    """Stage the seven targets in BOTH control slots: the articulation applies the one its ControlSource selects (0 = the
    network slot, the default, which set_control alone never reaches: MjArticulation.cpp ResolveDesiredControl)."""
    for j, v in zip(JOINTS, q):
        act = a.get_actuator(j)
        unreal.MjActuatorRuntime.set_network_control(act, float(v))
        unreal.MjActuatorRuntime.set_control(act, float(v))


def take_over(a):
    """Make the articulation apply our actuator targets: release the keyframe hold the Blueprint starts in (ApplyControls
    pins qpos to it every step), and switch off any controller component (a bound one would rewrite ctrl)."""
    d = {"was_holding": a.is_holding_keyframe(), "controllers": []}
    if d["was_holding"]:
        a.stop_hold_keyframe()
    for c in a.get_components_by_class(unreal.ActorComponent):
        if "Controller" in c.get_class().get_name():
            c.set_component_tick_enabled(False)
            c.deactivate()
            try:
                en = c.get_editor_property("enabled")
            except Exception:
                en = None
            d["controllers"].append((c.get_class().get_name(), en))
    d["holding"] = a.is_holding_keyframe()
    return d


args = common.take_op("_minigolf_op")
op = args[0]
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if op == "start":
    if ues.get_game_world() is not None:
        les.editor_request_end_play()
        common.out(TAG, {"stopped": True, "note": "PIE was running; stopped it, call start again"})
    else:
        les.load_level(args[1] if len(args) > 1 else "/Game/Maps/URL/Map_MiniGolf_URL")
        les.editor_request_begin_play()
        common.out(TAG, {"started": True})
elif op == "pie":
    if ues.get_game_world() is not None:
        raise RuntimeError("PIE is running; stop first")
    les.editor_request_begin_play()
    common.out(TAG, {"started": True})
elif op == "stop":
    if ues.get_game_world() is not None:
        les.editor_request_end_play()
    common.out(TAG, {"stopped": True})
elif op == "status":
    w = world()
    m = unreal.AMjManager.get_manager()
    a = arm(w)
    d = {"ready": m.is_initialized() and m.is_running(), "sim": round(m.get_sim_time(), 3), "dt": m.get_timestep(),
         "initialized": m.is_initialized(), "running": m.is_running(), "compile_error": str(m.get_last_compile_error()),
         "articulations": len(list(m.get_all_articulations())), "quick": len(list(m.get_all_quick_components()))}
    d.update(rel_pose(a))
    common.out(TAG, d)
elif op == "run":
    # the manager comes up initialized but not running on this map (no pawn or widget starts it): unpause it
    m = unreal.AMjManager.get_manager()
    before = m.is_running()
    m.set_paused(False)
    time.sleep(0.5)
    common.out(TAG, {"was_running": before, "running": m.is_running(), "sim": round(m.get_sim_time(), 3), "step_mode": str(m.get_editor_property("step_mode"))})
elif op == "arm":
    a = arm(world())
    d = {"actuators": list(a.get_actuator_names()), "joints": list(a.get_joint_names()), "bodies": list(a.get_body_names())}
    d.update(rel_pose(a))
    d["ctrl"] = [round(unreal.MjActuatorRuntime.get_control(a.get_actuator(j)), 4) for j in JOINTS]
    common.out(TAG, d)
elif op == "pose":
    common.out(TAG, rel_pose(arm(world())))
elif op == "probe":
    w = world()
    a = arm(w)
    m = unreal.AMjManager.get_manager()
    q = [float(v) for v in args[1:8]]
    settle = float(args[8]) if len(args) > 8 else 2.0
    took = take_over(a)
    set_ctrl(a, q)
    t0, w0 = m.get_sim_time(), time.perf_counter()
    while m.get_sim_time() - t0 < settle and time.perf_counter() - w0 < 4 * settle + 5:
        time.sleep(0.05)
    d = rel_pose(a)
    d["ctrl"] = q
    d["ctrl_readback"] = [round(unreal.MjActuatorRuntime.get_control(a.get_actuator(j)), 3) for j in JOINTS]
    d["ctrl_applied"] = [round(unreal.MjActuatorRuntime.get_applied_control(a.get_actuator(j)), 3) for j in JOINTS]
    d["settled_sim_s"] = round(m.get_sim_time() - t0, 3)
    d["take_over"] = took
    common.out(TAG, d)
elif op == "kick":
    # kick <vx m/s> <seconds>: set the ball's free-joint x velocity (an impulse-free launch, used to calibrate rolling friction), sample the ball per tick
    w = world()
    m = unreal.AMjManager.get_manager()
    vx, secs = float(args[1]), float(args[2])
    bart, ball = ball_body(w)
    fj = [c for c in bart.get_components_by_class(unreal.ActorComponent) if c.get_class().get_name() == "MjFreeJoint"]
    unreal.MjJointRuntime.set_velocity(fj[0], vx)
    t0 = m.get_sim_time()
    samples = []
    handle = []

    def tick(dt):
        bl = ball.get_world_position()
        samples.append([round(m.get_sim_time() - t0, 4), round(bl.x, 2), round(bl.y, 2), round(bl.z, 2)])
        if m.get_sim_time() - t0 > secs:
            unreal.unregister_slate_post_tick_callback(handle[0])
            unreal._minigolf_kick = samples
    handle.append(unreal.register_slate_post_tick_callback(tick))
    common.out(TAG, {"kicked": vx, "joint": fj[0].get_name() if fj else None})
elif op == "kickresult":
    sm = getattr(unreal, "_minigolf_kick", None)
    if not sm:
        common.out(TAG, {"done": False})
    else:
        common.out(TAG, {"done": True, "n": len(sm), "path": sm[::max(1, len(sm) // 24)], "last": sm[-1]})
elif op == "headbody":
    w = world()
    a = arm(w)
    head = a.get_body("putter_head")
    bart, ball = ball_body(w)
    common.out(TAG, {"arm_bodies_with_putter": [n for n in a.get_body_names() if "putter" in n], "head": body_xf(head) if head else None,
                "ball": body_xf(ball) if ball else None, "ball_art": bart.get_actor_label() if bart else None,
                "ball_joints": list(bart.get_joint_names()) if bart else None})
elif op == "goto":
    # goto <seconds> <q1..q7>: ramp the targets from the current joints to q over N s of sim time (smoothstep), one step per tick
    w = world()
    a = arm(w)
    m = unreal.AMjManager.get_manager()
    secs = float(args[1])
    q1 = [float(v) for v in args[2:9]]
    q0 = [unreal.MjJointRuntime.get_position(a.get_joint(j)) for j in JOINTS]
    took = take_over(a)
    t0 = m.get_sim_time()
    handle = []

    def tick(dt):
        u = min(1.0, (m.get_sim_time() - t0) / secs) if secs > 0 else 1.0
        s = 3 * u * u - 2 * u * u * u
        set_ctrl(a, [a0 + (a1 - a0) * s for a0, a1 in zip(q0, q1)])
        if u >= 1.0:
            unreal.unregister_slate_post_tick_callback(handle[0])
            unreal._minigolf_goto = None
    old = getattr(unreal, "_minigolf_goto", None)
    if old is not None:
        unreal.unregister_slate_post_tick_callback(old)
    handle.append(unreal.register_slate_post_tick_callback(tick))
    unreal._minigolf_goto = handle[0]
    common.out(TAG, {"goto": q1, "from": [round(v, 3) for v in q0], "seconds": secs, "take_over": took})
elif op == "play":
    # play <stroke.json>|<f0>|<f1>|<out.json>: play a 24 fps joint stroke (degrees, data/stroke_hole1.json) from frame f0 to f1 on the
    # sim clock, targets interpolated per tick, recording per tick: [sim_s, wall_s, frame, joints x7, bracelet xf, head xf, ball xf]
    # (xf = [x y z qx qy qz qw], UE world cm). Holds the last target after f1. `status` reports progress; the file is written at the end.
    w = world()
    a = arm(w)
    m = unreal.AMjManager.get_manager()
    fields = " ".join(args[1:]).split("|")                              # paths may carry spaces: fields are |-separated
    tl_path, f0, f1, out_path = fields[:4]
    f0, f1 = int(f0), int(f1)
    # chair-assist: slide the Gen3 ACTOR along +x at chair_v cm/s between frames fa and fb. With the non-fixed Blueprint the base
    # is a free body welded to a mocap base_target whose component follows the actor, so the whole arm rides the "chair"
    chair_v, fa, fb = (float(fields[4]), float(fields[5]), float(fields[6])) if len(fields) >= 7 else (0.0, 0.0, 0.0)
    chair_x0 = a.get_actor_location()
    chair_pos = [0.0]
    tl = [[math.radians(d) for d in row] for row in json.load(open(tl_path, encoding="utf-8"))["frames"]]
    take_over(a)
    brace = a.get_body("bracelet_link")
    head = a.get_body("putter_head")
    _, ball = ball_body(w)
    rec = {"format": "ramms-minigolf/2", "map": w.get_name(), "f0": f0, "f1": f1, "fps": 24, "stroke": tl_path,
           "row": "[sim_s, wall_s, frame, j1..j7 (rad), bracelet xf, putter_head xf, ball xf, chair_x_cm, base_link xf]; "
                  "xf = [x y z qx qy qz qw] UE world cm (MuJoCo bodies)",
           "bodies": {"head": head is not None, "ball": ball is not None}, "samples": [], "done": False,
           "chair": {"v_cm_s": chair_v, "fa": fa, "fb": fb},
           "row_extra": "format 2 adds [7] chair x offset (cm, the actor's slide since the start of play), [8] base_link xf"}
    unreal._minigolf_rec = rec
    t0, w0 = m.get_sim_time(), time.perf_counter()
    handle = []

    def xf_of_actor(ac):
        t = ac.get_actor_transform()
        p, q = t.translation, t.rotation
        return [round(p.x, 3), round(p.y, 3), round(p.z, 3), round(q.x, 6), round(q.y, 6), round(q.z, 6), round(q.w, 6)]

    def chair_speed(fr):
        if chair_v == 0.0 or fr < fa or fr > fb:
            return 0.0
        ramp = 6.0
        s = min(1.0, (fr - fa) / ramp, (fb - fr) / ramp)
        return chair_v * (3 * s * s - 2 * s * s * s)

    last = [m.get_sim_time()]

    def tick(dt):
        try:
            now = m.get_sim_time()
            fr = f0 + (now - t0) * 24.0
            i = min(int(math.floor(fr)), f1 - 1)
            u = min(1.0, max(0.0, fr - i))
            if fr >= f1:
                i, u = f1 - 1, 1.0
            q = [tl[i][k] + (tl[i + 1][k] - tl[i][k]) * u for k in range(7)]
            set_ctrl(a, q)
            v = chair_speed(fr)
            if v:
                chair_pos[0] += v * (now - last[0])
                a.set_actor_location(unreal.Vector(chair_x0.x + chair_pos[0], chair_x0.y, chair_x0.z), False, False)
            last[0] = now
            p, qq = brace.get_world_position(), brace.get_world_rotation()
            row = [round(now, 5), round(time.perf_counter() - w0, 4), round(fr, 3),
                   [round(unreal.MjJointRuntime.get_position(a.get_joint(j)), 5) for j in JOINTS],
                   [round(p.x, 3), round(p.y, 3), round(p.z, 3), round(qq.x, 6), round(qq.y, 6), round(qq.z, 6), round(qq.w, 6)],
                   body_xf(head) if head is not None else None,
                   body_xf(ball) if ball is not None else None,
                   round(chair_pos[0], 3), body_xf(a.get_body("base_link")) if a.get_body("base_link") else None]
            rec["samples"].append(row)
            if fr >= f1 + 24:          # a second of hold after the last frame, then stop
                rec["done"] = True
                unreal.unregister_slate_post_tick_callback(handle[0])
                unreal._minigolf_play = None
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(rec, f, separators=(",", ":"))
        except Exception as e:
            rec["error"] = repr(e)
            rec["done"] = True
            unreal.unregister_slate_post_tick_callback(handle[0])
            unreal._minigolf_play = None
    old = getattr(unreal, "_minigolf_play", None)
    if old is not None:
        unreal.unregister_slate_post_tick_callback(old)
    handle.append(unreal.register_slate_post_tick_callback(tick))
    unreal._minigolf_play = handle[0]
    common.out(TAG, {"playing": [f0, f1], "out": out_path, "bodies": rec["bodies"], "sim": round(t0, 3)})
elif op == "sequence":
    # sequence <spec.json>|<out.json>: one recording of several segments on the sim clock, for a hole played in more than one
    # stroke. spec: {"stroke": <stroke json, degrees>, "segments": [...]} with segments
    #   {"play": [f0, f1], "chair": [v_cm_s, fa, fb] | null, "hold": frames}   the stroke (stroke frames), optional chair slide
    #   {"goto": stroke_frame, "seconds": s}                                     ramp the arm to a stroke pose (the carry)
    #   {"drive": "ball", "seconds": s, "cup": [x, y], "ball_offset": [x, y], "mount": [x, y, z], "base_yaw": deg, "hold_frame": f}
    #                                                   drive the chair (the Gen3 actor) to park beside the ball facing the cup
    #   {"settle": s}
    # Rows: [sim_s, wall_s, seq_frame, joints x7, bracelet xf, head xf, ball xf, actor (x, y, yaw), base xf, segment, local_frame]
    spec_path, out_path = " ".join(args[1:]).split("|")
    spec = json.load(open(spec_path, encoding="utf-8"))
    tl = [[math.radians(d) for d in row] for row in json.load(open(spec["stroke"], encoding="utf-8"))["frames"]]
    segs = spec["segments"]
    w = world()
    a = arm(w)
    m = unreal.AMjManager.get_manager()
    take_over(a)
    brace, head = a.get_body("bracelet_link"), a.get_body("putter_head")
    _, ball = ball_body(w)
    rec = {"format": "ramms-minigolf/3", "map": w.get_name(), "fps": 24, "spec": spec, "samples": [], "done": False,
           "row": "[sim_s, wall_s, seq_frame, j1..j7 (rad), bracelet xf, putter_head xf, ball xf, actor (x, y, yaw deg), base_link xf, segment, local stroke frame]"}
    unreal._minigolf_rec = rec
    t0 = m.get_sim_time()
    w0 = time.perf_counter()
    st = {"i": 0, "t_seg": t0, "start": None, "target": None, "q0": None, "last": t0, "chair_pos": 0.0}
    handle = []

    def rot2(x, y, deg):
        c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        return x * c - y * s_, x * s_ + y * c

    def actor_pose():
        l, r = a.get_actor_location(), a.get_actor_rotation()
        return [l.x, l.y, l.z, r.yaw]

    def begin_segment(i, now):
        st["i"], st["t_seg"], st["last"], st["chair_pos"] = i, now, now, 0.0
        if i >= len(segs):
            return
        sg = segs[i]
        st["start"] = actor_pose()
        if "goto" in sg:
            st["q0"] = [unreal.MjJointRuntime.get_position(a.get_joint(j)) for j in JOINTS]
        if "drive" in sg:
            # park beside the ball facing the cup: chair yaw from ball to cup, chair position so the ball sits at ball_offset
            # in chair space, the actor (the arm's base) at mount in that chair frame
            bp = ball.get_world_position()
            cup, off, mnt = sg["cup"], sg["ball_offset"], sg["mount"]
            cyaw = math.degrees(math.atan2(cup[1] - bp.y, cup[0] - bp.x))
            ox, oy = rot2(off[0], off[1], cyaw)
            cx, cy = bp.x - ox, bp.y - oy
            mx, my = rot2(mnt[0], mnt[1], cyaw)
            st["target"] = [cx + mx, cy + my, mnt[2], sg["base_yaw"] + cyaw]
            rec.setdefault("drives", []).append({"segment": i, "ball": [bp.x, bp.y, bp.z], "chair": [cx, cy, cyaw], "actor": st["target"]})

    begin_segment(0, t0)

    def tick(dt):
        try:
            now = m.get_sim_time()
            fr_seq = (now - t0) * 24.0
            i = st["i"]
            local = None
            if i < len(segs):
                sg = segs[i]
                u_t = now - st["t_seg"]
                if "play" in sg:
                    f0, f1 = sg["play"]
                    fr = f0 + u_t * 24.0
                    local = fr
                    k = min(int(math.floor(fr)), f1 - 1)
                    u = min(1.0, max(0.0, fr - k))
                    if fr >= f1:
                        k, u = f1 - 1, 1.0
                    set_ctrl(a, [tl[k][j] + (tl[k + 1][j] - tl[k][j]) * u for j in range(7)])
                    ch = sg.get("chair")
                    if ch and ch[1] <= fr <= ch[2]:
                        ramp = 6.0
                        s_ = min(1.0, (fr - ch[1]) / ramp, (ch[2] - fr) / ramp)
                        v = ch[0] * (3 * s_ * s_ - 2 * s_ * s_ * s_)
                        st["chair_pos"] += v * (now - st["last"])
                        sx, sy, sz, syaw = st["start"]
                        dx, dy = rot2(st["chair_pos"], 0.0, syaw - sg.get("base_yaw", -90.0))   # along the chair's +x
                        a.set_actor_location(unreal.Vector(sx + dx, sy + dy, sz), False, False)
                    if fr >= f1 + sg.get("hold", 24):
                        begin_segment(i + 1, now)
                elif "goto" in sg:
                    u = min(1.0, u_t / sg["seconds"]) if sg["seconds"] > 0 else 1.0
                    s_ = 3 * u * u - 2 * u * u * u
                    q1 = tl[int(sg["goto"])]
                    set_ctrl(a, [q0 + (q1_ - q0) * s_ for q0, q1_ in zip(st["q0"], q1)])
                    if u >= 1.0:
                        begin_segment(i + 1, now)
                elif "drive" in sg:
                    set_ctrl(a, tl[int(sg.get("hold_frame", 0))])
                    u = min(1.0, u_t / sg["seconds"])
                    s_ = 3 * u * u - 2 * u * u * u
                    sx, sy, sz, syaw = st["start"]
                    tx, ty, tz, tyaw = st["target"]
                    dyaw = (tyaw - syaw + 180.0) % 360.0 - 180.0
                    a.set_actor_location_and_rotation(unreal.Vector(sx + (tx - sx) * s_, sy + (ty - sy) * s_, sz),
                                                      unreal.Rotator(0.0, 0.0, syaw + dyaw * s_), False, False)
                    if u >= 1.0:
                        begin_segment(i + 1, now)
                elif "settle" in sg:
                    if u_t >= sg["settle"]:
                        begin_segment(i + 1, now)
                st["last"] = now
            p, qq = brace.get_world_position(), brace.get_world_rotation()
            rec["samples"].append([round(now, 5), round(time.perf_counter() - w0, 4), round(fr_seq, 3),
                                   [round(unreal.MjJointRuntime.get_position(a.get_joint(j)), 5) for j in JOINTS],
                                   [round(p.x, 3), round(p.y, 3), round(p.z, 3), round(qq.x, 6), round(qq.y, 6), round(qq.z, 6), round(qq.w, 6)],
                                   body_xf(head) if head is not None else None, body_xf(ball) if ball is not None else None,
                                   [round(v, 3) for v in actor_pose()][:2] + [round(actor_pose()[3], 3)],
                                   body_xf(a.get_body("base_link")) if a.get_body("base_link") else None,
                                   st["i"], None if local is None else round(local, 3)])
            if st["i"] >= len(segs):
                rec["done"] = True
                unreal.unregister_slate_post_tick_callback(handle[0])
                unreal._minigolf_play = None
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(rec, f, separators=(",", ":"))
        except Exception as e:
            rec["error"] = repr(e)
            rec["done"] = True
            unreal.unregister_slate_post_tick_callback(handle[0])
            unreal._minigolf_play = None
    old = getattr(unreal, "_minigolf_play", None)
    if old is not None:
        unreal.unregister_slate_post_tick_callback(old)
    handle.append(unreal.register_slate_post_tick_callback(tick))
    unreal._minigolf_play = handle[0]
    common.out(TAG, {"sequence": len(segs), "out": out_path, "sim": round(t0, 3)})
elif op == "speed":
    # speed <percent>: the physics engine's sim_speed_percent (half speed = finer control updates and smaller mocap steps per
    # editor tick). Reports whether the articulation is still bound afterwards (a property set during PIE can unbind: #76)
    w = world()
    m = unreal.AMjManager.get_manager()
    eng = m.get_editor_property("physics_engine")
    before = eng.get_editor_property("sim_speed_percent")
    eng.set_editor_property("sim_speed_percent", float(args[1]))
    time.sleep(0.3)
    common.out(TAG, {"sim_speed_percent": eng.get_editor_property("sim_speed_percent"), "was": before, "bound": rel_pose(arm(w)).get("bound")})
elif op == "progress":
    rec = getattr(unreal, "_minigolf_rec", None)
    m = unreal.AMjManager.get_manager()
    common.out(TAG, {"samples": len(rec["samples"]) if rec else 0, "done": rec["done"] if rec else None, "error": rec.get("error") if rec else None,
                "frame": rec["samples"][-1][2] if rec and rec["samples"] else None, "sim": round(m.get_sim_time(), 3)})
else:
    raise RuntimeError("unknown op %r" % op)
