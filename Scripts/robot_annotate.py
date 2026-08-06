"""robot_annotate.py -- stamp articulation attributes onto the RAMMP robot
blends (arm + gripper: cad/kinova/gen3_6dof.blend; base + full robot:
cad/mebot/mebot_3_assembled.blend). Run INSIDE Blender:

    blender <file>.blend --python robot_annotate.py -- --save

SCHEMA (custom properties, editable in Object Properties > Custom
Properties; same family as the dojo furniture pipeline):

  dojo_joint            revolute | continuous | prismatic | fixed
                        (joint between this object and its PARENT body)
  dojo_axis             [x,y,z] joint axis, ASSET-ROOT local frame
  dojo_pivot            [x,y,z] root-local; DEFAULT = this object's origin
                        (only set to override)
  dojo_limits           [lo,hi] degrees (revolute) / meters (prismatic);
                        omitted for continuous/fixed
  dojo_mass             kg. 0.0 = FILL ME (importer falls back to
                        auto-mass from collision volume)
  dojo_motor_torque     N*m (revolute) / N (prismatic). 0 = passive joint
  dojo_motor_velocity   deg/s (revolute) / m/s (prismatic). 0 = unlimited
  dojo_spring_stiffness N*m/rad (revolute) / N/m (prismatic). 0 = none
  dojo_spring_damping   N*m*s/rad / N*s/m
  dojo_spring_rest      deg / m -- spring equilibrium position
  dojo_friction         joint dry friction, N*m / N
  dojo_mimic            name of the DRIVING joint object ("" = none);
                        this joint follows it kinematically
  dojo_mimic_ratio      follower angle = ratio * driver angle
  dojo_connect          on a loop-closure joint EMPTY: name of the OTHER
                        body; the joint links the empty's parent body to it

Props are only written when MISSING (setdefault): your hand-tuned values
survive re-runs. Values below marked GUESS need verification; masses at
0.0 must be filled in.
"""
import bpy
import re
import sys

# ---------------------------------------------------------------------------
# joint tables, keyed by base object name (numeric .NNN suffixes stripped so
# the duplicated arm/gripper copies inside mebot_3_assembled match too)
# ---------------------------------------------------------------------------

# --- Kinova Gen3 6DOF arm (chain base_link -> link_0..link_6) --------------
# masses ~ Kortex URDF; torque/speed ~ Gen3 actuator spec sheet.
# Axes alternate yaw(Z)/pitch(Y) in the upright modeling pose.
ARM = {
    #            joint         axis        limits(deg)       mass  tq(Nm) vel(deg/s)
    "link_0": ("continuous", (0, 0, 1), None,             1.377, 32.0, 50.0),   # J1
    "link_1": ("revolute",   (0, 1, 0), (-128.9, 128.9),  1.262, 32.0, 50.0),   # J2
    "link_2": ("revolute",   (0, 1, 0), (-147.8, 147.8),  0.930, 32.0, 50.0),   # J3
    "link_3": ("continuous", (0, 0, 1), None,             0.678, 13.0, 57.0),   # J4
    "link_4": ("revolute",   (0, 1, 0), (-120.3, 120.3),  0.678, 13.0, 57.0),   # J5
    "link_5": ("continuous", (0, 0, 1), None,             0.500, 13.0, 57.0),   # J6
    "link_6": ("fixed",      None,      None,             0.364, 0.0,  0.0),    # interface/vision
}
ARM_ROOT_MASS = 1.697          # base_link

# --- 2F-85-style four-bar gripper (roots 'base'; sides _l/_r) --------------
# Drive knuckle is link_0_<s>; everything else follows it (mimic). Limits
# are the drive range; signs per side are GUESSES -- flip if a finger opens
# the wrong way. Loop closure: EMPTY link_2_3_<s> joins link_2 <-> link_3.
def gripper_side(s, sign):
    return {
        "link_0_%s" % s: ("revolute", (0, 0, 1), (0.0, 46.0) if sign > 0 else (-46.0, 0.0),
                          0.070, 5.0, 150.0, "", 1.0),
        "link_1_%s" % s: ("revolute", (0, 0, 1), None, 0.030, 0.0, 0.0,
                          "link_0_%s" % s, 1.0),
        "link_2_%s" % s: ("revolute", (0, 0, 1), None, 0.030, 0.0, 0.0,
                          "link_0_%s" % s, 1.0),
        "link_3_%s" % s: ("revolute", (0, 0, 1), None, 0.030, 0.0, 0.0,
                          "link_0_%s" % s, -1.0),
        "end_%s" % s:    ("fixed",    None,      None, 0.020, 0.0, 0.0, "", 1.0),
        "pad_%s" % s:    ("fixed",    None,      None, 0.010, 0.0, 0.0, "", 1.0),
    }
