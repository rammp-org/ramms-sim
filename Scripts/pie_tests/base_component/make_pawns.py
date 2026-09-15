"""Turn the two MuJoCo lift_drive bases into keyboard-driveable pawns.

For each base a child Blueprint of the imported URLab articulation (which is an
APawn) gets: RobotBase (MuJoCo) + motor table, a differential drive on the centre
wheels, 5-bar controllers (linkage base only), a RammsKeyboardTeleopComponent
with key bindings, a follow camera (spring arm + camera parented to the
`base_link` body so it tracks the simulated body), and AutoPossessPlayer =
Player 0 so a placed instance is driven by the player as soon as PIE starts.

Keys (both pawns): W/S drive, A/D turn, E/Q linkage/leg endpoint up/down (linkage
base), R/F front cranks|hips, T/G rear cranks|hips, Y/H + U/J holonomic cranks.
Camera: N cycles follow / top-down cameras; right-mouse drag
orbits, wheel zooms, Home resets.

Idempotent: re-running updates existing components / tables.
"""
import json
import os
import re
import unreal

PRIVATE = "/RammsPrivateAssets"  # optional plugin: lift-drive CAD-derived content
DATA_DIR = PRIVATE + "/Robots/Data"
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
SDL = unreal.SubobjectDataBlueprintFunctionLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
PROJECT = unreal.SystemLibrary.get_project_directory()


def log(s):
    unreal.log("[make_pawns] " + str(s))


def key(name):
    k = unreal.Key()
    k.set_editor_property("key_name", name)
    return k


def make_table(name, row_struct, rows):
    path = DATA_DIR + "/" + name
    dt = EAL.load_asset(path) if EAL.does_asset_exist(path) else None
    if not dt:
        factory = unreal.DataTableFactory()
        factory.set_editor_property("struct", row_struct)
        dt = AT.create_asset(name, DATA_DIR, unreal.DataTable, factory)
    if not unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(dt, json.dumps(rows)):
        raise RuntimeError("fill failed for %s" % name)
    EAL.save_loaded_asset(dt)
    log("table %s rows=%s" % (name, [str(n) for n in unreal.DataTableFunctionLibrary.get_data_table_row_names(dt)]))
    return dt


def motor_row(name, kind, lo, hi, direction=1.0):
    return {"Name": name, "Id": name, "ChaosName": "None", "Type": kind,
            "ControlRange": {"X": float(lo), "Y": float(hi)}, "Direction": direction}


def motors_from_mjcf(xml_path):
    """One FRammsMotorSpec row per <motor>/<position>/<velocity> actuator."""
    rows = []
    xml = open(xml_path).read()
    axes = {m.group(1): m.group(2) for m in re.finditer(r'<joint name="([^"]+)"[^>]*?axis="([^"]+)"', xml)}
    for m in re.finditer(r'<(motor|position|velocity)\s+name="([^"]+)"\s+joint="([^"]+)"[^>]*?ctrlrange="([-\d.]+)\s+([-\d.]+)"', xml):
        kind, name, joint, lo, hi = m.groups()
        # Wheel hinges about -Y roll backwards for a positive ctrl: flip them.
        direction = -1.0 if (kind == "motor" and axes.get(joint, "").split() == ["0", "-1", "0"]) else 1.0
        rows.append(motor_row(name, kind.capitalize(), lo, hi, direction))
    return rows


# The 14 lift_drive_holonomic actuators (name, MJCF actuator kind, ctrlrange),
# transcribed from the URLab import's prepared MJCF. That file lives under
# Saved/ (ignored), so the rows are the source of truth here; when the MJCF is
# present it is parsed and compared, and any drift is reported.
HOLONOMIC_MOTORS = [
    motor_row("front_left_crank", "Position", -0.49880, 3.19897),
    motor_row("front_right_crank", "Position", -0.49880, 3.19897),
    motor_row("rear_left_crank", "Position", -0.49880, 3.19897),
    motor_row("rear_right_crank", "Position", -0.49880, 3.19897),
    motor_row("right_hip_rear", "Position", -0.10668, 1.73411),
    motor_row("right_hip_front", "Position", -0.07946, 1.66730),
    motor_row("left_hip_front", "Position", -0.10668, 1.73411),
    motor_row("left_hip_rear", "Position", -0.07946, 1.66730),
    motor_row("front_left_omni_wheel", "Motor", -30, 30),
    motor_row("front_right_omni_wheel", "Motor", -30, 30),
    motor_row("rear_left_omni_wheel", "Motor", -30, 30),
    motor_row("rear_right_omni_wheel", "Motor", -30, 30),
    # The centre (drive) wheel hinges are authored about -Y (the linkage base's
    # are +Y): a positive MuJoCo ctrl rolls them backwards, so Direction -1
    # makes "positive = rolls forward" hold, as the diff-drive assumes.
    motor_row("right_center_wheel", "Motor", -30, 30, direction=-1.0),
    motor_row("left_center_wheel", "Motor", -30, 30, direction=-1.0),
]
HOLONOMIC_MJCF = PROJECT + "Saved/URLab/ImportPrep/lift_drive_holonomic/lift_drive_holonomic_ue.xml"


