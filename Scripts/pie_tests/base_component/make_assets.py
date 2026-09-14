"""Create the motor / 5-bar data tables and wire the base-component architecture
onto the MeBot blueprints. Idempotent: re-running updates existing assets.

- /Game/Robots/Data/DT_Mebot_ChaosMotors      (FRammsMotorSpec)  -> BP_Mebot_Ramms
- /Game/Robots/Data/DT_LiftDriveLinkage_Motors (FRammsMotorSpec)  -> BP_LiftDriveLinkage_Ramms
- /Game/Robots/Data/DT_LiftDriveLinkage_5Bar   (FRamms5BarLinkageSpec)
- /Game/Robots/BP_LiftDriveLinkage_Ramms : child of lift_drive_linkage (AMjArticulation)
  with RobotBase(MuJoCo) + differential drive + left/right centre 5-bar controllers.
"""
import json
import unreal

DATA_DIR = "/Game/Robots/Data"
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
SDL = unreal.SubobjectDataBlueprintFunctionLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary


def log(s):
    unreal.log("[make_assets] " + str(s))


def ensure_dir(path):
    if not EAL.does_directory_exist(path):
        EAL.make_directory(path)


def make_table(name, row_struct, rows):
    """Create (or refill) a DataTable from a list of row dicts (each with 'Name')."""
    path = DATA_DIR + "/" + name
    dt = EAL.load_asset(path) if EAL.does_asset_exist(path) else None
    if not dt:
        factory = unreal.DataTableFactory()
        factory.set_editor_property("struct", row_struct)
        dt = AT.create_asset(name, DATA_DIR, unreal.DataTable, factory)
        log("created table %s" % path)
    else:
        log("refilling table %s" % path)
    ok = unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(dt, json.dumps(rows))
    if not ok:
        raise RuntimeError("fill_data_table_from_json_string failed for %s" % name)
    names = [str(n) for n in unreal.DataTableFunctionLibrary.get_data_table_row_names(dt)]
    log("  rows: %s" % names)
    EAL.save_loaded_asset(dt)
    return dt


def motor(name, mtype, chaos=None, rng=(0.0, 0.0), direction=1.0):
    return {"Name": name, "Id": name, "ChaosName": chaos or "None", "Type": mtype,
            "ControlRange": {"X": rng[0], "Y": rng[1]}, "Direction": direction}


def bp_handles(bp):
    return SDS.k2_gather_subobject_data_for_blueprint(bp)


def find_component(bp, cls_name=None, var_name=None):
    for h in bp_handles(bp):
        d = SDL.get_data(h)
        obj = SDL.get_object(d)
        if not obj:
            continue
        if cls_name and obj.get_class().get_name() != cls_name:
            continue
        if var_name and str(SDL.get_variable_name(d)) != var_name:
            continue
        return h, obj
    return None, None


def add_component(bp, cls, var_name):
    """Add an actor component to a Blueprint's SCS (or return the existing one)."""
    h, obj = find_component(bp, var_name=var_name)
    if obj:
        log("  component %s already present (%s)" % (var_name, obj.get_class().get_name()))
        return obj
    root = bp_handles(bp)[0]
    params = unreal.AddNewSubobjectParams(parent_handle=root, new_class=cls, blueprint_context=bp)
    new_h, fail = SDS.add_new_subobject(params)
    obj = SDL.get_object(SDL.get_data(new_h))
    if not obj:
        raise RuntimeError("add_new_subobject(%s) failed: %s" % (var_name, fail))
    SDS.rename_subobject(new_h, unreal.Text(var_name))
    log("  added component %s (%s)" % (var_name, obj.get_class().get_name()))
    return obj


def setp(obj, **props):
    for k, v in props.items():
        obj.set_editor_property(k, v)


def finish_bp(bp):
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    EAL.save_loaded_asset(bp)
    log("  compiled + saved %s" % bp.get_name())


ensure_dir(DATA_DIR)

# ---------------------------------------------------------------- Chaos chair
# The chair's diff-drive maps LEFT -> bone drive_wheel_r and RIGHT -> drive_wheel_l
# (that is how the existing BP is authored); preserve it via ChaosName.
#
# The chair's other actuators are physics-asset constraint drives (the same
# constraints UMebotControllerComponent lists): Position motors whose ChaosName
# is the constraint. Angular ones are commanded/read in radians, linear ones in
# cm; the Chaos backend infers the driven axis from the constraint's free DOF.
# Ranges are left to the constraint limits (ControlRange unset).
dt_chaos = make_table("DT_Mebot_ChaosMotors", unreal.RammsMotorSpec.static_struct(), [
    motor("left_motor", "Torque", chaos="drive_wheel_r"),
    motor("right_motor", "Torque", chaos="drive_wheel_l"),
    # drive-motor elevators: swing arms that raise/lower each drive wheel
    motor("left_elevator", "Position", chaos="motor_swing_arm_l"),
    motor("right_elevator", "Position", chaos="motor_swing_arm_r"),
    # drive-motor translators: linear actuators sliding each drive plate fore/aft
    motor("left_translator", "Position", chaos="dw_main_plate_l"),
    motor("right_translator", "Position", chaos="dw_main_plate_r"),
    # caster arm elevators
    motor("front_caster_elevator", "Position", chaos="front_caster_swing_arm"),
    motor("rear_caster_elevator", "Position", chaos="rear_caster_swing_arm"),
])

