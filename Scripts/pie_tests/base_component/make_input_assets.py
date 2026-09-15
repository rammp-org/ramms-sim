"""Author the Enhanced Input assets that drive the robots' control surfaces.

Creates (idempotently, overwriting mappings / bindings so this file stays the
source of truth):

  /Game/Input/Ramms/Actions/IA_Ramms_*     Input actions (Bool / Axis1D / 2D / 3D)
  /Game/Input/Ramms/IMC_RammsRobot         One mapping context: every key, once
  /Game/Input/Ramms/DA_RammsInput_<robot>  URammsControlInputMap per robot family:
                                           action -> control Id (wildcards ok)

Keys (see IMC below): W/S A/D drive; E/Q linkage height; Y/H T/B Z/X C/V four
motor groups; N / Home camera; I/K J/L U/O arm move, arrows + M/. arm rotate,
R resync; [ ] G gripper; Backspace / P / Slash sim reset / pause / step; 1-7
sim debug toggles. Mouse orbit / wheel zoom stay on the camera component.
"""
import unreal

EAL = unreal.EditorAssetLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
ROOT = "/Game/Input/Ramms"
ACTIONS = ROOT + "/Actions"
VT = unreal.InputActionValueType
Mode = unreal.RammsControlInputMode


def log(s):
    unreal.log("[make_input] " + s)


def ensure_dir(path):
    if not EAL.does_directory_exist(path):
        EAL.make_directory(path)


def key(name):
    k = unreal.Key()
    k.set_editor_property("key_name", name)
    return k


def action(name, value_type):
    path = ACTIONS + "/" + name
    if EAL.does_asset_exist(path):
        ia = EAL.load_asset(path)
    else:
        ia = AT.create_asset(name, ACTIONS, unreal.InputAction, unreal.InputAction_Factory())
        log("created %s" % path)
    ia.set_editor_property("value_type", value_type)
    EAL.save_loaded_asset(ia)
    return ia


def modifier(imc, cls, **props):
    m = unreal.new_object(cls, outer=imc)
    for k, v in props.items():
        m.set_editor_property(k, v)
    return m


def mapping(imc, ia, key_name, negate=False, swizzle=None):
    m = unreal.EnhancedActionKeyMapping()
    m.set_editor_property("action", ia)
    m.set_editor_property("key", key(key_name))
    mods = []
    if negate:
        mods.append(modifier(imc, unreal.InputModifierNegate))
    if swizzle:
        mods.append(modifier(imc, unreal.InputModifierSwizzleAxis, order=swizzle))
    m.set_editor_property("modifiers", mods)
    return m


def binding(ia, mode, cid, cid_y="", cid_z="", scale=1.0, rate=1.0):
    b = unreal.RammsControlInputBinding()
    b.set_editor_property("action", ia)
    b.set_editor_property("mode", mode)
    b.set_editor_property("control_id", cid)
    b.set_editor_property("control_id_y", cid_y)
    b.set_editor_property("control_id_z", cid_z)
    b.set_editor_property("scale", scale)
    b.set_editor_property("rate_per_second", rate)
    return b


def input_map(name, imc, bindings, priority=1):
    path = ROOT + "/" + name
    if EAL.does_asset_exist(path):
        da = EAL.load_asset(path)
    else:
        f = unreal.DataAssetFactory()
        f.set_editor_property("data_asset_class", unreal.RammsControlInputMap)
        da = AT.create_asset(name, ROOT, unreal.RammsControlInputMap, f)
        log("created %s" % path)
    da.set_editor_property("mapping_context", imc)
    da.set_editor_property("priority", priority)
    da.set_editor_property("bindings", bindings)
    EAL.save_loaded_asset(da)
    log("  %s: %d bindings" % (name, len(bindings)))
    return da


ensure_dir(ROOT)
ensure_dir(ACTIONS)