GRIPPER = {}
GRIPPER.update(gripper_side("l", +1))
GRIPPER.update(gripper_side("r", -1))
GRIPPER_ROOT_MASS = 0.640      # 'base'
GRIPPER_CLOSURE = {"link_2_3_l": "link_2_l", "link_2_3_r": "link_2_r"}

# --- RAMMP base (root 'chassis') -------------------------------------------
# ALL GUESSES on axes/limits; masses/springs 0.0 = FILL ME. Suspension
# pivots assumed about lateral Y; drive motors continuous about Y; caster
# swivels continuous about Z. Dampeners stamped as prismatic springs.
BASE = {
    # name                              joint         axis       limits       mass  tq    vel   stiff  damp
    "front_caster_arm":              ("revolute",   (0, 1, 0), (-20, 20),   0.0,  0.0,  0.0,  0.0,  0.0),
    "front_caster_linkage":          ("revolute",   (0, 1, 0), (-20, 20),   0.0,  0.0,  0.0,  0.0,  0.0),
    "front_caster_wheel_left":       ("continuous", (0, 0, 1), None,        0.0,  0.0,  0.0,  0.0,  0.0),
    "front_caster_wheel_right":      ("continuous", (0, 0, 1), None,        0.0,  0.0,  0.0,  0.0,  0.0),
    "rear_caster_arm":               ("revolute",   (0, 1, 0), (-20, 20),   0.0,  0.0,  0.0,  0.0,  0.0),
    "rear_caster_linkage":           ("revolute",   (0, 1, 0), (-20, 20),   0.0,  0.0,  0.0,  0.0,  0.0),
    "rear_left_caster":              ("continuous", (0, 0, 1), None,        0.0,  0.0,  0.0,  0.0,  0.0),
    "rear_right_caster":             ("continuous", (0, 0, 1), None,        0.0,  0.0,  0.0,  0.0,  0.0),
    "rear_caster_dampener":          ("prismatic",  (0, 0, 1), (-0.03, 0.03), 0.0, 0.0, 0.0,  0.0,  0.0),
    "left_motor_horizontal_assembly":  ("fixed",    None,      None,        0.0,  0.0,  0.0,  0.0,  0.0),
    "right_motor_horizontal_assembly": ("fixed",    None,      None,        0.0,  0.0,  0.0,  0.0,  0.0),
    "left_rail_bar":                 ("fixed",      None,      None,        0.0,  0.0,  0.0,  0.0,  0.0),
    "right_rail_bar":                ("fixed",      None,      None,        0.0,  0.0,  0.0,  0.0,  0.0),
    "left_motor_swing_arm":          ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
    "right_motor_swing_arm":         ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
    "left_motor":                    ("continuous", (0, 1, 0), None,        0.0, 20.0, 720.0, 0.0,  0.0),
    "right_motor":                   ("continuous", (0, 1, 0), None,        0.0, 20.0, 720.0, 0.0,  0.0),
    "left_motor_elevator":           ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
    "right_motor_elevator":          ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
    "left_motor_elevator_pivot":     ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
    "right_motor_elevator_pivot":    ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
    "left_motor_elevator_link":      ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
    "right_motor_elevator_link":     ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
    "left_motor_dampener":           ("prismatic",  (0, 0, 1), (-0.03, 0.03), 0.0, 0.0, 0.0,  0.0,  0.0),
    "right_motor_dampener":          ("prismatic",  (0, 0, 1), (-0.03, 0.03), 0.0, 0.0, 0.0,  0.0,  0.0),
    "left_motor_dampener_link":      ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
    "right_motor_dampener_link":     ("revolute",   (0, 1, 0), (-30, 30),   0.0,  0.0,  0.0,  0.0,  0.0),
}
BASE_ROOT_MASS = 0.0           # chassis -- FILL ME

# --- SIMPLIFIED mebot (root 'mebot' -- the working model) ------------------
# Suspension/linkage pivots: revolute about lateral Y (GUESS -- verify).
# Caster swivels: continuous about Z. Drive wheels: continuous about Y,
# motorized. '*_rod' parts are telescoping members: prismatic, axis
# COMPUTED from the parent->child origin direction; motor rods (linear
# actuators) get motor props, dampener rods get spring props (0 = FILL ME).
# Masses all 0.0 = FILL ME.
def _sym(table):
    out = {}
    for k, v in table.items():
        for s in ("_l", "_r"):
            out[k + s] = v
    return out

