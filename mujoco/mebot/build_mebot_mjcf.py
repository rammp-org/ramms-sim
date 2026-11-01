#!/usr/bin/env python3
"""Build the MeBot's MJCF models and test scenes from its Unreal geometry.

    python mujoco/mebot/build_mebot_mjcf.py [--rider-kg 75]

Reads source/mebot_ue.json (extract_ue_mebot.py) and source/mebot_meshes.json with meshes/
(extract_ue_mebot_meshes.py), both from the public ramms-assets MeBot, and writes next to this file:

  mebot.xml, mebot_scene.xml          the robot, and the robot on a floor facing a 15 cm curb
  mebot_powered_front.xml, mebot_powered_front_scene.xml
                                      the same with hub motors on the front omni wheels
  meshes/omni_front_roller.stl, meshes/omni_rear_roller.stl
                                      the omni wheels' rollers, generated from the measured rollers

The model, in MuJoCo's frame (m; X forward, Y left, Z up; the floor at z = 0 under the wheels):

  chassis              free joint; the frame, the caster-arm mounts, the seat and its rider
    translator_l / _r  slide along X: the drive-wheel plate (left / right independently)
      elevator_l / _r  hinge about Y at the swing arm's pivot: the drive wheel's height
        drive_wheel_*  hinge about Y, motor-driven
    front_arm          hinge about Y: one arm carrying both front omni wheels
      front_omni_*     omni wheels: a hub on the axle and two staggered rows of passive barrel rollers
    rear_arm           the same at the rear, but sprung: it is not driven itself
      rear_omni_*
    rear_lift          hinge about Y: the rear suspension arm, which the rear actuator turns; through the aux link,
                       the damper's pivot and the damper (rear_spring, a preloaded spring-damper on its rod) it
                       pushes the rear arm down
  and passive linkages (LINKAGES) that carry the linear actuators' and links' meshes

Lift joints are driven directly (position actuators at the joints, the rear one at the suspension arm). The
linear actuators and their links are passive bodies that follow those joints through loop closures (the
physics asset's user constraints), so the meshes move as the robot does; apart from the rear chain they carry no
load. The rear aux link hangs on the suspension arm (the physics asset's constraint; its skeleton bone is
parented to the frame), which is what makes the rear chain drive the rear arm. Signs: a positive
elevator / arm / rear-lift angle puts its wheels down, raising the chassis; a positive translator moves its drive
wheel forward; drive wheels and the powered front omni wheels are torque motors, positive forward.

The omni wheels' rollers are measured from the visual meshes (count, rows, axis radius, length) and rebuilt as
barrels whose outer profile is the wheel's circle, so the wheel rolls round. Each wheel sits where its rollers
are (the rear wheels' treads are 2.5 cm outboard of the physics asset's hulls).

Kinematics -- pivots, wheel centres and sizes, collision boxes -- come from the Unreal asset. Everything in
PARAMS is a PLACEHOLDER until measured on the robot: the Unreal asset has no masses (Unreal derived them from
the boxes' volumes) and its drives are not the robot's. The joint ranges are the Unreal physics asset's limits
(45 deg on the elevators and arms, 40 cm on the translators), read from its constraints and kept until
the robot's are known: a range set in PARAMS overrides.
The speeds in PARAMS are for whatever commands these position actuators (the Unreal motor table's
MaxVelocity; check_mebot.py's ramps): MuJoCo's position actuators have none.

Geom groups: 2 visual meshes, 3 collision (boxes, the drive wheels' cylinders, the rollers).
"""
import argparse
import json
import math
import os
import struct

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- PLACEHOLDERS (to be measured)
PARAMS = {
    # Masses, kg. The robot without its rider comes to about 90 kg.
    "mass": {"chassis": 50.0, "translator": 3.0, "elevator": 9.0, "drive_wheel": 2.5, "caster_arm": 2.5,
             "omni_hub": 0.5, "omni_roller": 0.01, "linkage": 0.3},
    "rider_kg": 75.0,                      # --rider-kg; 0 leaves the seat empty
    "rider_above_seat_cm": 25.0,           # the rider's centre of mass above the seat socket
    # Joint ranges: None takes the Unreal physics asset's limits (ASSET_RANGES, from source/mebot_ue.json).
    "elevator_deg": None,
    "caster_arm_deg": None,                # the front arm's, and the rear arm's stop
    "translator_cm": None,
    # Actuators: position gain, velocity gain, force/torque limit; speeds for the commands.
    "elevator": {"kp": 3000.0, "kv": 200.0, "force": 600.0, "speed_deg_s": 6.0},      # N*m/rad, N*m*s/rad, N*m
    "caster_arm": {"kp": 2000.0, "kv": 100.0, "force": 400.0, "speed_deg_s": 6.0},
    "rear_lift": {"kp": 3000.0, "kv": 150.0, "force": 400.0, "speed_deg_s": 8.0},      # at the suspension arm (~6 deg/s at the rear arm)
    "rear_lift_deg": (-35.0, 44.0),        # +44: the rear arm at its 45 deg stop; near -40 the rear actuator passes dead centre
    # The rear damper: spring rate, damping, the preload it holds against its top-out stop, and its travel from the
    # reference pose (top-out first; positive compresses it, as load on the rear wheels does).
    "rear_spring": {"stiffness": 200000.0, "damping": 5000.0, "preload": 600.0, "travel_cm": (-1.0, 2.0)},  # N/m, N*s/m, N
    "translator": {"kp": 30000.0, "kv": 2000.0, "force": 1500.0, "speed_cm_s": 2.0},  # N/m, N*s/m, N
    "drive": {"torque": 60.0, "max_speed_rad_s": 9.0},                                 # N*m; 9 rad/s ~ 6 km/h
    "front_omni_drive": {"torque": 15.0, "max_speed_rad_s": 22.0},                     # the powered-front variant
}
# ---------------------------------------------------------------------------