# ---------------------------------------------------------------- actions
IA = {
    "Drive": action("IA_Ramms_Drive", VT.AXIS2D),               # X = turn, Y = forward
    "LinkageHeight": action("IA_Ramms_LinkageHeight", VT.AXIS1D),
    "MotorGroupA": action("IA_Ramms_MotorGroupA", VT.AXIS1D),
    "MotorGroupB": action("IA_Ramms_MotorGroupB", VT.AXIS1D),
    "MotorGroupC": action("IA_Ramms_MotorGroupC", VT.AXIS1D),
    "MotorGroupD": action("IA_Ramms_MotorGroupD", VT.AXIS1D),
    "CameraNext": action("IA_Ramms_CameraNext", VT.BOOLEAN),
    "CameraReset": action("IA_Ramms_CameraReset", VT.BOOLEAN),
    "ArmMove": action("IA_Ramms_ArmMove", VT.AXIS3D),           # X fwd, Y strafe, Z up
    "ArmRotate": action("IA_Ramms_ArmRotate", VT.AXIS3D),       # X yaw, Y pitch, Z roll
    "ArmResync": action("IA_Ramms_ArmResync", VT.BOOLEAN),
    "GripperOpen": action("IA_Ramms_GripperOpen", VT.BOOLEAN),
    "GripperClose": action("IA_Ramms_GripperClose", VT.BOOLEAN),
    "GripperToggle": action("IA_Ramms_GripperToggle", VT.BOOLEAN),
    "SimReset": action("IA_Ramms_SimReset", VT.BOOLEAN),
    "SimPause": action("IA_Ramms_SimPause", VT.BOOLEAN),
    "SimStep": action("IA_Ramms_SimStep", VT.BOOLEAN),
}
for i in range(1, 8):
    IA["SimDebug%d" % i] = action("IA_Ramms_SimDebug%d" % i, VT.BOOLEAN)

# ------------------------------------------------------- mapping context
imc_path = ROOT + "/IMC_RammsRobot"
if EAL.does_asset_exist(imc_path):
    imc = EAL.load_asset(imc_path)
else:
    imc = AT.create_asset("IMC_RammsRobot", ROOT, unreal.InputMappingContext, unreal.InputMappingContext_Factory())
    log("created %s" % imc_path)
Sw = unreal.InputAxisSwizzle
maps = [
    mapping(imc, IA["Drive"], "W", swizzle=Sw.YXZ),
    mapping(imc, IA["Drive"], "S", negate=True, swizzle=Sw.YXZ),
    mapping(imc, IA["Drive"], "D"),
    mapping(imc, IA["Drive"], "A", negate=True),
    mapping(imc, IA["Drive"], "Gamepad_LeftY", swizzle=Sw.YXZ),
    mapping(imc, IA["Drive"], "Gamepad_LeftX"),
    mapping(imc, IA["LinkageHeight"], "E"),
    mapping(imc, IA["LinkageHeight"], "Q", negate=True),
    mapping(imc, IA["MotorGroupA"], "Y"),
    mapping(imc, IA["MotorGroupA"], "H", negate=True),
    mapping(imc, IA["MotorGroupB"], "T"),
    mapping(imc, IA["MotorGroupB"], "B", negate=True),
    mapping(imc, IA["MotorGroupC"], "Z"),
    mapping(imc, IA["MotorGroupC"], "X", negate=True),
    mapping(imc, IA["MotorGroupD"], "C"),
    mapping(imc, IA["MotorGroupD"], "V", negate=True),
    mapping(imc, IA["CameraNext"], "N"),
    mapping(imc, IA["CameraNext"], "Gamepad_FaceButton_Top"),
    mapping(imc, IA["CameraReset"], "Home"),
    mapping(imc, IA["ArmMove"], "I"),
    mapping(imc, IA["ArmMove"], "K", negate=True),
    mapping(imc, IA["ArmMove"], "L", swizzle=Sw.YXZ),
    mapping(imc, IA["ArmMove"], "J", negate=True, swizzle=Sw.YXZ),
    mapping(imc, IA["ArmMove"], "U", swizzle=Sw.ZYX),
    mapping(imc, IA["ArmMove"], "O", negate=True, swizzle=Sw.ZYX),
    mapping(imc, IA["ArmRotate"], "Right"),
    mapping(imc, IA["ArmRotate"], "Left", negate=True),
    mapping(imc, IA["ArmRotate"], "Up", swizzle=Sw.YXZ),
    mapping(imc, IA["ArmRotate"], "Down", negate=True, swizzle=Sw.YXZ),
    mapping(imc, IA["ArmRotate"], "Period", swizzle=Sw.ZYX),
    mapping(imc, IA["ArmRotate"], "M", negate=True, swizzle=Sw.ZYX),
    mapping(imc, IA["ArmResync"], "R"),
    mapping(imc, IA["GripperOpen"], "LeftBracket"),
    mapping(imc, IA["GripperClose"], "RightBracket"),
    mapping(imc, IA["GripperToggle"], "G"),
    mapping(imc, IA["SimReset"], "BackSpace"),
    mapping(imc, IA["SimPause"], "P"),
    mapping(imc, IA["SimStep"], "Slash"),
]
for i, k in enumerate(["One", "Two", "Three", "Four", "Five", "Six", "Seven"], 1):
    maps.append(mapping(imc, IA["SimDebug%d" % i], k))
