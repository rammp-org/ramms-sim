"""Exercise the player pawn's RammsRobotControlSurfaceComponent in PIE.

unreal._ramms_cs_op selects: describe | drive | stop | set <id> <value> | release <id>
| trigger <id> | read <id> | json. Local per-tick input writers (keyboard teleop,
access input, the chair pawn's own tick) are paused for the 'drive' step so the
surface is the only thing commanding the drive, as phase 4 will make permanent."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, pawn = cs_common.find_chaos_pawn()
cs = cs_common.surface_of(pawn)
op = getattr(unreal, "_ramms_cs_op", "describe").split()
SRC = unreal.RammsControlSource.SCRIPT
def log(s): unreal.log("[cs] " + s)
if op[0] == "describe":
    surf = cs.describe_control_surface()
    log("%s: %d controls, groups=%s, version=%d" % (surf.get_editor_property("robot_name"), len(surf.get_editor_property("axes")), [str(g) for g in surf.get_editor_property("groups")], cs.get_control_surface_version() if hasattr(cs, "get_control_surface_version") else -1))
    for a in surf.get_editor_property("axes"):
        r = a.get_editor_property("range")
        log("  %-32s %-8s %-10s %-12s [%7.2f, %7.2f] default=%.2f readback=%s paired=%s" % (
            a.get_editor_property("id"), a.get_editor_property("group"), str(a.get_editor_property("kind")).split(".")[-1],
            str(a.get_editor_property("units")).split(".")[-1], r.x, r.y, a.get_editor_property("default_value"), a.get_editor_property("readback"), a.get_editor_property("paired_axis")))
elif op[0] == "drive":
    cs_common.quiet_local_input(pawn)
    log("drive.forward=1.0 -> %s (owner now %s)" % (cs.set_control("drive.forward", 1.0, SRC), cs.get_axis_owner("drive.forward") if hasattr(cs, "get_axis_owner") else "?"))
elif op[0] == "stop":
    log("release drive.forward -> %s ; value now %.2f" % (cs.release_control("drive.forward", SRC), cs.get_control_value("drive.forward")))
elif op[0] == "set":
    ok = cs.set_control(op[1], float(op[2]), SRC)
    log("set %s=%s -> %s" % (op[1], op[2], ok))
    if not ok:
        raise RuntimeError("set %s refused" % op[1])
elif op[0] == "arbitration":
    Src = unreal.RammsControlSource
    r = []
    r.append(("remote set", cs.set_control("drive.turn", 0.5, Src.REMOTE), True))
    r.append(("keyboard while remote holds", cs.set_control("drive.turn", -1.0, Src.KEYBOARD), False))
    r.append(("autonomy overrides remote", cs.set_control("drive.turn", 0.25, Src.AUTONOMY), True))
    r.append(("keyboard release of autonomy-held", cs.release_control("drive.turn", Src.KEYBOARD), False))
    r.append(("autonomy release", cs.release_control("drive.turn", Src.AUTONOMY), True))
    r.append(("unknown id", cs.set_control("nope.axis", 1.0, SRC), False))
    r.append(("clamp 5.0 -> 1.0", cs.set_control("drive.forward", 5.0, SRC) and abs(cs.get_control_value("drive.forward") - 1.0) < 1e-4, True))
    cs.release_control("drive.forward", SRC)
    bad = [n for n, got, want in r if got != want]
    log("arbitration: %s" % ", ".join("%s=%s" % (n, got) for n, got, _ in r))
    if bad:
        raise RuntimeError("[cs] arbitration mismatch: %s" % bad)
elif op[0] == "release":
    log("release %s -> %s" % (op[1], cs.release_control(op[1], SRC)))
elif op[0] == "trigger":
    ok = cs.trigger_control(op[1], SRC)
    log("trigger %s -> %s" % (op[1], ok))
    if not ok:
        raise RuntimeError("trigger %s refused" % op[1])
elif op[0] == "read":
    log("read %s = %.4f" % (op[1], cs.get_control_value(op[1])))
elif op[0] == "registry":
    found = unreal.RammsRobotControlSurfaceComponent.find_control_surfaces(pawn)
    log("registry (RammsUISubsystem): %d surface(s): %s ; contains ours=%s" % (len(found), [f.get_outer().get_name() for f in found], cs in found))
    if cs not in found:
        raise RuntimeError("[cs] the pawn's surface is not registered with RammsUISubsystem")
elif op[0] == "json":
    j = cs.get_control_surface_json()
    log("json %d bytes: %s..." % (len(j), j[:160].replace("\n", " ")))
