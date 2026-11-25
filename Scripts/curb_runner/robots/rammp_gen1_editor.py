"""RAMMP Gen1's adapter inside the editor (runner_op.py runs it): how the runner reads and drives the robot.

An adapter module defines find(world, wheels) -> an object with:
  sim_time()       the physics' own clock (s), which the session times everything by (below 0: not yet)
  chassis()        {"xyz": [cm], "pitch", "yaw", "roll"} of the chassis body, world
  seat()           {"pitch", "roll"} of the rider's seat, or None (the chassis stands in)
  wheel_hubs()     [[x, y, z] or None, ...] the wheels' hubs (cm, world) in the profile's wheel order
  wheel_rates()    [rad/s] of the powered wheels (the steady gate's)
  prepare(setup)   put the robot in its standard setup (the profile's `setup`); returns what it set
  negotiate()      ask for a crossing: (accepted, the controller's words)
  abort()
  phase()          (generic, raw): generic IDLE / PLANNING (planning, not yet carrying it out) / DONE / FAULTED /
                   ABORTED, else the raw phase's name
  status()         the controller's status line
  step_found()     (step cm, crossing height cm) the controller found, or None
  stats()          the controller's own measurements, a dict
  lifts()          {name: value} of anything a crossing must put back (the runner compares the ask's and the end's)
  hold_stick(v) / release_stick()

For a level-assist course (runner_op.py's begin_course; a robot without these runs crossings only):
  drive(forward, turn) / release_drive()   the rider's stick held in whatever drive mode is active (source Script;
                   called every frame), and let go
  set_control(id, value)   any control, source Script -> whether the surface took it (level.assist, level.pref.*)
  level()          {"assist", "state", "tilt", "reach", "speed_scale", "pref_pitch", "pref_roll", "status", "sev"}:
                   the level.* controls, or None on a robot without a level assist
  mode() / set_mode(id)    the active drive mode's id, and a switch -> whether the selector took it
  commands()       {motor: [baseline, offset, joint]} of the motors a level assist moves (what each was told, in
                   two parts, and where it is)
  ground()         {"n": {wheel: normal force N, None off the ground}, "others": N on anything else, "com": [x, y],
                   "pts": {wheel: [x, y] where it bears}} from the physics' ground support, or None
"""

import unreal

REMOTE = unreal.RammsControlSource.REMOTE
SCRIPT = unreal.RammsControlSource.SCRIPT
# The wheels' motors (the body name -> the motor id), for the steady gate's wheel rates.
MOTORS = {"front_omni_l": "front_omni_l", "front_omni_r": "front_omni_r", "drive_wheel_l": "drive_l", "drive_wheel_r": "drive_r"}
LIFTS = ("elevator_l", "elevator_r", "translator_l", "translator_r", "front_arm", "rear_lift")  # rad, cm the translators
LEVEL_IDS = ("assist", "state", "tilt", "reach", "speed_scale", "pref.pitch", "pref.roll")
GROUND_WINDOW_S = 0.05


def find(world, wheels):
    for pawn in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn):
        curb = pawn.get_component_by_class(unreal.RammsRammpGen1CurbController)
        if curb is not None:
            return Adapter(pawn, curb, wheels)
    return None


def rot_of(comp):
    q = comp.get_world_rotation()
    return q.rotator() if hasattr(q, "rotator") else q


