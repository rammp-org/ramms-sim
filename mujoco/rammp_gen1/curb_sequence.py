#!/usr/bin/env python3
"""The RAMMP Gen1's curb crossing as a scripted sequence in MuJoCo: the reference for its curb controller.

    python mujoco/rammp_gen1/curb_sequence.py [--variant standard|powered_front] [--dir up|down] [--height 0.15]
                                         [--stance FRONT ELEVATORS REAR] [--sequence step|blended [--crawl 0.12]]
                                         [--clip out.mp4 [--speedup 8]]

--sequence step (the default, and what the Unreal controller does) stops for each step, below. --sequence blended
(powered_front only) is how the real robot's own sequence crosses: it keeps rolling at a crawl and moves each pair as
it reaches the edge, each touchdown one move until the pair carries load; it slows to a stop short of the edge only
for a pair that is not up yet. The order and the rule are the same; the drive wheels go over with the translators
where they are, and are drawn aft once down, as it rolls on to the rear's step. It prints each event, and the time
from the front omni wheels reaching the curb face or edge to the rear omni wheels down and to stopped, which the
robot's videos put at about 15 and 17 s up, and 10 and 13 s down, over a 15 cm curb.

The chassis stays level and rides just under curb height (raised for a climb, lowered for a descent), so its
frame clears the curb edge: the height is picked from where every support reaches the road and, lifted, clears
the upper level (the run aborts at once if none works). Each support -- front omni wheels, drive wheels, rear
omni wheels -- is lifted over the edge and set down in turn, and every touchdown lowers from the wheels' measured
height until the pair carries load (as a load or motor-current reading would tell the controller). The rear is
sprung, so it sags as it takes load: while its wheels are down, its lift is trimmed against the chassis's pitch.
The rule: the rear omni wheels are not lifted until both drive wheels are on the far level, translated aft and
carrying load, with the centre of mass ahead of their axle; the run aborts if that does not hold. On a descent
the chassis comes down on the drive and front omni wheels before the rear is set down, as the rear reaches least.

The robot starts in a stance (--stance, the front arm's, the elevators' and the rear lift's angles in degrees;
the outdoor stance is about -14 9 0: the front omni wheels up, the drive wheels down for ground clearance). Front
omni wheels that start off the ground stay up: the chassis is levelled with them at least as high as the crossing
needs, and they are not set down only to be lifted again at the curb. A crossing ends with every lift back where
it started.

standard       with the drive wheels up, the translators carry them forward over the edge; set down, they are
               translated aft braked, which pulls the chassis forward over them.
powered_front  with the drive wheels up, the front omni wheels' hub motors pull the robot forward while the
               translators bring the drive wheels aft, so they land already aft.

Needs the mujoco Python package (and imageio-ffmpeg and Pillow for --clip). Prints each phase with its duration,
the chassis's pitch and roll and the wheels in contact; the exit code is 1 if the crossing aborts.
"""
import argparse
import math
import os
import sys

import mujoco
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_rammp_gen1_mjcf as B  # noqa: E402

P = B.PARAMS
FACE = 1.5            # the curb face's x (m); up: the upper level ahead, down: the robot starts on it
LIFTS = ("elevator_l", "elevator_r", "translator_l", "translator_r", "front_arm", "rear_lift")
TOUCH = {"drive": ("drive_wheel_l", "drive_wheel_r"), "front_arm": ("front_omni_l", "front_omni_r"), "rear_lift": ("rear_omni_l", "rear_omni_r")}
AFT = -0.30           # the translators' aft position for the rear lift (m)
LOADED = 0.10         # the rule: each drive wheel carries this share of the weight before the rear lift
LEVEL_GAIN = 8.0      # the rear's levelling trim: rad/s of rear lift per rad of pitch, at most the rear lift's speed. Fast
                      # enough to level the chassis while the translators re-centre (3 s at 13 cm/s)
LAND = 0.12           # descents: the lifted drive wheels' centres this far past their radius beyond the edge (m), so the
                      # swing arms and motors, which trail the wheels, clear the edge as the wheels swing down


TOUCH_TOLERANCE = 0.008  # a wheel is down when its bottom is within this of the ground under it (m)

# --sequence blended: the robot rolls through the crossing, as the real robot's own sequence does (videos of it, Nov
# 2026: each pair of wheels goes over a 15 cm curb in 2-2.5 s while it keeps moving at about the translators' speed)
CRAWL = 0.12          # its speed through the crossing (m/s)
APPROACH = 0.25       # its speed until the front omni wheels are this close to the curb (m)
APPROACH_NEAR = 0.30
ACCEL = 0.5           # how fast its speed changes (m/s^2)
STOP_GAIN = 2.0       # slowing for a pair not ready for the edge: m/s per m left to the point it must stop at
CLEAR = 0.01          # a lifted pair is ready for the edge once its wheels are this far above the level they cross (m)
LEAD_UP = 0.05        # climbs: the drive wheels start up when they are this far from the curb face (m)
LEAD_DOWN = 0.10      # descents: the drive wheels start up when their axle is this far from the edge (m)
JOINTS = {"drive": ("elevator_l", "elevator_r"), "front_arm": ("front_arm",), "rear_lift": ("rear_lift",)}


def hull_margin(points, p):
    """The signed distance (m) from p to the boundary of the convex hull of points (x-y): positive inside. With
    fewer than three points off one line the hull is a segment or a point, and the margin is minus p's distance
    from it."""
    pts = sorted(set((round(a, 6), round(b, 6)) for a, b in points))
    if not pts:
        return -math.inf

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in pts:                              # Andrew's monotone chain
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    hull = lower[:-1] + upper[:-1]             # counter-clockwise
    if len(hull) < 3:
        def seg(a, b):
            ab = (b[0] - a[0], b[1] - a[1])
            L2 = ab[0] ** 2 + ab[1] ** 2
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / L2))
            return math.hypot(p[0] - a[0] - t * ab[0], p[1] - a[1] - t * ab[1])
        return -min(seg(hull[i], hull[(i + 1) % len(hull)]) for i in range(len(hull)))
    m = math.inf
    for i in range(len(hull)):
        a, b = hull[i], hull[(i + 1) % len(hull)]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        m = min(m, cross(a, b, p) / L)          # positive on the inner (left) side of a counter-clockwise edge
    return m


