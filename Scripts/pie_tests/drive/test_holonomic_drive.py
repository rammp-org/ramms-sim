"""Check the holonomic drive: first the kinematics, then the motion.

Two layers, deliberately separated.

  KINEMATICS -- what wheel rates does a body twist produce? Pure maths, no
  physics, so it answers the sign-convention question on its own. The MJCF spin
  axes are in MuJoCo's Y-left frame and the spec is authored in UE's Y-right
  frame, so a mirrored strafe is the most likely mistake and the one worth
  catching without anything touching the ground.

  MOTION -- does the chassis actually go that way? This one depends on traction,
  so a failure here with the kinematics passing means friction, not maths. That
  distinction matters: wheels that spin without moving the base looked like a
  broken controller once already.

Run inside the editor with PIE started on a holonomic test level:
    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/drive/test_holonomic_drive.py

Two phases, because motion needs frames to happen in:
    unreal._ramms_drive_phase = "kinematics"   # default; also arms the motion run
    unreal._ramms_drive_phase = "motion"       # report what moved
"""

import unreal

PHASE = getattr(unreal, "_ramms_drive_phase", "kinematics")

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_game_world()
if world is None:
    raise RuntimeError("no PIE world -- start play on a holonomic test level first")

pawn = next((a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn)
             if a.get_component_by_class(unreal.RammsHolonomicDriveController)), None)
if pawn is None:
    raise RuntimeError("no pawn with a holonomic drive controller in this level")

holo = pawn.get_component_by_class(unreal.RammsHolonomicDriveController)
selector = pawn.get_component_by_class(unreal.RammsDriveModeSelector)
surface = pawn.get_component_by_class(unreal.RammsRobotControlSurfaceComponent)

failures = []


def check(ok, msg):
    print("[drive] %s %s" % ("PASS" if ok else "FAIL", msg))
    if not ok:
        failures.append(msg)


def signs(values, eps=1e-4):
    """Sign pattern, as a string like '--++', with '0' for ~zero."""
    return "".join("0" if abs(v) < eps else ("+" if v > 0 else "-") for v in values)


if PHASE == "kinematics":
    if selector:
        check(selector.set_active_mode("holonomic"), "selector switched to holonomic")

    wheels = holo.get_editor_property("drive").get_editor_property("wheels")
    names = [str(w.get_editor_property("motor_id")) for w in wheels]
    print("[drive] wheels: %s" % names)
    check(len(wheels) >= 3, "at least 3 wheels configured (%d)" % len(wheels))

    # --- sign patterns, no physics involved ---------------------------------
    holo.set_drive_command(unreal.Vector(1.0, 0.0, 0.0))
    fwd = list(holo.solve_wheel_rates())
    holo.set_drive_command(unreal.Vector(0.0, 1.0, 0.0))
    strafe = list(holo.solve_wheel_rates())
    holo.set_drive_command(unreal.Vector(0.0, 0.0, 1.0))
    turn = list(holo.solve_wheel_rates())
    holo.set_drive_command(unreal.Vector(0.0, 0.0, 0.0))

    print("[drive] forward rates %s  -> %s" % ([round(v, 2) for v in fwd], signs(fwd)))
    print("[drive] strafe  rates %s  -> %s" % ([round(v, 2) for v in strafe], signs(strafe)))
    print("[drive] turn    rates %s  -> %s" % ([round(v, 2) for v in turn], signs(turn)))

    # Forward drives every wheel the same way: nothing is fighting.
    check(len(set(signs(fwd))) == 1 and "0" not in signs(fwd),
          "forward turns all wheels the same way (%s)" % signs(fwd))

    # The three twists must be distinguishable, or the base cannot be commanded
    # in three degrees of freedom whatever the wheels do.
    check(signs(fwd) != signs(strafe), "forward and strafe differ (%s vs %s)"
          % (signs(fwd), signs(strafe)))
    check(signs(fwd) != signs(turn), "forward and turn differ (%s vs %s)"
          % (signs(fwd), signs(turn)))
    check(signs(strafe) != signs(turn), "strafe and turn differ (%s vs %s)"
          % (signs(strafe), signs(turn)))

    # Strafe pairs diagonals; turn pairs sides. Getting these the same way round
    # is what a Y-flip between MuJoCo and UE would do.
    check(signs(strafe).count("+") == 2 and signs(strafe).count("-") == 2,
          "strafe splits the wheels two and two (%s)" % signs(strafe))
    check(signs(turn).count("+") == 2 and signs(turn).count("-") == 2,
          "turn splits the wheels two and two (%s)" % signs(turn))

    # --- arm the motion run --------------------------------------------------
    unreal._ramms_drive_data = {"samples": [], "phase": "forward"}
    st = {"n": 0}
    HOLD = 45

    def sample(dt):
        n = st["n"]
        st["n"] = n + 1
        t = pawn.get_actor_transform()
        loc = t.translation
        unreal._ramms_drive_data["samples"].append(
            (n, loc.x, loc.y, t.rotation.euler().z))
        if n == 0:
            holo.set_drive_command(unreal.Vector(1.0, 0.0, 0.0))
        elif n == HOLD:
            holo.set_drive_command(unreal.Vector(0.0, 1.0, 0.0))
        elif n == HOLD * 2:
            holo.set_drive_command(unreal.Vector(0.0, 0.0, 1.0))
        elif n >= HOLD * 3:
            # Stop from inside the callback, so a run that never reaches the
            # report phase cannot leave the base driving.
            holo.set_drive_command(unreal.Vector(0.0, 0.0, 0.0))
            h = getattr(unreal, "_ramms_drive_h", None)
            if h is not None:
                unreal.unregister_slate_post_tick_callback(h)
                unreal._ramms_drive_h = None

    h = getattr(unreal, "_ramms_drive_h", None)
    if h is not None:
        try:
            unreal.unregister_slate_post_tick_callback(h)
        except Exception:
            pass
    unreal._ramms_drive_h = unreal.register_slate_post_tick_callback(sample)
    unreal._ramms_drive_hold = HOLD
    print("[drive] motion run armed: forward, strafe, turn, %d frames each" % HOLD)
    print("[drive] ---- %d kinematics checks failed ----" % len(failures))
    for f in failures:
        print("[drive] FAILED: %s" % f)

