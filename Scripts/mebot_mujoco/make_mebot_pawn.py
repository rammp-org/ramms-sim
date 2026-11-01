"""Build the MeBot MuJoCo pawn (powered-front variant) on the imported articulation.

Step 2 of 3 (after import_mebot_mjcf.py, which deletes this pawn). A child Blueprint of the
articulation gets the RAMMS wiring the chair pawn (BP_Mebot_Ramms) has, driving MuJoCo actuators:

  RobotBase          MuJoCo backend + a motor table read from the MJCF's actuators
  DifferentialDrive  the drive wheels, at a speed (velocity control), brakes closed when it stops
  MebotController    the lifts, rate-limited at the MJCF's actuator speeds, under the chair's control
                     ids (lift.motor_swing_arm_*, lift.dw_main_plate_*, lift.*_caster_swing_arm), so
                     the chair's input map and gamepad layout drive it unchanged
  ControlSurface, ControlInput (DA_RammsInput_Mebot), SimControl (the MJCF's `home` key at spawn,
  which also stands the robot on the ground), cameras on the chassis body, AutoPossessPlayer 0
  CurbController     URammsMebotCurbController: the curb crossing (curb.negotiate / curb.abort / curb.phase),
                     configured from mujoco/mebot/curb_config_powered_front.json (export_curb_config.py)
  DriveModeSelector  the differential drive and the curb crossing as drive modes, differential first
  On the seat body   the chair's seat, rails, arm mount and camera mounts and cameras (meshes, where BP_Mebot_Ramms
                     carries them), and RammsSeat: its seated occupant, with the chair's settings copied
  ArmIK, ArmTeleop   the Gen3 arm in the MJCF: URammsMjEndEffectorController (only the arm's joints; home = the MJCF's
                     arm_stow) and URammsMjArmTeleopComponent (arm.* / gripper.* on the control surface), with the
                     settings of the standalone arm (gen3_2f85_fixed) copied

The powered front omni wheels are left to the control surface as raw motors (motor.front_omni_*):
nothing drives them in normal driving, so they freewheel. Everything geometric (ranges, the wheel
radius, the lifts' speeds) is read from the MJCF; what is authored here is intent (top speeds,
gains, which lift answers to which control).

Run inside the editor, with PIE stopped:
    python Scripts/editor_remote_exec.py --file Scripts/mebot_mujoco/make_mebot_pawn.py
"""

import json
import os
import re

import unreal

MJCF_REL = "mujoco/mebot/mebot_powered_front.xml"
CURB_CONFIG_REL = "mujoco/mebot/curb_config_powered_front.json"
ARTICULATION = "/Game/Robots/MeBot/URL/mebot_powered_front"
PAWN_DIR, PAWN_NAME = "/Game/Robots/MeBot", "BP_MebotPoweredFront_Ramms"
DATA_DIR, TABLE_NAME = "/Game/Robots/Data", "DT_MebotPoweredFront_Motors"
INPUT_MAP = "/Game/Input/Ramms/DA_RammsInput_Mebot"

DRIVE = ("drive_l", "drive_r")
# Wheel speed loops (FRammsVelocityGains) and the drive wheels' brake, as the lift-drive robots'
# 50 N*m wheels have them; the MeBot's are placeholders until its motors are known.
DRIVE_GAINS = {"Kp": 15.0, "Ki": 60.0, "MaxIntegralTorque": 25.0}
DRIVE_BRAKE_NM = 100.0
FRONT_OMNI_GAINS = {"Kp": 3.0, "Ki": 10.0, "MaxIntegralTorque": 10.0}
TOP_SPEED_CM_S = 120.0
TOP_TURN_DEG_S = 70.0
# MebotController entries: the chair's constraint name (its control id) -> this model's actuator,
# and the MJCF numeric that gives its speed.
ANGULAR = [("motor_swing_arm_l", "elevator_l", "elevator_speed_deg_s"), ("motor_swing_arm_r", "elevator_r", "elevator_speed_deg_s"),
           ("front_caster_swing_arm", "front_arm", "caster_arm_speed_deg_s"), ("rear_caster_swing_arm", "rear_lift", "rear_lift_speed_deg_s")]