class Meter:
    """The crossing's measurements, sampled every EVERY steps (20 ms) from the crossing proper's start to its end:
    - the stability margin: the robot's centre of mass, straight down, against the convex hull of the contacts of
      the wheels on the ground carrying load (each over 10 N);
    - the frame's clearance: the least distance from any of the robot's geoms but its wheels' (the frame, the caster
      arms, the drive motors, the arm) to the curb's top edge, as MuJoCo's geom distance gives it;
    - the rider: the chassis's pitch, roll and pitch rate, and the acceleration at the rider's mass (gravity left
      out; low-passed at about 50 ms, since the contacts shake the chassis at the step's scale), fore/aft along the
      heading, vertical, and its magnitude;
    - stops: the chassis's speed under 2 cm/s for 0.2 s or more, once it has first moved (5 cm/s)."""
    EVERY = 10
    TAU = 0.05          # the low-pass on the rider's velocity and acceleration, and the pitch rate (s): as the Unreal meter's

    def __init__(self, cx):
        self.cx = cx
        m = cx.m
        self.on = False
        self.n = 0
        self.edge = m.geom("edge_probe").id
        self.rider = m.geom("rider").id
        root = m.body("chassis").id
        robot = {b for b in range(m.nbody) if m.body_rootid[b] == root}   # the robot is the chassis's tree
        self.frame = [g for g in range(m.ngeom) if m.geom_bodyid[g] in robot and m.geom_contype[g] and m.geom_bodyid[g] not in cx.support]
        self.rows = []
        self.reset()

    def reset(self):
        self.min_margin = (math.inf, 0.0, "")
        self.min_clear = (math.inf, 0.0, "", "")
        self.max_pitch = self.max_roll = self.max_rate = 0.0
        self.peak = {"fore": 0.0, "vert": 0.0, "mag": 0.0}
        self.sum_a2, self.n_a = 0.0, 0
        self.stops, self.stopped, self.moved, self.still = 0, 0.0, False, 0.0
        self.prev = None

    def start(self):
        self.reset()
        self.on = True
        self.t0 = self.cx.d.time

    def stop(self):
        self.on = False
        self.t1 = self.cx.d.time

    def step(self):
        if not self.on:
            return
        self.n += 1
        if self.n % self.EVERY:
            return
        cx, m, d = self.cx, self.cx.m, self.cx.d
        t = d.time
        # stability margin
        pts, f6 = [], np.zeros(6)
        for i in range(d.ncon):
            c = d.contact[i]
            og = c.geom2 if c.geom1 in cx.world else c.geom1 if c.geom2 in cx.world else None
            if og is None or m.geom_bodyid[og] not in cx.support:
                continue
            mujoco.mj_contactForce(m, d, i, f6)
            if f6[0] > 10.0:
                pts.append((c.pos[0], c.pos[1]))
        com = d.subtree_com[m.body("chassis").id]
        margin = hull_margin(pts, (com[0], com[1]))
        if margin < self.min_margin[0]:
            self.min_margin = (margin, t, cx.label)
        # the frame's clearance to the curb's edge
        fromto = np.zeros(6)
        clear, which = math.inf, ""
        for g in self.frame:
            dist = mujoco.mj_geomDistance(m, d, g, self.edge, 0.3, fromto) + 0.001   # from the edge line, not the probe's skin
            if dist < clear:
                clear, which = dist, m.geom(g).name or m.body(m.geom_bodyid[g]).name
        if clear < self.min_clear[0]:
            self.min_clear = (clear, t, which, cx.label)
        # the chassis and the rider
        pitch, roll = cx.pitch_roll()
        self.max_pitch, self.max_roll = max(self.max_pitch, abs(pitch)), max(self.max_roll, abs(roll))
        fwd = d.body("chassis").xmat.reshape(3, 3)[:, 0].copy()
        fwd[2] = 0.0
        fwd /= max(np.linalg.norm(fwd), 1e-9)
        p = d.geom_xpos[self.rider].copy()
        speed = float(np.dot(d.qvel[0:3], fwd))
        a_fore = a_vert = a_mag = 0.0
        if self.prev is not None:
            dt = t - self.prev["t"]
            k = dt / (self.TAU + dt)
            v = self.prev["v"] + k * ((p - self.prev["p"]) / dt - self.prev["v"])
            a = self.prev["a"] + k * ((v - self.prev["v"]) / dt - self.prev["a"])
            rate = self.prev["rate"] + k * ((pitch - self.prev["pitch"]) / dt - self.prev["rate"])
            if t - self.t0 > 0.2:                # the filters settled
                a_fore, a_vert = float(np.dot(a, fwd)), float(a[2])
                a_mag = float(math.hypot(a_fore, a_vert))
                self.peak = {"fore": max(self.peak["fore"], abs(a_fore)), "vert": max(self.peak["vert"], abs(a_vert)),
                             "mag": max(self.peak["mag"], a_mag)}
                self.sum_a2 += a_mag ** 2
                self.n_a += 1
                self.max_rate = max(self.max_rate, abs(rate))
            self.prev.update(p=p, v=v, a=a, rate=rate, pitch=pitch, t=t)
            self.moved |= abs(speed) >= 0.05
            if self.moved:
                if abs(speed) < 0.02:
                    self.still += dt
                    self.stopped += dt
                    if self.still - dt < 0.2 <= self.still:
                        self.stops += 1
                else:
                    self.still = 0.0
        else:
            self.prev = {"t": t, "p": p, "v": np.zeros(3), "a": np.zeros(3), "rate": 0.0, "pitch": pitch}
        self.rows.append((t, cx.label, com[0], com[2], pitch, roll, speed, margin, clear, a_fore, a_vert, a_mag))

    def summary(self):
        mm, mt, ml = self.min_margin
        cc, ct, cg, cl = self.min_clear
        rms = math.sqrt(self.sum_a2 / self.n_a) if self.n_a else 0.0
        return ["measurements (the crossing proper, %.1f s):" % (getattr(self, "t1", self.cx.d.time) - self.t0),
                "  stability margin: least %.1f cm, at %.1f s (%s)" % (mm * 100, mt, ml),
                "  frame clearance to the curb's edge: least %.1f cm, at %.1f s (%s; %s)" % (cc * 100, ct, cg, cl),
                "  chassis: pitch at most %.1f deg, roll %.1f deg, pitch rate %.1f deg/s" % (self.max_pitch, self.max_roll, self.max_rate),
                "  rider: acceleration peak %.2f m/s^2 (fore/aft %.2f, vertical %.2f), RMS %.2f" % (
                    self.peak["mag"], self.peak["fore"], self.peak["vert"], rms),
                "  stops: %d, %.1f s stopped (under 2 cm/s for 0.2 s or more, once it moved)" % (self.stops, self.stopped)]

    def write_csv(self, path):
        with open(path + ".tmp", "w") as f:
            f.write("t_s,activity,com_x_m,com_z_m,pitch_deg,roll_deg,speed_m_s,margin_m,frame_clearance_m,rider_a_fore_m_s2,rider_a_vert_m_s2,rider_a_m_s2\n")
            for r in self.rows:
                f.write("%.3f,\"%s\",%.4f,%.4f,%.3f,%.3f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f\n" % r)
        os.replace(path + ".tmp", path)


