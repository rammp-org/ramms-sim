"""Drive and read the RAMMP Gen1 MuJoCo pawn in PIE, one operation per call.

    unreal._ramms_rammp_gen1_op = "<op> [args]"; then run this file in the editor (run_rammp_gen1_checks.sh does both)

  begin                      open Map_RammpGen1Curb_URL and start PIE
  end                        stop PIE
  state                      the chassis's position and attitude, every motor, the lift controls
  set <control id> <value>   a control-surface command (source Remote)
  trigger <control id>       a control-surface action (curb.negotiate, curb.abort)
  curb                       the curb crossing: phase, status, step and crossing height, the chassis
  stats                      the last crossing's measurements (times, stops, attitude, the rider's acceleration, margins)
  status                     curb.status: the panel's "Curb status" words and how much they need the rider
  expect_status <words...>   curb.status begins with those words (e.g. "Faulted:", "Crossing up")
  release <control id>       release it
  pad <key> <value> [...]    gamepad keys at values (URammsInputTestLibrary: through Enhanced Input)
  pad_key <key> <down|up>    a gamepad button (or any key) pressed or let go
  pad_release                every injected key back to rest
  drive_to <x cm> <stick>    one poll: drive forward at the stick until the chassis passes x, then release
  mark                       remember the chassis's pose (for the expect_* ops)
  expect_moved <axis> <lo> <hi>    the chassis moved along its own forward (x) or left (y) axis by lo..hi cm since mark
  expect_yaw <lo> <hi>       the heading changed by lo..hi degrees since mark (positive: clockwise from above)
  expect_motor <id> <lo> <hi>      a motor's value (rad or cm) is in lo..hi
  expect_level <deg>         |pitch| and |roll| are under deg
  expect_control <id> <lo> <hi>    a control-surface value (e.g. gripper.closed) is in lo..hi
  expect_refused <id> <value>      the control surface refuses that command (source Remote): something holds it
  expect_joint <joint> <lo> <hi>   an MJCF joint's position (rad, or m for a slide) is in lo..hi
  mark_body <body>           remember where an MJCF body is (for expect_body_moved)
  expect_body_moved <body> <lo> <hi>  the body moved lo..hi cm (any direction) since mark_body
  mark_lifts                 remember every lift motor's value (for expect_lifts_back)
  expect_lifts_back <deg> <cm>     each lift is within deg (the angles) or cm (the translators) of its mark_lifts value
  hold_stick <forward> [turn] [crossing] [back_in PHASE]
                             hold the rider's stick there every frame (source Script: whichever drive mode has
                             the robot, a curb crossing included), until release_stick or end; `crossing`: let go as
                             the crossing ends; `back_in PHASE`: pulled back from the frame the crossing reaches PHASE
  release_stick              let the stick go
"""
import math

import unreal

MAP = "/Game/Maps/Map_RammpGen1Curb_URL"
SRC = unreal.RammsControlSource.REMOTE
LIFTS = ("elevator_l", "elevator_r", "translator_l", "translator_r", "front_arm", "rear_lift")   # rad, but cm for the translators
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
op = getattr(unreal, "_ramms_rammp_gen1_op", "state").split()


def log(s):
    print("[rammp_gen1] " + s)


def pawn_and_parts():
    w = ues.get_game_world()
    if w is None:
        raise RuntimeError("PIE is not running")
    for p in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Pawn):
        base = p.get_component_by_class(unreal.RammsRobotBaseComponent)
        if base and p.get_class().get_name().startswith("BP_RammpGen1PoweredFront"):
            chassis = next((c for c in p.get_components_by_class(unreal.SceneComponent) if c.get_name() == "chassis"), None)
            if chassis is None:
                raise RuntimeError("%s has no chassis body component" % p.get_name())
            return w, p, base, p.get_component_by_class(unreal.RammsRobotControlSurfaceComponent), chassis
    raise RuntimeError("no RAMMP Gen1 pawn in PIE")


def pose(chassis):
    loc = chassis.get_world_location()
    q = chassis.get_world_rotation()
    rot = q.rotator() if hasattr(q, "rotator") else q
    return loc, rot


