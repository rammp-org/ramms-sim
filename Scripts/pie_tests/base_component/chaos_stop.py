import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, p = cs_common.find_chaos_pawn()
cs = cs_common.surface_of(p)
unreal.log("[stop] released drive.forward/turn -> %s ; forward now %.2f" % (cs_common.release(cs, "drive.forward", "drive.turn"), cs.get_control_value("drive.forward")))