MEBOT_REV_Y = ("revolute", (0, 1, 0), (-30, 30))
MEBOT = {}
MEBOT.update(_sym({
    "dw_main_plate":              ("fixed", None, None),
    "motor_swing_arm":            MEBOT_REV_Y,
    "drive_motor":                ("fixed", None, None),
    "drive_wheel":                ("continuous", (0, 1, 0), None),
    "motor_elevator":             MEBOT_REV_Y,
    "motor_elevator_rod":         ("rod_motor", None, (-0.05, 0.05)),
    "motor_elevator_pivot":       MEBOT_REV_Y,
    "motor_elevator_rod_link":    MEBOT_REV_Y,
    "elevator_dampener":          MEBOT_REV_Y,
    "elevator_dampener_rod":      ("rod_spring", None, (-0.03, 0.03)),
    "elevator_dampener_link":     MEBOT_REV_Y,
    "elevator_dampener_aux_link": MEBOT_REV_Y,
    # "casters" are actually PASSIVE OMNIWHEELS: they roll about the swing
    # arm's lateral Y axle and never swivel
    "front_caster_wheel":         ("continuous", (0, 1, 0), None),
    "rear_caster_wheel":          ("continuous", (0, 1, 0), None),
}))
MEBOT["rear_casteer_wheel_l"] = ("continuous", (0, 1, 0), None)  # sic
MEBOT.update({
    "front_caster_arm_mount":         ("fixed", None, None),
    "front_caster_swing_arm":         MEBOT_REV_Y,
    "front_caster_linkage":           MEBOT_REV_Y,
    "front_caster_linkage_arm":       MEBOT_REV_Y,
    "front_caster_linkage_aux":       MEBOT_REV_Y,
    "front_caster_linkage_aux_arm":   MEBOT_REV_Y,
    "front_caster_motor":             MEBOT_REV_Y,
    "front_caster_motor_rod":         ("rod_motor", None, (-0.08, 0.08)),
    "rear_caster_arm_mount":          ("fixed", None, None),
    "rear_caster_swing_arm":          MEBOT_REV_Y,
    "rear_caster_aux_linkage":        MEBOT_REV_Y,
    "rear_caster_suspension_arm":     MEBOT_REV_Y,
    "rear_caster_motor":              MEBOT_REV_Y,
    "rear_caster_motor_rod":          ("rod_motor", None, (-0.08, 0.08)),
    "rear_caster_motor_dampener_pivot": MEBOT_REV_Y,
    "rear_caster_dampener":           MEBOT_REV_Y,
    "rear_caster_dampener_rod":       ("rod_spring", None, (-0.05, 0.05)),
})
MEBOT_DRIVE_TORQUE = 20.0      # N*m, drive wheels -- GUESS
MEBOT_DRIVE_VEL = 720.0        # deg/s
MEBOT_LIN_FORCE = 400.0        # N, caster/elevator linear actuators -- GUESS
MEBOT_LIN_VEL = 0.05           # m/s


def base_name(name):
    return re.sub(r"\.\d+$", "", name)


def setdefault(o, key, val):
    if key not in o:
        o[key] = val
        return True
    return False


stamped, kept, missing_mass = [], [], []


def stamp(o, joint, axis, limits, mass, torque=0.0, vel=0.0,
          stiff=0.0, damp=0.0, mimic="", ratio=1.0):
    new = False
    new |= setdefault(o, "dojo_joint", joint)
    if axis is not None:
        new |= setdefault(o, "dojo_axis", list(axis))
    if limits is not None:
        new |= setdefault(o, "dojo_limits", [float(limits[0]), float(limits[1])])
    new |= setdefault(o, "dojo_mass", float(mass))
    if joint != "fixed":
        new |= setdefault(o, "dojo_motor_torque", float(torque))
        new |= setdefault(o, "dojo_motor_velocity", float(vel))
        new |= setdefault(o, "dojo_spring_stiffness", float(stiff))
        new |= setdefault(o, "dojo_spring_damping", float(damp))
        new |= setdefault(o, "dojo_spring_rest", 0.0)
        new |= setdefault(o, "dojo_friction", 0.0)
        new |= setdefault(o, "dojo_mimic", mimic)
        if mimic:
            new |= setdefault(o, "dojo_mimic_ratio", float(ratio))
    (stamped if new else kept).append(o.name)
    if float(o.get("dojo_mass", 0.0)) <= 0.0:
        missing_mass.append(o.name)