class Crossing:
    def __init__(self, variant, direction, h, clearance, stance=(0.0, 0.0, 0.0)):
        self.powered = variant == "powered_front"
        self.dir, self.h, self.clr = direction, h, clearance
        f, e, r = (math.radians(v) for v in stance)
        self.stance = {"front_arm": f, "elevator_l": e, "elevator_r": e, "rear_lift": r}
        spec = mujoco.MjSpec.from_file(os.path.join(HERE, "rammp_gen1_powered_front_scene.xml" if self.powered else "rammp_gen1_scene.xml"))
        curb = spec.geom("curb")
        if direction == "up":
            curb.pos, curb.size = [FACE + 1.5, 0, h / 2], [1.5, 3, h / 2]
        else:
            curb.pos, curb.size = [FACE - 3.0, 0, h / 2], [3.0, 3, h / 2]
            c = spec.body("chassis")
            c.pos = [c.pos[0] + 0.2, c.pos[1], c.pos[2] + h]
        # The curb's top edge, for the measurements' frame clearance: a thin capsule along it that collides with nothing.
        spec.worldbody.add_geom(name="edge_probe", type=mujoco.mjtGeom.mjGEOM_CAPSULE, fromto=[FACE, -3.0, h, FACE, 3.0, h],
                                size=[0.001, 0, 0], contype=0, conaffinity=0, group=5, rgba=[1, 0, 0, 0])
        self.m = m = spec.compile()
        self.d = mujoco.MjData(m)
        B.hold_arm_stowed(m, self.d)           # the arm stowed, and held there
        self.A = {m.actuator(i).name: i for i in range(m.nu)}
        self.r_dw = m.numeric("drive_wheel_radius").data[0]
        self.r_fo = m.numeric("front_omni_radius").data[0]
        self.r_ro = m.numeric("rear_omni_radius").data[0]
        deg = math.radians
        self.RATE = {"elevator_l": deg(P["elevator"]["speed_deg_s"]), "elevator_r": deg(P["elevator"]["speed_deg_s"]),
                     "front_arm": deg(P["caster_arm"]["speed_deg_s"]), "rear_lift": deg(P["rear_lift"]["speed_deg_s"]),
                     "translator_l": P["translator"]["speed_cm_s"] / 100, "translator_r": P["translator"]["speed_cm_s"] / 100}
        self.cmd = {k: 0.0 for k in LIFTS}
        self.goal = dict(self.cmd)
        self.rate = dict(self.RATE)
        self.integ = {k: 0.0 for k in LIFTS}
        self.drive = {"speed": None, "hold": {"l": 0.0, "r": 0.0}, "i": {"l": 0.0, "r": 0.0}}
        self.front = {"speed": None, "i": {"l": 0.0, "r": 0.0}}
        self.world = {m.geom("floor").id, m.geom("curb").id}
        self.support = {}
        for b in range(m.nbody):
            for s in ("drive_wheel_l", "drive_wheel_r", "front_omni_l", "front_omni_r", "rear_omni_l", "rear_omni_r"):
                if m.body(b).name.startswith(s):
                    self.support[b] = s
        self.weight = m.body_subtreemass[m.body("chassis").id] * 9.81
        self.tables = self.support_tables()
        d0 = mujoco.MjData(m)
        mujoco.mj_forward(m, d0)
        floor = min(d0.body(b).xpos[2] - r for b, r in (("drive_wheel_l", self.r_dw), ("front_omni_l", self.r_fo), ("rear_omni_l", self.r_ro)))
        self.belly = min(d0.geom_xpos[g][2] - m.geom_size[g][2] for g in range(m.ngeom)
                         if m.geom_bodyid[g] == m.body("chassis").id and m.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX and m.geom_contype[g]) - floor
        self.log, self.strikes = [], []
        self.label = ""
        self.worst = [0.0, 0.0]
        self.on_frame = None
        self.watch_rear = False                # while the chassis is pulled forward: the rear omni wheels must stay clear
        self.level = False                     # trim the sprung rear's lift to keep the chassis level: from the crossing's
        self.trim = 0.0                        # start, off while the rear is lifted and for the return to the stance
        self.start = dict(self.cmd)
        self.front_up = False
        self.roll = None                       # blended: the speed it rolls at (m/s), held back by self.limits
        self.limits = []                       # blended: callables, each the most speed it allows now (m/s) or None
        self.v = 0.0                           # blended: the speed it is rolling at
        self.tvel = 0.0                        # the translators' commanded speed (m/s)
        self.tds = {}                          # blended: touchdowns under way, per support
        self.events = {}                       # blended: when each event happened (s)
        self.t_event = 0.0
        self.meter = Meter(self)               # the crossing's measurements (on from the start of the crossing proper)

    # --- model geometry
    def support_tables(self):
        """b(q): how far each support's bottom rises (m, chassis level) from the reference pose as its joint turns:
        the drive wheels and front omni wheels from the kinematics; the sprung rear through its linkage, unloaded."""
        m, d0 = self.m, mujoco.MjData(self.m)
        mujoco.mj_forward(m, d0)
        out = {"rear_lift": self.rear_table()}
        for joint, body, r in (("elevator_l", "drive_wheel_l", self.r_dw), ("front_arm", "front_omni_l", self.r_fo)):
            adr = m.jnt_qposadr[m.joint(joint).id]
            dd = mujoco.MjData(m)
            qs = np.radians(np.arange(-45, 45.01, 0.25))
            bs = []
            for q in list(qs) + [0.0]:
                dd.qpos[:] = d0.qpos
                dd.qpos[adr] = q
                mujoco.mj_kinematics(m, dd)
                bs.append(dd.body(body).xpos[2] - r)
            out[joint] = (qs, np.array(bs[:-1]) - bs[-1])
        return out

    def rear_table(self):
        """The rear lift's b(q), unloaded: a copy of the robot with its chassis held, no gravity and no contacts,
        its rear lift stepped across its range and the linkage and damper left to settle at each step."""
        spec = mujoco.MjSpec.from_file(os.path.join(HERE, "rammp_gen1_powered_front_scene.xml" if self.powered else "rammp_gen1_scene.xml"))
        spec.delete(spec.joint("root"))
        for k in list(spec.keys):              # sized to the free robot's qpos
            spec.delete(k)
        m = spec.compile()
        m.opt.gravity[:] = 0
        m.opt.disableflags |= mujoco.mjtDisableBit.mjDSBL_CONTACT
        d = mujoco.MjData(m)
        mujoco.mj_kinematics(m, d)
        ref_bottom = d.body("rear_omni_l").xpos[2] - self.r_ro     # at the reference pose
        act = m.actuator("rear_lift").id
        lo, hi = m.actuator_ctrlrange[act]
        qs, bs = [], []
        for i, q in enumerate(list(np.linspace(0.0, lo, 21)) + list(np.linspace(lo, hi, 61))):
            d.ctrl[act] = q                      # out from the reference pose, then across, a step at a time
            for _ in range(150):
                mujoco.mj_step(m, d)
            if i >= 21:
                qs.append(d.joint("rear_lift").qpos[0])
                bs.append(d.body("rear_omni_l").xpos[2] - self.r_ro - ref_bottom)
        return np.array(qs), np.array(bs)

    def crossing_height(self):
        """The chassis's height above the road (m, from its reference pose) for the crossing, from the heights at
        which every support reaches the road and, lifted, clears the upper level by the clearance, and the frame
        clears the upper level by 2 cm: a quarter of the way up that band, since its top is what the sprung rear's
        sag and the touchdowns eat into."""
        lo = self.h + 0.02 - self.belly
        hi = 1.0
        for support, (_, bs) in self.tables.items():
            hi = min(hi, -bs.min())                  # reaches the road
            lo = max(lo, self.h + self.clr - bs.max())  # lifted, clears the upper level
        if lo > hi:
            raise RuntimeError("no crossing height works for a %.0f cm curb: the frame and the lifts need %.3f m, the "
                               "supports reach the road only from %.3f m" % (self.h * 100, lo, hi))
        H = lo + 0.25 * (hi - lo)
        self.log.append("        crossing height %.3f m (works from %.3f to %.3f)" % (H, lo, hi))
        return H

    def q_for(self, support, b):
        qs, bs = self.tables["elevator_l" if support == "drive" else support]
        if not (bs.min() - 1e-6 <= b <= bs.max() + 1e-6):
            raise RuntimeError("%s cannot reach %.3f m (range %.3f..%.3f)" % (support, b, bs.min(), bs.max()))
        return float(np.interp(b, bs[::-1], qs[::-1]))          # b falls as q rises

    def goals_for(self, heights):
        out = {}
        for k, b in heights.items():
            if k == "drive":
                out["elevator_l"] = out["elevator_r"] = self.q_for(k, b)
            else:
                out[k] = self.q_for(k, b)
        return out

    def x(self, body):
        return self.d.body(body).xpos[0]

    def rear_x(self):
        """The rear omni wheel further back: both are past the edge once it is."""
        return min(self.x("rear_omni_l"), self.x("rear_omni_r"))

    def pitch_roll(self):
        w, x, y, z = self.d.body("chassis").xquat
        return (math.degrees(math.asin(max(-1, min(1, 2 * (w * y - z * x))))),
                math.degrees(math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))))

    def contacts(self):
        """{support: (world geom, normal force N)} and the robot's other geoms touching the world."""
        m, d = self.m, self.d
        out, strikes, f6 = {}, [], np.zeros(6)
        for i in range(d.ncon):
            c = d.contact[i]
            og = c.geom2 if c.geom1 in self.world else c.geom1 if c.geom2 in self.world else None
            if og is None:
                continue
            wg = c.geom1 if og == c.geom2 else c.geom2
            mujoco.mj_contactForce(m, d, i, f6)
            b = m.geom_bodyid[og]
            if b in self.support:
                prev = out.get(self.support[b], ("", 0.0))
                out[self.support[b]] = (m.geom(wg).name, prev[1] + f6[0])
            else:
                strikes.append(m.geom(og).name or m.body(b).name)
        return out, strikes

    # --- control
    def step(self):
        m, d, dt = self.m, self.d, self.m.opt.timestep
        if self.level:                         # the rear sags as it takes load: trim its lift against the chassis's pitch
            lo, hi = m.actuator_ctrlrange[self.A["rear_lift"]]
            cap = self.RATE["rear_lift"] * dt   # the lift's speed, not the current move's
            self.trim -= max(-cap, min(cap, LEVEL_GAIN * math.radians(self.pitch_roll()[0]) * dt))
            self.trim = max(lo - self.cmd["rear_lift"], min(hi - self.cmd["rear_lift"], self.trim))
        for k in LIFTS:
            err = self.goal[k] - self.cmd[k]
            delta = max(-self.rate[k] * dt, min(self.rate[k] * dt, err))
            self.cmd[k] += delta
            if k == "translator_l":
                self.tvel = delta / dt
            q = d.joint(k).qpos[0]
            lim = 0.03 if k.startswith("translator") else math.radians(10)
            self.integ[k] = max(-lim, min(lim, self.integ[k] + 2.0 * (self.cmd[k] - q) * dt))   # the servo's integral action
            d.ctrl[self.A[k]] = self.cmd[k] + self.integ[k] + (self.trim if k == "rear_lift" else 0.0)
        if self.roll is not None:              # blended: rolling, as fast as every limit allows
            want = max(0.0, min([self.roll] + [v for v in (f() for f in self.limits) if v is not None]))
            self.v += max(-ACCEL * dt, min(ACCEL * dt, want - self.v))
            # the drive wheels roll at the chassis's speed plus their plates', so the chassis keeps its speed while
            # the translators move; lifted, they spin at it, so they meet the ground at its speed
            self.drive["speed"] = (self.v + self.tvel) / self.r_dw
            if self.powered:
                self.front["speed"] = self.v / self.r_fo
        tq = P["drive"]["torque"]
        for s in ("l", "r"):
            j = d.joint("drive_wheel_" + s)
            if self.drive.get("free"):         # freewheeling (blended: while their arms lift them off the ground)
                self.drive["i"][s] = d.ctrl[self.A["drive_" + s]] = 0.0
                continue
            if self.drive["speed"] is not None:
                e = self.drive["speed"] - j.qvel[0]
                self.drive["i"][s] = max(-3.0, min(3.0, self.drive["i"][s] + e * dt))
                u = 20.0 * e + 40.0 * self.drive["i"][s]
            else:                                # braked: hold the wheel's angle
                u = -400.0 * (j.qpos[0] - self.drive["hold"][s]) - 30.0 * j.qvel[0]
            d.ctrl[self.A["drive_" + s]] = max(-tq, min(tq, u))
        if self.powered:
            tq = P["front_omni_drive"]["torque"]
            for s in ("l", "r"):
                if self.front["speed"] is None:  # freewheeling
                    self.front["i"][s] = d.ctrl[self.A["front_omni_" + s]] = 0.0
                    continue
                e = self.front["speed"] - d.joint("front_omni_" + s).qvel[0]
                self.front["i"][s] = max(-1.0, min(1.0, self.front["i"][s] + e * dt))
                d.ctrl[self.A["front_omni_" + s]] = max(-tq, min(tq, 3.0 * e + 10.0 * self.front["i"][s]))
        mujoco.mj_step(m, d)
        _, strikes = self.contacts()
        for g in strikes:
            if not any(s[1] == g for s in self.strikes):
                self.strikes.append((self.label, g, round(d.time, 2)))
        p, r = self.pitch_roll()
        self.worst = [max(self.worst[0], abs(p)), max(self.worst[1], abs(r))]
        if self.watch_rear:
            near = self.x("rear_omni_l") + (self.r_ro + 0.02 if self.dir == "up" else 0.03)
            if near > FACE:
                raise RuntimeError("the rear omni wheels reached the curb while the chassis was pulled forward")
        self.meter.step()
        if self.on_frame:
            self.on_frame(self)

    def brake(self):
        self.drive["speed"] = None
        for s in ("l", "r"):
            self.drive["hold"][s] = self.d.joint("drive_wheel_" + s).qpos[0]

    def wait(self, seconds):
        t0 = self.d.time
        while self.d.time - t0 < seconds:
            self.step()

    def move(self, goals, settle=0.5, during=None):
        """Ramp the joints to goals together (each at the rate that lands them at the same time), then settle.
        during(): called each step, may drive the wheels; the move ends when it also returns True."""
        T = max([abs(v - self.cmd[k]) / self.RATE[k] for k, v in goals.items()] + [0.0])
        for k, v in goals.items():
            self.rate[k] = max(1e-6, abs(v - self.cmd[k]) / T) if T > 0 else self.RATE[k]
            self.goal[k] = v
        while True:
            self.step()
            done = all(abs(self.goal[k] - self.cmd[k]) < 1e-9 for k in LIFTS)
            if (during(done) if during else True) and done:
                break
        self.wait(settle)
        self.rate = dict(self.RATE)

    def drive_until(self, pred, speed=0.15, on=("drive",), limit=30.0, stop=True):
        """Drive at speed (m/s) on the drive wheels and/or the powered front omni wheels until pred(), then brake
        (unless stop is False: it drives on at that speed for the next drive_until)."""
        t0 = self.d.time
        self.set_speed(speed, on)
        while not pred():
            self.step()
            if self.d.time - t0 > limit:
                raise RuntimeError("driving timed out")
        if not stop:
            return
        self.set_speed(0.0, on)
        self.brake()
        self.front["speed"] = 0.0 if self.powered else None
        self.wait(0.8)
        self.front["speed"] = None

    def set_speed(self, v, on):
        if "drive" in on:
            self.drive["speed"] = v / self.r_dw
        if "front" in on:
            self.front["speed"] = v / self.r_fo

    def b_now(self, support):
        """A support's current height setting (b), from its joint."""
        qs, bs = self.tables["elevator_l" if support == "drive" else support]
        joints = ("elevator_l", "elevator_r") if support == "drive" else (support,)
        return float(np.interp(np.mean([self.d.joint(j).qpos[0] for j in joints]), qs, bs))

    def gap(self, support, level):
        """How far the higher of a support's two wheels is above level (m)."""
        r = {"drive": self.r_dw, "front_arm": self.r_fo, "rear_lift": self.r_ro}[support]
        return max(self.d.body(w).xpos[2] - r for w in TOUCH[support]) - (self.h if level == "curb" else 0.0)

    def touch_down(self, support, level, each=0.0, settle=1.0):
        """Lower a support by its measured height above level, then on, 5 mm at a time (up to 4 cm), until both its
        wheels are on level and together carry 8% of the weight (a rigid frame shares load unevenly between a
        pair), and each carries the share each of it."""
        b = self.b_now(support) - self.gap(support, level)
        self.move(self.goals_for({support: b}), settle=0.3)
        extra = 0.0
        lo = self.tables["elevator_l" if support == "drive" else support][1].min()
        while True:
            con, _ = self.contacts()
            if all(s in con and con[s][0] == level and con[s][1] > each * self.weight for s in TOUCH[support])                     and sum(con[s][1] for s in TOUCH[support]) > 0.08 * self.weight:
                break
            if extra >= 0.04 or b - extra - 0.005 < lo:
                raise RuntimeError("%s did not touch down on the %s" % (support, level))
            extra += 0.005
            self.move(self.goals_for({support: b - extra}), settle=0.2)
        self.wait(settle)
        if extra:
            self.log.append("        %s touched down %.1f cm past contact" % (support, extra * 100))

    def rule(self, level):
        """The rear-lift rule: (holds, what it found)."""
        con, _ = self.contacts()
        loads = {s: con.get(s, ("", 0.0)) for s in TOUCH["drive"]}
        on = all(loads[s][0] == level and loads[s][1] > LOADED * self.weight for s in TOUCH["drive"])
        aft = all(self.d.joint(t).qpos[0] < AFT + 0.05 for t in ("translator_l", "translator_r"))
        com = self.d.subtree_com[self.m.body("chassis").id][0]
        margin = com - 0.5 * (self.x("drive_wheel_l") + self.x("drive_wheel_r"))
        msg = "rear-lift rule: drive wheels on the %s carrying %.0f / %.0f N (need %.0f), translators aft %s, CoM %+.1f cm ahead of their axle" % (
            level, loads["drive_wheel_l"][1], loads["drive_wheel_r"][1], LOADED * self.weight, aft, margin * 100)
        return on and aft and margin > 0.03, msg

    def gate_rear(self, level):
        """The rule, checked before the rear omni wheels come up."""
        ok, msg = self.rule(level)
        self.log.append("        " + msg)
        if not ok:
            raise RuntimeError("rule not met: " + msg)

    def levelling(self, on):
        """Start or stop the rear's levelling trim; stopping folds the trim into the rear lift's command."""
        if not on:
            self.cmd["rear_lift"] += self.trim
            self.goal["rear_lift"] = self.cmd["rear_lift"]
            self.trim = 0.0
        self.level = on

    # --- blended: the robot keeps rolling and moves each pair as it reaches the edge
    def go(self, goals):
        """Start the joints toward goals, each at the rate that lands them together, and return at once (move()
        without the wait): other joints keep moving to theirs."""
        T = max([abs(v - self.cmd[k]) / self.RATE[k] for k, v in goals.items()] + [0.0])
        for k, v in goals.items():
            self.rate[k] = max(1e-6, abs(v - self.cmd[k]) / T) if T > 0 else self.RATE[k]
            self.goal[k] = v

    def arrived(self, keys=LIFTS):
        return all(abs(self.goal[k] - self.cmd[k]) < 1e-9 for k in keys)

    def bottom(self, support):
        """The lower of a support's two wheels' bottoms, above the road (m)."""
        r = {"drive": self.r_dw, "front_arm": self.r_fo, "rear_lift": self.r_ro}[support]
        return min(self.d.body(w).xpos[2] - r for w in TOUCH[support])

    def loaded(self, support, level, each=0.0):
        """Both of a support's wheels on level, together carrying 8% of the weight and each the share each of it."""
        con, _ = self.contacts()
        return (all(s in con and con[s][0] == level and con[s][1] > each * self.weight for s in TOUCH[support])
                and sum(con[s][1] for s in TOUCH[support]) > 0.08 * self.weight)

    def start_touchdown(self, support, level, each=0.0):
        """Lower a support at its full speed from its measured height above level, on past it (up to 4 cm, as far
        as it reaches) until the pair carries load: tick_touchdowns() stops it there. One move, no stops: a load or
        motor-current reading would tell the robot when."""
        b = self.b_now(support) - self.gap(support, level)
        lo = self.tables["elevator_l" if support == "drive" else support][1].min()
        self.go(self.goals_for({support: max(lo + 1e-6, b - 0.04)}))
        self.tds[support] = {"level": level, "each": each, "b": b}

    def tick_touchdowns(self):
        """Stop each touchdown under way once its pair carries load; True for each that finished this step."""
        done = []
        for support, td in list(self.tds.items()):
            joints = JOINTS[support]
            if self.loaded(support, td["level"], td["each"]):
                for j in joints:
                    self.goal[j] = self.cmd[j]
                past = td["b"] - self.b_now(support)
                if past > 0.002:
                    self.log.append("        %s touched down %.1f cm past contact" % (support, past * 100))
                del self.tds[support]
                done.append(support)
            elif self.arrived(joints) and self.arrived():
                raise RuntimeError("%s did not touch down on the %s" % (support, td["level"]))
        return done

    def t_to_touch(self, support, level):
        """How long a support's lift takes to bring its wheels down to level from here (s)."""
        q_now = np.mean([self.cmd[j] for j in JOINTS[support]])
        q_to = self.q_for(support, max(self.tables["elevator_l" if support == "drive" else support][1].min(),
                                       self.b_now(support) - self.gap(support, level)))
        return abs(q_to - q_now) / self.RATE[JOINTS[support][0]]

    def stop_short(self, lead, at):
        """The speed that brings a point at x = lead to rest at x = at (m/s)."""
        return max(0.0, STOP_GAIN * (at - lead))

    def event(self, key, label):
        """Note an event of a blended crossing in the log, with the time since the last one."""
        self.events[key] = self.d.time
        con, _ = self.contacts()
        p, r = self.pitch_roll()
        on = ", ".join("%s@%s %.0fN" % (s.replace("drive_wheel", "dw").replace("_omni", "o"), w[0], w[1]) for s, w in sorted(con.items()))
        self.log.append("%6.1fs %-56s %+5.1fs pitch %+5.1f roll %+5.1f v %4.2f | %s" % (
            self.d.time, label[:56], self.d.time - self.t_event, p, r, self.v, on))
        self.t_event = self.d.time

    def phase(self, label, fn):
        self.label = label
        t0 = self.d.time
        fn()
        con, _ = self.contacts()
        p, r = self.pitch_roll()
        on = ", ".join("%s@%s %.0fN" % (s.replace("drive_wheel", "dw").replace("_omni", "o"), w[0], w[1]) for s, w in sorted(con.items()))
        self.log.append("%6.1fs %-56s %5.1fs pitch %+5.1f roll %+5.1f | %s" % (self.d.time, label[:56], self.d.time - t0, p, r, on))

    # --- the sequences
    def begin(self):
        """Settle in the stance, and note where the crossing finds the lifts (it puts them back there) and whether the
        front omni wheels are already off the ground."""
        ph = self.phase
        ph("Settle", lambda: self.wait(1.5))
        if any(abs(v) > 1e-9 for v in self.stance.values()):
            ph("The stance (before the crossing)", lambda: self.move(self.stance, settle=1.5))
        self.start = dict(self.cmd)
        self.levelling(True)
        ground = self.h if self.dir == "down" else 0.0
        self.front_up = min(self.d.body(w).xpos[2] - self.r_fo for w in TOUCH["front_arm"]) - ground > TOUCH_TOLERANCE
        if self.front_up:
            self.log.append("        the front omni wheels start up: they stay up until they go down over the edge")
        self.meter.start()                     # the crossing proper, from here to the end

    def climb(self):
        h, clr = self.h, self.clr
        self.begin()
        Hc = self.crossing_height()
        lift = h + clr - Hc                    # a lifted support clears the curb top by clr
        ph = self.phase
        # Front omni wheels already up stay up, at least as high as the crossing lifts them.
        front = max(self.b_now("front_arm"), lift) if self.front_up else -Hc
        ph("Raise the chassis level for the crossing", lambda: self.move(self.goals_for({"drive": -Hc, "front_arm": front, "rear_lift": -Hc})))
        at_face = lambda: self.x("front_omni_l") + self.r_fo >= FACE - 0.05
        if self.front_up:
            ph("Drive up to the curb, the front omni wheels up", lambda: self.drive_until(at_face, speed=0.25, stop=False))
        else:
            ph("Drive up to the curb", lambda: self.drive_until(at_face, speed=0.25))
            ph("Front omni wheels up", lambda: self.move(self.goals_for({"front_arm": lift})))
        ph("Drive until the drive wheels reach the curb", lambda: self.drive_until(lambda: self.x("drive_wheel_l") + self.r_dw >= FACE - 0.03))
        ph("Front omni wheels down on the curb", lambda: self.touch_down("front_arm", "curb"))
        ph("Drive wheels up", lambda: self.drive_wheels_up(lift))
        if self.powered:
            target = FACE + 0.65 * self.r_dw
            ph("Front omni wheels pull it forward; drive wheels aft", lambda: self.pull_forward(lambda: self.x("drive_wheel_l") >= target))
        else:
            t_fwd = min(0.39, self.d.joint("translator_l").qpos[0] + (FACE + 0.65 * self.r_dw) - self.x("drive_wheel_l"))
            ph("Drive wheels forward over the curb", lambda: self.move({"translator_l": t_fwd, "translator_r": t_fwd}))
        ph("Drive wheels down on the curb", lambda: self.touch_down("drive", "curb", each=LOADED))
        if not self.powered:
            ph("Drive wheels aft (braked): pulls the chassis forward", self.pull_aft)
        self.gate_rear("curb")
        self.levelling(False)
        ph("Rear omni wheels up", lambda: self.move(self.goals_for({"rear_lift": lift})))
        on = ("drive", "front") if self.powered else ("drive",)
        ph("Drive until the rear omni wheels are over the curb", lambda: self.drive_until(lambda: self.rear_x() - self.r_ro >= FACE + 0.03, on=on))
        ph("Rear omni wheels down on the curb", lambda: self.touch_down("rear_lift", "curb"))
        self.levelling(True)
        self.finish()

    def descend(self):
        h, clr = self.h, self.clr
        self.begin()
        Hc = self.crossing_height()
        lift, on_upper = h + clr - Hc, h - Hc  # a lifted support clears the upper level by clr; one on it
        ph = self.phase
        # Front omni wheels already up stay up, clear of the upper level, until they go down over the edge.
        front = max(self.b_now("front_arm"), on_upper + clr) if self.front_up else on_upper
        ph("Lower the chassis level for the crossing", lambda: self.move(self.goals_for({"drive": on_upper, "front_arm": front, "rear_lift": on_upper})))
        ph("Drive up to the edge (front omni wheels over it)", lambda: self.drive_until(lambda: self.x("drive_wheel_l") >= FACE - 0.07))
        ph("Front omni wheels down to the road", lambda: self.touch_down("front_arm", "floor"))
        ph("Drive wheels up", lambda: self.drive_wheels_up(lift))
        if self.powered:
            target = FACE + self.r_dw + LAND
            ph("Front omni wheels pull it forward; drive wheels aft", lambda: self.pull_forward(lambda: self.x("drive_wheel_l") >= target))
        else:
            t_fwd = min(0.39, self.d.joint("translator_l").qpos[0] + (FACE + self.r_dw + LAND) - self.x("drive_wheel_l"))
            ph("Drive wheels forward over the edge", lambda: self.move({"translator_l": t_fwd, "translator_r": t_fwd}))
        ph("Drive wheels down to the road", lambda: self.touch_down("drive", "floor", each=LOADED))
        if not self.powered:
            ph("Drive wheels aft (braked): pulls the chassis forward", self.pull_aft)
        self.gate_rear("floor")
        self.levelling(False)
        ph("Rear omni wheels up", lambda: self.move(self.goals_for({"rear_lift": lift})))
        on = ("drive", "front") if self.powered else ("drive",)
        past = lambda: self.rear_x() - self.r_ro >= FACE + 0.03
        ph("Drive until the rear omni wheels are past the edge", lambda: self.drive_until(past, on=on))
        # Everything under the frame is over the road now: lower the chassis on the drive and front wheels, so the
        # sprung rear, which reaches least, has less to reach.
        drop = Hc / 2
        ph("Lower the chassis on the drive and front wheels", lambda: self.move(self.goals_for(
            {"drive": self.b_now("drive") + drop, "front_arm": self.b_now("front_arm") + drop})))
        # Lowering on the braked drive wheels swings them on their arms, which can roll the robot back: past the edge
        # again (a no-op when it did not).
        ph("Creep on until the rear omni wheels are past it again", lambda: self.drive_until(past, on=on))
        ph("Rear omni wheels down to the road", lambda: self.touch_down("rear_lift", "floor"))
        self.levelling(True)
        ph("Drive clear of the edge", lambda: self.drive_until(lambda: self.x("rear_omni_l") - self.r_ro >= FACE + 0.15, on=on))
        self.finish()

    def drive_wheels_up(self, lift):
        """The drive wheels up, the powered front omni wheels' hubs holding the robot from here: braked, the drive
        wheels grip the road as their arms swing them up and push the chassis back, and once they are off it nothing
        else stops it rolling."""
        if self.powered:
            self.front["speed"] = 0.0
        self.move(self.goals_for({"drive": lift}))

    def pull_forward(self, there):
        """Powered front: translators to AFT while the front omni wheels pull the robot forward until there()."""
        def during(done):
            self.watch_rear = True
            arrived = there()
            self.front["speed"] = 0.0 if arrived else 0.15 / self.r_fo
            return arrived
        self.move({"translator_l": AFT, "translator_r": AFT}, settle=0.0, during=during)
        self.watch_rear = False
        self.front["speed"] = 0.0
        self.wait(0.8)
        self.front["speed"] = None

    def pull_aft(self):
        """Standard: translators to AFT with the drive wheels braked and loaded, pulling the chassis forward."""
        self.watch_rear = True
        self.move({"translator_l": AFT, "translator_r": AFT}, settle=1.0)
        self.watch_rear = False

    def finish(self):
        ph = self.phase
        ph("Translators back where they started, the drive wheels rolling under it", self.recentre)
        # The lifts back where the crossing found them: the levelling trim goes into the rear's command and out with
        # the move, so the rear ends at its own starting angle and the chassis at its starting pitch.
        ph("Back to the stance it started in", lambda: (self.levelling(False), self.move({k: self.start[k] for k in LIFTS}, settle=1.5)))
        off = max(abs(self.d.joint(k).qpos[0] - self.start[k]) * (100.0 if k.startswith("translator") else math.degrees(1.0)) for k in LIFTS)
        self.log.append("        back in its stance: every lift within %.2f (deg or cm) of where it started" % off)
        self.meter.stop()

    def recentre(self):
        """Translators back where they started while the drive wheels roll at the plates' speed, so the chassis stays
        put."""
        start, to = self.cmd["translator_l"], self.start["translator_l"]

        def during(done):
            v = 0.0 if done or abs(to - start) < 1e-9 else math.copysign(self.rate["translator_l"], to - start)
            self.drive["speed"] = v / self.r_dw
            return True
        self.move({"translator_l": to, "translator_r": self.start["translator_r"]}, settle=0.0, during=during)
        self.brake()
        self.wait(0.8)

    # --- the blended sequences (--sequence blended): it rolls through the crossing
    def lead(self, body, r):
        """The foremost point of a pair of wheels (x, m)."""
        return max(self.x(body + "_l"), self.x(body + "_r")) + r

    def trail(self, body, r):
        """The hindmost point of a pair of wheels (x, m)."""
        return min(self.x(body + "_l"), self.x(body + "_r")) - r

    def axle(self, body):
        """The foremost of a pair of wheels' axles (x, m): on level ground, where the pair touches it."""
        return max(self.x(body + "_l"), self.x(body + "_r"))

    def run(self, tick, done, limit=120.0):
        """Step until done(), calling tick() after every step (it starts each pair's moves as their time comes)."""
        t0 = self.d.time
        while not done():
            self.step()
            tick()
            if self.d.time - t0 > limit:
                raise RuntimeError("the crossing stalled (%s)" % self.label)

    def rear_gate(self, st, level, lift):
        """Blended, with the drive wheels on the far level and the translators aft: the rear omni wheels up if the
        rule holds. Drawing the drive wheels aft under the chassis moves load onto the front omni wheels; if a drive
        wheel no longer carries its share, they are set down again until each does (the stop-and-step sequence sets
        them down after the translators are aft, so it never needs this)."""
        ok, msg = self.rule(level)
        if ok:
            self.log.append("        " + msg)
            self.levelling(False)
            self.go(self.goals_for({"rear_lift": lift}))
            st["rear"] = "lifting"
            self.event("rear_up", "Rear omni wheels up")
        elif not self.loaded("drive", level, LOADED) and "drive" not in self.tds:
            self.start_touchdown("drive", level, each=LOADED)
            st["drive"] = "pressing"
            self.event("drive_press", "Drive wheels down again: each to carry its share")

    def climb_blended(self):
        """The climb, rolling: each pair goes up the curb as it reaches it. The front omni wheels, held up, go down
        on the curb as soon as they are over it; the drive wheels go up as they near the face while the translators
        bring them aft (rolling at about the translators' speed, they hold their place on the road as they rise), and
        down once over the curb; the rear omni wheels go up once the rule holds and down once over the curb. The
        robot is held short of the face, slowing to a stop, whenever a pair reaching it is not up yet."""
        h, clr = self.h, self.clr
        self.begin()
        self.t_event = self.d.time
        Hc = self.crossing_height()
        lift = h + clr - Hc
        front = max(self.b_now("front_arm"), lift) if self.front_up else lift
        heights = self.goals_for({"drive": -Hc, "front_arm": front, "rear_lift": -Hc})
        self.go(heights)
        st = {"raised": False, "front": "low", "drive": "low", "rear": "low"}
        lead_f = lambda: self.lead("front_omni", self.r_fo)
        self.limits = [
            # the chassis at its crossing height before the front omni wheels reach the curb
            lambda: None if st["raised"] else self.stop_short(lead_f(), FACE - 0.05),
            # each pair held short of the face until it is up
            lambda: self.stop_short(lead_f(), FACE - 0.02) if st["front"] == "low" else None,
            lambda: self.stop_short(self.lead("drive_wheel", self.r_dw), FACE - 0.01) if st["drive"] in ("low", "lifting") else None,
            lambda: self.stop_short(self.lead("rear_omni", self.r_ro), FACE - 0.03) if st["rear"] in ("low", "lifting") else None,
        ]
        self.roll = APPROACH

        def tick():
            fin = self.tick_touchdowns()
            if not st["raised"] and self.arrived(heights.keys()):
                st["raised"] = True
                self.event("raised", "Chassis at its crossing height (rolling)")
            self.roll = APPROACH if FACE - lead_f() > APPROACH_NEAR else CRAWL
            if "front_at" not in self.events and lead_f() >= FACE:
                self.event("front_at", "Front omni wheels at the curb face")
            # front omni wheels: up (they may start up), down on the curb once over it
            if st["front"] == "low" and self.bottom("front_arm") >= h + CLEAR:
                st["front"] = "up"
            if st["front"] == "up" and self.trail("front_omni", self.r_fo) >= FACE + 0.02:
                self.start_touchdown("front_arm", "curb")
                st["front"] = "lowering"
                self.event("front_down", "Front omni wheels over the curb: down on it")
            if "front_arm" in fin:
                st["front"] = "on"
                self.event("front_on", "Front omni wheels on the curb")
            # drive wheels: up as they near the face; down once over the curb; then the translators aft, rolling on
            if st["drive"] == "low" and st["front"] == "on" and self.lead("drive_wheel", self.r_dw) >= FACE - LEAD_UP:
                self.drive["free"] = True
                self.go(self.goals_for({"drive": lift}))
                st["drive"] = "lifting"
                self.event("drive_up", "Drive wheels up")
            if st["drive"] == "lifting" and self.bottom("drive") >= h + CLEAR:
                st["drive"] = "up"
                self.event("drive_clear", "Drive wheels clear of the curb")
            if st["drive"] == "up" and min(self.x("drive_wheel_l"), self.x("drive_wheel_r")) >= FACE + 0.65 * self.r_dw:
                self.drive["free"] = False
                self.start_touchdown("drive", "curb", each=LOADED)
                st["drive"] = "lowering"
                self.event("drive_down", "Drive wheels over the curb: down on it")
            if "drive" in fin:
                if st["drive"] == "pressing":
                    self.event("drive_pressed", "Drive wheels carry their share again")
                else:
                    self.event("drive_on", "Drive wheels on the curb")
                    self.go({"translator_l": AFT, "translator_r": AFT})
                    self.event("aft", "Translators aft (rolling): chassis forward over them")
                st["drive"] = "on"
            # rear omni wheels: up once the rule holds, down once over the curb
            if st["rear"] == "low" and st["drive"] == "on" and self.arrived(("translator_l", "translator_r")):
                self.rear_gate(st, "curb", lift)
            if st["rear"] == "lifting" and self.bottom("rear_lift") >= h + CLEAR:
                st["rear"] = "up"
                self.event("rear_clear", "Rear omni wheels clear of the curb")
            if st["rear"] == "up" and self.rear_x() - self.r_ro >= FACE + 0.03:
                self.start_touchdown("rear_lift", "curb")
                st["rear"] = "lowering"
                self.event("rear_down", "Rear omni wheels over the curb: down on it")
            if "rear_lift" in fin:
                self.levelling(True)
                st["rear"] = "on"
                self.event("rear_on", "Rear omni wheels on the curb")
            self.label = "front %s | drive wheels %s | rear %s" % (st["front"], st["drive"], st["rear"])

        self.run(tick, lambda: st["rear"] == "on")
        self.finish_blended()

    def descend_blended(self):
        """The descent, rolling: each pair goes down off the edge as it passes it. The front omni wheels go down to
        the road as soon as they are past the edge; the drive wheels go up off the upper level as they near the edge
        while the translators bring them aft, and down to the road once their swing arms will clear the edge; the
        rear omni wheels go up once the rule holds and, once past the edge, down to the road while the chassis
        comes down on the drive and front wheels. The robot is held short of the edge, slowing to a stop, whenever
        a pair reaching it is not up off the upper level yet."""
        h, clr = self.h, self.clr
        self.begin()
        self.t_event = self.d.time
        Hc = self.crossing_height()
        lift, on_upper = h + clr - Hc, h - Hc
        front = max(self.b_now("front_arm"), on_upper + clr) if self.front_up else on_upper
        heights = self.goals_for({"drive": on_upper, "front_arm": front, "rear_lift": on_upper})
        self.go(heights)
        st = {"raised": False, "front": "on", "drive": "on", "rear": "on"}
        lead_f = lambda: self.lead("front_omni", self.r_fo)
        self.limits = [
            lambda: None if st["raised"] else self.stop_short(lead_f(), FACE - 0.05),
            # the drive and rear wheels held short of the edge until they are up off the upper level
            lambda: self.stop_short(self.axle("drive_wheel"), FACE - 0.02) if st["drive"] in ("on", "lifting") else None,
            lambda: self.stop_short(self.axle("rear_omni"), FACE - 0.02) if st["rear"] in ("on", "lifting") else None,
        ]
        self.roll = APPROACH

        def tick():
            fin = self.tick_touchdowns()
            if not st["raised"] and self.arrived(heights.keys()):
                st["raised"] = True
                self.event("raised", "Chassis at its crossing height (rolling)")
            self.roll = APPROACH if FACE - lead_f() > APPROACH_NEAR else CRAWL
            if "front_at" not in self.events and lead_f() >= FACE:
                self.event("front_at", "Front omni wheels at the edge")
            if st["front"] == "on" and self.trail("front_omni", self.r_fo) >= FACE + 0.02:
                self.start_touchdown("front_arm", "floor")
                st["front"] = "lowering"
                self.event("front_down", "Front omni wheels past the edge: down to the road")
            if "front_arm" in fin:
                st["front"] = "down"
                self.event("front_on", "Front omni wheels on the road")
            if st["drive"] == "on" and st["front"] == "down" and self.axle("drive_wheel") >= FACE - LEAD_DOWN:
                self.drive["free"] = True
                self.go(self.goals_for({"drive": lift}))
                st["drive"] = "lifting"
                self.event("drive_up", "Drive wheels up off the upper level")
            if st["drive"] == "lifting" and self.bottom("drive") >= h + CLEAR:
                st["drive"] = "up"
                self.event("drive_clear", "Drive wheels clear of the upper level")
            # down as they roll off the edge, starting early enough that they land where their swing arms and motors,
            # which trail them, clear it (r + LAND past it), as they would set down there in place
            dw = min(self.x("drive_wheel_l"), self.x("drive_wheel_r"))
            if st["drive"] == "up" and dw >= FACE + 0.3 * self.r_dw and dw + self.v * self.t_to_touch("drive", "floor") >= FACE + self.r_dw + LAND:
                self.drive["free"] = False
                self.start_touchdown("drive", "floor", each=LOADED)
                st["drive"] = "lowering"
                self.event("drive_down", "Drive wheels rolling off the edge: down to the road")
            if "drive" in fin:
                if st["drive"] == "pressing":
                    self.event("drive_pressed", "Drive wheels carry their share again")
                else:
                    self.event("drive_on", "Drive wheels on the road")
                    self.go({"translator_l": AFT, "translator_r": AFT})
                    self.event("aft", "Translators aft (rolling): chassis forward over them")
                st["drive"] = "down"
            if st["rear"] == "on" and st["drive"] == "down" and self.arrived(("translator_l", "translator_r")):
                self.rear_gate(st, "floor", lift)
            if st["rear"] == "lifting" and self.bottom("rear_lift") >= h + CLEAR:
                st["rear"] = "up"
                self.event("rear_clear", "Rear omni wheels clear of the upper level")
            if st["rear"] == "up" and self.rear_x() - self.r_ro >= FACE + 0.03:
                # the chassis comes down on the drive and front wheels as the rear goes down: the sprung rear, which
                # reaches least, has less to reach
                drop = Hc / 2
                self.go(self.goals_for({"drive": self.b_now("drive") + drop, "front_arm": self.b_now("front_arm") + drop}))
                self.start_touchdown("rear_lift", "floor")
                st["rear"] = "lowering"
                self.event("rear_down", "Rear omni wheels past the edge: down, chassis down")
            if "rear_lift" in fin:
                self.levelling(True)
                st["rear"] = "down"
                self.event("rear_on", "Rear omni wheels on the road")
            self.label = "front %s | drive wheels %s | rear %s" % (st["front"], st["drive"], st["rear"])

        self.run(tick, lambda: st["rear"] == "down")
        self.finish_blended()

    def finish_blended(self):
        """Rolling on: the translators back where they started (the drive wheels rolling at the plates' speed plus
        the chassis's), the rear trimmed level; then every lift back in the stance it started in, together (moving
        the front arm and elevators to it while the rear is still at its crossing height tips the chassis 6-14 deg,
        faster than the trim levels it); then it stops."""
        self.limits = []
        self.label = "translators back"
        self.go({"translator_l": self.start["translator_l"], "translator_r": self.start["translator_r"]})
        self.run(lambda: None, lambda: self.arrived())
        self.event("recentred", "Translators back where they started (rolling)")
        self.label = "back to the stance"
        self.levelling(False)
        self.go({k: self.start[k] for k in LIFTS if not k.startswith("translator")})
        self.run(lambda: None, lambda: self.arrived())
        self.event("stance", "Back in the stance it started in (rolling)")
        self.label = "stopping"
        self.roll = 0.0
        self.run(lambda: None, lambda: self.v < 1e-4)
        self.roll = None
        self.brake()
        self.front["speed"] = 0.0 if self.powered else None
        self.wait(0.8)
        self.front["speed"] = None
        self.event("done", "Stopped")
        self.meter.stop()
        off = max(abs(self.d.joint(k).qpos[0] - self.start[k]) * (100.0 if k.startswith("translator") else math.degrees(1.0)) for k in LIFTS)
        self.log.append("        back in its stance: every lift within %.2f (deg or cm) of where it started" % off)
        at, up = self.events["front_at"], self.dir == "up"
        self.log.append("        front omni wheels at the %s -> rear omni wheels down: %.1f s, -> stopped: %.1f s "
                        "(the real robot's videos: about %s and %s s)" % (
                            "curb face" if up else "edge", self.events["rear_on"] - at, self.events["done"] - at,
                            "15" if up else "10", "17" if up else "13"))


