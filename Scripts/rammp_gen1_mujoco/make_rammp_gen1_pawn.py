"""Build the RAMMP Gen1 MuJoCo pawn (powered-front variant) on the imported articulation.

Step 2 of 3 (after import_rammp_gen1_mjcf.py, which deletes this pawn). A child Blueprint of the
articulation gets the RAMMS wiring the chair pawn (BP_RammpGen1_Ramms) has, driving MuJoCo actuators:

  RobotBase          MuJoCo backend + a motor table read from the MJCF's actuators
  DifferentialDrive  the drive wheels, at a speed (velocity control), brakes closed when it stops
  RammpGen1Controller    the lifts, rate-limited at the MJCF's actuator speeds, under the chair's control
                     ids (lift.motor_swing_arm_*, lift.dw_main_plate_*, lift.*_caster_swing_arm), so
                     the chair's input map and gamepad layout drive it unchanged
  ControlSurface, ControlInput (DA_RammsInput_RammpGen1), SimControl (the MJCF's `home` key at spawn,
  which also stands the robot on the ground), cameras on the chassis body, AutoPossessPlayer 0
  CurbController     URammsRammpGen1CurbController: the curb crossing (curb.negotiate / curb.abort / curb.phase),
                     configured from mujoco/rammp_gen1/curb_config_powered_front.json (export_curb_config.py)
  DriveModeSelector  the differential drive and the curb crossing as drive modes, differential first
  LevelAssist        URammsLevelAssistComponent: the chassis (and so the rider: the seat is fixed to it) kept level on
                     sloping ground, in pitch by the three axles' heights and in roll by the two elevators, which
                     leaves the robot on three points; switched by level.assist, off at spawn. Its geometry is the curb
                     controller's (the tables, the bodies, the lifts' speeds, the frame); what is authored here is how
                     far and how fast it may correct (LEVEL_TUNING)
  On the seat body   the chair's seat, rails, arm mount and camera mounts and cameras (meshes, where BP_RammpGen1_Ramms
                     carries them), and RammsSeat: its seated occupant, with the chair's settings copied
  ArmIK, ArmTeleop   the Gen3 arm in the MJCF: URammsMjEndEffectorController (only the arm's joints; home = the MJCF's
                     arm_stow) and URammsMjArmTeleopComponent (arm.* / gripper.* on the control surface), with the
                     settings of the standalone arm (gen3_2f85_fixed) copied

The powered front omni wheels are left to the control surface as raw motors (motor.front_omni_*):
nothing drives them in normal driving, so they freewheel. Everything geometric (ranges, the wheel
radius, the lifts' speeds) is read from the MJCF; what is authored here is intent (top speeds,
gains, which lift answers to which control).

Run inside the editor, with PIE stopped:
    python Scripts/editor_remote_exec.py --file Scripts/rammp_gen1_mujoco/make_rammp_gen1_pawn.py
"""

import importlib
import json
import os
import re
import sys

import unreal

sys.path.insert(0, os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), "Scripts"))
import rammp_seat_pawn as seat_pawn  # noqa: E402  (the seat, occupant and arm; shared with RAMMP Gen2)
importlib.reload(seat_pawn)  # the editor keeps modules between runs
from rammp_seat_pawn import SDL, SDS, add_component, copy_settings, find_component, handles, setp, template  # noqa: E402,F401

MJCF_REL = "mujoco/rammp_gen1/rammp_gen1_powered_front.xml"
CURB_CONFIG_REL = "mujoco/rammp_gen1/curb_config_powered_front.json"
ARTICULATION = "/Game/Robots/RammpGen1/URL/rammp_gen1_powered_front"
PAWN_DIR, PAWN_NAME = "/Game/Robots/RammpGen1", "BP_RammpGen1PoweredFront_Ramms"
DATA_DIR, TABLE_NAME = "/Game/Robots/Data", "DT_RammpGen1PoweredFront_Motors"
INPUT_MAP = "/Game/Input/Ramms/DA_RammsInput_RammpGen1"

