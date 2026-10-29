"""Editor: drive the robot pawn in the open level through its control surface, on whichever engine
simulates it, and record what it does (see README.md):

  0-2 s     settle
  2-5 s     every 5-bar linkage to the bottom of its height range (2 cm inside)
  5-8 s     ... to the top
  8-10 s    ... to the middle
  10-13 s   drive.forward 1
  13-14 s   stop
  14-17 s   drive.turn 1
  17-19 s   stop

    import unreal; D = unreal.Paths.project_dir() + "Scripts/pie_tests/chaos_articulation/"
    exec(open(D + "robot_run.py").read())

The clock is the robot's (URammsRobotBaseComponent::GetSimulationTime, which is MuJoCo's when MuJoCo
steps it) else the game's, so a run on each engine follows the same schedule. Options (consumed):
CR_OUT (run name, default "robot"), CR_SWITCH (switch the robot to Chaos at the start with SwitchToChaos,
from this MJCF keyframe, "" for qpos0, instead of it carrying a URammsChaosArticulationComponent), CR_BEGIN (default True:
begin play here; False when PIE is already running), CR_WAIT (seconds between begin play and the run,
default 2; a MuJoCo scene takes longer to compile and start). Writes Saved/ChaosArticulation/<run>.json and
<run>_summary.txt.
"""
import json, math, os, time, unreal

_CR = {k: globals().pop(k) for k in list(globals()) if k.startswith("CR_")}

