"""Drive and read the MeBot MuJoCo pawn in PIE, one operation per call.

    unreal._ramms_mebot_op = "<op> [args]"; then run this file in the editor (run_mebot_checks.sh does both)

  begin                      open Map_MebotCurb_URL and start PIE
  end                        stop PIE
  state                      the chassis's position and attitude, every motor, the lift controls
  set <control id> <value>   a control-surface command (source Remote)
  trigger <control id>       a control-surface action (curb.negotiate, curb.abort)
  curb                       the curb crossing: phase, status, step and crossing height, the chassis
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
"""
import math

import unreal

MAP = "/Game/Maps/Map_MebotCurb_URL"
SRC = unreal.RammsControlSource.REMOTE
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
op = getattr(unreal, "_ramms_mebot_op", "state").split()


def log(s):
    print("[mebot] " + s)


def pawn_and_parts():
    w = ues.get_game_world()
    if w is None:
        raise RuntimeError("PIE is not running")
    for p in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Pawn):
        base = p.get_component_by_class(unreal.RammsRobotBaseComponent)
        if base and p.get_class().get_name().startswith("BP_MebotPoweredFront"):
            chassis = next((c for c in p.get_components_by_class(unreal.SceneComponent) if c.get_name() == "chassis"), None)
            if chassis is None:
                raise RuntimeError("%s has no chassis body component" % p.get_name())
            return w, p, base, p.get_component_by_class(unreal.RammsRobotControlSurfaceComponent), chassis
    raise RuntimeError("no MeBot pawn in PIE")


def pose(chassis):
    loc = chassis.get_world_location()
    q = chassis.get_world_rotation()
    rot = q.rotator() if hasattr(q, "rotator") else q
    return loc, rot


if op[0] == "begin":
    if ues.get_game_world() is not None:
        les.editor_request_end_play()
        raise RuntimeError("PIE was running -- stopped it; run begin again")
    if not les.load_level(MAP):
        raise RuntimeError("could not load " + MAP)
    les.editor_request_begin_play()
    log("PIE requested on " + MAP)
elif op[0] == "end":
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
            curb = pawn.get_component_by_class(unreal.RammsMebotCurbController)
            raise RuntimeError("%s refused%s" % (op[1], (": " + curb.get_status()) if curb else ""))
    elif op[0] == "curb":
        curb = pawn.get_component_by_class(unreal.RammsMebotCurbController)
        loc, rot = pose(chassis)
        step, height = curb.get_crossing()
        log("curb %s | %s | step %+.1f cm, crossing height %.1f cm | chassis (%.1f, %.1f, %.1f) pitch %+.1f" % (
            curb.get_phase().name, curb.get_status(), step, height, loc.x, loc.y, loc.z, rot.pitch))
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
        unreal._ramms_mebot_mark = (loc.x, loc.y, loc.z, rot.yaw)
        log("mark (%.1f, %.1f, %.1f) yaw %+.1f" % unreal._ramms_mebot_mark)
    elif op[0] == "expect_moved":
        loc, rot = pose(chassis)
        x0, y0, _, yaw0 = unreal._ramms_mebot_mark
        dx, dy = loc.x - x0, loc.y - y0
        c, s = math.cos(math.radians(yaw0)), math.sin(math.radians(yaw0))
        along = {"x": dx * c + dy * s, "y": -dx * s + dy * c}[op[1]]
        lo, hi = float(op[2]), float(op[3])
        log("moved %+.1f cm along %s (expect %g..%g) -> %s" % (along, op[1], lo, hi, "ok" if lo <= along <= hi else "FAIL"))
        if not lo <= along <= hi:
            raise RuntimeError("moved %.1f cm along %s, outside %g..%g" % (along, op[1], lo, hi))
    elif op[0] == "expect_yaw":
        _, rot = pose(chassis)
        d = (rot.yaw - unreal._ramms_mebot_mark[3] + 180.0) % 360.0 - 180.0
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
    else:
        raise RuntimeError("unknown op %s" % op[0])