bp = EAL.load_asset("/Game/Robots/BP_Mebot_Ramms")
log("=== BP_Mebot_Ramms")
base = add_component(bp, unreal.RammsRobotBaseComponent, "RobotBase")
# Explicit Chaos: Auto's "an articulation attached under me" heuristic is not
# right for a Chaos base that carries a MuJoCo arm child actor (BP_Mebot_Mujoco).
setp(base, motor_table=dt_chaos, backend=unreal.RammsPhysicsBackend.CHAOS,
     chaos_skeletal_mesh_component_name="VehicleMesh")
_, dd = find_component(bp, cls_name="RammsDifferentialDriveController")
setp(dd, left_motor_id="left_motor", right_motor_id="right_motor")
log("  diff-drive: left_motor_id=%s right_motor_id=%s bones=%s/%s" % (
    dd.get_editor_property("left_motor_id"), dd.get_editor_property("right_motor_id"),
    dd.get_editor_property("left_wheel_bone_name"), dd.get_editor_property("right_wheel_bone_name")))
finish_bp(bp)

# ------------------------------------------------------- MuJoCo lift_drive base
# Actuator names + ranges from lift_drive_linkage_ue.xml.
CRANK = (-0.02867, 2.30752)
REAR_CRANK = (0.0, 2.24614)
HIP_WIDE = (-0.76370, 0.81275)
HIP_FWD = (0.0, 1.71740)
dt_mj = make_table("DT_LiftDriveLinkage_Motors", unreal.RammsMotorSpec.static_struct(), [
    motor("left_front_crank", "Position", rng=CRANK),
    motor("left_rear_crank", "Position", rng=REAR_CRANK),
    motor("left_center_hip_a", "Position", rng=HIP_WIDE),
    motor("left_center_hip_b", "Position", rng=HIP_FWD),
    motor("right_front_crank", "Position", rng=CRANK),
    motor("right_rear_crank", "Position", rng=REAR_CRANK),
    motor("right_center_hip_a", "Position", rng=HIP_FWD),
    motor("right_center_hip_b", "Position", rng=HIP_WIDE),
    motor("left_front_wheel", "Torque", rng=(-30, 30)),
    motor("left_rear_wheel", "Torque", rng=(-30, 30)),
    motor("left_center_wheel", "Torque", rng=(-30, 30)),
    motor("right_front_wheel", "Torque", rng=(-30, 30)),
    motor("right_rear_wheel", "Torque", rng=(-30, 30)),
    motor("right_center_wheel", "Torque", rng=(-30, 30)),
])

# 5-bar geometry (cm, local x-z), measured from the MJCF. The right leg mirrors
# the left: its "a" pivot is the rear one and both joint axes flip.
# Joint sign: a MuJoCo hinge about +Y rotates +X toward -Z, so the link angle
# atan2(z, x) is ZeroDir - q => AngleSign -1 for axis "0 1 0", +1 for "0 -1 0".
# (left hip_a / right hip_b are +Y; left hip_b / right hip_a are -Y.)
def fivebar(name, ma, mb, pa, pb, zda, sa, eua, zdb, sb, eub, flip):
    return {"Name": name, "ProximalMotorA": ma, "ProximalMotorB": mb,
            "PivotA": {"X": pa[0], "Y": pa[1]}, "PivotB": {"X": pb[0], "Y": pb[1]},
            "ProximalLengthA": 16.0, "DistalLengthA": 22.5, "ProximalLengthB": 16.0, "DistalLengthB": 22.5,
            "ZeroDirA": zda, "AngleSignA": sa, "ZeroDirB": zdb, "AngleSignB": sb,
            "bElbowUpA": eua, "bElbowUpB": eub, "bFlipEndpointSide": flip}

dt_5bar = make_table("DT_LiftDriveLinkage_5Bar", unreal.Ramms5BarLinkageSpec.static_struct(), [
    fivebar("left_center", "left_center_hip_a", "left_center_hip_b",
            (6.5, 20.993), (-6.5, 20.992), -0.2397, -1.0, True, -2.9019, 1.0, False, False),
    fivebar("right_center", "right_center_hip_a", "right_center_hip_b",
            (-6.5, 20.993), (6.5, 20.993), -2.9019, 1.0, False, -0.2397, -1.0, True, True),
])

parent_bp = EAL.load_asset("/Game/Robots/URL/lift_drive_linkage")
child_path = "/Game/Robots/BP_LiftDriveLinkage_Ramms"
if EAL.does_asset_exist(child_path):
    child = EAL.load_asset(child_path)
    log("=== %s exists" % child_path)
else:
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent_bp.generated_class())
    child = AT.create_asset("BP_LiftDriveLinkage_Ramms", "/Game/Robots", unreal.Blueprint, factory)
    log("=== created %s (parent %s)" % (child_path, parent_bp.generated_class().get_name()))

base = add_component(child, unreal.RammsRobotBaseComponent, "RobotBase")
setp(base, motor_table=dt_mj, backend=unreal.RammsPhysicsBackend.MUJOCO)

dd = add_component(child, unreal.RammsDifferentialDriveController, "DifferentialDrive")
setp(dd, left_motor_id="left_center_wheel", right_motor_id="right_center_wheel",
     wheel_radius=12.7, track_width=54.8, skeletal_mesh_component_name="None",
     control_mode=unreal.DriveControlMode.TORQUE_CONTROL)

for side in ("left", "right"):
    fb = add_component(child, unreal.Ramms5BarLinkageController, "%sCenterLinkage" % side.capitalize())
    setp(fb, kinematic_table=dt_5bar, linkage_row="%s_center" % side)
finish_bp(child)
log("done")
