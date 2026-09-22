"""Check the holonomic drive: first the kinematics, then the motion.

Two layers, deliberately separated.

  KINEMATICS -- what wheel rates does a body twist produce? Pure maths, no
  physics, so it answers the sign-convention question on its own. The MJCF spin
  axes are in MuJoCo's Y-left frame and the spec is authored in UE's Y-right
  frame, so a mirrored strafe is the most likely mistake and the one worth
  catching without anything touching the ground.

  MOTION -- does the chassis actually go that way? Correct kinematics are not
  enough, and the ways this fails are not all "friction": a rate written into a
  torque actuator, a wheel radius that does not match the wheel, an input
  component re-asserting zero every frame over the top of the command. Each of
  those has happened here, and each looked like poor traction from the outside.

  So the phase reports three things rather than one -- the chassis displacement,
  the wheels' own speed against what was commanded, and the fraction of the
  rolling that reached the ground. Speed far below the command is the
  controller or the loop; speed on target with the base still is traction.

  As of the working configuration, forward and yaw drive the base properly.
  Strafe does not, and a failure confined to the strafe leg is expected: an omni
  wheel has to slide along its axle, MuJoCo's per-geom friction is a single
  isotropic coefficient, and the contact frame is only aligned to the geometry
  for capsules (these wheels are cylinders). That needs the rollers modelled,
  not a friction number.

Run inside the editor with PIE started on a holonomic test level:
    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/drive/test_holonomic_drive.py

Two phases, because motion needs frames to happen in:
    unreal._ramms_drive_phase = "kinematics"   # default; also arms the motion run
    unreal._ramms_drive_phase = "motion"       # report what moved
"""

import math

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

# The ACTOR is only an anchor: URLab writes poses to the body components, and
# the actor transform never moves. Measuring it reports a robot that drove off
# the map as perfectly stationary, which is exactly what it did here once.
bodies = {c.get_name(): c for c in pawn.get_components_by_class(unreal.ActorComponent)
          if c.get_class().get_name() == "MjBody"}
chassis = bodies.get("base_link")
if chassis is None:
    raise RuntimeError("no base_link MjBody on the pawn; nothing to measure")
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


# Wheel speed is read from the motor registry, not integrated from the wheel
# bodies' orientation. The quaternion route silently under-reports once a wheel
# turns more than half a revolution between samples -- the angle between two
# orientations is never more than pi, so the faster a wheel spins the smaller
# the answer gets, and it read a friction sweep as non-monotonic before this.