UE_TO_M = 0.01

# MJCF body -> the Unreal bones whose collision boxes it carries: the first is its frame (the joint pivot).
BODIES = {
    "chassis": ["mebot", "front_caster_arm_mount", "rear_caster_arm_mount"],
    "translator_l": ["dw_main_plate_l"], "translator_r": ["dw_main_plate_r"],
    "elevator_l": ["motor_swing_arm_l", "drive_motor_l"],
    "elevator_r": ["motor_swing_arm_r", "drive_motor_r"],
    "front_arm": ["front_caster_swing_arm"], "rear_arm": ["rear_caster_swing_arm"],
}
DRIVE_WHEELS = {"l": "drive_wheel_l", "r": "drive_wheel_r"}
OMNI_WHEELS = {"front_omni_l": ("front_arm", "front_caster_wheel_l"), "front_omni_r": ("front_arm", "front_caster_wheel_r"),
               "rear_omni_l": ("rear_arm", "rear_casteer_wheel_l"), "rear_omni_r": ("rear_arm", "rear_caster_wheel_r")}
OMNI_RUBBER = "caster_rubber"  # the omni wheels' roller material: measured, then replaced by the generated rollers

# Linkages: (body, parent body, frame bone, joint). Each carries its frame bone's meshes; slides run along the
# Unreal constraint's linear axis. All are passive except rear_lift (driven) and rear_spring (the damper).
LINKAGES = [
    ("elevator_act_l", "elevator_l", "motor_elevator_l", "hinge"), ("elevator_rod_l", "elevator_act_l", "motor_elevator_rod_l", "slide"),
    ("elevator_act_r", "elevator_r", "motor_elevator_r", "hinge"), ("elevator_rod_r", "elevator_act_r", "motor_elevator_rod_r", "slide"),
    ("front_aux", "chassis", "front_caster_linkage_aux", "hinge"), ("front_aux_arm", "front_aux", "front_caster_linkage_aux_arm", "hinge"),
    ("front_link", "chassis", "front_caster_linkage", "hinge"), ("front_link_arm", "front_link", "front_caster_linkage_arm", "hinge"),
    ("front_act", "chassis", "front_caster_motor", "hinge"), ("front_rod", "front_act", "front_caster_motor_rod", "slide"),
    ("rear_lift", "chassis", "rear_caster_suspension_arm", "hinge"),
    ("rear_act", "chassis", "rear_caster_motor", "hinge"), ("rear_rod", "rear_act", "rear_caster_motor_rod", "slide"),
    ("rear_aux", "rear_lift", "rear_caster_aux_linkage", "hinge"),
    ("rear_pivot", "chassis", "rear_caster_motor_dampener_pivot", "hinge"),
    ("rear_damper", "rear_pivot", "rear_caster_dampener", "hinge"), ("rear_spring", "rear_damper", "rear_caster_dampener_rod", "slide"),
]
LINKAGE_PARENT = {lk[0]: lk[1] for lk in LINKAGES}
# PARAMS ranges taken from the physics asset when left None: the constraints of these bones, which must agree.
ASSET_RANGES = {"elevator_deg": ("motor_swing_arm_l", "motor_swing_arm_r"),
                "caster_arm_deg": ("front_caster_swing_arm", "rear_caster_swing_arm"),
                "translator_cm": ("dw_main_plate_l", "dw_main_plate_r")}
REAR_LIFT_AXIS = "0 -1 0"  # positive turns the suspension arm the way that pushes the rear wheels down


def f(x):
    return "%.6g" % x


def fv(v):
    return " ".join(f(x) for x in v)


