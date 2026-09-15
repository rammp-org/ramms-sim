"""Command every 5-bar linkage's endpoint height through the control surface.

unreal._ramms_lift_z: a height in cm, or 'lo' / 'hi' = 1 cm inside the
bottom / top of the range the linkage reports (derived from its IK + motor
ControlRanges). Fails if the surface refuses the target."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, mj_find, cs_common; importlib.reload(mj_find); importlib.reload(cs_common)
w, a = mj_find.find()
cs = cs_common.surface_of(a)
cs_common.release(cs, "drive.forward", "drive.turn")
want = getattr(unreal, "_ramms_lift_z", "lo")
for c in a.get_components_by_class(unreal.Ramms5BarLinkageController):
    cid = "linkage.%s.height" % c.get_name()
    ax = cs_common.axis(cs, cid)
    r = ax.get_editor_property("range")
    z = {"lo": r.x + 1.0, "hi": r.y - 1.0}.get(want) if isinstance(want, str) else float(want)
    if z is None:
        z = float(want)
    ok = cs.set_control(cid, z, cs_common.SRC)
    unreal.log("[lift] %s range=[%.2f, %.2f] -> %s=%.2f applied=%s ; endpoint now=%s" % (
        c.get_name(), r.x, r.y, cid, z, ok, c.get_current_endpoint()))
    if not ok:
        raise RuntimeError("[lift] %s refused %.2f" % (cid, z))