if PHASE == "kinematics":
    if selector:
        check(selector.set_active_mode("holonomic"), "selector switched to holonomic")

    wheels = holo.get_editor_property("drive").get_editor_property("wheels")
    names = [str(w.get_editor_property("motor_id")) for w in wheels]
    radius = holo.get_editor_property("drive").get_editor_property("wheel_radius_cm")
    print("[drive] wheels: %s" % names)
    check(len(wheels) >= 3, "at least 3 wheels configured (%d)" % len(wheels))

    # State the friction this run happened under. A sweep that changes the
    # Blueprint but never reaches the runtime geoms measures the same value
    # twice and reads as "friction makes no difference", which has happened.
    omni = [c for c in pawn.get_components_by_class(unreal.ActorComponent)
            if c.get_class().get_name() == "MjGeom"
            and c.get_attach_parent() is not None
            and "omni_wheel" in c.get_attach_parent().get_name().lower()]
    overridden = [g for g in omni if g.has_friction()]
    if not omni:
        print("[drive] NOTE no geoms found under the omni wheel bodies")
    elif not overridden:
        print("[drive] omni friction: %d geoms, none overridden -- all on the "
              "model's shared collision class" % len(omni))
    else:
        # MuJoCo friction is a three-term array (slide, spin, roll), not a
        # Vector, however much it looks like one.
        f = list(overridden[0].get_friction())
        print("[drive] omni friction: %d of %d geoms overridden, %s"
              % (len(overridden), len(omni),
                 " ".join("%s=%.4f" % (k, v)
                          for k, v in zip(("slide", "spin", "roll"), f))))

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
    base = pawn.get_component_by_class(unreal.RammsRobotBaseComponent)
    if base is None:
        raise RuntimeError("no RammsRobotBaseComponent; wheel speeds unreadable")
    wheel_ids = [unreal.Name(n) for n in names]

    # Stamp the run with the world it was armed in. A PIE restart between the
    # two phases leaves the previous session's samples sitting on the unreal
    # module, and reporting those reads as a perfectly repeatable result --
    # three friction values once came back identical to the last decimal.
    unreal._ramms_drive_data = {"samples": [], "rolled": 0.0, "radius": radius,
                                "speed_sum": 0.0, "speed_n": 0, "peak_speed": 0.0,
                                "error": None, "world": world.get_path_name()}
    st = {"n": 0}
    HOLD = 45
    # Switching to holonomic raises the centre wheels off the ground, and the
    # base then drops onto the omni wheels. Drive before that settles and the
    # first leg measures the fall, not the command.
    SETTLE = 60

    def stop_sampling():
        h = getattr(unreal, "_ramms_drive_h", None)
        if h is not None:
            unreal.unregister_slate_post_tick_callback(h)
            unreal._ramms_drive_h = None

    def sample(dt):
        # A raise in here is invisible from the remote-exec side and repeats
        # every frame, so catch it once, keep it, and stand the run down.
        try:
            sample_inner(dt)
        except Exception:
            import traceback
            unreal._ramms_drive_data["error"] = traceback.format_exc()
            holo.set_drive_command(unreal.Vector(0.0, 0.0, 0.0))
            stop_sampling()

    def sample_inner(dt):
        n = st["n"]
        st["n"] = n + 1
        loc = chassis.get_world_location()
        # MjBody hands back a Quat here, not a Rotator; reading `.yaw` off it
        # raises inside the callback, which fails silently frame after frame and
        # leaves the motion phase with an empty sample list.
        yaw = chassis.get_world_rotation().rotator().yaw

        # Mean wheel speed this frame, so a leg can be scored on how much of
        # the rolling the ground took up -- and so a loop that never reaches
        # its commanded rate is visible separately from one that reaches it
        # and slips.
        if n > SETTLE and dt > 0.0:
            speeds = [abs(base.get_motor_velocity(mid)) for mid in wheel_ids]
            mean = sum(speeds) / max(1, len(speeds))
            d = unreal._ramms_drive_data
            d["rolled"] += mean * radius * dt
            d["speed_sum"] += mean
            d["speed_n"] += 1
            d["peak_speed"] = max(d["peak_speed"], max(speeds))

        unreal._ramms_drive_data["samples"].append((n, loc.x, loc.y, yaw))
        if n == SETTLE:
            holo.set_drive_command(unreal.Vector(1.0, 0.0, 0.0))
        elif n == SETTLE + HOLD:
            holo.set_drive_command(unreal.Vector(0.0, 1.0, 0.0))
        elif n == SETTLE + HOLD * 2:
            holo.set_drive_command(unreal.Vector(0.0, 0.0, 1.0))
        elif n >= SETTLE + HOLD * 3:
            # Stop from inside the callback, so a run that never reaches the
            # report phase cannot leave the base driving.
            holo.set_drive_command(unreal.Vector(0.0, 0.0, 0.0))
            stop_sampling()

    stop_sampling()
    unreal._ramms_drive_h = unreal.register_slate_post_tick_callback(sample)
    unreal._ramms_drive_hold = HOLD
    unreal._ramms_drive_settle = SETTLE
    print("[drive] motion run armed: %d settle frames, then forward, strafe, "
          "turn, %d frames each" % (SETTLE, HOLD))
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
    if data and data.get("error"):
        print("[drive] the sampler died during the run:")
        print(data["error"])
    if not data or not data["samples"]:
        raise RuntimeError("nothing sampled -- run the kinematics phase first")
    if data.get("world") != world.get_path_name():
        raise RuntimeError(
            "these samples were taken in %s, not the session running now (%s) "
            "-- re-run the kinematics phase" % (data.get("world"), world.get_path_name()))
    s = data["samples"]
    HOLD = getattr(unreal, "_ramms_drive_hold", 45)
    SETTLE = getattr(unreal, "_ramms_drive_settle", 0)
    print("[drive] %d samples collected (%d settle + 3 x %d expected)"
          % (len(s), SETTLE, HOLD))
    if len(s) < SETTLE + HOLD * 3:
        print("[drive] NOTE the run was cut short; give it more wall time next run")

    def leg(a, b):
        a = min(a, len(s) - 1)
        b = min(b, len(s) - 1)
        return (s[b][1] - s[a][1], s[b][2] - s[a][2], s[b][3] - s[a][3])

    ddx, ddy, ddyaw = leg(0, SETTLE)
    fdx, fdy, fdyaw = leg(SETTLE, SETTLE + HOLD)
    sdx, sdy, sdyaw = leg(SETTLE + HOLD, SETTLE + HOLD * 2)
    tdx, tdy, tdyaw = leg(SETTLE + HOLD * 2, SETTLE + HOLD * 3)

    # Undriven drift is the yardstick. A leg that moves no further than the
    # robot moves on its own says nothing about the command, so the checks below
    # are written against the drift rather than against zero.
    drift = max(abs(ddx), abs(ddy))
    drift_yaw = abs(ddyaw)
    print("[drive] settle drift: dx=%+.1f dy=%+.1f dyaw=%+.1f" % (ddx, ddy, ddyaw))
    print("[drive] forward leg: dx=%+.1f dy=%+.1f dyaw=%+.1f" % (fdx, fdy, fdyaw))
    print("[drive] strafe  leg: dx=%+.1f dy=%+.1f dyaw=%+.1f" % (sdx, sdy, sdyaw))
    print("[drive] turn    leg: dx=%+.1f dy=%+.1f dyaw=%+.1f" % (tdx, tdy, tdyaw))

    # How much of the rolling reached the ground? The wheels turning while the
    # base stays put is the traction failure, and it is invisible in the
    # displacement numbers alone.
    radius = data.get("radius") or 7.5
    rolled = data.get("rolled", 0.0)
    n_speed = max(1, data.get("speed_n", 1))
    mean_speed = data.get("speed_sum", 0.0) / n_speed
    peak_speed = data.get("peak_speed", 0.0)
    travelled = math.hypot(s[-1][1] - s[SETTLE][1], s[-1][2] - s[SETTLE][2])
    print("[drive] wheel speed: mean %.2f rad/s, peak %.2f rad/s over %d frames"
          % (mean_speed, peak_speed, n_speed))
    print("[drive] that is %.1f cm of rolling at r=%.1f cm; the base covered %.1f cm"
          % (rolled, radius, travelled))
    if rolled > 1.0:
        print("[drive] traction: %.0f%% of the rolling reached the ground"
              % (100.0 * travelled / rolled))

    # Each leg has to clear the drift by a clear margin, or it is noise wearing
    # the right sign. 3x the drift and 2 cm absolute; a leg the size of the
    # drift is not evidence of anything.
    floor = max(3.0 * drift, 2.0)
    yaw_floor = max(3.0 * drift_yaw, 5.0)
    check(abs(fdx) > floor and abs(fdx) > abs(fdy),
          "forward leg drove along X (dx=%+.1f dy=%+.1f, needs |dx|>%.1f)"
          % (fdx, fdy, floor))
    check(abs(sdy) > floor and abs(sdy) > abs(sdx),
          "strafe leg drove along Y (dx=%+.1f dy=%+.1f, needs |dy|>%.1f)"
          % (sdx, sdy, floor))
    check(abs(tdyaw) > yaw_floor,
          "turn leg rotated the chassis (dyaw=%+.1f, needs |dyaw|>%.1f)"
          % (tdyaw, yaw_floor))

    if failures and rolled > 10.0 and travelled < 0.2 * rolled:
        print("[drive] NOTE the wheels turned and the base did not follow. "
              "Check the commanded-vs-achieved speed above first: on target "
              "means traction, well below means the controller or the loop. "
              "Traction on the strafe leg alone is the known one -- the omni "
              "rollers are not simulated, so the wheels cannot slide along "
              "their axles.")

    print("[drive] ---- %d motion checks failed ----" % len(failures))
    for f in failures:
        print("[drive] FAILED: %s" % f)
