"""Editor: PIE; open and close the doors and drawers of every articulation in the open level, on whichever engine
simulates it (Chaos: URammsChaosArticulationComponent; MuJoCo: URLab, which needs the level's manager), with the
same controller and schedule, and record the joints (optionally frames from a fixed camera).

    import unreal; D = unreal.Paths.project_dir() + "Scripts/pie_tests/chaos_articulation/"
    exec(open(D + "simready_open.py").read())

Each door or drawer is moved by a PD force toward a target that ramps from closed to 80 % open over 1.5 s (from 1 s)
and back over 1.5 s, drawers first (from 4 s) and doors after them (from 5.5 s), so a closing door does not meet a
drawer still out (the joints are read from each articulation's MJCF: limited hinges of 30 degrees or more and
slides of 8 cm or more, not knobs, dials, buttons, levers, pedals or wheels). Options (consumed): SO_OUT (run name),
SO_MJCF (the folder Tools/simready_mjcf.py wrote the models to, <name>/<name>.xml; else the env var
RAMMS_SIMREADY_MJCF, else C:/Users/waemf/data/simready/mjcf), SO_CAM ((location, look-at) for frames), SO_FPS (20),
SO_FRAMES (False), SO_SLOMO (game time dilation, and MuJoCo's sim speed with it; 0.25 with frames, so saving them
does not slow the controller's ticks, else 1), SO_READY (15: seconds to wait for every articulation's engine).
Writes Saved/ChaosArticulation/<run>.json and <run>_summary.txt (and <run>_frames/). The schedule starts once every
articulation is built on Chaos or the MuJoCo manager runs; a Chaos build that failed, no MuJoCo manager, or no
articulation with an MJCF in the folder ends the run with an ERROR line instead.
"""
import json, math, os, re, time, unreal
import xml.etree.ElementTree as ET

_SO = {k: globals().pop(k) for k in list(globals()) if k.startswith("SO_")}

SKIP = re.compile(r"knob|dial|button|lever|pedal|rod|stopper|release|roller|rolling|motor|drum|turntable", re.I)


def _mjcf_joints(path):
    """[(name, kind, lo, hi)] of the MJCF's limited hinges / slides, in rad / m."""
    root = ET.parse(path).getroot()
    comp = root.find("compiler")
    deg = comp is None or comp.get("angle", "degree") == "degree"
    defaults = {}
    for d in root.iter("default"):
        j = d.find("joint")
        if j is not None and d.get("class"):
            defaults[d.get("class")] = j.attrib
    out = []
    for j in root.iter("joint"):
        name = j.get("name")
        if not name:
            continue
        attrs = dict(defaults.get(j.get("class"), {}))
        attrs.update(j.attrib)
        kind = attrs.get("type", "hinge")
        rng = attrs.get("range")
        if kind not in ("hinge", "slide") or not rng or attrs.get("limited") == "false":
            continue
        lo, hi = (float(v) for v in rng.split())
        if kind == "hinge" and deg:
            lo, hi = math.radians(lo), math.radians(hi)
        out.append((name, kind, lo, hi))
    return out


