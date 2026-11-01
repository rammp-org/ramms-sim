#!/usr/bin/env python3
"""Headless checks of the MeBot MJCFs: each stands on its six wheels, every motor moves the way the model says,
and the passive linkages stay closed.

    python mujoco/mebot/check_mebot.py [--scene mujoco/mebot/mebot_scene.xml ...]

Checks mebot_scene.xml and mebot_powered_front_scene.xml unless scenes are given. Needs the mujoco Python
package. Each lift command is ramped at its PARAMS speed (as the Unreal motor table's MaxVelocity would), each
wheel speed is held by a small PI loop, and every check prints PASS or FAIL; the exit code is the number of
failures.
"""
import argparse
import math
import os
import sys

import mujoco

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_mebot_mjcf as B  # noqa: E402

P = B.PARAMS
LIFTS = ("elevator_l", "elevator_r", "translator_l", "translator_r", "front_arm", "rear_lift")
WHEELS = ("drive_wheel_l", "drive_wheel_r", "front_omni_l", "front_omni_r", "rear_omni_l", "rear_omni_r")


class Sim:
    def __init__(self, scene):
        self.m = mujoco.MjModel.from_xml_path(scene)
        self.d = mujoco.MjData(self.m)
        self.act = {self.m.actuator(i).name: i for i in range(self.m.nu)}
        el, arm, tr = math.radians(P["elevator"]["speed_deg_s"]), math.radians(P["caster_arm"]["speed_deg_s"]), P["translator"]["speed_cm_s"] / 100
        rear = math.radians(P["rear_lift"]["speed_deg_s"])
        self.rate = {"elevator_l": el, "elevator_r": el, "front_arm": arm, "rear_lift": rear, "translator_l": tr, "translator_r": tr}
        self.cmd = {k: 0.0 for k in LIFTS}
        self.goal = dict(self.cmd)
        self.wheel_goal = {"l": 0.0, "r": 0.0}
        self.integ = {"l": 0.0, "r": 0.0}
        self.front_goal = None                  # the powered front omni wheels freewheel unless given a speed
        self.front_integ = {"l": 0.0, "r": 0.0}
        self.floor = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        # Each wheel's geoms: its own and its rollers'.
        self.wheel_geoms = {}
        for w in WHEELS:
            root = self.m.body(w).id
            self.wheel_geoms[w] = {g for g in range(self.m.ngeom) if self._under(self.m.geom_bodyid[g], root)}

    def _under(self, b, root):
        while b > 0:
            if b == root:
                return True
            b = self.m.body_parentid[b]
        return False

    def q(self, joint):
        return self.d.joint(joint).qpos[0]

    def body(self, name):
        return self.d.body(name).xpos.copy()

    def pitch_roll_yaw(self):
        w, x, y, z = self.d.body("chassis").xquat
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))))
        roll = math.degrees(math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)))
        yaw = math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))
        return pitch, roll, yaw

    def touching(self):
        """The wheels with a contact against the floor."""
        on = set()
        for c in self.d.contact[: self.d.ncon]:
            other = c.geom2 if c.geom1 == self.floor else c.geom1 if c.geom2 == self.floor else None
            for w, gs in self.wheel_geoms.items():
                if other in gs:
                    on.add(w)
        return on

    def step(self):
        dt = self.m.opt.timestep
        for k in LIFTS:
            err = self.goal[k] - self.cmd[k]
            self.cmd[k] += max(-self.rate[k] * dt, min(self.rate[k] * dt, err))
            self.d.ctrl[self.act[k]] = self.cmd[k]
        for s in ("l", "r"):
            e = self.wheel_goal[s] - self.d.joint("drive_wheel_" + s).qvel[0]
            # The integral stops at what the motor can give: past that it winds up, the wheels' speeds part,
            # and a turn in place drifts along an arc.
            tq = P["drive"]["torque"]
            self.integ[s] = max(-tq / 100.0, min(tq / 100.0, self.integ[s] + e * dt))
            self.d.ctrl[self.act["drive_" + s]] = max(-tq, min(tq, 60.0 * e + 100.0 * self.integ[s]))
        if "front_omni_l" in self.act:         # the powered-front variant's hub motors
            for s in ("l", "r"):
                if self.front_goal is None:
                    self.front_integ[s] = self.d.ctrl[self.act["front_omni_" + s]] = 0.0
                    continue
                e = self.front_goal[s] - self.d.joint("front_omni_" + s).qvel[0]
                self.front_integ[s] = max(-1.0, min(1.0, self.front_integ[s] + e * dt))
                tq = P["front_omni_drive"]["torque"]
                self.d.ctrl[self.act["front_omni_" + s]] = max(-tq, min(tq, 3.0 * e + 10.0 * self.front_integ[s]))
        mujoco.mj_step(self.m, self.d)

    def closure_mm(self):
        """The largest gap across the linkages' loop closures, mm."""
        worst = 0.0
        for i in range(self.m.neq):
            b1, b2 = self.m.eq_obj1id[i], self.m.eq_obj2id[i]
            p1 = self.d.xpos[b1] + self.d.xmat[b1].reshape(3, 3) @ self.m.eq_data[i][0:3]
            p2 = self.d.xpos[b2] + self.d.xmat[b2].reshape(3, 3) @ self.m.eq_data[i][3:6]
            worst = max(worst, float(((p1 - p2) ** 2).sum() ** 0.5))
        return worst * 1000

    def run(self, seconds=None, goals=None, wheels=None, front=None, settle=1.0):
        """Command goals (ramped) and/or wheel speeds (drive, powered front omni); run until the ramps finish,
        then settle seconds more (or exactly seconds, if given)."""
        self.goal.update(goals or {})
        if wheels is not None:
            self.wheel_goal["l"], self.wheel_goal["r"] = wheels
        if front is not None:
            self.front_goal = None if front == "free" else {"l": front[0], "r": front[1]}
        t0, held = self.d.time, 0.0
        while True:
            self.step()
            if seconds is not None:
                if self.d.time - t0 >= seconds:
                    return
                continue
            if all(abs(self.goal[k] - self.cmd[k]) < 1e-9 for k in LIFTS):
                held += self.m.opt.timestep
                if held >= settle:
                    return


