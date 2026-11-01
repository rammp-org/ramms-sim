#!/usr/bin/env python3
"""Build the MeBot's MJCF (mebot.xml) and a test scene (mebot_scene.xml) from its Unreal geometry.

    python mujoco/mebot/build_mebot_mjcf.py [--rider-kg 75]

Reads source/mebot_ue.json (extract_ue_mebot.py, from the public ramms-assets MeBot) and writes, next to this
file, mebot.xml (the robot) and mebot_scene.xml (a floor and a 15 cm curb, for check_mebot.py and the viewer).

The model, in MuJoCo's frame (m; X forward, Y left, Z up; the floor at z = 0 under the wheels):

  chassis              free joint; the frame box, the caster-arm mounts, the seat and its rider
    translator_l / _r  slide along X: the drive-wheel plate (left / right independently)
      elevator_l / _r  hinge about Y at the swing arm's pivot: the drive wheel's height
        drive_wheel_*  hinge about Y, motor-driven
    front_arm          hinge about Y: one arm carrying both front omni wheels
      front_omni_*     passive omni wheels: a hub on the axle and two staggered rows of passive rollers
    rear_arm           the same at the rear (the Unreal model's suspension damper is not modelled)
      rear_omni_*

Lift joints are driven directly (position actuators at the joints; the real linear actuators and their
linkages are not modelled). Their sign: a positive elevator / arm angle puts its wheels down, raising the
chassis; a positive translator moves its drive wheel forward. Drive wheels: torque motors, positive forward.

Kinematics -- pivots, wheel centres and sizes, collision boxes -- come from the Unreal asset. Everything in
PARAMS is a PLACEHOLDER until measured on the robot: the Unreal asset has no masses (Unreal derived them from
the boxes' volumes) and its drives are not the robot's. The joint ranges are the Unreal physics asset's limits
(45 deg on the elevators and arms, 40 cm on the translators), kept until the robot's are known.
The speeds in PARAMS are for whatever commands these position actuators (the Unreal motor table's
MaxVelocity; check_mebot.py's ramps): MuJoCo's position actuators have none.
"""
import argparse
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------- PLACEHOLDERS (to be measured)
PARAMS = {
    # Masses, kg. The robot without its rider comes to about 87 kg.
    "mass": {"chassis": 50.0, "translator": 3.0, "elevator": 9.0, "drive_wheel": 2.5, "caster_arm": 2.5,
             "omni_hub": 0.5, "omni_roller": 0.025},
    "rider_kg": 75.0,                      # --rider-kg; 0 leaves the seat empty
    "rider_above_seat_cm": 25.0,           # the rider's centre of mass above the seat socket
    # Joint ranges.
    "elevator_deg": (-45.0, 45.0),         # the Unreal physics asset's limits
    "caster_arm_deg": (-45.0, 45.0),
    "translator_cm": (-40.0, 40.0),
    # Actuators: position gain, velocity gain, force/torque limit; speeds for the commands.
    "elevator": {"kp": 3000.0, "kv": 200.0, "force": 600.0, "speed_deg_s": 6.0},      # N*m/rad, N*m*s/rad, N*m
    "caster_arm": {"kp": 2000.0, "kv": 100.0, "force": 400.0, "speed_deg_s": 6.0},
    "translator": {"kp": 30000.0, "kv": 2000.0, "force": 1500.0, "speed_cm_s": 2.0},  # N/m, N*s/m, N
    "drive": {"torque": 60.0, "max_speed_rad_s": 9.0},                                 # N*m; 9 rad/s ~ 6 km/h
    # Omni wheels: rollers per row (two staggered rows) and the rollers' radius as a fraction of the wheel's.
    "omni_rollers_per_row": 6,
    "omni_roller_radius_frac": 0.22,
}
# ---------------------------------------------------------------------------

UE_TO_M = 0.01

