"""Turn check for the Chaos chair: drive.turn = +1 must turn RIGHT (UE yaw increases).

Set unreal._ramms_turn_op to 'start' (record yaw, command the turn), 'check'
(compare yaw, release the control)."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, p = cs_common.find_chaos_pawn()
cs = cs_common.surface_of(p)
op = getattr(unreal, "_ramms_turn_op", "check")
yaw = p.get_actor_rotation().yaw
if op == "start":
    unreal._ramms_turn_yaw0 = yaw
    cs_common.set_control(cs, "drive.turn", 1.0)
    unreal.log("[turn] start yaw=%.1f, drive.turn=+1 via surface (turn right)" % yaw)
else:
    y0 = getattr(unreal, "_ramms_turn_yaw0", 0.0)
    d = unreal.MathLibrary.normalize_axis(yaw - y0)
    cs_common.release(cs, "drive.turn")
    verdict = "turned RIGHT (ok)" if d > 5.0 else ("turned LEFT (WRONG)" if d < -5.0 else "no turn (FAIL)")
    unreal.log("[turn] check yaw=%.1f delta=%+.1f deg -> %s" % (yaw, d, verdict))
    if "ok" not in verdict:
        raise RuntimeError("[turn] " + verdict)