def check_scene(scene):
    print("== %s" % os.path.basename(scene))
    s = Sim(scene)
    fails = []
    gap = [0.0]

    def check(name, ok, detail):
        print("%s  %-46s %s" % ("PASS" if ok else "FAIL", name, detail))
        if not ok:
            fails.append(name)
        gap[0] = max(gap[0], s.closure_mm())

    deg = math.radians
    s.run(seconds=2.0)
    p, r, _ = s.pitch_roll_yaw()
    on = s.touching()
    check("stands on all six wheels", on == set(WHEELS), "touching: %s" % ", ".join(sorted(on)))
    check("stands level", abs(p) < 3 and abs(r) < 1, "pitch %+.1f roll %+.1f deg" % (p, r))
    top = P["rear_spring"]["travel_cm"][0] / 100
    check("the rear wheels' load compresses the damper", s.q("rear_spring") > top + 0.001,
          "damper %.1f mm off its top-out" % ((s.q("rear_spring") - top) * 1000))

    z0 = s.body("chassis")[2]
    s.run(goals={"elevator_l": deg(10), "elevator_r": deg(10)})
    dz = s.body("chassis")[2] - z0
    check("elevators +10 deg raise the chassis", dz > 0.01, "chassis %+.1f cm, elevators %.1f / %.1f deg" % (
        dz * 100, math.degrees(s.q("elevator_l")), math.degrees(s.q("elevator_r"))))
    s.run(goals={"elevator_l": 0.0, "elevator_r": 0.0})

    s.run(goals={"elevator_l": deg(-10)})
    on = s.touching()
    check("left elevator -10 deg lifts the left drive wheel", "drive_wheel_l" not in on and "drive_wheel_r" in on,
          "touching: %s" % ", ".join(sorted(on)))
    s.run(goals={"elevator_l": 0.0})

    rel0 = s.body("drive_wheel_l")[0] - s.body("chassis")[0]
    s.run(goals={"translator_l": 0.10, "translator_r": 0.10})
    drel = s.body("drive_wheel_l")[0] - s.body("chassis")[0] - rel0
    check("translators +10 cm move the drive wheels forward", abs(drel - 0.10) < 0.01 and abs(s.q("translator_r") - 0.10) < 0.01,
          "drive wheel %+.1f cm on the chassis (L %.1f, R %.1f cm)" % (drel * 100, s.q("translator_l") * 100, s.q("translator_r") * 100))
    s.run(goals={"translator_l": 0.0, "translator_r": 0.0})

    for lift, arm in (("front_arm", "front_arm"), ("rear_lift", "rear_arm")):
        z0, a0 = s.body(arm)[2], s.q(arm)
        s.run(goals={lift: deg(15)})
        dz = s.body(arm)[2] - z0
        check("%s +15 deg raises its end of the chassis" % lift.replace("_", " "), dz > 0.01, "pivot %+.1f cm, %s %+.1f deg" % (
            dz * 100, arm.replace("_", " "), math.degrees(s.q(arm) - a0)))
        s.run(goals={lift: 0.0})

    x0 = s.body("chassis")[0]
    _, _, yaw0 = s.pitch_roll_yaw()
    s.run(seconds=2.0, wheels=(3.0, 3.0))
    s.run(seconds=1.0, wheels=(0.0, 0.0))
    dx = s.body("chassis")[0] - x0
    _, _, yaw = s.pitch_roll_yaw()
    check("drive wheels + drive forward, straight", dx > 0.4 and abs(yaw - yaw0) < 5, "%+.2f m, yaw %+.1f deg" % (dx, yaw - yaw0))

    # In place: about the drive axle's midpoint (the chassis origin is aft of it and circles in a correct turn).
    axle0 = (s.body("drive_wheel_l") + s.body("drive_wheel_r"))[:2] / 2
    s.run(seconds=2.0, wheels=(-2.0, 2.0))
    s.run(seconds=1.0, wheels=(0.0, 0.0))
    _, _, yaw2 = s.pitch_roll_yaw()
    dyaw = (yaw2 - yaw + 180) % 360 - 180
    drift = float(((s.body("drive_wheel_l") + s.body("drive_wheel_r"))[:2] / 2 - axle0) @ ((s.body("drive_wheel_l") + s.body("drive_wheel_r"))[:2] / 2 - axle0)) ** 0.5
    check("left -, right + turns left in place", dyaw > 30 and drift < 0.06, "yaw %+.0f deg, drive axle midpoint moved %.1f cm" % (dyaw, drift * 100))

    if "front_omni_l" in s.act:
        s.run(goals={"elevator_l": deg(-15), "elevator_r": deg(-15)})
        on = s.touching()
        p0, heading = s.body("chassis"), s.d.body("chassis").xmat.reshape(3, 3)[:, 0].copy()
        s.run(seconds=2.0, front=(6.0, 6.0))
        s.run(seconds=1.0, front=(0.0, 0.0))
        dx = float((s.body("chassis") - p0) @ heading)
        s.run(seconds=0.1, front="free")
        check("powered front omni wheels drive it on its omnis", dx > 0.5 and not on & {"drive_wheel_l", "drive_wheel_r"},
              "%+.2f m forward with the drive wheels up" % dx)
        s.run(goals={"elevator_l": 0.0, "elevator_r": 0.0})

    check("linkages stay closed", gap[0] < 1.0, "largest loop-closure gap %.2f mm" % gap[0])
    return fails


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scene", nargs="*", default=[os.path.join(HERE, n) for n in ("mebot_scene.xml", "mebot_powered_front_scene.xml")])
    args = ap.parse_args()
    fails = sum((check_scene(sc) for sc in args.scene), [])
    print("%d check(s) failed" % len(fails) if fails else "all checks passed")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