# MJCF body -> the Unreal bones it is made of: the first is its frame (the joint pivot), the rest ride on it.
BODIES = {
    "chassis": ["mebot", "front_caster_arm_mount", "rear_caster_arm_mount"],
    "translator_l": ["dw_main_plate_l"], "translator_r": ["dw_main_plate_r"],
    "elevator_l": ["motor_swing_arm_l", "drive_motor_l", "motor_elevator_l"],
    "elevator_r": ["motor_swing_arm_r", "drive_motor_r", "motor_elevator_r"],
    "front_arm": ["front_caster_swing_arm"], "rear_arm": ["rear_caster_swing_arm"],
}
DRIVE_WHEELS = {"l": "drive_wheel_l", "r": "drive_wheel_r"}
OMNI_WHEELS = {"front_omni_l": ("front_arm", "front_caster_wheel_l"), "front_omni_r": ("front_arm", "front_caster_wheel_r"),
               "rear_omni_l": ("rear_arm", "rear_casteer_wheel_l"), "rear_omni_r": ("rear_arm", "rear_caster_wheel_r")}

# Collision: the robot's geoms touch the world only (contype 2 / conaffinity 1 against the world's 1 / 1).
ROBOT_COLLIDE = 'contype="2" conaffinity="1"'
VISUAL = 'contype="0" conaffinity="0" group="2" mass="0"'


def f(x):
    return "%.5g" % x


def fv(v):
    return " ".join(f(x) for x in v)


class Model:
    def __init__(self, ue):
        self.bones = {b["name"]: b["component"]["loc"] for b in ue["bones"]}
        self.prims = {b["bone"]: b["primitives"] for b in ue["bodies"]}
        self.sockets = {s["name"]: s for s in ue["sockets"]}
        for b, ps in self.prims.items():
            for p in ps:
                if any(abs(a) > 1e-3 for a in p.get("rpy", (0, 0, 0))):
                    raise ValueError("%s has a rotated primitive; the conversion assumes axis-aligned ones" % b)
        # The floor: the lowest point of any wheel at the reference pose.
        self.ground_z = min(self.bones[b][2] + h["min"][2] for b in list(DRIVE_WHEELS.values()) + [w for _, w in OMNI_WHEELS.values()]
                            for h in self.hulls(b))

    def hulls(self, bone):
        return [p for p in self.prims.get(bone, []) if p["type"] == "hull"]

    def mj(self, p):
        """An Unreal component-space point (cm) in MuJoCo's frame (m, Y left, floor at 0)."""
        return [p[0] * UE_TO_M, -p[1] * UE_TO_M, (p[2] - self.ground_z) * UE_TO_M]

    def rel(self, p, frame_bone):
        """p (Unreal component space) relative to frame_bone's origin, in MuJoCo's axes and metres."""
        o = self.bones[frame_bone]
        return [(p[0] - o[0]) * UE_TO_M, -(p[1] - o[1]) * UE_TO_M, (p[2] - o[2]) * UE_TO_M]

    def boxes(self, bones, frame_bone, mass, name):
        """Each bone's physics-asset boxes as geoms in frame_bone's body; the body's mass on the largest."""
        out, vols = [], []
        for b in bones:
            for p in self.prims.get(b, []):
                if p["type"] != "box":
                    continue
                c = [self.bones[b][i] + p["center"][i] for i in range(3)]
                half = [s * UE_TO_M / 2 for s in p["size"]]
                out.append((b, self.rel(c, frame_bone), half))
                vols.append(half[0] * half[1] * half[2])
        big = vols.index(max(vols))
        lines = []
        for i, (b, pos, half) in enumerate(out):
            m = ' mass="%s"' % f(mass) if i == big else ' mass="0"'
            lines.append('<geom name="%s_%s" type="box" pos="%s" size="%s" %s%s rgba="%s"/>' % (
                name, b, fv(pos), fv(half), ROBOT_COLLIDE, m, "0.35 0.36 0.4 1" if i == big else "0.45 0.46 0.5 1"))
        return lines

    def wheel_size(self, bone):
        h = self.hulls(bone)[0]
        ext = [h["max"][i] - h["min"][i] for i in range(3)]
        return (ext[0] + ext[2]) / 4 * UE_TO_M, ext[1] * UE_TO_M  # radius, width


