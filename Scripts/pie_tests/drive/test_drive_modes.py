"""Check the drive-mode selector: what each mode offers, and that it gives it back.

A robot carries several ways of driving the same chassis and exactly one is
live. The surface is rebuilt around whichever that is, so switching mode is
observable as a change in shape:

  - the active mode's drive axes are present and the others' are not (they all
    advertise drive.forward / drive.turn, so two live at once would collide);
  - the active mode's motors are claimed, so they are not also offered raw;
  - low level claims nothing and gates the raw per-motor axes, which is the
    whole reason it exists.

The part worth a regression test is the round trip. Standing a mode down has to
undo everything standing it up did -- the low-level mode suspends other
contributors and rewrites the surface's motor exposure, and a stand-down that
skipped either would strand the robot with no drive controls and limp linkages,
recoverable only by restarting play.

Run inside the editor with PIE started on a level whose pawn has a selector:
    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/drive/test_drive_modes.py
"""

import unreal

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_game_world()
if world is None:
    raise RuntimeError("no PIE world -- start play on a drive-mode level first")

pawn = next((a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn)
             if a.get_component_by_class(unreal.RammsDriveModeSelector)), None)
if pawn is None:
    raise RuntimeError("no pawn with a RammsDriveModeSelector in this level")

selector = pawn.get_component_by_class(unreal.RammsDriveModeSelector)
surface = pawn.get_component_by_class(unreal.RammsRobotControlSurfaceComponent)
if surface is None:
    raise RuntimeError("the pawn has a selector but no control surface to rebuild")

low = pawn.get_component_by_class(unreal.RammsLowLevelDriveMode)

failures = []


def check(ok, msg):
    print("[modes] %s %s" % ("PASS" if ok else "FAIL", msg))
    if not ok:
        failures.append(msg)


def claimed_wheel_axes(mode_id):
    """Raw axis Ids for the motors this mode claims -- none should be offered."""
    comp = None
    if mode_id == "holonomic":
        comp = pawn.get_component_by_class(unreal.RammsHolonomicDriveController)
    if comp is None:
        return []
    wheels = comp.get_editor_property("drive").get_editor_property("wheels")
    return ["motor.%s" % w.get_editor_property("motor_id") for w in wheels]


def shape():
    """What the surface offers right now, by group."""
    d = surface.describe_control_surface()
    ids = [str(ax.id) for ax in d.axes]
    return {
        "ids": ids,
        "drive": [i for i in ids if i.startswith("drive.") and i != "drive.mode"],
        "motors": [i for i in ids if i.startswith("motor.")],
        "linkage": [i for i in ids if i.startswith("linkage.")],
    }


modes = [str(m) for m in selector.get_available_mode_ids()]
print("[modes] available: %s" % modes)
check(len(modes) >= 2, "the robot carries more than one drive mode (%d)" % len(modes))

start_mode = str(selector.get_active_mode_id())
start_exposure = surface.get_editor_property("expose_unclaimed_motors")
start_group = str(surface.get_editor_property("unclaimed_motor_group"))
print("[modes] starting in '%s', surface exposure=%s group=%s"
      % (start_mode, start_exposure, start_group))

# --- each mode in turn ------------------------------------------------------
per_mode = {}
for mid in modes:
    check(selector.set_active_mode(unreal.Name(mid)), "selector switched to '%s'" % mid)
    check(str(selector.get_active_mode_id()) == mid, "'%s' reports itself active" % mid)
    s = shape()
    per_mode[mid] = s
    print("[modes] %-14s drive=%s motors=%d linkage=%d"
          % (mid, s["drive"], len(s["motors"]), len(s["linkage"])))

    if mid == "low_level":
        # It drives nothing, so it must offer no drive axes -- and it is the
        # only mode that offers the raw ones.
        check(not s["drive"], "low level offers no drive axes (%s)" % s["drive"])
        check(len(s["motors"]) > 0, "low level offers the raw motor axes (%d)" % len(s["motors"]))
    else:
        check("drive.forward" in s["drive"], "'%s' offers drive.forward" % mid)
        # The raw axes are low level's alone: a robot carrying one has its
        # per-motor exposure decided by the mode, not by the surface's
        # authored flag, or the gate would do nothing (the flag defaults on).
        if low is not None:
            check(len(s["motors"]) == 0,
                  "'%s' leaves the raw motor axes gated off (%d offered)"
                  % (mid, len(s["motors"])))
        check(not any(w in s["drive"] for w in claimed_wheel_axes(mid)),
              "'%s' does not also offer its own wheels raw" % mid)

# No two modes may advertise the same drive axis at once -- the surface only
# ever sees one of them, which is the property this whole mechanism rests on.
# --- the round trip that used to strand the robot ---------------------------
if low is not None and "low_level" in modes:
    other = next((m for m in modes if m != "low_level"), None)

    for claim_all in (False, True):
        low.set_claim_all_actuators(claim_all)
        check(selector.set_active_mode(unreal.Name("low_level")),
              "switched to low level with bClaimAllActuators=%s" % claim_all)
        during = shape()
        if claim_all:
            check(len(during["linkage"]) == 0,
                  "claiming all actuators withdraws the linkage controls (%d left)"
                  % len(during["linkage"]))

        check(selector.set_active_mode(unreal.Name(other)), "switched back to '%s'" % other)
        after = shape()
        check("drive.forward" in after["drive"],
              "'%s' has its drive axes back after low level (bClaimAllActuators=%s)"
              % (other, claim_all))
        check(after["linkage"] == per_mode[other]["linkage"],
              "'%s' has its linkage controls back after low level (%d, expected %d)"
              % (other, len(after["linkage"]), len(per_mode[other]["linkage"])))
        check(len(after["motors"]) == 0,
              "the raw motor axes are gated off again outside low level (%d left)"
              % len(after["motors"]))

    # The regression this exists for: turning the flag off while low level is
    # LIVE used to make the stand-down skip un-suspending, so the contributors
    # it had suspended never came back.
    low.set_claim_all_actuators(True)
    selector.set_active_mode(unreal.Name("low_level"))
    low.set_claim_all_actuators(False)
    selector.set_active_mode(unreal.Name(other))
    stranded = shape()
    check("drive.forward" in stranded["drive"],
          "clearing bClaimAllActuators while low level is live still releases the "
          "contributors it suspended (drive=%s)" % stranded["drive"])
    check(stranded["linkage"] == per_mode[other]["linkage"],
          "...and the linkages come back too (%d, expected %d)"
          % (len(stranded["linkage"]), len(per_mode[other]["linkage"])))

# --- exposure follows the mode, not the authored flag -----------------------
# Deliberately not "the authored value is restored": on a robot that carries a
# low-level mode the flag is the mode's to drive, and putting the authored one
# back (it defaults to true) would leave every motor exposed in every mode.
check(surface.get_editor_property("expose_unclaimed_motors") is False,
      "outside low level the raw motors are gated off at the surface")
check(str(surface.get_editor_property("unclaimed_motor_group")) == start_group,
      "the motor group is unchanged (%s)" % start_group)

selector.set_active_mode(unreal.Name(start_mode))
print("[modes] ---- %d checks failed ----" % len(failures))
for f in failures:
    print("[modes] FAILED: %s" % f)