LINEAR = [("dw_main_plate_l", "translator_l", "translator_speed_cm_s"), ("dw_main_plate_r", "translator_r", "translator_speed_cm_s")]
# The seat's parts on the MJCF's seat body (its frame is the seat_base socket's), where BP_Mebot_Ramms carries them on its
# mesh: (component, static mesh, location cm, rotation (pitch, yaw, roll) deg), from the socket. Decoration: no collision.
SEAT_PARTS = [
    ("Seat", "/RammsAssets/Robots/RAMMP/Seat/rammp_seat", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
    ("rail_l", "/RammsAssets/Robots/RAMMP/Mounts/rammp_mount_rail", (2.0, -26.5, 8.5), (0.0, 0.0, 0.0)),
    ("rail_r", "/RammsAssets/Robots/RAMMP/Mounts/rammp_mount_rail", (2.0, 26.5, 8.5), (0.0, 0.0, 0.0)),
    ("mount_arm", "/RammsAssets/Robots/RAMMP/Mounts/rammp_mount_arm", (16.0, 26.5, 10.5), (0.0, 0.0, 0.0)),
    ("mount_luci_l", "/RammsAssets/Robots/RAMMP/Mounts/rammp_mount_luci", (18.0, -26.5, 7.0), (0.0, 180.0, 0.0)),
    ("mount_luci_r", "/RammsAssets/Robots/RAMMP/Mounts/rammp_mount_luci", (18.0, 26.5, 7.0), (0.0, 0.0, 0.0)),
    ("SM_LUCI_FL", "/RammsAssets/Sensors/LUCI/SM_LUCI_FL_F", (19.0, -21.0, 1.0), (0.0, 180.0, -90.0)),
    ("SM_LUCI_FR", "/RammsAssets/Sensors/LUCI/SM_LUCI_FR_F", (19.0, 21.0, 1.0), (0.0, -180.0, -90.0)),
    ("SM_Gemini_FL", "/RammsAssets/Sensors/Gemini_336L/SM_Orbbec_Gemini_336L", (21.5, -26.5, 8.5), (0.0, 0.0, 90.0)),
    ("SM_Gemini_FR", "/RammsAssets/Sensors/Gemini_336L/SM_Orbbec_Gemini_336L", (21.5, 26.5, 8.5), (0.0, 0.0, -90.0)),
]
# Settings copied from elsewhere, so the two cannot drift apart: the seated occupant from the chair, the arm's IK and
# teleop from the standalone arm.
CHAIR = "/Game/Robots/BP_Mebot_Ramms"
ARM = "/Game/Robots/URL/gen3_2f85_fixed"
SEAT_SETTINGS = ["spawn_on_begin_play", "occupant_mode", "occupant_actor_class", "randomize_appearance", "occupant_mesh",
                 "occupant_offset", "pose_bone_offsets", "align_pelvis", "pelvis_location", "body_adjustments", "left_hand",
                 "right_hand", "left_foot", "right_foot", "passive_sway", "sway_amount", "trunk_control", "voluntary_motion",
                 "voluntary_amount", "look_where_going", "look_at_people"]
IK_SETTINGS = ["end_effector_site_name", "gripper_actuator_suffix", "damping_lambda", "step_gain", "control_orientation",
               "apply_home_on_bind", "track_base_frame", "enabled"]
TELEOP_SETTINGS = ["teleop_enabled", "enable_key_polling", "local_frame", "linear_speed", "angular_speed", "fast_multiplier",
                   "slow_multiplier", "forward_sign", "strafe_sign", "up_sign", "yaw_sign", "pitch_sign", "roll_sign"]

EAL = unreal.EditorAssetLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
SDL = unreal.SubobjectDataBlueprintFunctionLibrary
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)

if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; re-run this script")


def log(s):
    print("[mebot_pawn] " + str(s))


# --- the MJCF: actuators, joints, numerics ----------------------------------------------------
xml = open(os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), MJCF_REL), encoding="utf-8").read()
joints = {m.group(1): m.group(0) for m in re.finditer(r'<joint name="([^"]+)"[^>]*>', xml)}
numeric = {m.group(1): float(m.group(2)) for m in re.finditer(r'<numeric name="([^"]+)" data="([-\d.e]+)"/>', xml)}
arm_stow = re.search(r'<numeric name="arm_stow" data="([^"]+)"/>', xml)
if not arm_stow:
    raise RuntimeError("%s has no arm (numeric arm_stow): build it without --no-arm" % MJCF_REL)
arm_stow = [float(v) for v in arm_stow.group(1).split()]