def omni_wheel(model, name, parent_bone, wheel_bone, P, ind):
    """A passive omni wheel: a hub on the axle (Y) and two staggered rows of rollers, each a capsule on a
    passive hinge along its own axis (the wheel's tangent), so the wheel rolls freely sideways."""
    radius, width = model.wheel_size(wheel_bone)
    n = P["omni_rollers_per_row"]
    r = P["omni_roller_radius_frac"] * radius
    rc = radius - r                                      # roller axes' distance from the axle
    half_len = 0.9 * rc * math.sin(math.pi / n) - r      # capsule half-length (cylinder part)
    pos = model.rel(model.bones[wheel_bone], parent_bone)
    pad = " " * ind
    hub = P["mass"]["omni_hub"]
    i_axle = 0.5 * hub * rc ** 2                         # a disc of the rollers' radius, as thick as the wheel
    i_across = 0.25 * hub * rc ** 2 + hub * width ** 2 / 12
    lines = ['%s<body name="%s" pos="%s">' % (pad, name, fv(pos)),
             '%s  <joint name="%s" type="hinge" axis="0 1 0" damping="0.01" armature="0.0005"/>' % (pad, name),
             '%s  <geom name="%s_hub" type="cylinder" fromto="0 %s 0 0 %s 0" size="%s" %s rgba="0.2 0.2 0.22 1"/>' % (
                 pad, name, f(-width / 2), f(width / 2), f(rc * 0.8), VISUAL),
             '%s  <inertial pos="0 0 0" mass="%s" diaginertia="%s %s %s"/>' % (pad, f(hub), f(i_across), f(i_axle), f(i_across))]
    for row, dy in enumerate((-width / 4, width / 4)):
        for k in range(n):
            phi = 2 * math.pi * (k + 0.5 * row) / n          # 0 at the bottom
            c = [rc * math.sin(phi), dy, -rc * math.cos(phi)]
            t = [math.cos(phi), 0.0, math.sin(phi)]          # the tangent: the roller's axis
            a = [-half_len * x for x in t]
            b = [half_len * x for x in t]
            rn = "%s_roller%d%d" % (name, row, k)
            lines += ['%s  <body name="%s" pos="%s">' % (pad, rn, fv(c)),
                      '%s    <joint name="%s" type="hinge" axis="%s" damping="0.0005" armature="0.00001"/>' % (pad, rn, fv(t)),
                      '%s    <geom name="%s" type="capsule" fromto="%s %s" size="%s" mass="%s" %s priority="1" solref="0.005 1" '
                      'friction="1 0.005 0.0001" rgba="0.1 0.1 0.1 1"/>' % (
                          pad, rn, fv(a), fv(b), f(r), f(P["mass"]["omni_roller"]), ROBOT_COLLIDE),
                      '%s  </body>' % pad]
    lines.append('%s</body>' % pad)
    return lines


