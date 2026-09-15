import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, mj_find, cs_common; importlib.reload(mj_find); importlib.reload(cs_common)
w, a = mj_find.find()
cs_common.quiet_local_input(a)
cs = cs_common.surface_of(a)
cs_common.set_control(cs, "drive.forward", 1.0)
unreal.log("[drv] drive.forward=1 via control surface (owner=%s, value=%.2f)" % (cs.get_axis_owner("drive.forward"), cs.get_control_value("drive.forward")))