# The level assist's tuning (FRammsLevelTuning; every member not named keeps its default). Worked out on a robot of
# this shape and these rates in the plugin's kinematic dry run (RammsLevelGen1ShapeTests.cpp), to be confirmed in the
# simulator:
#   max_correction_deg        pitch 10: in the outdoor stance the frame's clearance stops a nose-up correction at about
#                             8.5 deg (9 with the chassis let up 3 cm) and the rear lift's travel a nose-down one at
#                             about 8 (11.5 with the chassis let up), so 10 binds only nose down with the chassis let
#                             up. Roll 6: the owner's limit for standing on three points (the elevators 6.4 cm apart,
#                             one rear omni wheel about 2.3 cm off the ground).
#   max_correction_rate_...   8 deg/s: about what the elevators give alone. The rear lift is the slow one and does two
#                             thirds of a pitch correction (the ride height is kept), so a pitch correction moves at
#                             under 6 deg/s whatever this says; the drive is slowed where the ground turns faster.
#   integral_max_deg          4: what the loaded elevators sag by, the sprung rear and its unloaded table are trimmed
#                             out by the integral.
#   ride_height_up_cm         3: the chassis may rise that far where it makes a correction fit (it buys nose-down
#                             reach; lowering it buys none, the frame is what stops a nose-up one).
#   min_belly_clearance_cm    4 under the frame's underside.
#   level_reference_deg       (0, 0): on, the stance's own lean on the flat (about 1.4 deg nose up) is taken out too.
LEVEL_TUNING = {
    "level_reference_deg": unreal.Vector2D(0.0, 0.0),
    "max_correction_deg": unreal.Vector2D(10.0, 6.0),
    "max_correction_rate_deg_per_sec": 8.0,
    "leg_rate_fraction": 0.8,
    "feed_forward_gain": 1.0,
    "proportional_gain": 0.3,
    "integral_gain": 2.0,
    "integral_max_deg": 4.0,
    "ride_height_up_cm": 3.0,
    "ride_height_down_cm": 0.0,
    "min_belly_clearance_cm": 4.0,
    "min_speed_scale": 0.25,
    "max_tilt_deg": 5.0,
    "tilt_rate_deg_per_sec": 3.0,
    "tilt_accel_deg_per_sec2": 4.0,
}
LEVEL_MODES = ["differential"]

DRIVE = ("drive_l", "drive_r")
# Wheel speed loops (FRammsVelocityGains) and the drive wheels' brake, as the lift-drive robots'
# 50 N*m wheels have them; the RAMMP Gen1's are placeholders until its motors are known.
DRIVE_GAINS = {"Kp": 15.0, "Ki": 60.0, "MaxIntegralTorque": 25.0}
# The differential drive's own speed loop may wind its integral up to the drive motors' torque less
# this (as the lift-drive robots' wheel loops do), not DRIVE_GAINS' 25 N*m: a turn in place from rest
# asks the wheels for about 1 rad/s, so with the integral at 25 the loop gave at most 15 + 25 = 39 N*m,
# and the robot at rest needs about 50 to break away into a turn -- it stood still under a held turn.
DIFF_INTEGRAL_HEADROOM_NM = 5.0
DRIVE_BRAKE_NM = 100.0
FRONT_OMNI_GAINS = {"Kp": 3.0, "Ki": 10.0, "MaxIntegralTorque": 10.0}
TOP_SPEED_CM_S = 120.0
TOP_TURN_DEG_S = 70.0
# RammpGen1Controller entries: the chair's constraint name (its control id) -> this model's actuator,
# and the MJCF numeric that gives its speed.
ANGULAR = [("motor_swing_arm_l", "elevator_l", "elevator_speed_deg_s"), ("motor_swing_arm_r", "elevator_r", "elevator_speed_deg_s"),
           ("front_caster_swing_arm", "front_arm", "caster_arm_speed_deg_s"), ("rear_caster_swing_arm", "rear_lift", "rear_lift_speed_deg_s")]