def clip_writer(path, speedup, cx):
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1280, 720
    m = cx.m
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
    m.geom_rgba[m.geom("rider").id][3] = 0.3   # the rider's mass, shown
    rnd = mujoco.Renderer(m, H, W)
    opt = mujoco.MjvOption()
    opt.geomgroup[:] = [1, 0, 1, 0, 0, 0]
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.distance, cam.azimuth, cam.elevation = 2.9, 95.0, -6.0
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 26)
        small = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 19)
    except OSError:
        font = small = ImageFont.load_default()
    w = imageio_ffmpeg.write_frames(path, (W, H), fps=30, codec="libx264", quality=8, macro_block_size=8)
    w.send(None)
    nxt = [0.0]
    title = "Curb %s %.0f cm  %s" % (cx.dir, cx.h * 100, "(powered front omni wheels)" if cx.powered else "")

    def frame(c):
        if c.d.time < nxt[0]:
            return
        nxt[0] += speedup / 30.0
        com = c.d.subtree_com[c.m.body("chassis").id]
        cam.lookat[:] = [com[0], 0.0, 0.25]
        rnd.update_scene(c.d, cam, opt)
        img = Image.fromarray(rnd.render())
        dr = ImageDraw.Draw(img, "RGBA")
        dr.rectangle([0, 0, W, 50], fill=(0, 0, 0, 150))
        dr.text((16, 9), "%s  |  %s" % (title, c.label), font=font, fill=(255, 255, 255))
        con, _ = c.contacts()

        def st(s):
            return "air" if s not in con else "%s %4.0fN" % ("curb" if con[s][0] == "curb" else "road", con[s][1])
        p, r = c.pitch_roll()
        lines = ["elevators %+5.1f deg   translators %+5.1f cm" % (math.degrees(c.d.joint("elevator_l").qpos[0]), c.d.joint("translator_l").qpos[0] * 100),
                 "front arm %+5.1f deg   rear lift %+5.1f deg (arm %+5.1f, damper %4.1f mm)" % (
                     math.degrees(c.d.joint("front_arm").qpos[0]), math.degrees(c.d.joint("rear_lift").qpos[0]),
                     math.degrees(c.d.joint("rear_arm").qpos[0]), (c.d.joint("rear_spring").qpos[0] - P["rear_spring"]["travel_cm"][0] / 100) * 1000),
                 "front omni %-10s drive %-10s rear omni %-10s" % (st("front_omni_l"), st("drive_wheel_l"), st("rear_omni_l")),
                 "chassis pitch %+5.1f deg  roll %+5.1f deg   t %5.1f s" % (p, r, c.d.time)]
        dr.rectangle([0, H - 30 * len(lines) - 44, 660, H], fill=(0, 0, 0, 150))
        for i, s in enumerate(lines):
            dr.text((14, H - 30 * len(lines) - 34 + 30 * i), s, font=small, fill=(230, 230, 230))
        note = "%gx  |  RAMMP Gen1 MJCF, placeholder masses/speeds, %.0f kg rider" % (speedup, P["rider_kg"])
        dr.text((W - 10 - dr.textlength(note, font=small), H - 28), note, font=small, fill=(230, 230, 230))
        w.send(np.ascontiguousarray(np.asarray(img)))
    return frame, w