def joint_attr(joint, attr, default=""):
    m = re.search(r'%s="([^"]+)"' % attr, joints.get(joint, ""))
    return m.group(1) if m else default


rows = []
for m in re.finditer(r'<(motor|position)\s+name="([^"]+)"\s+joint="([^"]+)"[^>]*?ctrlrange="([-\d.e]+)\s+([-\d.e]+)"', xml):
    kind, name, joint, lo, hi = m.group(1), m.group(2), m.group(3), float(m.group(4)), float(m.group(5))
    slide = joint_attr(joint, "type") == "slide"
    if kind == "position" and slide:
        lo, hi = lo * 100.0, hi * 100.0           # the robot base speaks cm for a slide joint
    row = {"Name": name, "Id": name, "ChaosName": "None", "Type": "Torque" if kind == "motor" else "Position",
           "ControlRange": {"X": lo, "Y": hi}, "Direction": 1.0}
    if kind == "motor":
        # A wheel hinge about +Y rolls the robot forward for a positive torque; about -Y, backwards.
        row["Direction"] = -1.0 if joint_attr(joint, "axis").split() == ["0", "-1", "0"] else 1.0
        row["VelocityGains"] = DRIVE_GAINS if name in DRIVE else FRONT_OMNI_GAINS
        if name in DRIVE:
            row["BrakeTorque"] = DRIVE_BRAKE_NM
    rows.append(row)
ids = [r["Id"] for r in rows]
for need in list(DRIVE) + [a for _, a, _ in ANGULAR + LINEAR]:
    if need not in ids:
        raise RuntimeError("the MJCF has no actuator %s (has %s)" % (need, ids))
log("motors from the MJCF: %s" % ", ".join("%s %s [%g, %g]" % (r["Id"], r["Type"], r["ControlRange"]["X"], r["ControlRange"]["Y"]) for r in rows))

table_path = DATA_DIR + "/" + TABLE_NAME
dt = EAL.load_asset(table_path) if EAL.does_asset_exist(table_path) else None
if not dt:
    factory = unreal.DataTableFactory()
    factory.set_editor_property("struct", unreal.RammsMotorSpec.static_struct())
    dt = AT.create_asset(TABLE_NAME, DATA_DIR, unreal.DataTable, factory)
if not unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(dt, json.dumps(rows)):
    raise RuntimeError("could not fill %s" % table_path)
back = {r["Id"]: r for r in json.loads(unreal.DataTableFunctionLibrary.export_data_table_to_json_string(dt))}
for r in rows:
    b = back.get(r["Id"])
    if not b or b["Type"] != r["Type"] or abs(b["ControlRange"]["X"] - r["ControlRange"]["X"]) > 1e-4 or \
            abs(b.get("BrakeTorque", 0.0) - r.get("BrakeTorque", 0.0)) > 1e-4:
        raise RuntimeError("%s row %s did not read back: %s" % (TABLE_NAME, r["Id"], b))
EAL.save_loaded_asset(dt)
log("table %s: %d rows" % (table_path, len(rows)))


# --- the pawn -----------------------------------------------------------------------------------
def handles(bp):
    return SDS.k2_gather_subobject_data_for_blueprint(bp)


def find_component(bp, var_name):
    for h in handles(bp):
        d = SDL.get_data(h)
        o = SDL.get_object(d)
        if o and str(SDL.get_variable_name(d)) == var_name:
            return h, o
    return None, None


def add_component(bp, cls, var_name, parent_var=None):
    h, o = find_component(bp, var_name)
    if o:
        return o
    parent = handles(bp)[0]
    if parent_var:
        ph, _ = find_component(bp, parent_var)
        if ph is None:
            raise RuntimeError("%s has no component %s to put %s under" % (bp.get_name(), parent_var, var_name))
        parent = ph
    new_h, fail = SDS.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=parent, new_class=cls, blueprint_context=bp))
    o = SDL.get_object(SDL.get_data(new_h))
    if not o:
        raise RuntimeError("add_new_subobject(%s) failed: %s" % (var_name, fail))
    SDS.rename_subobject(new_h, unreal.Text(var_name))
    return o


def setp(o, **props):
    for k, v in props.items():
        o.set_editor_property(k, v)


