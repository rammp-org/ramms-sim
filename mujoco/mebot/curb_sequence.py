#!/usr/bin/env python3
"""The MeBot's curb crossing as a scripted stop-and-step sequence in MuJoCo: the reference for its curb controller.

    python mujoco/mebot/curb_sequence.py [--variant standard|powered_front] [--dir up|down] [--height 0.15]
                                         [--clip out.mp4 [--speedup 8]]

The chassis stays level throughout and rides just under curb height (raised for a climb, lowered for a descent),
so its frame clears the curb edge. Each support -- front omni wheels, drive wheels, rear omni wheels -- is lifted
over the edge and set down in turn, and every touchdown lowers until the pair carries load (as a load or
motor-current reading would tell the controller). The rule: the rear omni wheels are not lifted until both drive
wheels are on the far level, translated aft and carrying load, with the centre of mass ahead of their axle; the
run aborts if that does not hold.

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
import build_mebot_mjcf as B  # noqa: E402

P = B.PARAMS
FACE = 1.5            # the curb face's x (m); up: the upper level ahead, down: the robot starts on it
LIFTS = ("elevator_l", "elevator_r", "translator_l", "translator_r", "front_arm", "rear_arm")
TOUCH = {"drive": ("drive_wheel_l", "drive_wheel_r"), "front_arm": ("front_omni_l", "front_omni_r"), "rear_arm": ("rear_omni_l", "rear_omni_r")}
AFT = -0.30           # the translators' aft position for the rear lift (m)
LOADED = 0.10         # the rule: each drive wheel carries this share of the weight before the rear lift
LAND = 0.12           # descents: the lifted drive wheels' centres this far past their radius beyond the edge (m), so the
                      # swing arms and motors, which trail the wheels, clear the edge as the wheels swing down


class Crossing:
    def __init__(self, variant, direction, h, clearance):
        self.powered = variant == "powered_front"
        self.dir, self.h, self.clr = direction, h, clearance
        spec = mujoco.MjSpec.from_file(os.path.join(HERE, "mebot_powered_front_scene.xml" if self.powered else "mebot_scene.xml"))
        curb = spec.geom("curb")
        if direction == "up":
            curb.pos, curb.size = [FACE + 1.5, 0, h / 2], [1.5, 3, h / 2]
        else:
            curb.pos, curb.size = [FACE - 3.0, 0, h / 2], [3.0, 3, h / 2]
            c = spec.body("chassis")
            c.pos = [c.pos[0] + 0.2, c.pos[1], c.pos[2] + h]
        self.m = m = spec.compile()
        self.d = mujoco.MjData(m)
        self.A = {m.actuator(i).name: i for i in range(m.nu)}
        self.r_dw = m.numeric("drive_wheel_radius").data[0]
        self.r_fo = m.numeric("front_omni_radius").data[0]
        self.r_ro = m.numeric("rear_omni_radius").data[0]
        deg = math.radians
        self.RATE = {"elevator_l": deg(P["elevator"]["speed_deg_s"]), "elevator_r": deg(P["elevator"]["speed_deg_s"]),
                     "front_arm": deg(P["caster_arm"]["speed_deg_s"]), "rear_arm": deg(P["caster_arm"]["speed_deg_s"]),
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
        self.log, self.strikes = [], []
        self.label = ""
        self.worst = [0.0, 0.0]
        self.on_frame = None
        self.watch_rear = False                # while the chassis is pulled forward: the rear omni wheels must stay clear

    # --- model geometry
    def support_tables(self):
        """b(q): how far each support's bottom rises (m, chassis level) as its joint turns, from the kinematics."""
        m, d0 = self.m, mujoco.MjData(self.m)
        mujoco.mj_forward(m, d0)
        out = {}
        for joint, body, r in (("elevator_l", "drive_wheel_l", self.r_dw), ("front_arm", "front_omni_l", self.r_fo), ("rear_arm", "rear_omni_l", self.r_ro)):
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
        for k in LIFTS:
            err = self.goal[k] - self.cmd[k]
            self.cmd[k] += max(-self.rate[k] * dt, min(self.rate[k] * dt, err))
            q = d.joint(k).qpos[0]
            lim = 0.03 if k.startswith("translator") else math.radians(10)
            self.integ[k] = max(-lim, min(lim, self.integ[k] + 2.0 * (self.cmd[k] - q) * dt))   # the servo's integral action
            d.ctrl[self.A[k]] = self.cmd[k] + self.integ[k]
        tq = P["drive"]["torque"]
        for s in ("l", "r"):
            j = d.joint("drive_wheel_" + s)
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

    def drive_until(self, pred, speed=0.15, on=("drive",), limit=30.0):
        """Drive at speed (m/s) on the drive wheels and/or the powered front omni wheels until pred(), then brake."""
        t0 = self.d.time
        self.set_speed(speed, on)
        while not pred():
            self.step()
            if self.d.time - t0 > limit:
                raise RuntimeError("driving timed out")
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
        r = {"drive": self.r_dw, "front_arm": self.r_fo, "rear_arm": self.r_ro}[support]
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

    def gate_rear(self, level):
        """The rule, checked before the rear omni wheels come up."""
        con, _ = self.contacts()
        loads = {s: con.get(s, ("", 0.0)) for s in TOUCH["drive"]}
        on = all(loads[s][0] == level and loads[s][1] > LOADED * self.weight for s in TOUCH["drive"])
        aft = all(self.d.joint(t).qpos[0] < AFT + 0.05 for t in ("translator_l", "translator_r"))
        com = self.d.subtree_com[self.m.body("chassis").id][0]
        margin = com - 0.5 * (self.x("drive_wheel_l") + self.x("drive_wheel_r"))
        msg = "rear-lift rule: drive wheels on the %s carrying %.0f / %.0f N (need %.0f), translators aft %s, CoM %+.1f cm ahead of their axle" % (
            level, loads["drive_wheel_l"][1], loads["drive_wheel_r"][1], LOADED * self.weight, aft, margin * 100)
        self.log.append("        " + msg)
        if not (on and aft and margin > 0.03):
            raise RuntimeError("rule not met: " + msg)

    def phase(self, label, fn):
        self.label = label
        t0 = self.d.time
        fn()
        con, _ = self.contacts()
        p, r = self.pitch_roll()
        on = ", ".join("%s@%s %.0fN" % (s.replace("drive_wheel", "dw").replace("_omni", "o"), w[0], w[1]) for s, w in sorted(con.items()))
        self.log.append("%6.1fs %-56s %5.1fs pitch %+5.1f roll %+5.1f | %s" % (self.d.time, label[:56], self.d.time - t0, p, r, on))

    # --- the sequences
    def climb(self):
        h, clr = self.h, self.clr
        Hc = h - 0.02                          # the chassis's height for the crossing: the frame clears the curb edge
        lift = h + clr - Hc                    # a lifted support clears the curb top by clr
        ph = self.phase
        ph("Settle", lambda: self.wait(1.5))
        ph("Raise the chassis level for the crossing", lambda: self.move(self.goals_for({"drive": -Hc, "front_arm": -Hc, "rear_arm": -Hc})))
        ph("Drive up to the curb", lambda: self.drive_until(lambda: self.x("front_omni_l") + self.r_fo >= FACE - 0.05, speed=0.25))
        ph("Front omni wheels up", lambda: self.move(self.goals_for({"front_arm": lift})))
        ph("Drive until the drive wheels reach the curb", lambda: self.drive_until(lambda: self.x("drive_wheel_l") + self.r_dw >= FACE - 0.03))
        ph("Front omni wheels down on the curb", lambda: self.touch_down("front_arm", "curb"))
        ph("Drive wheels up", lambda: self.move(self.goals_for({"drive": lift})))
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
        ph("Rear omni wheels up", lambda: self.move(self.goals_for({"rear_arm": lift})))
        on = ("drive", "front") if self.powered else ("drive",)
        ph("Drive until the rear omni wheels are over the curb", lambda: self.drive_until(lambda: self.x("rear_omni_l") - self.r_ro >= FACE + 0.03, on=on))
        ph("Rear omni wheels down on the curb", lambda: self.touch_down("rear_arm", "curb"))
        self.finish()

    def descend(self):
        h, clr = self.h, self.clr
        Hc = h - 0.03                          # the chassis's height above the road: the frame clears the upper level
        lift, on_upper = h + clr - Hc, h - Hc  # a lifted support clears the upper level by clr; one on it
        ph = self.phase
        ph("Settle", lambda: self.wait(1.5))
        ph("Lower the chassis level for the crossing", lambda: self.move(self.goals_for({"drive": on_upper, "front_arm": on_upper, "rear_arm": on_upper})))
        ph("Drive up to the edge (front omni wheels over it)", lambda: self.drive_until(lambda: self.x("drive_wheel_l") >= FACE - 0.07))
        ph("Front omni wheels down to the road", lambda: self.touch_down("front_arm", "floor"))
        ph("Drive wheels up", lambda: self.move(self.goals_for({"drive": lift})))
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
        ph("Rear omni wheels up", lambda: self.move(self.goals_for({"rear_arm": lift})))
        on = ("drive", "front") if self.powered else ("drive",)
        ph("Drive until the rear omni wheels are past the edge", lambda: self.drive_until(lambda: self.x("rear_omni_l") - self.r_ro >= FACE + 0.03, on=on))
        ph("Rear omni wheels down to the road", lambda: self.touch_down("rear_arm", "floor"))
        ph("Drive clear of the edge", lambda: self.drive_until(lambda: self.x("rear_omni_l") - self.r_ro >= FACE + 0.15, on=on))
        self.finish()

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
        ph("Drive wheels up a little", lambda: self.move(self.goals_for({"drive": self.b_now("drive") + 0.03})))
        ph("Translators back to centre", lambda: self.move({"translator_l": 0.0, "translator_r": 0.0}))
        ph("Back to the driving pose", lambda: self.move({k: 0.0 for k in LIFTS}, settle=1.5))


