"""The RAMMP seat on a MuJoCo pawn: its parts, its seated occupant, and the Gen3 arm's IK and teleop, on the MJCF's seat
body. Shared by RAMMP Gen1 (rammp_gen1_mujoco/make_rammp_gen1_pawn.py) and RAMMP Gen2's lift-drive pawn; the MJCF side,
the seat body and the arm, is mujoco/rammp_seat_arm.py. Runs in the editor.
"""
import re

import unreal

# The seat's parts on the MJCF's seat body (its frame is the seat socket's), where BP_RammpGen1_Ramms carries them on its
# mesh: (component, static mesh, location cm, rotation (pitch, yaw, roll) deg), from the socket. Decoration: no collision.
SEAT_PARTS = [
    ("SeatMesh", "/RammsAssets/Robots/RAMMP/Seat/rammp_seat", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
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
CHAIR = "/Game/Robots/BP_RammpGen1_Ramms"
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
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
SDL = unreal.SubobjectDataBlueprintFunctionLibrary


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
    """The Blueprint's component var_name, added (of class cls, under parent_var or the root) if it has none."""
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
    # Unreal's names ignore case: a name another component has (the seat body's "seat" for "Seat") is refused, and
    # the component, left with its default name, would be added again on every run.
    if not SDS.rename_subobject(new_h, unreal.Text(var_name)):
        raise RuntimeError("could not name the new %s %s: is the name taken?" % (cls.__name__, var_name))
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


def arm_stow(xml, what):
    """The arm's stowed joint angles (rad, joint_1..7), from the MJCF text's numeric arm_stow."""
    m = re.search(r'<numeric name="arm_stow" data="([^"]+)"/>', xml)
    if not m:
        raise RuntimeError("%s has no arm (numeric arm_stow)" % what)
    return [float(v) for v in m.group(1).split()]


def add_seat_and_arm(bp, stow, seat_body="seat"):
    """The seat's parts and its occupant on the MJCF's seat body, and the arm's IK (home: stow) and teleop (the arm
    itself is in the MJCF). Returns how many copies of the seat's mesh left by earlier runs it removed."""
    # Earlier runs named the seat's mesh "Seat", which the seat body's "seat" refused: each left a copy under its default
    # name (StaticMesh, StaticMesh1, ...). Those go first.
    stray = []
    for h in handles(bp):
        d = SDL.get_data(h)
        o = SDL.get_object(d)
        if (isinstance(o, unreal.StaticMeshComponent) and str(SDL.get_variable_name(d)).startswith("StaticMesh")
                and o.get_editor_property("static_mesh") and o.get_editor_property("static_mesh").get_path_name().split(".")[0] == SEAT_PARTS[0][1]):
            stray.append(h)
    if stray:
        SDS.delete_subobjects(handles(bp)[0], stray, bp)
    for name, mesh, loc, rot in SEAT_PARTS:
        part = add_component(bp, unreal.StaticMeshComponent, name, parent_var=seat_body)
        setp(part, static_mesh=EAL.load_asset(mesh), relative_location=unreal.Vector(*loc),
             relative_rotation=unreal.Rotator(pitch=rot[0], yaw=rot[1], roll=rot[2]), mobility=unreal.ComponentMobility.MOVABLE)
        part.set_collision_profile_name("NoCollision")
        part.set_editor_property("generate_overlap_events", False)
    occupant = add_component(bp, unreal.RammsSeatComponent, "RammsSeat", parent_var=seat_body)
    copy_settings(occupant, template(CHAIR, unreal.RammsSeatComponent), SEAT_SETTINGS)
    # On the seat body's origin, the socket, as on the chair. Set, not left: URLab re-parents a component added under a
    # body keeping where it was, so it would sit the body's offset back and down.
    setp(occupant, relative_location=unreal.Vector(0.0, 0.0, 0.0), relative_rotation=unreal.Rotator(pitch=0.0, yaw=0.0, roll=0.0))
    ik = add_component(bp, unreal.RammsMjEndEffectorController, "ArmIK")
    copy_settings(ik, template(ARM, unreal.RammsMjEndEffectorController), IK_SETTINGS)
    # Mounted on the robot, not on a mocap target: no tracking base; the target rides the robot (track_base_frame). The
    # chain stops at the arm's own base: the default, "base_link", is matched by suffix and RAMMP Gen2's chassis is
    # base_link too, so the IK drove the seat mechanism's joints under the arm.
    setp(ik, home_arm_angles=stow, base_target_body_name="", smooth_base_target=False, arm_root_body_name="arm_base_link")
    copy_settings(add_component(bp, unreal.RammsMjArmTeleopComponent, "ArmTeleop"), template(ARM, unreal.RammsMjArmTeleopComponent), TELEOP_SETTINGS)
    return len(stray)