def _robot_run(opts):
    out_dir = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "ChaosArticulation")
    os.makedirs(out_dir, exist_ok=True)
    name = opts.get("CR_OUT", "robot")
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    SRC = unreal.RammsControlSource.SCRIPT
    wait = float(opts.get("CR_WAIT", 2.0))
    st = {"phase": "start" if opts.get("CR_BEGIN", True) else "find", "samples": [], "log": [],
          "until": time.time() + (0.0 if opts.get("CR_BEGIN", True) else wait)}

    def finish(msg):
        lines = [msg] + st.get("log", [])
        s = st["samples"]
        if s:
            def at(t):
                return min(s, key=lambda x: abs(x["t"] - t))
            for label, t0, t1 in (("lift lo", 2.0, 5.0), ("lift hi", 5.0, 8.0), ("lift mid", 8.0, 10.0),
                                  ("forward", 10.0, 14.0), ("turn", 14.0, 19.0)):
                a, b = at(t0), at(t1)
                pa, pb = a["base"], b["base"]
                seg = [x["base"][5] for x in s if t0 <= x["t"] <= t1]
                turned = sum((y - x + 180.0) % 360.0 - 180.0 for x, y in zip(seg, seg[1:]))   # unwrapped
                lines.append("%-8s %4.1f-%4.1f s: moved %6.1f cm, heading %7.1f deg, z %6.1f -> %6.1f cm, endpoints %s" % (
                    label, t0, t1, math.hypot(pb[0] - pa[0], pb[1] - pa[1]),
                    turned, pa[2], pb[2],
                    " ".join("%s=(%.1f, %.1f)" % (k, v[0], v[1]) for k, v in b["links"].items())))
            last = s[-1]
            for m, v in sorted(last["motors"].items()):
                lines.append("  %-28s value %9.3f  velocity %9.3f" % (m, v[0], v[1]))
        with open(os.path.join(out_dir, name + "_summary.txt"), "w") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(out_dir, name + ".json"), "w") as f:
            json.dump(s, f)
        les.editor_request_end_play()
        unreal.unregister_slate_post_tick_callback(st["handle"])
        st.clear()

    def _rate_cmd(base, m):
        r = base.get_motor_velocity_command(m)   # (commanded, rad/s) -- or just the rate when the bool is dropped
        if isinstance(r, (tuple, list)):
            return r[-1] if r[0] else None
        return r

    def set_ctl(cid, v):
        if not st["cs"].set_control(cid, float(v), SRC):
            st["log"].append("refused %s=%s" % (cid, v))

    def tick(_dt):
        try:
            now = time.time()
            if now < st["until"]:
                return
            if st["phase"] == "start":
                les.editor_request_begin_play()
                st.update(phase="find", until=now + wait)
                return
            gw = ues.get_game_world()
            if st["phase"] == "find":
                pawn = None
                for p in unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.Pawn):
                    if p.get_component_by_class(unreal.RammsRobotControlSurfaceComponent):
                        pawn = p
                if pawn is None:
                    raise RuntimeError("no pawn with a control surface")
                if "CR_SWITCH" in opts:
                    unreal.RammsChaosArticulationComponent.switch_to_chaos(pawn, opts["CR_SWITCH"] or "")
                chaos = pawn.get_component_by_class(unreal.RammsChaosArticulationComponent)
                if chaos and opts.get("CR_NOSYNC"):   # profiling: stop the visuals following the bodies
                    chaos.set_component_tick_enabled(False)
                body = [b for b in pawn.get_components_by_class(unreal.MjBody) if b.get_name() != "worldbody"][0]
                base = pawn.get_component_by_class(unreal.RammsRobotBaseComponent)
                links = list(pawn.get_components_by_class(unreal.Ramms5BarLinkageController))
                cs = pawn.get_component_by_class(unreal.RammsRobotControlSurfaceComponent)
                st["log"].append("pawn %s, engine %s, root body %s, motors %d, linkages %s" % (
                    pawn.get_name(), "Chaos (built=%s %s)" % (chaos.is_built(), chaos.get_build_error()) if chaos and chaos.get_editor_property("simulate_with_chaos") else "MuJoCo",
                    body.get_name(), len(base.get_motor_ids()), [l.get_name() for l in links]))
                rng = {}
                for l in links:
                    cid = "linkage.%s.height" % l.get_name()
                    for ax in cs.describe_control_surface().get_editor_property("axes"):
                        if str(ax.get_editor_property("id")) == cid:
                            r = ax.get_editor_property("range"); rng[cid] = (r.x + 2.0, r.y - 2.0)
                st["log"].append("height ranges %s" % rng)
                st["log"].append("components: %s" % ", ".join(sorted({c.get_class().get_name() for c in pawn.get_components_by_class(unreal.ActorComponent) if not c.get_class().get_name().startswith("Mj")})))
                st.update(phase="run", pawn=pawn, body=body, base=base, links=links, cs=cs, rng=rng,
                          motors=[str(m) for m in base.get_motor_ids()], t0=None, step=-1)
                return
            base = st["base"]
            sim = base.get_simulation_time()
            clock = sim if sim >= 0.0 else unreal.GameplayStatics.get_time_seconds(gw)
            if st["t0"] is None:
                st["t0"] = clock
            t = clock - st["t0"]
            steps = [(2.0, "lo"), (5.0, "hi"), (8.0, "mid"), (10.0, "fwd"), (13.0, "stop"), (14.0, "turn"), (17.0, "stop"), (19.0, "end")]
            k = max([i for i, (ts, _) in enumerate(steps) if t >= ts], default=-1)
            if k != st["step"]:
                st["step"] = k
                what = steps[k][1]
                if what in ("lo", "hi", "mid"):
                    for cid, (lo, hi) in st["rng"].items():
                        set_ctl(cid, {"lo": lo, "hi": hi, "mid": 0.5 * (lo + hi)}[what])
                elif what == "fwd":
                    set_ctl("drive.forward", 1.0)
                elif what == "turn":
                    set_ctl("drive.turn", 1.0)
                elif what == "stop":
                    set_ctl("drive.forward", 0.0); set_ctl("drive.turn", 0.0)
                st["log"].append("t=%.2f %s" % (t, what))
                if what == "end":
                    finish("done: %d samples, %.1f s" % (len(st["samples"]), t))
                    return
            b = st["body"]
            xf = b.get_world_transform(); p = xf.translation; r = xf.rotation.rotator()
            st["samples"].append({
                "t": t, "base": [p.x, p.y, p.z, r.roll, r.pitch, r.yaw],
                "motors": {m: [base.get_motor_value(m), base.get_motor_velocity(m)] for m in st["motors"]},
                "rate_cmd": {m: _rate_cmd(base, m) for m in st["motors"]},
                "links": {l.get_name(): [l.get_current_endpoint().x, l.get_current_endpoint().y] for l in st["links"]}})
        except Exception:
            import traceback
            finish("ERROR " + traceback.format_exc())

    st["handle"] = unreal.register_slate_post_tick_callback(tick)

_robot_run(_CR)
del _robot_run, _CR