def holonomic_motors():
    rows = HOLONOMIC_MOTORS
    if os.path.exists(HOLONOMIC_MJCF):
        parsed = motors_from_mjcf(HOLONOMIC_MJCF)
        if parsed != rows:
            log("WARNING: %s differs from the HOLONOMIC_MOTORS rows in this script; update the script:\n%s" % (HOLONOMIC_MJCF, parsed))
    return rows


def handles(bp):
    return SDS.k2_gather_subobject_data_for_blueprint(bp)


def find_component(bp, var_name=None, cls_name=None):
    for h in handles(bp):
        d = SDL.get_data(h)
        obj = SDL.get_object(d)
        if not obj:
            continue
        if var_name and str(SDL.get_variable_name(d)) != var_name:
            continue
        if cls_name and obj.get_class().get_name() != cls_name:
            continue
        return h, obj
    return None, None


def add_component(bp, cls, var_name, parent_var=None):
    h, obj = find_component(bp, var_name=var_name)
    if obj:
        return obj
    parent = handles(bp)[0]
    if parent_var:
        ph, _ = find_component(bp, var_name=parent_var)
        if ph is not None:
            parent = ph
    params = unreal.AddNewSubobjectParams(parent_handle=parent, new_class=cls, blueprint_context=bp)
    new_h, fail = SDS.add_new_subobject(params)
    obj = SDL.get_object(SDL.get_data(new_h))
    if not obj:
        raise RuntimeError("add_new_subobject(%s) failed: %s" % (var_name, fail))
    SDS.rename_subobject(new_h, unreal.Text(var_name))
    log("  added %s (%s) under %s" % (var_name, getattr(cls, "__name__", str(cls)), parent_var or "root"))
    return obj


def setp(obj, **props):
    for k, v in props.items():
        obj.set_editor_property(k, v)


# Key budget: URLab's UMjInputHandler owns 1-7, P (pause), R (reset), O (orbit
# cameras), F (launchers) and its simulate widget uses Tab; the arm teleops own
# I/K/J/L/U/O/M/./arrows/[/]/G/R. The base pawns therefore use W/S/A/D, E/Q,
# Y/H, T/B, Z/X, C/V and N (camera), which collide with none of them.
def motor_binding(label, inc, dec, ids, rate=0.6):
    b = unreal.RammsMotorKeyBinding()
    setp(b, label=label, increase_key=key(inc), decrease_key=key(dec), motor_ids=ids, rate_per_second=rate)
    return b


def child_bp(parent_path, child_name):
    path = PRIVATE + "/Robots/" + child_name
    if EAL.does_asset_exist(path):
        return EAL.load_asset(path)
    parent = EAL.load_asset(parent_path)
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent.generated_class())
    bp = AT.create_asset(child_name, PRIVATE + "/Robots", unreal.Blueprint, factory)
    log("created %s (parent %s)" % (path, parent.generated_class().get_name()))
    return bp


