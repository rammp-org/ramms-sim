"""Exercise the pawn's RammsControlInputComponent (Enhanced Input -> surface).

unreal._ramms_ci_op: 'status' | 'inject <IA name> <x> <y> <z> [hold_s]' |
'expect <control id> <min> <max>' (fails when the surface value is outside)."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, pawn = cs_common.find_chaos_pawn()
cs = cs_common.surface_of(pawn)
ci = pawn.get_component_by_class(unreal.RammsControlInputComponent)
op = getattr(unreal, "_ramms_ci_op", "status").split()
def log(s): unreal.log("[ci] " + s)
if not ci:
    raise RuntimeError("no RammsControlInputComponent on %s" % pawn.get_name())
if op[0] == "status":
    maps = [m.get_name() for m in ci.get_editor_property("input_maps")]
    log("bound=%s maps=%s actions=%s" % (ci.is_bound(), maps, [str(a) for a in ci.get_bound_action_names()]))
    if not ci.is_bound():
        raise RuntimeError("[ci] input component is not bound to the player's Enhanced Input component")
elif op[0] == "inject":
    hold = float(op[5]) if len(op) > 5 else 0.0
    ok = ci.inject_action_by_name(op[1], unreal.Vector(float(op[2]), float(op[3]), float(op[4])), hold)
    log("inject %s (%s, %s, %s) hold %.1fs -> %s" % (op[1], op[2], op[3], op[4], hold, ok))
    if not ok:
        raise RuntimeError("[ci] %s is not bound by any input map" % op[1])
elif op[0] == "camera":
    cam = pawn.get_component_by_class(unreal.RammsRobotCameraComponent)
    active = cam.get_active_camera() if cam else None
    log("active camera: %s" % (active.get_name() if active else None))
    unreal._ramms_ci_cam_prev = getattr(unreal, "_ramms_ci_cam", None)
    unreal._ramms_ci_cam = active.get_name() if active else None
elif op[0] == "camera_changed":
    if unreal._ramms_ci_cam == unreal._ramms_ci_cam_prev:
        raise RuntimeError("[ci] camera did not change (%s)" % unreal._ramms_ci_cam)
    log("camera changed %s -> %s" % (unreal._ramms_ci_cam_prev, unreal._ramms_ci_cam))
elif op[0] == "urlab":
    m = [x for x in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Actor) if x.get_class().get_name() == "AMjManager"]
    if not m:
        log("no AMjManager in this world")
    else:
        m = m[0]
        ih = m.get_editor_property("input_handler")
        ticking = ih.is_component_tick_enabled() if ih else None
        log("URLab InputHandler ticking=%s" % ticking)
        if ticking:
            raise RuntimeError("[ci] URLab hotkeys are still enabled")
elif op[0] == "expect":
    v = cs.get_control_value(op[1])
    lo, hi = float(op[2]), float(op[3])
    log("%s = %.3f (expect %.2f..%.2f) -> %s" % (op[1], v, lo, hi, "ok" if lo <= v <= hi else "FAIL"))
    if not (lo <= v <= hi):
        raise RuntimeError("[ci] %s = %.3f outside %.2f..%.2f" % (op[1], v, lo, hi))