def write_stl(path, tris):
    with open(path + ".tmp", "wb") as fh:
        fh.write(b"generated by build_mebot_mjcf.py".ljust(80, b" "))
        fh.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            n = np.cross(b - a, c - a)
            n = n / (np.linalg.norm(n) or 1.0)
            fh.write(struct.pack("<12fH", *n, *a, *b, *c, 0))
    os.replace(path + ".tmp", path)


def read_stl(path):
    with open(path, "rb") as fh:
        fh.read(80)
        n = struct.unpack("<I", fh.read(4))[0]
        data = np.frombuffer(fh.read(50 * n), dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
    return data["v"].reshape(-1, 3, 3).astype(np.float64)


def components(tris):
    """Split a triangle soup into connected parts (vertices shared by position)."""
    _, inv = np.unique(np.round(tris.reshape(-1, 3), 5), axis=0, return_inverse=True)
    inv = inv.reshape(-1, 3)
    parent = list(range(int(inv.max()) + 1))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b, c in inv:
        for u, v in ((a, b), (a, c)):
            ru, rv = find(u), find(v)
            if ru != rv:
                parent[ru] = rv
    roots = np.array([find(a) for a in inv[:, 0]])
    return [tris[roots == r] for r in np.unique(roots)]


def measure_rollers(tris, centre):
    """An omni wheel's rollers from its roller mesh (centre: the wheel bone, m): rows (y, count, phase) relative to
    the tread's centre, the tread centre's offset in Y, the rollers' axis radius, outer radius and half length."""
    rollers = []
    for comp in components(tris):
        p = comp.reshape(-1, 3) - centre
        m = p.mean(axis=0)
        q = p - m
        axis = np.linalg.eigh(q.T @ q)[1][:, 2]
        if abs(axis[1]) > 0.2:
            raise ValueError("a roller's axis is not in the wheel's plane")
        along = q @ axis
        rollers.append((m, along.max() - along.min(), math.atan2(m[0], -m[2]) % (2 * math.pi)))
    rows = {}
    for r in rollers:
        key = next((k for k in rows if abs(k - r[0][1]) < 0.003), r[0][1])
        rows.setdefault(key, []).append(r)
    counts = {len(v) for v in rows.values()}
    if len(rows) != 2 or len(counts) != 1:
        raise ValueError("expected two rows of equal roller counts, got %s" % {round(k, 4): len(v) for k, v in rows.items()})
    n = counts.pop()
    y_centre = float(np.mean(list(rows)))
    pts = tris.reshape(-1, 3) - centre
    out = {"n": n, "y_centre": y_centre,
           "axis_radius": float(np.mean([math.hypot(r[0][0], r[0][2]) for r in rollers])),
           "radius": float(np.max(np.hypot(pts[:, 0], pts[:, 2]))),
           "half_length": float(np.mean([r[1] for r in rollers]) / 2),
           "rows": []}
    for y, rs in sorted(rows.items()):
        step = 2 * math.pi / n
        out["rows"].append((float(np.mean([r[0][1] for r in rs])) - y_centre, min(r[2] % step for r in rs)))
    return out


def roller_mesh(radius, axis_radius, half_length, rings=9, segments=16):
    """A barrel along X whose profile is the wheel's circle: at axial offset u its radius is sqrt(R^2 - u^2) - d."""
    us = np.linspace(-half_length, half_length, rings)
    rho = np.sqrt(radius ** 2 - us ** 2) - axis_radius
    th = np.linspace(0, 2 * math.pi, segments, endpoint=False)
    ring = [np.stack([np.full(segments, u), r * np.cos(th), r * np.sin(th)], axis=1) for u, r in zip(us, rho)]
    tris = []
    for i in range(rings - 1):
        for j in range(segments):
            a, b = ring[i][j], ring[i][(j + 1) % segments]
            c, d = ring[i + 1][j], ring[i + 1][(j + 1) % segments]
            tris += [(a, b, d), (a, d, c)]
    for end, sign in ((0, -1), (rings - 1, 1)):
        ctr = np.array([us[end], 0.0, 0.0])
        for j in range(segments):
            a, b = ring[end][j], ring[end][(j + 1) % segments]
            tris.append((ctr, b, a) if sign < 0 else (ctr, a, b))
    return tris


class Model:
    def __init__(self, ue, meshes):
        self.bones = {b["name"]: b["component"]["loc"] for b in ue["bones"]}
        self.parent = {b["name"]: b["parent"] for b in ue["bones"]}
        for b in ue["bones"]:
            if any(abs(a) > 1e-3 for a in b["component"]["rpy"]):
                raise ValueError("bone %s is rotated; the conversion assumes the reference pose is axis-aligned" % b["name"])
        self.prims = {b["bone"]: b["primitives"] for b in ue["bodies"]}
        self.sockets = {s["name"]: s for s in ue["sockets"]}
        self.constraints = ue["constraints"]
        for b, ps in self.prims.items():
            for p in ps:
                if any(abs(a) > 1e-3 for a in p.get("rpy", (0, 0, 0))):
                    raise ValueError("%s has a rotated primitive; the conversion assumes axis-aligned ones" % b)
        # The floor: the lowest point of any wheel at the reference pose.
        self.ground_z = min(self.bones[b][2] + h["min"][2] for b in list(DRIVE_WHEELS.values()) + [w for _, w in OMNI_WHEELS.values()]
                            for h in self.hulls(b))
        self.parts = meshes["parts"]
        # Each body's frame bone, and the body every bone's meshes ride on.
        self.frame = {b: bones[0] for b, bones in BODIES.items()}
        self.frame.update({lk[0]: lk[2] for lk in LINKAGES})
        self.frame.update({s: w for s, w in (("drive_wheel_" + k, v) for k, v in DRIVE_WHEELS.items())})
        self.bone_body = {}
        for body, bones in BODIES.items():
            for b in bones:
                self.bone_body[b] = body
        for lk in LINKAGES:
            self.bone_body[lk[2]] = lk[0]
        for k, w in DRIVE_WHEELS.items():
            self.bone_body[w] = "drive_wheel_" + k
        for name, (_, w) in OMNI_WHEELS.items():
            self.bone_body[w] = name
        for b in self.bones:
            a = b
            while a not in self.bone_body:
                a = self.parent[a]
            self.bone_body[b] = self.bone_body[a]
        # The omni wheels' rollers, measured; each wheel's centre is its tread's.
        self.omni = {}
        for name, (_, w) in OMNI_WHEELS.items():
            part = next(p for p in self.parts if p["bone"] == w and p["material"] == OMNI_RUBBER)
            self.omni[name] = measure_rollers(read_stl(os.path.join(HERE, part["file"])), np.array(self.comp(self.bones[w])))
            self.frame[name] = w

    def hulls(self, bone):
        return [p for p in self.prims.get(bone, []) if p["type"] == "hull"]

    def comp(self, p):
        """An Unreal component-space point (cm) in MuJoCo's axes (m, Y left), still in component space."""
        return [p[0] * UE_TO_M, -p[1] * UE_TO_M, p[2] * UE_TO_M]

    def origin(self, body):
        """A body's frame origin in component space (m, MuJoCo axes)."""
        o = self.comp(self.bones[self.frame[body]])
        if body in self.omni:
            o[1] += self.omni[body]["y_centre"]
        return o

    def rel(self, body, parent):
        a, b = self.origin(body), self.origin(parent)
        return [a[i] - b[i] for i in range(3)]

    def boxes(self, body, mass):
        """The body's bones' physics-asset boxes as collision geoms; the body's mass on the largest."""
        out, vols = [], []
        o = self.origin(body)
        for b in BODIES[body]:
            for p in self.prims.get(b, []):
                if p["type"] != "box":
                    continue
                c = self.comp([self.bones[b][i] + p["center"][i] for i in range(3)])
                half = [s * UE_TO_M / 2 for s in p["size"]]
                out.append((b, [c[i] - o[i] for i in range(3)], half))
                vols.append(half[0] * half[1] * half[2])
        big = vols.index(max(vols))
        return ['<geom name="%s_%s" class="collision" type="box" pos="%s" size="%s" mass="%s"/>' % (
            body, b, fv(pos), fv(half), f(mass if i == big else 0.0)) for i, (b, pos, half) in enumerate(out)]

    def visuals(self, body):
        """The body's visual meshes (the omni wheels' rollers are generated instead)."""
        o = self.origin(body)
        return ['<geom class="visual" mesh="%s" pos="%s" rgba="%s"/>' % (mesh_name(p), fv([-x for x in o]), fv(p["rgba"]))
                for p in self.parts if self.bone_body[p["bone"]] == body and not (body in self.omni and p["material"] == OMNI_RUBBER)]

    def wheel_size(self, bone):
        h = self.hulls(bone)[0]
        ext = [h["max"][i] - h["min"][i] for i in range(3)]
        return (ext[0] + ext[2]) / 4 * UE_TO_M, ext[1] * UE_TO_M  # radius, width

    def asset_range(self, bone):
        """A joint's range from its physics-asset constraint, (-limit, limit): cm for its limited linear axis, else
        degrees for its limited swing or twist."""
        c = next(c for c in self.constraints if c["child"] == bone and c["parent"] == self.parent[bone])
        if any(c["linear"][k] == "Limited" for k in "xyz"):
            return (-c["linear"]["limit_cm"], c["linear"]["limit_cm"])
        for k in ("swing1", "swing2", "twist"):
            if c[k]["motion"] == "Limited":
                return (-c[k]["limit_deg"], c[k]["limit_deg"])
        raise ValueError("%s's constraint has no limited motion" % bone)

    def slide_axis(self, bone):
        c = next(c for c in self.constraints if c["child"] == bone and c["parent"] == self.parent[bone])
        pri, sec = np.array(c["pri_axis_in_parent"]), np.array(c["sec_axis_in_parent"])
        ax = pri if c["linear"]["x"] != "Locked" else np.cross(pri, sec) if c["linear"]["z"] != "Locked" else sec
        return [ax[0], -ax[1], ax[2]]

    def closures(self):
        """The physics asset's loop closures between bones on different bodies: (body1, anchor in body1, body2)."""
        out = []
        for c in self.constraints:
            child, parent = c["child"], c["parent"]
            if self.parent.get(child) == parent:
                continue                                     # a tree joint, not a loop closure
            b1, b2 = self.bone_body[child], self.bone_body[parent]
            if b1 == b2:
                continue
            p = self.comp([self.bones[child][i] + c["pos_in_child"][i] for i in range(3)])
            o = self.origin(b1)
            anchor = [p[i] - o[i] for i in range(3)]
            if LINKAGE_PARENT.get(b1) == b2 and max(abs(a) for a in anchor) < 1e-6:
                continue                                     # already the linkage's own joint
            out.append((b1, anchor, b2))
        return out


def mesh_name(part):
    return os.path.splitext(os.path.basename(part["file"]))[0]


def roller_kind(name):
    return name.split("_")[0]      # front / rear


def omni_wheel(model, name, parent, P, ind, powered):
    """An omni wheel: a hub on the axle carrying its visual meshes, and two staggered rows of passive barrel
    rollers, each on a hinge along its own axis (the wheel's tangent there)."""
    o = model.omni[name]
    _, width = model.wheel_size(OMNI_WHEELS[name][1])
    pad = " " * ind
    hub = P["mass"]["omni_hub"]
    d = o["axis_radius"]
    i_axle = 0.5 * hub * d ** 2                          # a disc of the rollers' axis radius, as thick as the wheel
    i_across = 0.25 * hub * d ** 2 + hub * width ** 2 / 12
    L = ['%s<body name="%s" pos="%s">' % (pad, name, fv(model.rel(name, parent))),
         '%s  <joint name="%s" type="hinge" axis="0 1 0" damping="0.01" armature="%s"/>' % (pad, name, "0.002" if powered else "0.0005"),
         '%s  <inertial pos="0 0 0" mass="%s" diaginertia="%s %s %s"/>' % (pad, f(hub), f(i_across), f(i_axle), f(i_across))]
    L += [pad + "  " + g for g in model.visuals(name)]
    mesh = "omni_%s_roller" % roller_kind(name)
    for row, (dy, phase) in enumerate(o["rows"]):
        for k in range(o["n"]):
            phi = phase + 2 * math.pi * k / o["n"]           # 0 at the bottom, positive towards +X
            c = [d * math.sin(phi), dy, -d * math.cos(phi)]
            rn = "%s_roller%d_%02d" % (name, row, k)
            L += ['%s  <body name="%s" pos="%s" axisangle="0 1 0 %s">' % (pad, rn, fv(c), f(-phi)),
                  '%s    <joint name="%s" type="hinge" axis="1 0 0" damping="0.0005" armature="0.00001"/>' % (pad, rn),
                  '%s    <geom name="%s" class="roller" mesh="%s" mass="%s"/>' % (pad, rn, mesh, f(P["mass"]["omni_roller"])),
                  '%s    <geom class="visual" mesh="%s" rgba="0.26 0.26 0.26 1"/>' % (pad, mesh),
                  '%s  </body>' % pad]
    L.append('%s</body>' % pad)
    return L


def build(m, P, powered_front):
    M = P["mass"]
    deg = math.radians
    name = "mebot_powered_front" if powered_front else "mebot"
    L = ['<mujoco model="%s">' % name,
         '  <!-- Generated by build_mebot_mjcf.py from source/mebot_ue.json and source/mebot_meshes.json; edit the generator,',
         '       not this file. Masses, joint ranges and actuator limits are PLACEHOLDERS (see PARAMS). -->',
         '  <compiler angle="radian" autolimits="true"/>',
         '  <option timestep="0.002" integrator="implicitfast" cone="elliptic" impratio="10"/>',
         '  <default>',
         '    <geom friction="1 0.005 0.0001" solref="0.01 1"/>',
         '    <default class="visual"><geom type="mesh" contype="0" conaffinity="0" group="2" mass="0"/></default>',
         '    <default class="collision"><geom contype="2" conaffinity="1" group="3" rgba="0.5 0.5 0.55 0.5"/></default>',
         '    <default class="roller"><geom type="mesh" contype="2" conaffinity="1" group="3" priority="1" solref="0.005 1" rgba="0.1 0.1 0.1 1"/></default>',
         '    <default class="linkage"><joint damping="0.05" armature="0.001"/></default>',
         '  </default>',
         '  <custom>']
    r_dw, _ = m.wheel_size(DRIVE_WHEELS["l"])
    L.append('    <numeric name="drive_wheel_radius" data="%s"/>' % f(r_dw))
    for kind in ("front", "rear"):
        L.append('    <numeric name="%s_omni_radius" data="%s"/>' % (kind, f(m.omni[kind + "_omni_l"]["radius"])))
    # The lift actuators' speeds (PARAMS), for whatever commands them: the curb sequence, the Unreal pawn.
    for name, v in (("elevator_speed_deg_s", P["elevator"]["speed_deg_s"]), ("caster_arm_speed_deg_s", P["caster_arm"]["speed_deg_s"]),
                    ("rear_lift_speed_deg_s", P["rear_lift"]["speed_deg_s"]), ("translator_speed_cm_s", P["translator"]["speed_cm_s"])):
        L.append('    <numeric name="%s" data="%s"/>' % (name, f(v)))
    L += ['  </custom>', '  <asset>']
    for p in m.parts:
        if p["material"] != OMNI_RUBBER or p["bone"] not in [w for _, w in OMNI_WHEELS.values()]:
            L.append('    <mesh name="%s" file="%s"/>' % (mesh_name(p), p["file"]))
    for kind in ("front", "rear"):
        L.append('    <mesh name="omni_%s_roller" file="meshes/omni_%s_roller.stl"/>' % (kind, kind))
    L += ['  </asset>', '  <worldbody>']

    chassis_pos = m.comp(m.bones["mebot"])
    chassis_pos[2] -= m.ground_z * UE_TO_M
    L.append('    <body name="chassis" pos="%s">' % fv([chassis_pos[0], chassis_pos[1], chassis_pos[2] + 0.005]))
    L.append('      <freejoint name="root"/>')
    L += ["      " + g for g in m.boxes("chassis", M["chassis"])]
    L += ["      " + g for g in m.visuals("chassis")]
    seat = m.sockets["seat_base"]
    seat_c = m.comp([m.bones[seat["bone"]][i] + seat["loc"][i] for i in range(3)])
    o = m.origin("chassis")
    L.append('      <site name="seat" pos="%s" size="0.02"/>' % fv([seat_c[i] - o[i] for i in range(3)]))
    if P["rider_kg"] > 0:
        rider = [seat_c[i] - o[i] for i in range(3)]
        rider[2] += P["rider_above_seat_cm"] * UE_TO_M
        L.append('      <body name="rider" pos="%s">' % fv(rider))
        # Transparent: the rider is its mass. (URLab draws any alpha above 0 opaque, which would hide the
        # robot; MuJoCo clips can tint it in.)
        L.append('        <geom name="rider" class="visual" type="box" size="0.2 0.2 0.3" rgba="0.6 0.45 0.35 0"/>')
        L.append('        <inertial pos="0 0 0" mass="%s" diaginertia="%s %s %s"/>' % (
            f(P["rider_kg"]), f(P["rider_kg"] * 0.13 / 12 * 4), f(P["rider_kg"] * 0.13 / 12 * 4), f(P["rider_kg"] * 0.08 / 12 * 4)))
        L.append('      </body>')

    children = {}
    for lk in LINKAGES:
        children.setdefault(lk[1], []).append(lk)

    def linkages(parent, ind):
        out = []
        for body, _, bone, joint in children.get(parent, []):
            pad = " " * ind
            out.append('%s<body name="%s" pos="%s">' % (pad, body, fv(m.rel(body, parent))))
            axis = "0 1 0" if joint == "hinge" else fv(m.slide_axis(bone))
            if body == "rear_lift":
                out.append('%s  <joint name="%s" type="hinge" axis="%s" range="%s %s" damping="10" armature="1"/>' % (
                    pad, body, REAR_LIFT_AXIS, f(deg(P["rear_lift_deg"][0])), f(deg(P["rear_lift_deg"][1]))))
            elif body == "rear_spring":
                sp = P["rear_spring"]
                top = sp["travel_cm"][0] * UE_TO_M
                out.append('%s  <joint name="%s" type="slide" axis="%s" range="%s %s" stiffness="%s" springref="%s" damping="%s" armature="5"/>' % (
                    pad, body, axis, f(top), f(sp["travel_cm"][1] * UE_TO_M), f(sp["stiffness"]), f(top - sp["preload"] / sp["stiffness"]), f(sp["damping"])))
            else:
                out.append('%s  <joint name="%s" class="linkage" type="%s" axis="%s"/>' % (pad, body, joint, axis))
            out.append('%s  <inertial pos="0 0 0" mass="%s" diaginertia="0.0005 0.0005 0.0005"/>' % (pad, f(M["linkage"])))
            out += [pad + "  " + g for g in m.visuals(body)]
            out += linkages(body, ind + 2)
            out.append('%s</body>' % pad)
        return out

    for s in ("l", "r"):
        tr, el, dw = "translator_" + s, "elevator_" + s, "drive_wheel_" + s
        L.append('      <body name="%s" pos="%s">' % (tr, fv(m.rel(tr, "chassis"))))
        L.append('        <joint name="%s" type="slide" axis="1 0 0" range="%s %s" damping="200" armature="5"/>' % (
            tr, f(P["translator_cm"][0] * UE_TO_M), f(P["translator_cm"][1] * UE_TO_M)))
        L += ["        " + g for g in m.boxes(tr, M["translator"])]
        L += ["        " + g for g in m.visuals(tr)]
        L.append('        <body name="%s" pos="%s">' % (el, fv(m.rel(el, tr))))
        L.append('          <joint name="%s" type="hinge" axis="0 1 0" range="%s %s" damping="20" armature="2"/>' % (
            el, f(deg(P["elevator_deg"][0])), f(deg(P["elevator_deg"][1]))))
        L += ["          " + g for g in m.boxes(el, M["elevator"])]
        L += ["          " + g for g in m.visuals(el)]
        L += linkages(el, 10)
        radius, width = m.wheel_size(DRIVE_WHEELS[s])
        L.append('          <body name="%s" pos="%s">' % (dw, fv(m.rel(dw, el))))
        L.append('            <joint name="%s" type="hinge" axis="0 1 0" damping="0.05" armature="0.01"/>' % dw)
        L.append('            <geom name="%s" class="collision" type="cylinder" fromto="0 %s 0 0 %s 0" size="%s" mass="%s"/>' % (
            dw, f(-width / 2), f(width / 2), f(radius), f(M["drive_wheel"])))
        L += ["            " + g for g in m.visuals(dw)]
        L.append('          </body>')
        L.append('        </body>')
        L.append('      </body>')

    for arm, axis in (("front_arm", "0 1 0"), ("rear_arm", "0 -1 0")):
        # The rear arm's wheels trail its pivot, so its axis is reversed: positive is wheels down at both ends.
        # The rear arm is not driven: the rear chain pushes it through the damper.
        L.append('      <body name="%s" pos="%s">' % (arm, fv(m.rel(arm, "chassis"))))
        L.append('        <joint name="%s" type="hinge" axis="%s" range="%s %s" damping="%s" armature="%s"/>' % (
            arm, axis, f(deg(P["caster_arm_deg"][0])), f(deg(P["caster_arm_deg"][1])), "10" if arm == "front_arm" else "1",
            "1" if arm == "front_arm" else "0.05"))
        L += ["        " + g for g in m.boxes(arm, M["caster_arm"])]
        L += ["        " + g for g in m.visuals(arm)]
        for wname, (parent, _) in OMNI_WHEELS.items():
            if parent == arm:
                L += omni_wheel(m, wname, arm, P, 8, powered_front and arm == "front_arm")
        L.append('      </body>')
    L += linkages("chassis", 6)
    L.append('    </body>')
    L.append('  </worldbody>')

    L.append('  <equality>')
    for b1, anchor, b2 in m.closures():
        L.append('    <connect body1="%s" body2="%s" anchor="%s" solref="0.005 1" solimp="0.99 0.999 0.001"/>' % (b1, b2, fv(anchor)))
    L.append('  </equality>')

    L.append('  <actuator>')
    for s in ("l", "r"):
        L.append('    <motor name="drive_%s" joint="drive_wheel_%s" ctrlrange="%s %s"/>' % (s, s, f(-P["drive"]["torque"]), f(P["drive"]["torque"])))
    if powered_front:
        t = P["front_omni_drive"]["torque"]
        for s in ("l", "r"):
            L.append('    <motor name="front_omni_%s" joint="front_omni_%s" ctrlrange="%s %s"/>' % (s, s, f(-t), f(t)))
    for s in ("l", "r"):
        e, t = P["elevator"], P["translator"]
        L.append('    <position name="elevator_%s" joint="elevator_%s" kp="%s" kv="%s" forcerange="%s %s" ctrlrange="%s %s"/>' % (
            s, s, f(e["kp"]), f(e["kv"]), f(-e["force"]), f(e["force"]), f(deg(P["elevator_deg"][0])), f(deg(P["elevator_deg"][1]))))
        L.append('    <position name="translator_%s" joint="translator_%s" kp="%s" kv="%s" forcerange="%s %s" ctrlrange="%s %s"/>' % (
            s, s, f(t["kp"]), f(t["kv"]), f(-t["force"]), f(t["force"]), f(P["translator_cm"][0] * UE_TO_M), f(P["translator_cm"][1] * UE_TO_M)))
    for a, c, rng in (("front_arm", P["caster_arm"], P["caster_arm_deg"]), ("rear_lift", P["rear_lift"], P["rear_lift_deg"])):
        L.append('    <position name="%s" joint="%s" kp="%s" kv="%s" forcerange="%s %s" ctrlrange="%s %s"/>' % (
            a, a, f(c["kp"]), f(c["kv"]), f(-c["force"]), f(c["force"]), f(deg(rng[0])), f(deg(rng[1]))))
    L.append('  </actuator>')

    L.append('  <sensor>')
    L.append('    <framequat name="chassis_quat" objtype="body" objname="chassis"/>')
    L.append('    <framepos name="chassis_pos" objtype="body" objname="chassis"/>')
    L.append('  </sensor>')
    # The reference pose, every lift at 0: what the Unreal pawn is put in (and stood on the ground) at spawn.
    L.append('  <keyframe><key name="home"/></keyframe>')
    L.append('</mujoco>')
    return "\n".join(L) + "\n"


SCENE = """<mujoco model="%(name)s_scene">
  <!-- Generated by build_mebot_mjcf.py: the MeBot on a floor, facing a 15 cm curb 1.5 m ahead. -->
  <include file="%(name)s.xml"/>
  <visual><headlight diffuse="0.6 0.6 0.6" ambient="0.3 0.3 0.3"/><global azimuth="135" elevation="-20"/></visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1="0.55 0.55 0.55" rgb2="0.45 0.45 0.45" width="512" height="512"/>
    <material name="grid" texture="grid" texrepeat="8 8"/>
  </asset>
  <worldbody>
    <light pos="0 0 4" dir="0 0 -1"/>
    <geom name="floor" type="plane" size="20 20 0.1" material="grid" contype="1" conaffinity="1"/>
    <geom name="curb" type="box" pos="2.5 0 0.075" size="1 3 0.075" rgba="0.78 0.55 0.3 1" contype="1" conaffinity="1"/>
  </worldbody>
</mujoco>
"""


def write(path, text):
    with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(path + ".tmp", path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rider-kg", type=float, default=PARAMS["rider_kg"])
    args = ap.parse_args()
    P = dict(PARAMS, rider_kg=args.rider_kg)
    with open(os.path.join(HERE, "source", "mebot_ue.json"), encoding="utf-8") as fh:
        ue = json.load(fh)
    with open(os.path.join(HERE, "source", "mebot_meshes.json"), encoding="utf-8") as fh:
        meshes = json.load(fh)
    m = Model(ue, meshes)
    for key, bones in ASSET_RANGES.items():
        if P[key] is None:
            ranges = {m.asset_range(b) for b in bones}
            if len(ranges) != 1:
                raise ValueError("%s: the physics asset's limits differ across %s: %s" % (key, bones, sorted(ranges)))
            P[key] = ranges.pop()
    for kind in ("front", "rear"):
        a, b = m.omni[kind + "_omni_l"], m.omni[kind + "_omni_r"]
        if a["n"] != b["n"] or any(abs(a[k] - b[k]) > 5e-4 for k in ("axis_radius", "radius", "half_length")):
            raise ValueError("the %s omni wheels' rollers differ left to right" % kind)
        write_stl(os.path.join(HERE, "meshes", "omni_%s_roller.stl" % kind), roller_mesh(a["radius"], a["axis_radius"], a["half_length"]))
    for powered in (False, True):
        name = "mebot_powered_front" if powered else "mebot"
        write(os.path.join(HERE, name + ".xml"), build(m, P, powered))
        write(os.path.join(HERE, name + "_scene.xml"), SCENE % {"name": name})
    print("wrote mebot.xml, mebot_powered_front.xml and their scenes (floor at Unreal z = %.2f cm)" % m.ground_z)
    for s in ("l", "r"):
        r, w = m.wheel_size(DRIVE_WHEELS[s])
        print("  drive wheel %s: radius %.3f, width %.3f" % (s, r, w))
    for name, o in m.omni.items():
        print("  %s: 2 rows x %d rollers, radius %.4f, roller axis at %.4f, rollers %.1f mm long, tread %+.1f mm from the bone" % (
            name, o["n"], o["radius"], o["axis_radius"], o["half_length"] * 2000, o["y_centre"] * 1000))
    print("  ranges: elevators %s deg, caster arms %s deg, translators %s cm, rear lift %s deg" % (
        P["elevator_deg"], P["caster_arm_deg"], P["translator_cm"], P["rear_lift_deg"]))
    print("  %d visual meshes, %d loop closures" % (sum(1 for p in m.parts if p["material"] != OMNI_RUBBER), len(m.closures())))


if __name__ == "__main__":
    main()
