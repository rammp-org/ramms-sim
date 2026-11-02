"""The RAMMP seat and the Gen3 arm it carries, for a robot's MJCF: shared by RAMMP Gen1 (rammp_gen1/build_rammp_gen1_mjcf.py)
and RAMMP Gen2's lift-drive model.

The seat is ramms-assets' rammp_seat on its socket, with its rails, mounts and sensors; its rider; and the Kinova Gen3 +
Robotiq 2F-85 (gen3_2f85/gen3_2f85_fixed.xml) on the arm mount of its right rail, its names prefixed ARM_PREFIX. In the
MJCF the seat and the rider are their masses; the Unreal pawn hangs the seat's meshes and its occupant on the seat body.
"""
import os
import re
import xml.etree.ElementTree as ET

UE_TO_M = 0.01
# The seat's mesh: its bounds in its own frame (the socket's), Unreal cm.
SEAT_BOUNDS_CM = ((-48.5, -35.6, -2.8), (39.8, 35.1, 58.3))
# Where the RAMMP chairs carry the arm's base (its arm mount on the right rail), from the seat socket, Unreal cm.
ARM_MOUNT_CM = (16.0, 26.5, 12.0)
ARM_XML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen3_2f85", "gen3_2f85_fixed.xml")
ARM_PREFIX = "arm_"
ARM_JOINTS = ["joint_%d" % i for i in range(1, 8)]
# The arm stowed: the Gen3's Retract position, folded upright over its base beside the rider (rad, joint_1..7; the
# numeric arm_stow: the Unreal IK's home pose and the curb mass models' arm).
ARM_STOW = [0.0, -0.34906585, 3.14159265, -2.54818071, 0.0, -0.87266463, 1.57079633]


def f(x):
    """A number for the MJCF text: %.6g, but never in exponent form (the Unreal importer reads a <numeric>'s data
    with FString::IsNumeric, which refuses it)."""
    s = "%.6g" % x
    if "e" in s:
        s = ("%.9f" % x).rstrip("0").rstrip(".")
    return s


def fv(v):
    return " ".join(f(x) for x in v)


def arm_mesh_files():
    """The arm's mesh files (paths), for a model that keeps its own copy of them (splice_arm's mesh_dir)."""
    return [os.path.join(os.path.dirname(ARM_XML), el.get("file")) for el in ET.parse(ARM_XML).getroot().iter("mesh") if el.get("file")]


def arm_mount_pos():
    """The arm mount from the seat socket, m, in MuJoCo's axes (Unreal's Y flipped)."""
    return [ARM_MOUNT_CM[0] * UE_TO_M, -ARM_MOUNT_CM[1] * UE_TO_M, ARM_MOUNT_CM[2] * UE_TO_M]


def seat_com():
    """The seat's centre of mass from its socket, m: a third of the way up its mesh's bounds."""
    lo, hi = SEAT_BOUNDS_CM
    return [(lo[0] + hi[0]) / 2 * UE_TO_M, -(lo[1] + hi[1]) / 2 * UE_TO_M, (lo[2] + (hi[2] - lo[2]) / 3) * UE_TO_M]


def seat_inertial(seat_kg):
    """The seat body's <inertial>: its mass as a box of its mesh's bounds."""
    lo, hi = SEAT_BOUNDS_CM
    dims = [(hi[i] - lo[i]) * UE_TO_M for i in range(3)]
    k = seat_kg / 12
    return '<inertial pos="%s" mass="%s" diaginertia="%s %s %s"/>' % (
        fv(seat_com()), f(seat_kg), f(k * (dims[1] ** 2 + dims[2] ** 2)), f(k * (dims[0] ** 2 + dims[2] ** 2)), f(k * (dims[0] ** 2 + dims[1] ** 2)))


def rider_lines(rider_kg, pos):
    """The rider's body at pos (m, from the seat socket): its mass. Transparent: URLab draws any alpha above 0 opaque,
    which would hide the robot; MuJoCo clips can tint it in."""
    return ['<body name="rider" pos="%s">' % fv(pos),
            '  <geom name="rider" class="visual" type="box" size="0.2 0.2 0.3" rgba="0.6 0.45 0.35 0"/>',
            '  <inertial pos="0 0 0" mass="%s" diaginertia="%s %s %s"/>' % (
                f(rider_kg), f(rider_kg * 0.13 / 12 * 4), f(rider_kg * 0.13 / 12 * 4), f(rider_kg * 0.08 / 12 * 4)),
            '</body>']