LINEAR = [("dw_main_plate_l", "translator_l", "translator_speed_cm_s"), ("dw_main_plate_r", "translator_r", "translator_speed_cm_s")]
EAL = unreal.EditorAssetLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)

if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; re-run this script")


def log(s):
    print("[rammp_gen1_pawn] " + str(s))


# --- the MJCF: actuators, joints, numerics ----------------------------------------------------
xml = open(os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), MJCF_REL), encoding="utf-8").read()
joints = {m.group(1): m.group(0) for m in re.finditer(r'<joint name="([^"]+)"[^>]*>', xml)}
numeric = {m.group(1): float(m.group(2)) for m in re.finditer(r'<numeric name="([^"]+)" data="([-\d.e]+)"/>', xml)}
arm_stow = seat_pawn.arm_stow(xml, MJCF_REL + " (build it without --no-arm)")


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
pawn_path = PAWN_DIR + "/" + PAWN_NAME
if EAL.does_asset_exist(pawn_path):
    bp = EAL.load_asset(pawn_path)
else:
    parent = EAL.load_asset(ARTICULATION)
    if not parent:
        raise RuntimeError("missing %s: run import_rammp_gen1_mjcf.py first" % ARTICULATION)
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
     pid_kp=DRIVE_GAINS["Kp"], pid_ki=DRIVE_GAINS["Ki"], pid_kd=0.0)
drive_torque = next(r["ControlRange"]["Y"] for r in rows if r["Id"] == DRIVE[0])
# pid_integral_max is in rad*s (the error's integral); Ki times it is the integral's torque.
diff_integral_nm = max(DRIVE_GAINS["MaxIntegralTorque"], drive_torque - DIFF_INTEGRAL_HEADROOM_NM)
setp(diff, pid_integral_max=diff_integral_nm / DRIVE_GAINS["Ki"])
log("differential drive: speed loop Kp %g / Ki %g, integral up to %g of the motors' %g N*m" % (
    DRIVE_GAINS["Kp"], DRIVE_GAINS["Ki"], diff_integral_nm, drive_torque))
for side in ("left_motor_params", "right_motor_params"):
    mp = diff.get_editor_property(side)
    mp.set_editor_property("max_torque", drive_torque)
    mp.set_editor_property("max_rpm", 300.0)   # past full speed: the loop, not the curve, sets it
    diff.set_editor_property(side, mp)

lifts = add_component(bp, unreal.RammpGen1ControllerComponent, "RammpGen1Controller")
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
removed = seat_pawn.add_seat_and_arm(bp, arm_stow)
if removed:
    log("removed %d copies of the seat mesh left by earlier runs" % removed)

# The curb crossing, configured from the model (export_curb_config.py), and the drive modes it switches between.
with open(os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), CURB_CONFIG_REL), encoding="utf-8") as fh:
    curb_fields = json.load(fh)["config"]
# The differential drive's VehicleMass: the robot's whole mass (the curb config's mass model, fixed
# plus both drive assemblies), which its torque hold brakes and holds. Left at the 100 kg default, the
# hold braked the 246 kg robot short of its target and pulled it back some 6 cm once it had stopped.
setp(diff, vehicle_mass=curb_fields["fixed_mass_kg"] + 2.0 * curb_fields["drive_assembly_mass_kg"])
log("differential drive: vehicle mass %.1f kg" % diff.get_editor_property("vehicle_mass"))
curb_cfg = unreal.RammsRammpGen1CurbConfig()
for key, value in curb_fields.items():
    if key.endswith("_table"):
        t = unreal.RammsRammpGen1SupportTable()
        t.set_editor_property("angle_rad", value["angle_rad"])
        t.set_editor_property("height_cm", value["height_cm"])
        value = t
    curb_cfg.set_editor_property(key, value)
curb = add_component(bp, unreal.RammsRammpGen1CurbController, "CurbController")
setp(curb, config=curb_cfg, return_mode_id="differential")
setp(add_component(bp, unreal.RammsDriveModeSelector, "DriveModeSelector"), initial_mode_id="differential")