def stop_stick():
    """Stop hold_stick's per-frame callback (the stick is not released: release_stick does that)."""
    handle = getattr(unreal, "_ramms_rammp_gen1_stick", None)
    if handle is not None:
        unreal.unregister_slate_post_tick_callback(handle)
        unreal._ramms_rammp_gen1_stick = None


if op[0] == "begin":
    if ues.get_game_world() is not None:
        les.editor_request_end_play()
        raise RuntimeError("PIE was running -- stopped it; run begin again")
    if not les.load_level(MAP):
        raise RuntimeError("could not load " + MAP)
    les.editor_request_begin_play()
    log("PIE requested on " + MAP)
elif op[0] == "end":
    stop_stick()
    if ues.get_game_world() is not None:
        les.editor_request_end_play()
    log("PIE ended")
else:
    w, pawn, base, cs, chassis = pawn_and_parts()
    if op[0] == "state":
        loc, rot = pose(chassis)
        log("t %.1f s  chassis at (%.1f, %.1f, %.1f) cm  yaw %+.1f pitch %+.1f roll %+.1f deg" % (
            unreal.GameplayStatics.get_time_seconds(w), loc.x, loc.y, loc.z, rot.yaw, rot.pitch, rot.roll))
        motors = [str(n) for n in unreal.DataTableFunctionLibrary.get_data_table_row_names(base.get_editor_property("motor_table"))]
        log("motors: " + "  ".join("%s %+.3f" % (m, base.get_motor_value(m)) for m in motors))
        log("lift controls: " + "  ".join("%s %+.2f" % (c, cs.get_control_value(c)) for c in (
            "lift.motor_swing_arm_l", "lift.motor_swing_arm_r", "lift.dw_main_plate_l", "lift.dw_main_plate_r",
            "lift.front_caster_swing_arm", "lift.rear_caster_swing_arm")))
    elif op[0] == "surface":
        ids = [str(a.get_editor_property("id")) for a in cs.describe_control_surface().get_editor_property("axes")]
        log("%d controls: %s" % (len(ids), " ".join(ids)))
    elif op[0] == "set":
        if not cs.set_control(op[1], float(op[2]), SRC):
            raise RuntimeError("set_control(%s, %s) refused" % (op[1], op[2]))
        log("set %s %s" % (op[1], op[2]))
    elif op[0] == "trigger":
        ok = cs.trigger_control(op[1], SRC)
        log("trigger %s -> %s" % (op[1], ok))
        if not ok:
            curb = pawn.get_component_by_class(unreal.RammsRammpGen1CurbController)
            raise RuntimeError("%s refused%s" % (op[1], (": " + curb.get_status()) if curb else ""))
    elif op[0] == "curb":
        curb = pawn.get_component_by_class(unreal.RammsRammpGen1CurbController)
        loc, rot = pose(chassis)
        step, height = curb.get_crossing()
        log("curb %s | %s | step %+.1f cm, crossing height %.1f cm | chassis (%.1f, %.1f, %.1f) pitch %+.1f" % (
            curb.get_phase().name, curb.get_status(), step, height, loc.x, loc.y, loc.z, rot.pitch))
    elif op[0] in ("status", "expect_status"):
        # curb.status, as the panel shows it: its words, and its value the severity (0 info, 1 attention, 2 fault).
        words = cs.get_control_text("curb.status")
        severity = int(round(cs.get_control_value("curb.status")))
        log("status [%s] %s" % (("info", "attention", "fault")[max(0, min(severity, 2))], words))
        want = " ".join(op[1:])
        if op[0] == "expect_status" and not words.startswith(want):
            raise RuntimeError("curb.status is %r, not %r..." % (words, want))
    elif op[0] == "stats":
        s = pawn.get_component_by_class(unreal.RammsRammpGen1CurbController).get_stats()
        frame = ("frame %.1f cm over the edge (%s)" % (s.min_frame_clearance_cm, s.min_clearance_phase.name)
                 if s.frame_measured else "frame never over the edge")
        log("stats: %.1f s (front at the edge -> rear down %.1f s, -> end %.1f s); %d stops, %.1f s stopped; pitch %.1f deg, "
            "roll %.1f, rate %.1f deg/s; rider peak %.2f m/s^2 (fore/aft %.2f, vertical %.2f), RMS %.2f; stability margin "
            "%.1f cm (%s); %s" % (
                s.crossing_seconds, s.edge_to_rear_down_seconds, s.edge_to_end_seconds, s.stops, s.seconds_stopped,
                s.max_abs_pitch_deg, s.max_abs_roll_deg, s.max_pitch_rate_deg_s, s.peak_rider_accel_ms2,
                s.peak_rider_fore_aft_accel_ms2, s.peak_rider_vertical_accel_ms2, s.rms_rider_accel_ms2,
                s.min_stability_margin_cm, s.min_margin_phase.name, frame))
    elif op[0] == "release":
        cs.release_control(op[1], SRC)
        log("released %s" % op[1])
    elif op[0] == "pad_key":
        if op[2] not in ("down", "up"):
            raise RuntimeError("pad_key %s: down or up, not %s" % (op[1], op[2]))
        pc = unreal.GameplayStatics.get_player_controller(w, 0)
        if pc is None:
            raise RuntimeError("no player controller")
        # The name checked first: SetKeyDown's result is whether the controller consumed the key, false for a
        # key Enhanced Input took, so it cannot tell a misspelled name from a delivered press.
        key = unreal.Key()
        key.import_text(op[1])
        if not unreal.InputLibrary.key_is_valid(key):
            raise RuntimeError("pad_key: %s is not a key's name" % op[1])
        unreal.RammsInputTestLibrary.set_key_down(pc, unreal.Name(op[1]), op[2] == "down")
        log("pad_key %s %s" % (op[1], op[2]))
    elif op[0] in ("pad", "pad_release"):
        pc = unreal.GameplayStatics.get_player_controller(w, 0)
        if op[0] == "pad_release":
            unreal.RammsInputTestLibrary.release_all_injected_keys(pc)
            log("pad released")
        else:
            for k, v in zip(op[1::2], op[2::2]):
                if not unreal.RammsInputTestLibrary.set_axis_key(pc, k, float(v)):
                    raise RuntimeError("could not set %s" % k)
            log("pad " + " ".join(op[1:]))
    elif op[0] == "drive_to":
        # One poll: forward at the stick value until the chassis passes x (cm), then release. The caller
        # repeats it; a loop here would hold the game thread and stop the simulation it waits on.
        loc, _ = pose(chassis)
        if loc.x >= float(op[1]):
            cs.release_control("drive.forward", SRC)
            log("arrived at x %.1f" % loc.x)
        else:
            cs.set_control("drive.forward", float(op[2]), SRC)
            log("driving, x %.1f" % loc.x)
    elif op[0] == "mark":
        loc, rot = pose(chassis)
        unreal._ramms_rammp_gen1_mark = (loc.x, loc.y, loc.z, rot.yaw)
        log("mark (%.1f, %.1f, %.1f) yaw %+.1f" % unreal._ramms_rammp_gen1_mark)
    elif op[0] == "expect_moved":
        loc, rot = pose(chassis)
        x0, y0, _, yaw0 = unreal._ramms_rammp_gen1_mark
        dx, dy = loc.x - x0, loc.y - y0
        c, s = math.cos(math.radians(yaw0)), math.sin(math.radians(yaw0))
        along = {"x": dx * c + dy * s, "y": -dx * s + dy * c}[op[1]]
        lo, hi = float(op[2]), float(op[3])
        log("moved %+.1f cm along %s (expect %g..%g) -> %s" % (along, op[1], lo, hi, "ok" if lo <= along <= hi else "FAIL"))
        if not lo <= along <= hi:
            raise RuntimeError("moved %.1f cm along %s, outside %g..%g" % (along, op[1], lo, hi))
    elif op[0] == "expect_yaw":
        _, rot = pose(chassis)
        d = (rot.yaw - unreal._ramms_rammp_gen1_mark[3] + 180.0) % 360.0 - 180.0
        lo, hi = float(op[1]), float(op[2])
        log("yaw changed %+.1f deg (expect %g..%g) -> %s" % (d, lo, hi, "ok" if lo <= d <= hi else "FAIL"))
        if not lo <= d <= hi:
            raise RuntimeError("yaw changed %.1f deg, outside %g..%g" % (d, lo, hi))
    elif op[0] == "expect_motor":
        v = base.get_motor_value(op[1])
        lo, hi = float(op[2]), float(op[3])
        log("%s = %+.3f (expect %g..%g) -> %s" % (op[1], v, lo, hi, "ok" if lo <= v <= hi else "FAIL"))
        if not lo <= v <= hi:
            raise RuntimeError("%s = %.3f, outside %g..%g" % (op[1], v, lo, hi))
    elif op[0] == "expect_level":
        _, rot = pose(chassis)
        lim = float(op[1])
        ok = abs(rot.pitch) < lim and abs(rot.roll) < lim
        log("pitch %+.1f roll %+.1f (expect under %g) -> %s" % (rot.pitch, rot.roll, lim, "ok" if ok else "FAIL"))
        if not ok:
            raise RuntimeError("pitch %.1f / roll %.1f over %g deg" % (rot.pitch, rot.roll, lim))
    elif op[0] == "expect_control":
        v = cs.get_control_value(op[1])
        lo, hi = float(op[2]), float(op[3])
        log("%s = %+.3f (expect %g..%g) -> %s" % (op[1], v, lo, hi, "ok" if lo <= v <= hi else "FAIL"))
        if not lo <= v <= hi:
            raise RuntimeError("%s = %.3f, outside %g..%g" % (op[1], v, lo, hi))
    elif op[0] == "expect_refused":
        ok = cs.set_control(op[1], float(op[2]), SRC)
        log("set %s %s -> %s (expect refused) -> %s" % (op[1], op[2], "accepted" if ok else "refused", "FAIL" if ok else "ok"))
        if ok:
            cs.release_control(op[1], SRC)
            raise RuntimeError("%s %s was accepted, expected refused" % (op[1], op[2]))
    elif op[0] == "expect_joint":
        joint = next((c for c in pawn.get_components_by_class(unreal.ActorComponent) if c.get_name() == op[1]), None)
        if joint is None:
            raise RuntimeError("%s has no joint %s" % (pawn.get_name(), op[1]))
        v = unreal.MjJointRuntime.get_position(joint)
        lo, hi = float(op[2]), float(op[3])
        log("%s = %+.3f (expect %g..%g) -> %s" % (op[1], v, lo, hi, "ok" if lo <= v <= hi else "FAIL"))
        if not lo <= v <= hi:
            raise RuntimeError("%s = %.3f, outside %g..%g" % (op[1], v, lo, hi))
    elif op[0] in ("mark_body", "expect_body_moved"):
        body = next((c for c in pawn.get_components_by_class(unreal.SceneComponent) if c.get_name() == op[1]), None)
        if body is None:
            raise RuntimeError("%s has no body %s" % (pawn.get_name(), op[1]))
        p = body.get_world_location()
        if op[0] == "mark_body":
            unreal._ramms_rammp_gen1_body_mark = (op[1], (p.x, p.y, p.z))
            log("mark %s at (%.1f, %.1f, %.1f)" % (op[1], p.x, p.y, p.z))
        else:
            name, p0 = getattr(unreal, "_ramms_rammp_gen1_body_mark", (None, (0.0, 0.0, 0.0)))
            if name != op[1]:
                raise RuntimeError("no mark on %s (mark_body it first)" % op[1])
            dist = math.sqrt((p.x - p0[0]) ** 2 + (p.y - p0[1]) ** 2 + (p.z - p0[2]) ** 2)
            lo, hi = float(op[2]), float(op[3])
            log("%s moved %.1f cm (%+.1f, %+.1f, %+.1f) (expect %g..%g) -> %s" % (op[1], dist, p.x - p0[0], p.y - p0[1], p.z - p0[2], lo, hi,
                                                                       "ok" if lo <= dist <= hi else "FAIL"))
            if not lo <= dist <= hi:
                raise RuntimeError("%s moved %.1f cm, outside %g..%g" % (op[1], dist, lo, hi))
    elif op[0] == "hold_stick":
        # Every frame, as a rider holds a stick: through the surface to whichever drive mode has the robot (a curb
        # crossing takes drive.* while it runs), at the lowest source, so a person's keyboard or gamepad takes over.
        # With `crossing`, only through the curb crossing under way (or about to begin): let go the frame it ends, as a
        # rider would, so the drive mode it hands back to does not drive on. With `back_in PHASE`, pulled back (-0.6)
        # from the frame the crossing reaches that phase (curb.get_phase().name): a rider cancelling at once.
        stop_stick()
        words = op[2:]
        back_in = words[words.index("back_in") + 1] if "back_in" in words and words.index("back_in") + 1 < len(words) else None
        numbers = [w for w in words if w not in ("crossing", "back_in", back_in)]
        fwd, turn = float(op[1]), float(numbers[0]) if numbers else 0.0
        curb = pawn.get_component_by_class(unreal.RammsRammpGen1CurbController)
        ended = (unreal.RammsRammpGen1CurbPhase.IDLE, unreal.RammsRammpGen1CurbPhase.DONE, unreal.RammsRammpGen1CurbPhase.ABORTED)

        # Everything it reads bound here: remote execution reuses one namespace, so later ops reassign its globals.
        def hold(dt, cs=cs, curb=curb, fwd=fwd, turn=turn, state={"seen": False, "back": False}, ended=ended,
                 through_crossing="crossing" in words, back_in=back_in, script=unreal.RammsControlSource.SCRIPT,
                 ues=ues, stop=stop_stick):
            try:
                if ues.get_game_world() is None:
                    stop()
                    return
                phase = curb.get_phase()
                if through_crossing:
                    running = phase not in ended
                    state["seen"] |= running
                    if state["seen"] and not running:
                        stop()
                        for i in ("drive.forward", "drive.turn"):
                            cs.release_control(i, script)
                        return
                state["back"] |= back_in is not None and phase.name == back_in
                cs.set_control("drive.forward", -0.6 if state["back"] else fwd, script)
                cs.set_control("drive.turn", 0.0 if state["back"] else turn, script)
            except Exception:  # noqa: BLE001  (PIE ended under it)
                stop()
        unreal._ramms_rammp_gen1_stick = unreal.register_slate_post_tick_callback(hold)
        log("holding the stick at forward %+.2f, turn %+.2f%s%s" % (fwd, turn, " through the crossing" if "crossing" in words else "",
                                                                     ", back from %s" % back_in if back_in else ""))
    elif op[0] == "release_stick":
        stop_stick()
        for i in ("drive.forward", "drive.turn"):
            cs.release_control(i, unreal.RammsControlSource.SCRIPT)
        log("stick let go")
    elif op[0] == "mark_lifts":
        unreal._ramms_rammp_gen1_lifts = {m: base.get_motor_value(m) for m in LIFTS}
        log("mark lifts: " + "  ".join("%s %+.3f" % kv for kv in unreal._ramms_rammp_gen1_lifts.items()))
    elif op[0] == "expect_lifts_back":
        marked = getattr(unreal, "_ramms_rammp_gen1_lifts", None)
        if marked is None:
            raise RuntimeError("no lifts marked (mark_lifts first)")
        off = {}
        for m in LIFTS:
            d = base.get_motor_value(m) - marked[m]
            off[m] = d if m.startswith("translator") else math.degrees(d)   # cm, deg
        bad = [m for m in LIFTS if abs(off[m]) > float(op[2] if m.startswith("translator") else op[1])]
        log("lifts back: " + "  ".join("%s %+.2f %s" % (m, off[m], "cm" if m.startswith("translator") else "deg") for m in LIFTS)
            + " (expect within %s deg, %s cm) -> %s" % (op[1], op[2], "FAIL" if bad else "ok"))
        if bad:
            raise RuntimeError("not back where they were: %s" % ", ".join(bad))
    else:
        raise RuntimeError("unknown op %s" % op[0])