def setup_pawn(bp, motor_table, drive_ids, bindings, linkage_rows=None, fivebar_table=None):
    log("=== %s" % bp.get_name())
    base = add_component(bp, unreal.RammsRobotBaseComponent, "RobotBase")
    setp(base, motor_table=motor_table, backend=unreal.RammsPhysicsBackend.MUJOCO)

    dd = add_component(bp, unreal.RammsDifferentialDriveController, "DifferentialDrive")
    setp(dd, left_motor_id=drive_ids[0], right_motor_id=drive_ids[1], wheel_radius=12.7, track_width=54.8,
         skeletal_mesh_component_name="None", control_mode=unreal.DriveControlMode.TORQUE_CONTROL,
         use_motor_separation_as_track_width=True)
    # The defaults are tuned for the Chaos chair; the MuJoCo <motor>s allow +-30 N*m
    # and four undriven wheels + position-servo legs add drag, so give it headroom.
    for side in ("left_motor_params", "right_motor_params"):
        mp = dd.get_editor_property(side)
        mp.set_editor_property("max_torque", 20.0)
        mp.set_editor_property("max_rpm", 150.0)
        dd.set_editor_property(side, mp)

    for row in (linkage_rows or []):
        c = add_component(bp, unreal.Ramms5BarLinkageController, row.split("_")[0].capitalize() + "CenterLinkage")
        setp(c, kinematic_table=fivebar_table, linkage_row=row)

    tele = add_component(bp, unreal.RammsKeyboardTeleopComponent, "KeyboardTeleop")
    lk = unreal.RammsLinkageKeyBinding()
    setp(lk, up_key=key("E"), down_key=key("Q"), rate_cm_per_second=6.0)
    setp(tele, linkage=lk, motor_bindings=bindings, turn_scale=0.8, forward_scale=1.0, log_commands=True)

    # Follow camera on the simulated body (the actor root does not move; base_link does).
    arm = add_component(bp, unreal.SpringArmComponent, "FollowArm", parent_var="base_link")
    setp(arm, target_arm_length=320.0, socket_offset=unreal.Vector(0, 0, 60), relative_rotation=unreal.Rotator(roll=0.0, pitch=-18.0, yaw=0.0),
         do_collision_test=False, enable_camera_lag=True, camera_lag_speed=6.0,
         # The MuJoCo body's frame carries pitch/roll; follow its yaw only so the view stays level.
         use_pawn_control_rotation=False, inherit_pitch=False, inherit_roll=False, inherit_yaw=True)
    add_component(bp, unreal.CameraComponent, "FollowCamera", parent_var="FollowArm")

    # A second, top-down camera (world-aligned: inherits nothing) to switch to (N).
    top = add_component(bp, unreal.SpringArmComponent, "TopArm", parent_var="base_link")
    setp(top, target_arm_length=550.0, relative_rotation=unreal.Rotator(roll=0.0, pitch=-89.0, yaw=0.0),
         do_collision_test=False, enable_camera_lag=True, camera_lag_speed=6.0,
         use_pawn_control_rotation=False, inherit_pitch=False, inherit_roll=False, inherit_yaw=False)
    topcam = add_component(bp, unreal.CameraComponent, "TopCamera", parent_var="TopArm")
    setp(topcam, auto_activate=False)

    # N cycles cameras (FollowCamera, TopCamera);
    # right-mouse drag orbits the active camera's arm, wheel zooms, Home resets.
    # Control surface: every contributor's controls + unclaimed registry motors.
    add_component(bp, unreal.RammsRobotControlSurfaceComponent, "ControlSurface")
    camctl = add_component(bp, unreal.RammsRobotCameraComponent, "CameraControl")
    # Cycle only the authored cameras: URLab's PossessCamera hangs off Bodies[0]
    # (the static worldbody here), so it never follows the robot.
    setp(camctl, orbit_sensitivity=0.25, zoom_sensitivity=1.0, zoom_step_fraction=0.08, zoom_interp_speed=10.0,
         min_arm_length=60.0, max_arm_length=1500.0,
         camera_names=["FollowCamera", "TopCamera"], next_camera_key=key("N"))

    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    cdo = unreal.get_default_object(bp.generated_class())
    cdo.set_editor_property("auto_possess_player", unreal.AutoReceiveInput.PLAYER0)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    EAL.save_loaded_asset(bp)
    log("  auto_possess_player=%s; saved" % cdo.get_editor_property("auto_possess_player"))


# ------------------------------------------------------------- linkage base
dt_link = EAL.load_asset(DATA_DIR + "/DT_LiftDriveLinkage_Motors")
dt_5bar = EAL.load_asset(DATA_DIR + "/DT_LiftDriveLinkage_5Bar")
setup_pawn(child_bp(PRIVATE + "/Robots/URL/lift_drive_linkage", "BP_LiftDriveLinkage_Ramms"), dt_link,
           ("left_center_wheel", "right_center_wheel"),
           [motor_binding("front cranks", "Y", "H", ["left_front_crank", "right_front_crank"]),
            motor_binding("rear cranks", "T", "B", ["left_rear_crank", "right_rear_crank"])],
           linkage_rows=["left_center", "right_center"], fivebar_table=dt_5bar)

# ----------------------------------------------------------- holonomic base
dt_holo = make_table("DT_LiftDriveHolonomic_Motors", unreal.RammsMotorSpec.static_struct(), holonomic_motors())
setup_pawn(child_bp(PRIVATE + "/Robots/URL/lift_drive_holonomic", "BP_LiftDriveHolonomic_Ramms"), dt_holo,
           ("left_center_wheel", "right_center_wheel"),
           [motor_binding("front hips", "Y", "H", ["left_hip_front", "right_hip_front"]),
            motor_binding("rear hips", "T", "B", ["left_hip_rear", "right_hip_rear"]),
            motor_binding("front cranks", "Z", "X", ["front_left_crank", "front_right_crank"]),
            motor_binding("rear cranks", "C", "V", ["rear_left_crank", "rear_right_crank"])])
log("done")
