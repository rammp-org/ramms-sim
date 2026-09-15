"""RammsAccess (UDP intents, protocol v1) -> the chair's control surface.

unreal._ramms_access_op: 'status' (targets + sink) | 'owner <id>' (log the
surface's current owner of a control) | 'expect_owner <id> <Source>'."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, pawn = cs_common.find_chaos_pawn()
cs = cs_common.surface_of(pawn)
acc = [c for c in pawn.get_components_by_class(unreal.ActorComponent) if c.get_class().get_name() == "RammsAccessInputComponent"]
op = getattr(unreal, "_ramms_access_op", "status").split()
def log(s): unreal.log("[access] " + s)
if not acc:
    raise RuntimeError("[access] no RammsAccessInputComponent on %s" % pawn.get_name())
acc = acc[0]
if op[0] == "status":
    log("component=%s port=%s use_surface=%s estop=%s" % (acc.get_name(), acc.get_editor_property("port"), acc.get_editor_property("use_control_surface"), acc.is_e_stop_latched()))
elif op[0] == "owner":
    log("%s owner=%s value=%.2f" % (op[1], cs.get_axis_owner(op[1]), cs.get_control_value(op[1])))
elif op[0] == "expect_owner":
    owner = str(cs.get_axis_owner(op[1])).split(".")[-1].split(":")[0]
    log("%s owner=%s (expect %s) value=%.2f" % (op[1], owner, op[2], cs.get_control_value(op[1])))
    if owner.upper() != op[2].upper():
        raise RuntimeError("[access] %s owned by %s, expected %s" % (op[1], owner, op[2]))