def template(path, cls):
    """The component of class cls in the Blueprint at path (its template: what an instance starts with)."""
    other = EAL.load_asset(path)
    if not other:
        raise RuntimeError("missing %s" % path)
    for h in handles(other):
        o = SDL.get_object_for_blueprint(SDS.k2_find_subobject_data_from_handle(h), other)
        if o and isinstance(o, cls):
            return o
    raise RuntimeError("%s has no %s" % (path, cls.__name__))


def copy_settings(dst, src, names):
    for n in names:
        dst.set_editor_property(n, src.get_editor_property(n))


pawn_path = PAWN_DIR + "/" + PAWN_NAME
if EAL.does_asset_exist(pawn_path):
    bp = EAL.load_asset(pawn_path)
else:
    parent = EAL.load_asset(ARTICULATION)
    if not parent:
        raise RuntimeError("missing %s: run import_mebot_mjcf.py first" % ARTICULATION)
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent.generated_class())
    bp = AT.create_asset(PAWN_NAME, PAWN_DIR, unreal.Blueprint, factory)
    log("created %s on %s" % (pawn_path, parent.generated_class().get_name()))

base = add_component(bp, unreal.RammsRobotBaseComponent, "RobotBase")
setp(base, motor_table=dt, backend=unreal.RammsPhysicsBackend.MUJOCO)

diff = add_component(bp, unreal.RammsDifferentialDriveController, "DifferentialDrive")
setp(diff, left_motor_id=DRIVE[0], right_motor_id=DRIVE[1], wheel_radius=numeric["drive_wheel_radius"] * 100.0,
     track_width=60.8, use_motor_separation_as_track_width=True, skeletal_mesh_component_name="None",
     control_mode=unreal.DriveControlMode.VELOCITY_CONTROL, max_velocity=TOP_SPEED_CM_S, max_turning_speed=TOP_TURN_DEG_S,
     pid_kp=DRIVE_GAINS["Kp"], pid_ki=DRIVE_GAINS["Ki"], pid_kd=0.0, pid_integral_max=DRIVE_GAINS["MaxIntegralTorque"] / DRIVE_GAINS["Ki"])
drive_torque = next(r["ControlRange"]["Y"] for r in rows if r["Id"] == DRIVE[0])
for side in ("left_motor_params", "right_motor_params"):
    mp = diff.get_editor_property(side)
    mp.set_editor_property("max_torque", drive_torque)
    mp.set_editor_property("max_rpm", 300.0)   # past full speed: the loop, not the curve, sets it
    diff.set_editor_property(side, mp)

lifts = add_component(bp, unreal.MebotControllerComponent, "MebotController")
angular = []
for constraint, motor, speed in ANGULAR:
    c = unreal.AngularMotorConfig()
    setp(c, constraint_name=constraint, motor_id=motor, enabled=True, max_speed=numeric[speed])
    angular.append(c)
linear = []
for constraint, motor, speed in LINEAR:
    c = unreal.LinearMotorConfig()
    setp(c, constraint_name=constraint, motor_id=motor, enabled=True, max_speed=numeric[speed])
    linear.append(c)
setp(lifts, angular_motors=angular, linear_motors=linear, use_robot_base=True)

ctrl_in = add_component(bp, unreal.RammsControlInputComponent, "ControlInput")
setp(ctrl_in, input_maps=[EAL.load_asset(INPUT_MAP)])

# Cameras on the simulated chassis body (the actor root does not move with it).
arm = add_component(bp, unreal.SpringArmComponent, "FollowArm", parent_var="chassis")
setp(arm, target_arm_length=320.0, socket_offset=unreal.Vector(0, 0, 60), relative_rotation=unreal.Rotator(roll=0.0, pitch=-18.0, yaw=0.0),
     do_collision_test=False, enable_camera_lag=True, camera_lag_speed=6.0,
     use_pawn_control_rotation=False, inherit_pitch=False, inherit_roll=False, inherit_yaw=True)
add_component(bp, unreal.CameraComponent, "FollowCamera", parent_var="FollowArm")
top = add_component(bp, unreal.SpringArmComponent, "TopArm", parent_var="chassis")
setp(top, target_arm_length=550.0, relative_rotation=unreal.Rotator(roll=0.0, pitch=-89.0, yaw=0.0),
     do_collision_test=False, enable_camera_lag=True, camera_lag_speed=6.0,
     use_pawn_control_rotation=False, inherit_pitch=False, inherit_roll=False, inherit_yaw=False)
setp(add_component(bp, unreal.CameraComponent, "TopCamera", parent_var="TopArm"), auto_activate=False)