def build(ue, P):
    m = Model(ue)
    M = P["mass"]
    deg = math.radians
    L = []
    L.append('<mujoco model="mebot">')
    L.append('  <!-- Generated by build_mebot_mjcf.py from source/mebot_ue.json; edit the generator, not this file.')
    L.append('       Masses, joint ranges and actuator limits are PLACEHOLDERS (see PARAMS). -->')
    L.append('  <compiler angle="radian" autolimits="true"/>')
    L.append('  <option timestep="0.002" integrator="implicitfast" cone="elliptic" impratio="10"/>')
    L.append('  <default>')
    L.append('    <geom friction="1 0.005 0.0001" solref="0.01 1"/>')
    L.append('    <joint damping="0"/>')
    L.append('  </default>')
    L.append('  <worldbody>')
    chassis_pos = m.mj(m.bones["mebot"])
    L.append('    <body name="chassis" pos="%s">' % fv([chassis_pos[0], chassis_pos[1], chassis_pos[2] + 0.005]))
    L.append('      <freejoint name="root"/>')
    L += ["      " + g for g in m.boxes(BODIES["chassis"], "mebot", M["chassis"], "chassis")]
    seat = m.sockets["seat_base"]
    seat_c = [m.bones[seat["bone"]][i] + seat["loc"][i] for i in range(3)]
    L.append('      <site name="seat" pos="%s" size="0.02"/>' % fv(m.rel(seat_c, "mebot")))
    if P["rider_kg"] > 0:
        rider = list(seat_c)
        rider[2] += P["rider_above_seat_cm"]
        L.append('      <body name="rider" pos="%s">' % fv(m.rel(rider, "mebot")))
        L.append('        <geom name="rider" type="box" size="0.2 0.2 0.3" %s rgba="0.6 0.45 0.35 0.35"/>' % VISUAL)
        L.append('        <inertial pos="0 0 0" mass="%s" diaginertia="%s %s %s"/>' % (
            f(P["rider_kg"]), f(P["rider_kg"] * 0.13 / 12 * 4), f(P["rider_kg"] * 0.13 / 12 * 4), f(P["rider_kg"] * 0.08 / 12 * 4)))
        L.append('      </body>')

    for s in ("l", "r"):
        plate = "dw_main_plate_" + s
        arm = "motor_swing_arm_" + s
        wheel = DRIVE_WHEELS[s]
        L.append('      <body name="translator_%s" pos="%s">' % (s, fv(m.rel(m.bones[plate], "mebot"))))
        L.append('        <joint name="translator_%s" type="slide" axis="1 0 0" range="%s %s" damping="200" armature="5"/>' % (
            s, f(P["translator_cm"][0] * UE_TO_M), f(P["translator_cm"][1] * UE_TO_M)))
        L += ["        " + g for g in m.boxes(BODIES["translator_" + s], plate, M["translator"], "translator_" + s)]
        L.append('        <body name="elevator_%s" pos="%s">' % (s, fv(m.rel(m.bones[arm], plate))))
        L.append('          <joint name="elevator_%s" type="hinge" axis="0 1 0" range="%s %s" damping="20" armature="2"/>' % (
            s, f(deg(P["elevator_deg"][0])), f(deg(P["elevator_deg"][1]))))
        L += ["          " + g for g in m.boxes(BODIES["elevator_" + s], arm, M["elevator"], "elevator_" + s)]
        radius, width = m.wheel_size(wheel)
        L.append('          <body name="drive_wheel_%s" pos="%s">' % (s, fv(m.rel(m.bones[wheel], arm))))
        L.append('            <joint name="drive_wheel_%s" type="hinge" axis="0 1 0" damping="0.05" armature="0.01"/>' % s)
        L.append('            <geom name="drive_wheel_%s" type="cylinder" fromto="0 %s 0 0 %s 0" size="%s" mass="%s" %s '
                 'friction="1 0.005 0.0001" rgba="0.12 0.12 0.12 1"/>' % (s, f(-width / 2), f(width / 2), f(radius), f(M["drive_wheel"]), ROBOT_COLLIDE))
        L.append('          </body>')
        L.append('        </body>')
        L.append('      </body>')

    for arm_body, bone, axis in (("front_arm", "front_caster_swing_arm", "0 1 0"), ("rear_arm", "rear_caster_swing_arm", "0 -1 0")):
        # The rear arm's wheels trail its pivot, so its axis is reversed: positive is wheels down at both ends.
        L.append('      <body name="%s" pos="%s">' % (arm_body, fv(m.rel(m.bones[bone], "mebot"))))
        L.append('        <joint name="%s" type="hinge" axis="%s" range="%s %s" damping="10" armature="1"/>' % (
            arm_body, axis, f(deg(P["caster_arm_deg"][0])), f(deg(P["caster_arm_deg"][1]))))
        L += ["        " + g for g in m.boxes(BODIES[arm_body], bone, M["caster_arm"], arm_body)]
        for wname, (parent, wbone) in OMNI_WHEELS.items():
            if parent == arm_body:
                L += omni_wheel(m, wname, bone, wbone, P, 8)
        L.append('      </body>')
    L.append('    </body>')
    L.append('  </worldbody>')

    L.append('  <actuator>')
    for s in ("l", "r"):
        L.append('    <motor name="drive_%s" joint="drive_wheel_%s" ctrlrange="%s %s"/>' % (s, s, f(-P["drive"]["torque"]), f(P["drive"]["torque"])))
    for s in ("l", "r"):
        e, t = P["elevator"], P["translator"]
        L.append('    <position name="elevator_%s" joint="elevator_%s" kp="%s" kv="%s" forcerange="%s %s" ctrlrange="%s %s"/>' % (
            s, s, f(e["kp"]), f(e["kv"]), f(-e["force"]), f(e["force"]), f(deg(P["elevator_deg"][0])), f(deg(P["elevator_deg"][1]))))
        L.append('    <position name="translator_%s" joint="translator_%s" kp="%s" kv="%s" forcerange="%s %s" ctrlrange="%s %s"/>' % (
            s, s, f(t["kp"]), f(t["kv"]), f(-t["force"]), f(t["force"]), f(P["translator_cm"][0] * UE_TO_M), f(P["translator_cm"][1] * UE_TO_M)))
    for a in ("front_arm", "rear_arm"):
        c = P["caster_arm"]
        L.append('    <position name="%s" joint="%s" kp="%s" kv="%s" forcerange="%s %s" ctrlrange="%s %s"/>' % (
            a, a, f(c["kp"]), f(c["kv"]), f(-c["force"]), f(c["force"]), f(deg(P["caster_arm_deg"][0])), f(deg(P["caster_arm_deg"][1]))))
    L.append('  </actuator>')

    L.append('  <sensor>')
    L.append('    <framequat name="chassis_quat" objtype="body" objname="chassis"/>')
    L.append('    <framepos name="chassis_pos" objtype="body" objname="chassis"/>')
    L.append('  </sensor>')
    L.append('</mujoco>')
    return "\n".join(L) + "\n", m


