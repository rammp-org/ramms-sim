"""PIE: drive the Chaos prototype through traj.py's schedule, log measured joint angles (from body poses),
loop-closure gaps, and optionally frames, to Saved/ChaosSpike/<CP_OUT>.json. Options (CP_* globals, consumed):
CP_OUT, CP_TRAJ ("grasp" or the arm schedule), CP_SLOMO, CP_WARM, CP_FRAMES, CP_CAM, CP_ARMSCALE, CP_DRIVE_OVERRIDE."""
import os, sys, math, json, time, importlib, unreal
CH = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "ChaosSpike").replace("\\", "/")   # data: JSON in, logs and runs out
SRC = os.path.join(os.path.abspath(unreal.Paths.project_dir()), "Scripts", "chaos_spike")
os.makedirs(CH, exist_ok=True)
sys.path.insert(0, SRC); import traj; importlib.reload(traj)
_CP_OPTS = {k: globals().pop(k) for k in list(globals()) if k.startswith("CP_")}   # consumed: the editor's globals outlive a run
def _cp(opts):
    J = json.load(open(CH + "/gen3_2f85_chaos.json"))
    sign = float(opts.get("CP_SIGN", 1.0)); slomo = float(opts.get("CP_SLOMO", 0.25))
    frames = opts.get("CP_FRAMES", False); outn = opts.get("CP_OUT", "chaos_run")
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem); ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    fdir = CH + "/" + outn + "_frames"
    if frames: os.makedirs(fdir, exist_ok=True)
    def qmul(a, b):
        aw, ax, ay, az = a; bw, bx, by, bz = b
        return (aw*bw - ax*bx - ay*by - az*bz, aw*bx + ax*bw + ay*bz - az*by, aw*by - ax*bz + ay*bw + az*bx, aw*bz + ax*by - ay*bx + az*bw)
    def qinv(a): return (a[0], -a[1], -a[2], -a[3])
    def qrot(q, v):
        r = qmul(qmul(q, (0.0,) + tuple(v)), qinv(q)); return r[1:]
    B = {b["name"]: b for b in J["bodies"]}
    MID = {j["name"]: 0.5 * (j["range"][0] + j["range"][1]) for j in J["joints"] if j["range"]}
    jointed = {j["child"] for j in J["joints"]}
    def root(n):
        while n not in jointed and n != "base_link" and n in B: n = B[n]["parent"]
        return n
    st = {"phase": "load", "until": 0.0, "log": [], "h": None, "fi": 0}
    def finish(msg):
        try: unreal.GameplayStatics.set_global_time_dilation(ues.get_game_world(), 1.0)
        except Exception: pass
        les.editor_request_end_play(); unreal.unregister_slate_post_tick_callback(st["h"])
        json.dump(st["log"], open(CH + "/" + outn + ".json", "w")); open(CH + "/" + outn + ".done", "w").write(msg); st.clear()
    def tick(_):
        now = time.time()
        try:
            if now < st["until"]: return
            if st["phase"] == "load":
                if not ues.get_editor_world().get_path_name().startswith("/Game/ChaosProto/Map_ChaosProto"): les.load_level("/Game/ChaosProto/Map_ChaosProto")
                st.update(phase="pie", until=now + 1.0); return
            if st["phase"] == "pie":
                les.editor_request_begin_play(); st.update(phase="bind", until=now + float(opts.get("CP_WARM", 1.5))); return
            gw = ues.get_game_world()
            if st["phase"] == "bind":
                acts = {str(a.tags[1]): a for a in unreal.GameplayStatics.get_all_actors_with_tag(gw, "ChaosRobot")}
                cons = {str(a.tags[1]): a.constraint_comp for a in unreal.GameplayStatics.get_all_actors_with_tag(gw, "ChaosRobotJoint")}
                meas = []
                if "base_link" not in acts or len(cons) < 17:
                    open(CH + "/" + outn + ".bind.txt", "w").write("acts=%s\ncons=%s\nall=%s" % (sorted(acts), sorted(cons), [(a.get_name(), [str(t) for t in a.tags]) for a in unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.StaticMeshActor)][:40]))
                for j in J["joints"]:
                    p, c = root(j["parent"]), root(j["child"])
                    bp, bc = B[p], B[c]
                    rel0 = qmul(qinv(tuple(bp["quat"])), tuple(bc["quat"]))
                    ax = qrot(qinv(tuple(bp["quat"])), j["axis"])
                    meas.append((j["name"], acts[p], acts[c], rel0, ax))
                loops = []
                for e in J["equality"]:
                    if e["type"] != "connect": continue
                    a1, a2 = acts[root(e["body1"])], acts[root(e["body2"])]
                    def local(b):
                        bb = B[root(b)]; d = [e["anchor"][k] - bb["pos"][k] for k in range(3)]
                        return qrot(qinv(tuple(bb["quat"])), d)
                    loops.append((a1, local(e["body1"]), a2, local(e["body2"])))
                ov = opts.get("CP_DRIVE_OVERRIDE")   # {joint: (stiffness, damping, maxforce)} or a callable(name, cc)
                if ov:
                    for n, cc in cons.items():
                        if callable(ov): ov(n, cc)
                        elif n in ov: cc.set_angular_drive_params(*ov[n])
                info = []
                for n in ("joint_2", "joint_4"):
                    cc = cons[n]; info.append("%s twist=%.2f sw1=%.2f sw2=%.2f" % (n, cc.get_current_twist(), cc.get_current_swing1(), cc.get_current_swing2()))
                open(CH + "/" + outn + ".bind.txt", "w").write("\n".join(info))
                cv = opts.get("CP_CAM")
                if cv:
                    for a in unreal.GameplayStatics.get_all_actors_with_tag(gw, "ChaosRobotCam"):
                        loc = unreal.Vector(*cv[0]); a.set_actor_location_and_rotation(loc, unreal.MathLibrary.find_look_at_rotation(loc, unreal.Vector(*cv[1])), False, False)
                        a.camera_component.set_editor_property("field_of_view", cv[2])
                unreal.GameplayStatics.set_global_time_dilation(gw, slomo)
                bxs = unreal.GameplayStatics.get_all_actors_with_tag(gw, "ChaosRobotBox")
                st.update(box=bxs[0] if bxs else None, rel0=None)
                st.update(acts=acts, cons=cons, meas=meas, loops=loops, g0=unreal.GameplayStatics.get_time_seconds(gw), phase="run", nf=0.0)
                return
            if st["phase"] == "run":
                t = unreal.GameplayStatics.get_time_seconds(gw) - st["g0"]
                q, g = (traj.targets_grasp if opts.get("CP_TRAJ") == "grasp" else traj.targets)(t)
                tgt = {k: v * float(opts.get("CP_ARMSCALE", 1.0)) for k, v in q.items()}; tgt["2f85_right_driver_joint"] = tgt["2f85_left_driver_joint"] = g * 0.8 / 255.0
                for n, v in tgt.items():   # a ranged joint's constraint frame sits at the middle of its range
                    st["cons"][n].set_angular_orientation_target(unreal.Rotator(roll=sign * math.degrees(v - MID.get(n, 0.0)), pitch=0.0, yaw=0.0))
                for a in st["acts"].values():   # a drive target does not wake a sleeping body
                    c = a.static_mesh_component
                    if c.is_simulating_physics(): c.wake_rigid_body("None")
                rec = {"t": round(t, 4), "q": {}, "target": tgt}
                for n, ap, ac, rel0, ax in st["meas"]:
                    qp = ap.get_actor_transform().rotation; qc = ac.get_actor_transform().rotation
                    rel = qmul(qinv((qp.w, qp.x, qp.y, qp.z)), (qc.w, qc.x, qc.y, qc.z))
                    dq = qmul(rel, qinv(rel0))
                    s = dq[1] * ax[0] + dq[2] * ax[1] + dq[3] * ax[2]
                    ang = 2.0 * math.atan2(s, dq[0]); ang = (ang + math.pi) % (2 * math.pi) - math.pi
                    rec["q"][n] = ang
                gaps = []
                for a1, l1, a2, l2 in st["loops"]:
                    p1 = a1.get_actor_transform().transform_location(unreal.Vector(*l1)); p2 = a2.get_actor_transform().transform_location(unreal.Vector(*l2))
                    gaps.append((p1 - p2).length())
                rec["loop_gap_cm"] = max(gaps) if gaps else 0.0
                st["log"].append(rec)
                if frames and t >= st["nf"]:
                    unreal.SystemLibrary.execute_console_command(gw, "HighResShot 960x540 filename=%s/f_%04d.png" % (fdir, st["fi"])); st["fi"] += 1; st["nf"] += 1.0 / 15
                if st.get("box"):
                    br = st["acts"]["bracelet_link"].get_actor_transform(); bp = st["box"].get_actor_location()
                    rel = br.inverse_transform_location(bp)
                    if st.get("rel0") is None and t >= 2.9: st["rel0"] = rel
                    rec["box_z_cm"] = bp.z; rec["slip_cm"] = (rel - st["rel0"]).length() if st.get("rel0") is not None else 0.0
                if t >= (traj.GRASP_END if opts.get("CP_TRAJ") == "grasp" else traj.T_END): finish("done %d" % len(st["log"]))
        except Exception:
            import traceback; open(CH + "/" + outn + ".err", "w").write(traceback.format_exc()); finish("error")
    st["h"] = unreal.register_slate_post_tick_callback(tick)
_cp(_CP_OPTS); del _cp, _CP_OPTS