imc.set_editor_property("mappings", maps)
EAL.save_loaded_asset(imc)
log("IMC_RammsRobot: %d key mappings" % len(maps))

# ------------------------------------------------------------ input maps
A, X, R = Mode.AXIS, Mode.ACTION, Mode.INCREMENT_RATE
common = [
    binding(IA["Drive"], A, "drive.turn", cid_y="drive.forward"),
    binding(IA["CameraNext"], X, "camera.next"),
    binding(IA["CameraReset"], X, "camera.reset"),
    binding(IA["ArmMove"], A, "arm.forward", cid_y="arm.strafe", cid_z="arm.up"),
    binding(IA["ArmRotate"], A, "arm.yaw", cid_y="arm.pitch", cid_z="arm.roll"),
    binding(IA["ArmResync"], X, "arm.resync"),
    binding(IA["GripperOpen"], X, "gripper.open"),
    binding(IA["GripperClose"], X, "gripper.close"),
    binding(IA["GripperToggle"], X, "gripper.toggle"),
]
sim = [
    binding(IA["SimReset"], X, "sim.reset"),
    binding(IA["SimPause"], X, "sim.pause"),
    binding(IA["SimStep"], X, "sim.step"),
] + [binding(IA["SimDebug%d" % i], X, "sim.debug.%s" % n) for i, n in enumerate(
    ["contacts", "visuals", "collisions", "joints", "quick_convert_collisions", "shader_mode", "tendons"], 1)]

# lift_drive_linkage: E/Q both centre legs; Y/H front cranks, T/B rear cranks (rad/s)
input_map("DA_RammsInput_LiftDriveLinkage", imc, common + sim + [
    binding(IA["LinkageHeight"], R, "linkage.*.height", rate=6.0),
    binding(IA["MotorGroupA"], R, "motor.*_front_crank", rate=0.6),
    binding(IA["MotorGroupB"], R, "motor.*_rear_crank", rate=0.6),
])
# lift_drive_holonomic: Y/H front hips, T/B rear hips, Z/X front cranks, C/V rear cranks
input_map("DA_RammsInput_LiftDriveHolonomic", imc, common + sim + [
    binding(IA["MotorGroupA"], R, "motor.*_hip_front", rate=0.6),
    binding(IA["MotorGroupB"], R, "motor.*_hip_rear", rate=0.6),
    binding(IA["MotorGroupC"], R, "motor.front_*_crank", rate=0.6),
    binding(IA["MotorGroupD"], R, "motor.rear_*_crank", rate=0.6),
])
# MeBot chair (Chaos): Y/H drive elevators (deg/s), T/B translators (cm/s), Z/X caster arms
input_map("DA_RammsInput_Mebot", imc, common + [
    binding(IA["MotorGroupA"], R, "lift.motor_swing_arm_*", rate=30.0),
    binding(IA["MotorGroupB"], R, "lift.dw_main_plate_*", rate=10.0),
    binding(IA["MotorGroupC"], R, "lift.*_caster_swing_arm", rate=30.0),
])
log("done")