def splice_arm(text, model_dir, stow=ARM_STOW, contact=(2, 1), defaults_extra=(), mesh_dir=None):
    """The model text with the arm spliced in on the arm_mount site, its names prefixed ARM_PREFIX, and its stowed pose
    as the numeric arm_stow (the model's keyframes are the caller's to extend). Spliced as text, not through
    MjSpec.attach and to_xml, so the robot's own elements stay as written: to_xml would rewrite every actuator as
    <general>, and the Unreal import and the pawn builders read <motor> and <position>. model_dir: the folder the model
    is written to (the arm's mesh files are found from it); mesh_dir: where the arm's meshes are, if not beside ARM_XML.
    contact: the arm's contype and conaffinity, the robot's own, so that like the robot's geoms it collides only with the
    world. defaults_extra: more lines for the arm's default class (the robot's own defaults reach it otherwise); its
    equalities and tendon name that class, so they take its defaults too."""
    arm = ET.parse(ARM_XML).getroot()
    refs = ("name", "class", "childclass", "mesh", "material", "joint", "joint1", "joint2", "body1", "body2", "tendon")
    for el in arm.iter():
        for a in refs:
            if a in el.attrib:
                el.set(a, ARM_PREFIX + el.get(a))
        if el.tag == "mesh" and "file" in el.attrib:   # found from the model's folder
            src = os.path.join(mesh_dir, os.path.basename(el.get("file"))) if mesh_dir else os.path.join(os.path.dirname(ARM_XML), el.get("file"))
            el.set("file", os.path.relpath(src, model_dir).replace(os.sep, "/"))
    # The arm's equalities and tendon sit outside the body tree, where its childclass does not reach: without a class
    # of their own they take the robot's top-level defaults (Gen2's stiff solimp width) instead of the arm's.
    for tag in ("equality", "tendon"):
        for child in arm.findall(tag):
            for el in child:
                el.attrib.setdefault("class", ARM_PREFIX + "main")

    def block(tag, indent):
        out = []
        for child in arm.findall(tag):
            for el in list(child):
                ET.indent(el, space="  ", level=indent // 2)
                out.append(" " * indent + ET.tostring(el, encoding="unicode").strip())
        return out

    # The arm's top-level defaults go in a class of their own, so they reach only the arm. Like the robot's own geoms,
    # the arm collides only with the world, not with the robot it is mounted on; its contacts keep MuJoCo's defaults.
    defaults = (['    <default class="%smain">' % ARM_PREFIX,
                 '      <geom contype="%d" conaffinity="%d" friction="1 0.005 0.0001" solref="0.02 1"/>' % contact]
                + ["      " + l for l in defaults_extra] + block("default", 6) + ['    </default>'])
    mount = re.search(r'( *)<site name="arm_mount"[^\n]*\n', text)
    indent = mount.group(1)
    base_link = arm.find("worldbody/body")
    base_link.set("pos", re.search(r'pos="([^"]+)"', mount.group(0)).group(1))
    base_link.set("childclass", ARM_PREFIX + "main")
    ET.indent(base_link, space="  ", level=len(indent) // 2)
    body = [indent + ET.tostring(base_link, encoding="unicode").strip()]
    stow_line = ['    <numeric name="arm_stow" data="%s"/>' % " ".join(f(q) for q in stow)]
    extra = (["  <contact>"] + block("contact", 4) + ["  </contact>", "  <tendon>"] + block("tendon", 4) + ["  </tendon>"])

    def insert(text, marker, lines, before=True):
        key = "\n" + marker            # a whole line: "  </default>" ends "    </default>" lines too
        assert text.count(key) == 1, marker
        add = "".join(l + "\n" for l in lines)
        return text.replace(key, "\n" + add + marker if before else key + add)

    text = insert(text, "  </default>\n", defaults)
    if "  </custom>\n" not in text:
        text = insert(text, "  <actuator>\n", ["  <custom>", "  </custom>"])
    text = insert(text, "  </custom>\n", stow_line)
    text = insert(text, "  </asset>\n", block("asset", 4))
    text = insert(text, mount.group(0), body, before=False)
    text = insert(text, "  </equality>\n", block("equality", 4))
    text = insert(text, "  <actuator>\n", extra)
    text = insert(text, "  </actuator>\n", block("actuator", 4))
    return text


def stow_arm(m, qpos, ctrl, stow=None):
    """qpos and ctrl (arrays of m's sizes) with the arm's joints at its stowed pose and its servos holding there."""
    import mujoco
    if stow is None:
        stow = m.numeric("arm_stow").data
    for name, q in zip(ARM_JOINTS, stow):
        qpos[m.jnt_qposadr[m.joint(ARM_PREFIX + name).id]] = q
        ctrl[m.actuator(ARM_PREFIX + name).id] = q
    return qpos, ctrl


def hold_arm_stowed(m, d):
    """Put the arm's joints at its numeric arm_stow and its position servos holding there (a model without the arm
    keeps its pose), then bring d up to date."""
    import mujoco
    if mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_NUMERIC, "arm_stow") >= 0:
        stow_arm(m, d.qpos, d.ctrl)
    mujoco.mj_forward(m, d)
