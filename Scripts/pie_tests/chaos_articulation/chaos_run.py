"""Editor: run every URLab articulation in the open level on Chaos (URammsChaosArticulationComponent) and
put each through a generic schedule, from a slate tick so the console returns at once:

  0-1 s      settle (at CA_KEY's pose if given, else qpos0)
  2 s each   ramp the actuators to each MJCF keyframe's ctrl in turn (a base's stances)
  0.5 s      push every unactuated joint open (2 N.m on a hinge, 10 N on a slide), then let go
  2.5 s      run the torque motors (wheels) at a quarter of their ctrl range, then stop

    import unreal; D = unreal.Paths.project_dir() + "Scripts/pie_tests/chaos_articulation/"
    exec(open(D + "chaos_run.py").read())

Options (consumed): CA_OUT (run name, default "run"), CA_KEY, CA_SLOMO (0.25), CA_FRAMES (False).
Writes Saved/ChaosArticulation/<run>.json (every sample) and <run>_summary.txt.
"""
import json, math, os, time, unreal

_CA = {k: globals().pop(k) for k in list(globals()) if k.startswith("CA_")}

def _chaos_run(opts):
    out_dir = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "ChaosArticulation")
    os.makedirs(out_dir, exist_ok=True)
    name = opts.get("CA_OUT", "run")
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    st = {"phase": "start", "until": time.time(), "samples": [], "frame": 0, "next_frame": 0.0}

    def finish(msg):
        try:
            unreal.GameplayStatics.set_global_time_dilation(ues.get_game_world(), 1.0)
        except Exception:
            pass
        lines = [msg]
        for label, a in st.get("arts", {}).items():
            c = a["c"]
            lines.append("%s: built=%s %s bodies=%d simulating=%d joints=%d actuators=%d" % (
                label, c.is_built(), c.get_build_error(), len(a["bodies"]),
                sum(1 for b in a["bodies"] if b.is_simulating_physics()), len(a["joints"]), len(a["acts"])))
            qs = [s[label]["q"] for s in st["samples"] if label in s]
            for j in a["joints"]:
                v = [q[j] for q in qs if j in q]
                if v:
                    lines.append("  %-32s min %8.3f max %8.3f end %8.3f%s" % (j, min(v), max(v), v[-1], "  NaN!" if any(x != x for x in v) else ""))
            poses = [s[label]["base"] for s in st["samples"] if label in s and "base" in s[label]]
            if poses:
                p0, p1 = poses[0], poses[-1]
                lines.append("  base moved %.1f cm, z %.1f -> %.1f cm, yaw %.1f -> %.1f deg" % (
                    math.hypot(p1[0] - p0[0], p1[1] - p0[1]), p0[2], p1[2], p0[5], p1[5]))
        with open(os.path.join(out_dir, name + "_summary.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(out_dir, name + ".json"), "w") as f:
            json.dump(st["samples"], f)
        les.editor_request_end_play()
        unreal.unregister_slate_post_tick_callback(st["handle"])
        st.clear()

    def schedule(a, t):
        """{actuator: ctrl} and {joint: force} for one articulation at time t."""
        c = a["c"]; keys = a["keys"]; ctrl = {}; force = {}
        cur = list(a["start"])
        for k, key in enumerate(keys):
            s = min(max((t - 1.0 - 2.0 * k) / 1.5, 0.0), 1.0)
            target = c.get_keyframe_controls(key)
            cur = [x + s * (y - x) for x, y in zip(cur, target)] if len(target) == len(cur) else cur
        t_push = 1.0 + 2.0 * len(keys)
        t_drive = t_push + 1.5
        for n, v in zip(a["acts"], cur):
            ctrl[n] = v
        for n in a["acts"]:
            if c.is_motor(n):
                r = c.get_control_range(n)   # Python gives the out params; the bool may or may not lead
                lo, hi = r[-2], r[-1]; ok = hi > lo
                ctrl[n] = (0.25 * hi if ok else 5.0) if t_drive <= t < t_drive + 2.5 else 0.0
        if t_push <= t < t_push + 0.5:
            for j in a["passive"]:
                force[j] = 10.0 if a["slide"].get(j) else 2.0
        return ctrl, force, t_drive + 3.0

    def tick(_dt):
        try:
            now = time.time()
            if now < st["until"]:
                return
            if st["phase"] == "start":
                les.editor_request_begin_play()
                st.update(phase="switch", until=now + 1.0)
                return
            gw = ues.get_game_world()
            if st["phase"] == "switch":
                arts = {}
                for actor in unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.MjArticulation):
                    c = unreal.RammsChaosArticulationComponent.switch_to_chaos(actor, opts.get("CA_KEY", ""))
                    acts = [str(n) for n in c.get_actuator_names()]
                    joints = [str(n) for n in c.get_joint_names()]
                    passive = [j for j in joints if not c.is_actuated(j)]   # doors, drawers: pushed, not driven
                    slide = {j: c.is_slide(j) for j in joints}
                    bodies = list(c.get_body_components())
                    start_key = opts.get("CA_KEY", "")
                    start = c.get_keyframe_controls(start_key) if start_key else [0.0] * len(acts)
                    arts[actor.get_name()] = {"c": c, "acts": acts, "joints": joints, "passive": passive, "slide": slide,
                                              "keys": [k for k in c.get_keyframe_names()], "bodies": bodies,
                                              # a free-floating root (a mobile base) is reported; a fixed one is not
                                              "base": bodies[0] if bodies and bodies[0].is_simulating_physics() else None,
                                              "start": start or [0.0] * len(acts)}
                cams = unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.CameraActor)
                pc = unreal.GameplayStatics.get_player_controller(gw, 0)
                if cams and pc:   # an articulation is a pawn and may have taken the view
                    pc.set_view_target_with_blend(cams[0], 0.0)
                unreal.GameplayStatics.set_global_time_dilation(gw, float(opts.get("CA_SLOMO", 0.25)))
                st.update(arts=arts, phase="run", g0=unreal.GameplayStatics.get_time_seconds(gw), end=0.0)
                return
            t = unreal.GameplayStatics.get_time_seconds(gw) - st["g0"]
            sample = {"t": t}
            end = 0.0
            for label, a in st["arts"].items():
                c = a["c"]
                ctrl, force, a_end = schedule(a, t)
                end = max(end, a_end)
                for n, v in ctrl.items():
                    c.set_control(n, v)
                for j in a["passive"]:
                    c.set_joint_force(j, force.get(j, 0.0))
                rec = {"q": {j: c.get_joint_position(j) for j in a["joints"]}}
                if a["base"]:
                    p = a["base"].get_world_location(); r = a["base"].get_world_rotation()
                    rec["base"] = [p.x, p.y, p.z, r.roll, r.pitch, r.yaw]
                sample[label] = rec
            st["samples"].append(sample)
            if opts.get("CA_FRAMES") and t >= st["next_frame"]:
                unreal.SystemLibrary.execute_console_command(gw, "HighResShot 960x540 filename=%s/%s_frames/f_%04d.png" % (out_dir.replace("\\", "/"), name, st["frame"]))
                st["frame"] += 1; st["next_frame"] += 1.0 / 15
            if t >= end:
                finish("done: %d samples, %.1f s" % (len(st["samples"]), t))
        except Exception:
            import traceback
            st.setdefault("samples", [])
            finish("ERROR " + traceback.format_exc())

    st["handle"] = unreal.register_slate_post_tick_callback(tick)

_chaos_run(_CA)
del _chaos_run, _CA
