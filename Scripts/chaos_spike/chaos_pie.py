"""PIE: run a traj.py schedule on the Chaos robot that build_chaos_proto.py made, and log every joint's
angle (measured from body poses), the free body's pose and the loop-closure gaps to
Saved/ChaosSpike/<CP_OUT>.json. Options (CP_* globals, consumed by the run):
CP_JSON (the export), CP_OUT, CP_SCHED ("arm", "grasp", "base"), CP_SLOMO, CP_WARM, CP_FRAMES, CP_CAM,
CP_DRIVE_OVERRIDE (callable(joint name, constraint component) applied once at bind)."""
import os, sys, math, json, time, importlib, unreal
CH = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "ChaosSpike").replace("\\", "/")   # data: JSON in, logs and runs out
SRC = os.path.join(os.path.abspath(unreal.Paths.project_dir()), "Scripts", "chaos_spike")
os.makedirs(CH, exist_ok=True)
sys.path.insert(0, SRC); import traj; importlib.reload(traj)
_CP_OPTS = {k: globals().pop(k) for k in list(globals()) if k.startswith("CP_")}   # consumed: the editor's globals outlive a run
def _cp(opts):
    J = json.load(open(CH + "/" + opts.get("CP_JSON", "gen3_2f85_chaos.json")))
    sched = traj.SCHEDULES[opts.get("CP_SCHED", "arm")]
    slomo = float(opts.get("CP_SLOMO", 0.25)); frames = opts.get("CP_FRAMES", False); outn = opts.get("CP_OUT", "chaos_run")
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem); ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    fdir = CH + "/" + outn + "_frames"
    if frames: os.makedirs(fdir, exist_ok=True)
    def qmul(a, b):
        aw, ax, ay, az = a; bw, bx, by, bz = b
        return (aw*bw - ax*bx - ay*by - az*bz, aw*bx + ax*bw + ay*bz - az*by, aw*by - ax*bz + ay*bw + az*bx, aw*bz + ax*by - ay*bx + az*bw)
    def qinv(a): return (a[0], -a[1], -a[2], -a[3])
    def qrot(q, v): return qmul(qmul(q, (0.0,) + tuple(v)), qinv(q))[1:]
    B = {b["name"]: b for b in J["bodies"]}
    jointed = {j["child"] for j in J["joints"]}
    def root(n):   # the simulated body a (possibly welded) MuJoCo body belongs to
        while n in B and n not in jointed and not B[n]["free"] and B[n]["parent"] in B: n = B[n]["parent"]
        return n
    JT = {j["name"]: j for j in J["joints"]}
    MID = {j["name"]: 0.5 * (j["range"][0] + j["range"][1]) for j in J["joints"] if j["range"]}
    free = [b["name"] for b in J["bodies"] if b["free"]]
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
                les.editor_request_begin_play(); st.update(phase="bind", until=now + float(opts.get("CP_WARM", 0.2))); return
            gw = ues.get_game_world()
            if st["phase"] == "bind":
                acts = {str(a.tags[1]): a for a in unreal.GameplayStatics.get_all_actors_with_tag(gw, "ChaosRobot")}
                cons = {str(a.tags[1]): a.constraint_comp for a in unreal.GameplayStatics.get_all_actors_with_tag(gw, "ChaosRobotJoint")}
                meas = {}
                for j in J["joints"]:
                    p, c = root(j["parent"]), root(j["child"])
                    bp, bc = B[p], B[c]
                    meas[j["name"]] = (acts[p], acts[c], qmul(qinv(tuple(bp["quat"])), tuple(bc["quat"])), qrot(qinv(tuple(bp["quat"])), j["axis"]))
                loops = []
                for e in J["equality"]:
                    if e["type"] != "connect": continue
                    def local(b):
                        bb = B[root(b)]; d = [e["anchor"][k] - bb["pos"][k] for k in range(3)]
                        return qrot(qinv(tuple(bb["quat"])), d)
                    loops.append((acts[root(e["body1"])], local(e["body1"]), acts[root(e["body2"])], local(e["body2"])))
                for j in J["joints"]:
                    if j["type"] == "slide" and j["range"] and j["name"] in cons:
                        mid = 50.0 * (j["range"][0] + j["range"][1]); cc = cons[j["name"]]; ach = meas[j["name"]][1]
                        ax_w = unreal.Vector(*j["axis"])
                        ach.set_actor_location(ach.get_actor_location() - ax_w * mid, False, True)   # built mid-range (see the builder): back to q = 0
                        cc.set_linear_position_target(unreal.Vector(100.0 * j.get("springref", 0.0) - mid, 0.0, 0.0))   # the spring rests at springref
                ov = opts.get("CP_DRIVE_OVERRIDE")
                if ov:
                    for n, cc in cons.items(): ov(n, cc)
                cv = opts.get("CP_CAM")
                if cv:
                    for a in unreal.GameplayStatics.get_all_actors_with_tag(gw, "ChaosRobotCam"):
                        loc = unreal.Vector(*cv[0]); a.set_actor_location_and_rotation(loc, unreal.MathLibrary.find_look_at_rotation(loc, unreal.Vector(*cv[1])), False, False)
                        a.camera_component.set_editor_property("field_of_view", cv[2])
                bxs = unreal.GameplayStatics.get_all_actors_with_tag(gw, "ChaosRobotBox")
                unreal.GameplayStatics.set_global_time_dilation(gw, slomo)
                st.update(acts=acts, cons=cons, meas=meas, slide0={}, prevq={}, loops=loops, box=bxs[0] if bxs else None, rel0=None,
                          g0=unreal.GameplayStatics.get_time_seconds(gw), phase="run", nf=0.0)
                return
            if st["phase"] == "run":
                t = unreal.GameplayStatics.get_time_seconds(gw) - st["g0"]
                ctrl = sched(t, J)
                for a in st["acts"].values():   # a drive target does not wake a sleeping body
                    c = a.static_mesh_component
                    if c.is_simulating_physics(): c.wake_rigid_body("None")
                for ac in J["actuators"]:
                    if ac["name"] not in ctrl: continue
                    v = ctrl[ac["name"]]
                    for jn, coef in ac.get("joints", []):
                        if ac["kind"] == "servo":   # a servo's ctrl is its target: q = gain * ctrl / kp
                            q = ac["gain"] * v / ac["kp"]
                            st["cons"][jn].set_angular_orientation_target(unreal.Rotator(roll=math.degrees(q - MID.get(jn, 0.0)), pitch=0.0, yaw=0.0))
                        else:                       # a motor: torque about the joint, child +, parent -
                            ap, ach, _, ax = st["meas"][jn]
                            tw = ap.get_actor_transform().rotation.rotate_vector(unreal.Vector(*ax)) * (coef * ac["gain"] * v * 1.0e4)
                            if v == 0.0: continue
                            ach.static_mesh_component.add_torque_in_radians(tw, "None", False)
                            if ap.static_mesh_component.is_simulating_physics(): ap.static_mesh_component.add_torque_in_radians(tw * -1.0, "None", False)
                for jn, f in ctrl.get("__qfrc__", {}).items():   # an external generalized force on a joint (N.m or N)
                    ap, ach, _, ax = st["meas"][jn]
                    v = ap.get_actor_transform().rotation.rotate_vector(unreal.Vector(*ax))
                    if JT[jn]["type"] == "slide":
                        ach.static_mesh_component.add_force(v * (f * 100.0), "None", False)
                    else:
                        ach.static_mesh_component.add_torque_in_radians(v * (f * 1.0e4), "None", False)
                rec = {"t": round(t, 4), "q": {}, "ctrl": {k: v for k, v in ctrl.items() if k != "__qfrc__"}}
                for n, (ap, ac, rel0, ax) in st["meas"].items():
                    if JT[n]["type"] == "slide":
                        if n not in st["slide0"]:   # the child's place in the parent frame at q = 0, from the export
                            bp_, bc_ = B[root(JT[n]["parent"])], B[root(JT[n]["child"])]
                            st["slide0"][n] = qrot(qinv(tuple(bp_["quat"])), [bc_["pos"][k] - bp_["pos"][k] for k in range(3)])
                        p0 = st["slide0"][n]; d_ = ap.get_actor_transform().inverse_transform_location(ac.get_actor_location())
                        rec["q"][n] = ((d_.x - p0[0]) * ax[0] + (d_.y - p0[1]) * ax[1] + (d_.z - p0[2]) * ax[2]) / 100.0
                        continue
                    qp = ap.get_actor_transform().rotation; qc = ac.get_actor_transform().rotation
                    dq = qmul(qmul(qinv((qp.w, qp.x, qp.y, qp.z)), (qc.w, qc.x, qc.y, qc.z)), qinv(rel0))
                    s = dq[1] * ax[0] + dq[2] * ax[1] + dq[3] * ax[2]
                    a_ = (2.0 * math.atan2(s, dq[0]) + math.pi) % (2 * math.pi) - math.pi
                    prev = st["prevq"].get(n)   # unwrap, so a continuous joint (a wheel, a turntable) keeps counting
                    if prev is not None: a_ = prev + ((a_ - prev + math.pi) % (2 * math.pi) - math.pi)
                    st["prevq"][n] = a_; rec["q"][n] = a_
                if free:
                    a = st["acts"][free[0]]; p = a.get_actor_location(); r = a.get_actor_rotation()
                    rec["base"] = [p.x, p.y, p.z]; rec["rpy"] = [r.roll, r.pitch, r.yaw]
                gaps = []
                for a1, l1, a2, l2 in st["loops"]:
                    gaps.append((a1.get_actor_transform().transform_location(unreal.Vector(*l1)) - a2.get_actor_transform().transform_location(unreal.Vector(*l2))).length())
                rec["loop_gap_cm"] = max(gaps) if gaps else 0.0
                if st["box"]:
                    br = st["acts"]["bracelet_link"].get_actor_transform(); bp = st["box"].get_actor_location()
                    rel = br.inverse_transform_location(bp)
                    if st["rel0"] is None and t >= 2.9: st["rel0"] = rel
                    rec["box_z_cm"] = bp.z; rec["slip_cm"] = (rel - st["rel0"]).length() if st["rel0"] is not None else 0.0
                st["log"].append(rec)
                if frames and t >= st["nf"]:
                    unreal.SystemLibrary.execute_console_command(gw, "HighResShot 960x540 filename=%s/f_%04d.png" % (fdir, st["fi"])); st["fi"] += 1; st["nf"] += 1.0 / 15
                if t >= sched.end: finish("done %d" % len(st["log"]))
        except Exception:
            import traceback; open(CH + "/" + outn + ".err", "w").write(traceback.format_exc()); finish("error")
    st["h"] = unreal.register_slate_post_tick_callback(tick)
_cp(_CP_OPTS); del _cp, _CP_OPTS
