"""Kinova arm + gripper through the chair's control surface.

unreal._ramms_arm_op: 'start' (record the end-effector pose, arm.forward=1),
'check' (release, assert the end effector moved forward), 'gripper' (toggle and
read gripper.closed), 'resync' (arm.resync)."""
import unreal, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
import importlib, cs_common; importlib.reload(cs_common)
w, p = cs_common.find_chaos_pawn()
cs = cs_common.surface_of(p)
kin = p.get_component_by_class(unreal.KinovaGen3ControllerComponent)
op = getattr(unreal, "_ramms_arm_op", "start")
mesh = [c for c in p.get_components_by_class(unreal.SkeletalMeshComponent) if c.get_name() == str(kin.get_editor_property("skeletal_mesh_component_name"))][0]
def ee():
    # Live end-effector bone (world).
    return mesh.get_socket_location(kin.get_editor_property("end_effector_bone_name"))
if op == "start":
    unreal._ramms_arm_ee0 = ee()
    cs_common.set_control(cs, "arm.forward", 1.0)
    unreal.log("[arm] ee0=%s ; arm.forward=1 via surface (mode %s, frame %s)" % (unreal._ramms_arm_ee0, kin.get_editor_property("arm_control_mode"), kin.get_editor_property("target_frame")))
elif op == "check":
    cs_common.release(cs, "arm.forward")
    e0, e1 = unreal._ramms_arm_ee0, ee()
    d = e1 - e0
    moved = d.length()
    unreal.log("[arm] released; end effector moved %.2f cm (delta %s)" % (moved, d))
    if moved < 2.0:
        raise RuntimeError("[arm] end effector did not move through the surface (%.2f cm)" % moved)
elif op == "gripper":
    before = cs.get_control_value("gripper.closed")
    action = "gripper.open" if before >= 0.5 else "gripper.close"
    ok = cs.trigger_control(action, cs_common.SRC)
    if not ok:
        raise RuntimeError("[arm] %s refused" % action)
    # gripper.closed is readback-only: a write must be refused.
    if cs.set_control("gripper.closed", 1.0, cs_common.SRC):
        raise RuntimeError("[arm] gripper.closed accepted a write; it is read-only")
    unreal._ramms_arm_gripper_expect = 0.0 if before >= 0.5 else 1.0  # gripper_check asserts the flip
    unreal.log("[arm] gripper.closed %.0f -> %s (write to gripper.closed refused as expected)" % (before, action))
elif op == "gripper_check":
    now = cs.get_control_value("gripper.closed")
    expected = getattr(unreal, "_ramms_arm_gripper_expect", None)
    unreal.log("[arm] gripper.closed now %.0f (expected %s)" % (now, expected))
    if expected is not None and abs(now - expected) > 0.01:
        raise RuntimeError("[arm] gripper.closed = %.0f, expected %.0f after the action" % (now, expected))
elif op == "resync":
    ok = cs.trigger_control("arm.resync", cs_common.SRC)
    unreal.log("[arm] arm.resync -> %s" % ok)
    if not ok:
        raise RuntimeError("[arm] resync refused")