# The seat's parts and its occupant on the seat body; the arm's IK and teleop (the arm itself is in the MJCF).
for name, mesh, loc, rot in SEAT_PARTS:
    part = add_component(bp, unreal.StaticMeshComponent, name, parent_var="seat")
    setp(part, static_mesh=EAL.load_asset(mesh), relative_location=unreal.Vector(*loc),
         relative_rotation=unreal.Rotator(pitch=rot[0], yaw=rot[1], roll=rot[2]), mobility=unreal.ComponentMobility.MOVABLE)
    part.set_collision_profile_name("NoCollision")
    part.set_editor_property("generate_overlap_events", False)
occupant = add_component(bp, unreal.RammsSeatComponent, "RammsSeat", parent_var="seat")
copy_settings(occupant, template(CHAIR, unreal.RammsSeatComponent), SEAT_SETTINGS)
# On the seat body's origin, the socket, as on the chair. Set, not left: URLab re-parents a component added under a
# body keeping where it was, so it would sit the body's offset back and down.
setp(occupant, relative_location=unreal.Vector(0.0, 0.0, 0.0), relative_rotation=unreal.Rotator(pitch=0.0, yaw=0.0, roll=0.0))
ik = add_component(bp, unreal.RammsMjEndEffectorController, "ArmIK")
copy_settings(ik, template(ARM, unreal.RammsMjEndEffectorController), IK_SETTINGS)
# Mounted on the chassis, not on a mocap target: no tracking base; the target rides the chassis (track_base_frame).
setp(ik, home_arm_angles=arm_stow, base_target_body_name="", smooth_base_target=False)
copy_settings(add_component(bp, unreal.RammsMjArmTeleopComponent, "ArmTeleop"), template(ARM, unreal.RammsMjArmTeleopComponent), TELEOP_SETTINGS)

# The curb crossing, configured from the model (export_curb_config.py), and the drive modes it switches between.
with open(os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), CURB_CONFIG_REL), encoding="utf-8") as fh:
    curb_fields = json.load(fh)["config"]
curb_cfg = unreal.RammsMebotCurbConfig()
for key, value in curb_fields.items():
    if key.endswith("_table"):
        t = unreal.RammsMebotSupportTable()
        t.set_editor_property("angle_rad", value["angle_rad"])
        t.set_editor_property("height_cm", value["height_cm"])
        value = t
    curb_cfg.set_editor_property(key, value)
curb = add_component(bp, unreal.RammsMebotCurbController, "CurbController")
setp(curb, config=curb_cfg, return_mode_id="differential")
setp(add_component(bp, unreal.RammsDriveModeSelector, "DriveModeSelector"), initial_mode_id="differential")

add_component(bp, unreal.RammsRobotControlSurfaceComponent, "ControlSurface")
setp(add_component(bp, unreal.RammsMjSimControlComponent, "SimControl"), initial_keyframe="home")
setp(add_component(bp, unreal.RammsRobotCameraComponent, "CameraControl"), orbit_sensitivity=0.25, zoom_sensitivity=1.0,
     zoom_step_fraction=0.08, zoom_interp_speed=10.0, min_arm_length=60.0, max_arm_length=1500.0,
     camera_names=["FollowCamera", "TopCamera"])

unreal.BlueprintEditorLibrary.compile_blueprint(bp)
cdo = unreal.get_default_object(bp.generated_class())
cdo.set_editor_property("auto_possess_player", unreal.AutoReceiveInput.PLAYER0)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
if not EAL.save_loaded_asset(bp, False):
    raise RuntimeError("could not save %s" % pawn_path)
log("curb controller: %d / %d / %d table points, rear lift up to %.1f cm" % tuple(
    [len(curb_cfg.get_editor_property(k).get_editor_property("angle_rad")) for k in ("drive_table", "front_table", "rear_table")]
    + [max(curb_fields["rear_table"]["height_cm"])]))
log("saved %s: wheel radius %.1f cm, lifts %s" % (pawn_path, numeric["drive_wheel_radius"] * 100.0,
    ", ".join("%s->%s %g" % (c, m, numeric[s]) for c, m, s in ANGULAR + LINEAR)))
log("seat: %d parts and RammsSeat on the seat body; arm stowed at %s rad" % (len(SEAT_PARTS), " ".join("%.3f" % q for q in arm_stow)))