def clip_writer(path, speedup, cx):
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1280, 720
    m = cx.m
    m.vis.global_.offwidth, m.vis.global_.offheight = W, H
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
                 "front arm %+5.1f deg   rear arm %+5.1f deg" % (math.degrees(c.d.joint("front_arm").qpos[0]), math.degrees(c.d.joint("rear_arm").qpos[0])),
                 "front omni %-10s drive %-10s rear omni %-10s" % (st("front_omni_l"), st("drive_wheel_l"), st("rear_omni_l")),
                 "chassis pitch %+5.1f deg  roll %+5.1f deg   t %5.1f s" % (p, r, c.d.time)]
        dr.rectangle([0, H - 30 * len(lines) - 44, 660, H], fill=(0, 0, 0, 150))
        for i, s in enumerate(lines):
            dr.text((14, H - 30 * len(lines) - 34 + 30 * i), s, font=small, fill=(230, 230, 230))
        note = "%gx  |  MeBot MJCF, placeholder masses/speeds, %.0f kg rider" % (speedup, P["rider_kg"])
        dr.text((W - 10 - dr.textlength(note, font=small), H - 28), note, font=small, fill=(230, 230, 230))
        w.send(np.ascontiguousarray(np.asarray(img)))
    return frame, w


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", choices=("standard", "powered_front"), default="standard")
    ap.add_argument("--dir", choices=("up", "down"), default="up")
    ap.add_argument("--height", type=float, default=0.15, help="curb height, m")
    ap.add_argument("--clearance", type=float, default=0.03, help="a lifted support's clearance over the level it crosses, m")
    ap.add_argument("--clip", help="write a video of the crossing")
    ap.add_argument("--speedup", type=float, default=8.0)
    args = ap.parse_args()
    cx = Crossing(args.variant, args.dir, args.height, args.clearance)
    writer = None
    if args.clip:
        cx.on_frame, writer = clip_writer(args.clip, args.speedup, cx)
    ok = True
    try:
        cx.climb() if args.dir == "up" else cx.descend()
    except RuntimeError as e:
        cx.log.append("ABORT in '%s': %s" % (cx.label, e))
        ok = False
    if writer is not None:
        writer.close()
    print("\n".join(cx.log))
    print("frame contacts with the world: %s" % (cx.strikes or "none"))
    print("%s: %.1f s, worst pitch %.1f deg, roll %.1f deg" % ("crossed" if ok else "aborted", cx.d.time, cx.worst[0], cx.worst[1]))
    return 0 if ok and not cx.strikes else 1


if __name__ == "__main__":
    sys.exit(main())