class Adapter(object):
    def __init__(self, pawn, curb, wheels):
        self.pawn, self.curb = pawn, curb
        self.cs = pawn.get_component_by_class(unreal.RammsRobotControlSurfaceComponent)
        self.base = pawn.get_component_by_class(unreal.RammsRobotBaseComponent)
        comps = {c.get_name(): c for c in pawn.get_components_by_class(unreal.SceneComponent)}
        self.chassis_c = comps.get("chassis")
        if self.chassis_c is None:
            raise RuntimeError("%s has no chassis body component" % pawn.get_name())
        self.seat_c = comps.get("seat")
        self.wheel_c = [comps.get(w["name"]) for w in wheels]
        self.wheel_names = [w["name"] for w in wheels]
        missing = [w["name"] for w, c in zip(wheels, self.wheel_c) if c is None]
        if missing:
            raise RuntimeError("%s has no wheel body %s" % (pawn.get_name(), ", ".join(missing)))
        self.powered = [MOTORS[w["name"]] for w in wheels if w.get("powered") and w["name"] in MOTORS]

    def chassis(self):
        loc, r = self.chassis_c.get_world_location(), rot_of(self.chassis_c)
        return {"xyz": [loc.x, loc.y, loc.z], "pitch": r.pitch, "yaw": r.yaw, "roll": r.roll}

    def seat(self):
        if self.seat_c is None:
            return None
        r = rot_of(self.seat_c)
        return {"pitch": r.pitch, "roll": r.roll}

    def sim_time(self):
        """The physics' own clock (s): the robot base's simulation time (the snapshot the controller reads); below 0
        before the physics has published one."""
        return self.base.get_simulation_time() if self.base else -1.0

    def wheel_hubs(self):
        out = []
        for c in self.wheel_c:
            p = c.get_world_location()
            out.append([p.x, p.y, p.z])
        return out

    def wheel_rates(self):
        return [self.base.get_motor_velocity(m) for m in self.powered] if self.base else []

    def prepare(self, setup):
        done = {}
        if "style" in setup:
            self.cs.set_control("curb.style", float(setup["style"]), REMOTE)
            done["curb.style"] = setup["style"]
        for cid, v in (setup.get("stance") or {}).items():
            if not self.cs.set_control(cid, float(v), REMOTE):
                raise RuntimeError("the control surface refused %s %s" % (cid, v))
            done[cid] = v
        return done

    def negotiate(self):
        ok = bool(self.cs.trigger_control("curb.negotiate", REMOTE))
        return ok, str(self.curb.get_status())

    def abort(self):
        self.cs.trigger_control("curb.abort", REMOTE)

    def phase(self):
        raw = self.curb.get_phase().name
        if raw == "IDLE":
            return "IDLE", raw
        if raw == "DONE":
            return "DONE", raw
        if raw == "ABORTED":
            return ("FAULTED" if self.status().startswith("Faulted:") else "ABORTED"), raw
        return raw, raw

    def status(self):
        try:
            return str(self.cs.get_control_text("curb.status"))
        except Exception:  # noqa: BLE001
            return str(self.curb.get_status())

    def step_found(self):
        step, height = self.curb.get_crossing()
        return [round(step, 2), round(height, 2)]

    def stats(self):
        s = self.curb.get_stats()
        out = {}
        for k in ("crossing_seconds", "edge_to_rear_down_seconds", "edge_to_end_seconds", "stops", "seconds_stopped",
                  "max_abs_pitch_deg", "max_abs_roll_deg", "max_inclination_deg", "max_pitch_rate_deg_s",
                  "peak_rider_accel_ms2", "peak_rider_fore_aft_accel_ms2", "peak_rider_vertical_accel_ms2",
                  "rms_rider_accel_ms2", "min_stability_margin_cm", "min_frame_clearance_cm", "frame_measured"):
            try:
                v = s.get_editor_property(k)
            except Exception:  # noqa: BLE001  (a field this build does not have)
                continue
            out[k] = v if isinstance(v, (bool, int)) else round(float(v), 3)
        for k in ("min_margin_phase", "min_clearance_phase"):
            try:
                out[k] = s.get_editor_property(k).name
            except Exception:  # noqa: BLE001
                pass
        try:
            out["style"] = self.curb.get_editor_property("style").name
        except Exception:  # noqa: BLE001
            pass
        return out

    def lifts(self):
        return {m: round(self.base.get_motor_value(m), 4) for m in LIFTS} if self.base else {}

    def hold_stick(self, v):
        self.cs.set_control("drive.forward", float(v), SCRIPT)
        self.cs.set_control("drive.turn", 0.0, SCRIPT)

    def release_stick(self):
        for i in ("drive.forward", "drive.turn"):
            self.cs.release_control(i, SCRIPT)

    # --- a level-assist course ----------------------------------------------------------------------------------
    def drive(self, forward, turn):
        self.cs.set_control("drive.forward", float(forward), SCRIPT)
        self.cs.set_control("drive.turn", float(turn), SCRIPT)

    def release_drive(self):
        self.release_stick()

    def set_control(self, cid, value):
        return bool(self.cs.set_control(cid, float(value), SCRIPT))

    def level(self):
        if getattr(self, "_has_level", None) is None:
            self._has_level = '"level.assist"' in str(self.cs.get_control_surface_json())
        if not self._has_level:
            return None
        out = {i.replace(".", "_"): float(self.cs.get_control_value("level." + i)) for i in LEVEL_IDS}
        out["status"] = str(self.cs.get_control_text("level.status"))
        out["sev"] = float(self.cs.get_control_value("level.status"))
        return out

    def _selector(self):
        if getattr(self, "_sel", None) is None:
            cls = getattr(unreal, "RammsDriveModeSelector", None)
            self._sel = self.pawn.get_component_by_class(cls) if cls is not None else False
        return self._sel or None

    def mode(self):
        sel = self._selector()
        return str(sel.get_active_mode_id()) if sel is not None else None

    def set_mode(self, mode_id):
        sel = self._selector()
        return bool(sel.set_active_mode(mode_id)) if sel is not None else False

    def _command(self, motor):
        r = self.base.get_motor_command(motor)  # the value alone when the motor is found, None when it is not
        if r is None:
            return None
        if isinstance(r, tuple):
            r = next((x for x in r if not isinstance(x, bool)), None)
        return None if r is None else float(r)

    def commands(self):
        offset = getattr(self.base, "get_motor_command_offset", None)
        return {m: [self._command(m), float(offset(m)) if offset is not None else None, float(self.base.get_motor_value(m))]
                for m in LIFTS}

    def ground(self):
        lib = getattr(unreal, "RammsMjGroundSupportLibrary", None)
        if lib is None or self.base is None:
            return None
        names = [w for w in MOTORS]  # the wheels with a motor; the rest are found among the other bodies that bear
        g = lib.get_ground_support(self.base, [MOTORS[w] for w in names], GROUND_WINDOW_S)
        if not g.get_editor_property("valid"):
            return None
        n, pts, others = {}, {}, 0.0
        for w, c in zip(names, g.get_editor_property("wheels")):
            bears = c.get_editor_property("contacts") > 0
            n[w] = round(float(c.get_editor_property("normal_force_n")), 2) if bears else None
            if bears:
                q = c.get_editor_property("point")
                pts[w] = [round(q.x, 2), round(q.y, 2)]
        # A wheel without a motor bears through its rollers, and the physics names each body after the pawn:
        # "<pawn>_rear_omni_l_roller0_00". Every bearing body with the wheel's name in its own is that wheel's; the
        # wheel's point is where their forces act together.
        wheel_bodies = sorted(set(self.wheel_names) - set(names), key=len, reverse=True)
        acc = {w: [0.0, 0.0, 0.0] for w in wheel_bodies}
        for c in g.get_editor_property("others"):
            body, force = str(c.get_editor_property("body")), float(c.get_editor_property("normal_force_n"))
            w = next((w for w in wheel_bodies if body == w or body.endswith("_" + w) or ("_" + w + "_") in body), None)
            if w is None or c.get_editor_property("contacts") <= 0:
                others += force
                continue
            q = c.get_editor_property("point")
            acc[w][0] += force
            acc[w][1] += force * q.x
            acc[w][2] += force * q.y
        for w in wheel_bodies:
            f = acc[w][0]
            n[w] = round(f, 2) if f > 0.0 else None
            if f > 0.0:
                pts[w] = [round(acc[w][1] / f, 2), round(acc[w][2] / f, 2)]
        com = g.get_editor_property("center_of_mass")
        return {"n": n, "others": round(others, 2), "com": [round(com.x, 2), round(com.y, 2)], "pts": pts}