SCENE = """<mujoco model="mebot_scene">
  <!-- Generated by build_mebot_mjcf.py: the MeBot on a floor, facing a 15 cm curb 1.5 m ahead. -->
  <include file="mebot.xml"/>
  <visual><headlight diffuse="0.6 0.6 0.6" ambient="0.3 0.3 0.3"/><global azimuth="135" elevation="-20"/></visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1="0.55 0.55 0.55" rgb2="0.45 0.45 0.45" width="512" height="512"/>
    <material name="grid" texture="grid" texrepeat="8 8"/>
  </asset>
  <worldbody>
    <light pos="0 0 4" dir="0 0 -1"/>
    <geom name="floor" type="plane" size="20 20 0.1" material="grid" contype="1" conaffinity="1"/>
    <geom name="curb" type="box" pos="2.5 0 0.075" size="1 3 0.075" rgba="0.7 0.7 0.68 1" contype="1" conaffinity="1"/>
  </worldbody>
</mujoco>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rider-kg", type=float, default=PARAMS["rider_kg"])
    ap.add_argument("--source", default=os.path.join(HERE, "source", "mebot_ue.json"))
    args = ap.parse_args()
    P = dict(PARAMS, rider_kg=args.rider_kg)
    with open(args.source, encoding="utf-8") as fh:
        ue = json.load(fh)
    xml, m = build(ue, P)
    for name, text in (("mebot.xml", xml), ("mebot_scene.xml", SCENE)):
        p = os.path.join(HERE, name)
        with open(p + ".tmp", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(p + ".tmp", p)
    print("wrote mebot.xml, mebot_scene.xml (floor at Unreal z = %.2f cm)" % m.ground_z)
    for s in ("l", "r"):
        r, w = m.wheel_size(DRIVE_WHEELS[s])
        print("  drive wheel %s at %s m, radius %.3f, width %.3f" % (s, fv(m.mj(m.bones[DRIVE_WHEELS[s]])), r, w))
    for name, (_, b) in OMNI_WHEELS.items():
        r, w = m.wheel_size(b)
        print("  %s at %s m, radius %.3f, width %.3f" % (name, fv(m.mj(m.bones[b])), r, w))


if __name__ == "__main__":
    main()