def main():
    global CRAWL
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", choices=("standard", "powered_front"), default="standard")
    ap.add_argument("--dir", choices=("up", "down"), default="up")
    ap.add_argument("--height", type=float, default=0.15, help="curb height, m")
    ap.add_argument("--clearance", type=float, default=0.03, help="a lifted support's clearance over the level it crosses, m")
    ap.add_argument("--stance", type=float, nargs=3, default=(0.0, 0.0, 0.0), metavar=("FRONT", "ELEVATORS", "REAR"),
                    help="the lifts' angles the robot starts in, deg (the outdoor stance: about -14 9 0)")
    ap.add_argument("--sequence", choices=("step", "blended"), default="step",
                    help="step: stop and step, each pair in turn (what the Unreal controller does); blended: it rolls "
                         "through the crossing, moving each pair as it reaches the edge (as the real robot does)")
    ap.add_argument("--crawl", type=float, default=CRAWL, help="blended: its speed through the crossing, m/s")
    ap.add_argument("--csv", help="write the measurements' time series (every 20 ms of the crossing proper) to this file")
    ap.add_argument("--clip", help="write a video of the crossing")
    ap.add_argument("--speedup", type=float, default=8.0)
    args = ap.parse_args()
    if args.sequence == "blended" and args.variant != "powered_front":
        ap.error("--sequence blended needs --variant powered_front: with the drive wheels up, the front omni wheels' "
                 "hub motors keep the robot rolling")
    CRAWL = args.crawl
    cx = Crossing(args.variant, args.dir, args.height, args.clearance, args.stance)
    writer = None
    if args.clip:
        cx.on_frame, writer = clip_writer(args.clip, args.speedup, cx)
    ok = True
    try:
        if args.sequence == "blended":
            cx.climb_blended() if args.dir == "up" else cx.descend_blended()
        else:
            cx.climb() if args.dir == "up" else cx.descend()
    except RuntimeError as e:
        cx.log.append("ABORT in '%s': %s" % (cx.label, e))
        ok = False
    if writer is not None:
        writer.close()
    print("\n".join(cx.log + cx.meter.summary()))
    if args.csv:
        cx.meter.write_csv(args.csv)
    print("frame contacts with the world: %s" % (cx.strikes or "none"))
    print("%s: %.1f s, worst pitch %.1f deg, roll %.1f deg" % ("crossed" if ok else "aborted", cx.d.time, cx.worst[0], cx.worst[1]))
    return 0 if ok and not cx.strikes else 1


if __name__ == "__main__":
    sys.exit(main())