print("== robot_annotate ==")
# one-time correction: the omniwheels ("casters") were first stamped as
# Z-axis swivels; they are passive rollers about the lateral Y axle
for _wn in ("front_caster_wheel_l", "front_caster_wheel_r",
            "rear_casteer_wheel_l", "rear_caster_wheel_l",
            "rear_caster_wheel_r",
            "front_caster_wheel_left", "front_caster_wheel_right",
            "rear_left_caster", "rear_right_caster"):
    _w = bpy.data.objects.get(_wn)
    if (_w is not None and str(_w.get("dojo_joint")) == "continuous"
            and list(_w.get("dojo_axis", [])) == [0.0, 0.0, 1.0]):
        _w["dojo_axis"] = [0.0, 1.0, 0.0]
        print("  omniwheel axis Z->Y:", _wn)

# one-time correction: the simplified mebot's rear_caster_dampener BODY was
# stamped prismatic by an earlier table collision; the sliding joint lives
# on its *_rod child -- the body is a revolute mount
_rcd = bpy.data.objects.get("rear_caster_dampener")
if (_rcd is not None and _rcd.parent is not None
        and _rcd.parent.name.startswith("rear_caster_motor_dampener_pivot")
        and str(_rcd.get("dojo_joint")) == "prismatic"):
    _rcd["dojo_joint"] = "revolute"
    _rcd["dojo_axis"] = [0.0, 1.0, 0.0]
    _rcd["dojo_limits"] = [-30.0, 30.0]
    print("  corrected rear_caster_dampener -> revolute Y")

for o in bpy.context.scene.objects:
    bn = base_name(o.name)
    if bn in ARM:
        j, ax, lim, mass, tq, vel = ARM[bn]
        stamp(o, j, ax, lim, mass, tq, vel)
    elif bn in GRIPPER:
        j, ax, lim, mass, tq, vel, mimic, ratio = GRIPPER[bn]
        # mimic references live inside the SAME gripper copy: carry the
        # numeric suffix over (link_0_l.001 drives link_1_l.001)
        if mimic and "." in o.name:
            mimic = mimic + o.name[o.name.index("."):]
        stamp(o, j, ax, lim, mass, tq, vel, mimic=mimic, ratio=ratio)
    elif bn in GRIPPER_CLOSURE:
        other = GRIPPER_CLOSURE[bn]
        if "." in o.name:
            other = other + o.name[o.name.index("."):]
        new = setdefault(o, "dojo_joint", "revolute")
        new |= setdefault(o, "dojo_axis", [0.0, 0.0, 1.0])
        new |= setdefault(o, "dojo_connect", other)
        (stamped if new else kept).append(o.name)
    elif bn in BASE:
        j, ax, lim, mass, tq, vel, stiff, damp = BASE[bn]
        stamp(o, j, ax, lim, mass, tq, vel, stiff, damp)
    elif bn in MEBOT:
        j, ax, lim = MEBOT[bn]
        tq = vel = stiff = damp = 0.0
        if j == "continuous" and "drive_wheel" in bn:
            tq, vel = MEBOT_DRIVE_TORQUE, MEBOT_DRIVE_VEL
        if j in ("rod_motor", "rod_spring"):
            # telescoping member: prismatic along the parent->child origin
            # direction (computed, root-local == world for direction)
            d = (o.matrix_world.translation
                 - o.parent.matrix_world.translation).normalized()
            ax = [round(v, 4) for v in d]
            if j == "rod_motor":
                tq, vel = MEBOT_LIN_FORCE, MEBOT_LIN_VEL
            j = "prismatic"
        stamp(o, j, ax, lim, 0.0, tq, vel, stiff, damp)
    elif bn == "mebot":                         # simplified-base root
        if setdefault(o, "dojo_mass", 0.0):
            stamped.append(o.name)
        if float(o.get("dojo_mass", 0.0)) <= 0.0:
            missing_mass.append(o.name)
    elif bn == "base_link":                     # arm root
        if setdefault(o, "dojo_mass", ARM_ROOT_MASS):
            stamped.append(o.name)
    elif bn == "base":                          # gripper root
        if setdefault(o, "dojo_mass", GRIPPER_ROOT_MASS):
            stamped.append(o.name)
    elif bn == "chassis":                       # base root
        if setdefault(o, "dojo_mass", BASE_ROOT_MASS):
            stamped.append(o.name)
        if float(o.get("dojo_mass", 0.0)) <= 0.0:
            missing_mass.append(o.name)

print("  stamped new props on %d objects" % len(stamped))
for n in sorted(stamped):
    print("    +", n)
if kept:
    print("  %d objects already annotated (left untouched)" % len(kept))
if missing_mass:
    print("  !! dojo_mass still 0.0 (FILL ME) on %d objects:" % len(missing_mass))
    for n in sorted(missing_mass):
        print("    ?", n)

if "--save" in sys.argv:
    bpy.ops.wm.save_mainfile()
    print("saved", bpy.data.filepath)
sys.stdout.flush()