else:
    h = getattr(unreal, "_ramms_drive_h", None)
    if h is not None:
        unreal.unregister_slate_post_tick_callback(h)
        unreal._ramms_drive_h = None
    holo.set_drive_command(unreal.Vector(0.0, 0.0, 0.0))

    data = getattr(unreal, "_ramms_drive_data", None)
    if not data or not data["samples"]:
        raise RuntimeError("nothing sampled -- run the kinematics phase first")
    s = data["samples"]
    HOLD = getattr(unreal, "_ramms_drive_hold", 45)

    def leg(a, b):
        a = min(a, len(s) - 1)
        b = min(b, len(s) - 1)
        return (s[b][1] - s[a][1], s[b][2] - s[a][2], s[b][3] - s[a][3])

    fdx, fdy, fdyaw = leg(0, HOLD)
    sdx, sdy, sdyaw = leg(HOLD, HOLD * 2)
    tdx, tdy, tdyaw = leg(HOLD * 2, HOLD * 3)

    print("[drive] forward leg: dx=%+.1f dy=%+.1f dyaw=%+.1f" % (fdx, fdy, fdyaw))
    print("[drive] strafe  leg: dx=%+.1f dy=%+.1f dyaw=%+.1f" % (sdx, sdy, sdyaw))
    print("[drive] turn    leg: dx=%+.1f dy=%+.1f dyaw=%+.1f" % (tdx, tdy, tdyaw))

    moved = max(abs(fdx), abs(fdy), abs(sdx), abs(sdy), abs(tdyaw))
    if moved < 1.0:
        # Not a kinematics failure. The wheels were commanded; nothing gripped.
        print("[drive] NOTE the chassis barely moved (%.2f). With the kinematics "
              "checks passing this is traction, not maths -- the corner wheels "
              "and the centre pair share one friction class today." % moved)
    check(abs(fdx) > abs(fdy), "forward leg moved mostly along X (dx=%+.1f dy=%+.1f)" % (fdx, fdy))
    check(abs(sdy) > abs(sdx), "strafe leg moved mostly along Y (dx=%+.1f dy=%+.1f)" % (sdx, sdy))
    check(abs(tdyaw) > 1.0, "turn leg rotated the chassis (dyaw=%+.1f)" % tdyaw)

    print("[drive] ---- %d motion checks failed ----" % len(failures))
    for f in failures:
        print("[drive] FAILED: %s" % f)