def _simready_open(opts):
    out_dir = os.path.join(os.path.abspath(unreal.Paths.project_saved_dir()), "ChaosArticulation")
    os.makedirs(out_dir, exist_ok=True)
    name = opts.get("SO_OUT", "open")
    mjcf_dir = opts.get("SO_MJCF") or os.environ.get("RAMMS_SIMREADY_MJCF") or "C:/Users/waemf/data/simready/mjcf"
    fps = float(opts.get("SO_FPS", 20.0))
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    fdir = os.path.join(out_dir, name + "_frames")
    if opts.get("SO_FRAMES"):
        os.makedirs(fdir, exist_ok=True)
        for f in os.listdir(fdir):
            try:
                os.remove(os.path.join(fdir, f))
            except OSError:
                pass
    st = {"phase": "start", "until": time.time(), "samples": [], "frame": 0, "next": 0.0, "log": []}

    def set_speed(gw, k):
        unreal.GameplayStatics.set_global_time_dilation(gw, k)
        for m in unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.AMjManager):
            if m.physics_engine:
                m.physics_engine.set_sim_speed(max(5.0, 100.0 * k))

    def finish(msg):
        gw = ues.get_game_world()
        if gw:
            try:
                set_speed(gw, 1.0)
            except Exception:
                pass
        lines = [msg] + st.get("log", [])
        for label, a in st.get("arts", {}).items():
            lines.append("%s (%s)" % (label, a["engine"]))
            for j in a["joints"]:
                v = [s[label][j[0]] for s in st["samples"] if j[0] in s.get(label, {})]
                if v:
                    lines.append("  %-24s %-5s range %6.3f..%6.3f  max %7.3f  end %7.3f" % (j[0], j[1], j[2], j[3], max(v), v[-1]))
        open(os.path.join(out_dir, name + "_summary.txt"), "w").write("\n".join(lines) + "\n")
        json.dump(st.get("samples", []), open(os.path.join(out_dir, name + ".json"), "w"))
        les.editor_request_end_play()
        if st.get("tmp_cap"):
            unreal.get_editor_subsystem(unreal.EditorActorSubsystem).destroy_actor(st["tmp_cap"])
        unreal.unregister_slate_post_tick_callback(st["h"])
        st.clear()

    def discover(gw):
        """(articulations, None) once every one is ready on its engine, (None, None) while waiting, (None, error)."""
        arts, missing, waiting = {}, [], []
        managers = list(unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.AMjManager))
        mujoco_running = any(m.is_running() for m in managers)
        for actor in unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.MjArticulation):
            stem = actor.get_class().get_name()[:-2] if actor.get_class().get_name().endswith("_C") else actor.get_class().get_name()
            xml = os.path.join(mjcf_dir, stem, stem + ".xml")
            if not os.path.isfile(xml):
                missing.append(stem)
                continue
            joints = [j for j in _mjcf_joints(xml) if not SKIP.search(j[0]) and ((j[1] == "hinge" and j[3] - j[2] >= math.radians(30)) or (j[1] == "slide" and j[3] - j[2] >= 0.08))]
            c = actor.get_component_by_class(unreal.RammsChaosArticulationComponent)
            if c and c.get_editor_property("simulate_with_chaos"):
                if c.is_built():
                    engine = "Chaos"
                elif c.get_build_error():
                    return None, "%s: the Chaos build failed: %s" % (actor.get_name(), c.get_build_error())
                else:
                    waiting.append(actor.get_name())
                    continue
            else:
                if not managers:
                    return None, "%s is on MuJoCo, but the level has no MuJoCo manager (and no ARammsPhysicsSettings picking an engine)" % actor.get_name()
                if not mujoco_running:
                    waiting.append(actor.get_name())
                    continue
                engine = "MuJoCo"
            handles = {}
            if engine == "MuJoCo":
                for n, _k, _lo, _hi in joints:
                    jc = actor.get_joint(n)
                    handles[n] = (jc, jc.get_attach_parent() if jc else None)
            arts[actor.get_name()] = {"actor": actor, "c": c, "engine": engine, "joints": joints, "h": handles, "prev": {}}
        if waiting:
            return None, None
        if missing:
            st["log"].append("no MJCF in %s for: %s (set SO_MJCF or RAMMS_SIMREADY_MJCF to the folder simready_mjcf.py wrote)" % (mjcf_dir, ", ".join(sorted(set(missing)))))
        if not any(a["joints"] for a in arts.values()):
            return None, "no articulation with a door, drawer or lid to move (MJCF folder %s; set SO_MJCF or RAMMS_SIMREADY_MJCF)" % mjcf_dir
        return arts, None

    def target(t, lo, hi, hinge):
        closed, far = (lo, hi) if abs(lo) <= abs(hi) else (hi, lo)
        back = 5.5 if hinge else 4.0
        s = min(max((t - 1.0) / 1.5, 0.0), 1.0) - min(max((t - back) / 1.5, 0.0), 1.0)
        return closed + 0.8 * s * (far - closed)

    def tick(_dt):
        try:
            now = time.time()
            if now < st["until"]:
                return
            if st["phase"] == "start":
                if opts.get("SO_FRAMES"):
                    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                    if not [a for a in eas.get_all_level_actors() if isinstance(a, unreal.SceneCapture2D)]:
                        # PIE copies the editor level, so a camera placed now is there; removed again at the end
                        st["tmp_cap"] = eas.spawn_actor_from_class(unreal.SceneCapture2D, unreal.Vector(0, 0, 200))
                        st["tmp_cap"].capture_component2d.set_editor_property("capture_every_frame", False)
                les.editor_request_begin_play()
                st.update(phase="find", until=now + 0.5, deadline=now + float(opts.get("SO_READY", 15.0)))
                return
            gw = ues.get_game_world()
            if st["phase"] == "find":
                arts, err = discover(gw) if gw else (None, None)
                if err:
                    finish("ERROR " + err)
                    return
                if arts is None:
                    if now > st["deadline"]:
                        finish("ERROR the articulations' engines were not ready after %.0f s (Chaos not built, or the MuJoCo manager not running)" % float(opts.get("SO_READY", 15.0)))
                    else:
                        st["until"] = now + 0.25
                    return
                st["log"].append("articulations: %s" % {k: (v["engine"], len(v["joints"])) for k, v in arts.items()})
                cap = None
                if opts.get("SO_FRAMES"):
                    cam = opts.get("SO_CAM", ((0.0, -950.0, 280.0), (0.0, -150.0, 60.0)))
                    L = unreal.Vector(*cam[0])
                    scs = unreal.GameplayStatics.get_all_actors_of_class(gw, unreal.SceneCapture2D)
                    sc = scs[0] if scs else None
                    if sc:
                        sc.set_actor_location_and_rotation(L, unreal.MathLibrary.find_look_at_rotation(L, unreal.Vector(*cam[1])), False, False)
                    if sc:
                        cap = sc.capture_component2d
                        rt = unreal.RenderingLibrary.create_render_target2d(gw, 1280, 720, unreal.TextureRenderTargetFormat.RTF_RGBA8, unreal.LinearColor(0, 0, 0, 1), False)
                        cap.set_editor_property("texture_target", rt)
                        cap.set_editor_property("capture_every_frame", True)
                        cap.set_editor_property("always_persist_rendering_state", True)
                        cap.set_editor_property("fov_angle", 60.0)
                        cap.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
                        st["rt"] = rt
                    else:
                        st["log"].append("no SceneCapture2D in the level: no frames")
                unreal.SystemLibrary.execute_console_command(gw, "DisableAllScreenMessages")
                slomo = float(opts.get("SO_SLOMO", 0.25 if cap else 1.0))
                if slomo != 1.0:
                    set_speed(gw, slomo)
                    st["log"].append("slow motion %.2f (game time and MuJoCo's sim speed)" % slomo)
                st.update(arts=arts, cap=cap, phase="run", g0=None, until=time.time() + 1.0)
                return
            t = unreal.GameplayStatics.get_time_seconds(gw)
            if st["g0"] is None:
                st["g0"] = t
            t -= st["g0"]
            sample = {"t": t}
            for label, a in st["arts"].items():
                rec = {}
                for n, kind, lo, hi in a["joints"]:
                    hinge = kind == "hinge"
                    if a["engine"] == "Chaos":
                        q = a["c"].get_joint_position(n)
                        qd = a["c"].get_joint_velocity(n)
                    else:
                        jc, body = a["h"].get(n, (None, None))
                        if jc is None:
                            continue
                        q = unreal.MjJointRuntime.get_position(jc)
                        qd = unreal.MjJointRuntime.get_velocity(jc)
                    kp, kd, most = (30.0, 6.0, 20.0) if hinge else (400.0, 80.0, 80.0)
                    f = max(-most, min(most, kp * (target(t, lo, hi, hinge) - q) - kd * qd))
                    if a["engine"] == "Chaos":
                        a["c"].set_joint_force(n, f)
                    elif body is not None:
                        if not body.is_awake():
                            body.wake()   # MuJoCo's sleeping islands ignore an applied wrench
                        # The joint's axis comes through the Y mirror as a direction, a torque as a pseudovector
                        # (X and Z flip): a torque about the joint is minus the axis. ApplyForce takes N and N*m
                        # and holds them until the next call.
                        axis = unreal.MjJointRuntime.get_world_axis(jc)
                        if hinge:
                            body.apply_force(unreal.Vector(0, 0, 0), axis * -f)
                        else:
                            body.apply_force(axis * f, unreal.Vector(0, 0, 0))
                    rec[n] = q
                sample[label] = rec
            st["samples"].append(sample)
            if st.get("cap") and t >= st["next"]:
                unreal.RenderingLibrary.export_render_target(gw, st["rt"], fdir, "f_%04d" % st["frame"])
                st["frame"] += 1
                st["next"] += 1.0 / fps
            if t >= 8.0:
                finish("done: %d samples, %d frames, %.1f s" % (len(st["samples"]), st["frame"], t))
        except Exception:
            import traceback
            if "h" in st:   # not finished already
                st.setdefault("samples", [])
                finish("ERROR " + traceback.format_exc())

    st["h"] = unreal.register_slate_post_tick_callback(tick)

_simready_open(_SO)
del _simready_open, _SO
