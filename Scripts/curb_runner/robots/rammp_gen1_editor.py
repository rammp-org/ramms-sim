"""RAMMP Gen1's adapter inside the editor (runner_op.py runs it): how the runner reads and drives the robot.

An adapter module defines find(world, wheels) -> an object with:
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
"""

import unreal

REMOTE = unreal.RammsControlSource.REMOTE
SCRIPT = unreal.RammsControlSource.SCRIPT
# The wheels' motors (the body name -> the motor id), for the steady gate's wheel rates.
MOTORS = {"front_omni_l": "front_omni_l", "front_omni_r": "front_omni_r", "drive_wheel_l": "drive_l", "drive_wheel_r": "drive_r"}
LIFTS = ("elevator_l", "elevator_r", "translator_l", "translator_r", "front_arm", "rear_lift")  # rad, cm the translators


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