# The level assist, beside the curb controller that describes the robot to it.
level = add_component(bp, unreal.RammsLevelAssistComponent, "LevelAssist")
level_tuning = unreal.RammsLevelTuning()
for key, value in LEVEL_TUNING.items():
    level_tuning.set_editor_property(key, value)
setp(level, tuning=level_tuning, enabled_mode_ids=LEVEL_MODES, enabled_at_start=False,
     attitude_source=unreal.RammsLevelAttitudeSource.EXACT)

add_component(bp, unreal.RammsRobotControlSurfaceComponent, "ControlSurface")
setp(add_component(bp, unreal.RammsMjSimControlComponent, "SimControl"), initial_keyframe="home")
setp(add_component(bp, unreal.RammsRobotCameraComponent, "CameraControl"), orbit_sensitivity=0.25, zoom_sensitivity=1.0,
     zoom_step_fraction=0.08, zoom_interp_speed=10.0, min_arm_length=60.0, max_arm_length=1500.0,
     camera_names=["FollowCamera", "TopCamera", seat_pawn.EYE_CAMERA])

unreal.BlueprintEditorLibrary.compile_blueprint(bp)
cdo = unreal.get_default_object(bp.generated_class())
cdo.set_editor_property("auto_possess_player", unreal.AutoReceiveInput.PLAYER0)
unreal.BlueprintEditorLibrary.compile_blueprint(bp)
if not EAL.save_loaded_asset(bp, False):
    raise RuntimeError("could not save %s" % pawn_path)


def _same(a, b):
    if isinstance(b, unreal.Vector2D):
        return abs(a.x - b.x) < 1e-4 and abs(a.y - b.y) < 1e-4
    return abs(a - b) < 1e-4


# Read back from the saved Blueprint's own component: what a pawn will start with.
_, level_saved = find_component(bp, "LevelAssist")
if not level_saved:
    raise RuntimeError("%s has no LevelAssist after the compile" % pawn_path)
saved_tuning = level_saved.get_editor_property("tuning")
wrong = [k for k, v in LEVEL_TUNING.items() if not _same(saved_tuning.get_editor_property(k), v)]
if [str(m) for m in level_saved.get_editor_property("enabled_mode_ids")] != LEVEL_MODES:
    wrong.append("enabled_mode_ids")
if level_saved.get_editor_property("enabled_at_start"):
    wrong.append("enabled_at_start")
if level_saved.get_editor_property("attitude_source") != unreal.RammsLevelAttitudeSource.EXACT:
    wrong.append("attitude_source")
if wrong:
    raise RuntimeError("the level assist's settings did not take: %s" % ", ".join(wrong))
log("level assist: modes %s, off at spawn; correction up to %g deg pitch / %g deg roll at %g deg/s, integral %g deg, "
    "ride height %g cm up / %g down, %g cm under the frame, speed scale down to %g" % (
        LEVEL_MODES, saved_tuning.max_correction_deg.x, saved_tuning.max_correction_deg.y,
        saved_tuning.max_correction_rate_deg_per_sec, saved_tuning.integral_max_deg, saved_tuning.ride_height_up_cm,
        saved_tuning.ride_height_down_cm, saved_tuning.min_belly_clearance_cm, saved_tuning.min_speed_scale))
log("curb controller: %d / %d / %d table points, rear lift up to %.1f cm" % tuple(
    [len(curb_cfg.get_editor_property(k).get_editor_property("angle_rad")) for k in ("drive_table", "front_table", "rear_table")]
    + [max(curb_fields["rear_table"]["height_cm"])]))
log("saved %s: wheel radius %.1f cm, lifts %s" % (pawn_path, numeric["drive_wheel_radius"] * 100.0,
    ", ".join("%s->%s %g" % (c, m, numeric[s]) for c, m, s in ANGULAR + LINEAR)))
log("seat: %d parts and RammsSeat on the seat body; arm stowed at %s rad" % (len(seat_pawn.SEAT_PARTS), " ".join("%.3f" % q for q in arm_stow)))
