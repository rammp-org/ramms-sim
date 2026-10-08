"""Does orbiting still drive the axes it names, once the arm hangs off a head bone?

Head tracking re-parents a camera rig onto the occupant's head bone. Anything
that aims that rig does so in its PARENT's space -- URammsRobotCameraComponent's
Orbit() adds to the spring arm's relative yaw, clamps its relative pitch and
zeroes its relative roll -- and all of that was written for a parent aligned
with the vehicle. Parented to a head bone whose axes are permuted, "yaw" turns
about a sideways axis and "roll = 0" levels against the skull.

Keeping the tracked component's rotation ABSOLUTE is what preserves those
controls, and this is the check that it did. Position still comes from the bone;
only the rotation is world-aligned.

Run with PIE running and the Mebot spawned:

    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/seat/verify_head_tracking_controls.py
"""

import unreal

ACTOR = "BP_Mebot_Ramms0"
CAMERA = "Front Camera"
# Inside the component's own pitch clamp, so this measures the AXES rather than
# re-measuring MinPitch/MaxPitch.
YAW_STEP = 30.0
PITCH_STEP = 10.0
TOL = 2.0

ML = unreal.MathLibrary
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
if world is None:
    raise RuntimeError("PIE is not running")

fails = []


def check(ok, what):
    print("[orbit] %s  %s" % ("pass" if ok else "FAIL", what))
    if not ok:
        fails.append(what)


actor = next((a for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor)
              if a.get_actor_label() == ACTOR), None)
if actor is None:
    raise RuntimeError("no %s in the PIE world" % ACTOR)

rc = actor.get_component_by_class(unreal.RammsRobotCameraComponent)
cam = next((c for c in actor.get_components_by_class(unreal.CameraComponent)
            if c.get_name() == CAMERA), None)
check(rc is not None and cam is not None, "robot camera component and %s both present" % CAMERA)
if rc is None or cam is None:
    raise SystemExit(1)

for _ in range(4):
    if cam.is_active():
        break
    rc.call_method("NextCamera")
check(cam.is_active(), "%s can still be reached by cycling (discovery intact)" % CAMERA)

seat = actor.get_component_by_class(unreal.RammsSeatComponent)
if seat and seat.get_editor_property("track_occupant_head"):
    print("[orbit] head tracking is ON, tracking %r, bone %r"
          % (str(seat.get_editor_property("tracked_component_name")),
             str(seat.get_resolved_head_bone())))
    check(str(seat.get_resolved_head_bone()) not in ("None", ""),
          "a head bone is resolved, so the rig really is on the occupant")


def rot():
    return cam.get_world_rotation()


rest = rot()
print("[orbit] at rest: yaw=%.2f pitch=%.2f roll=%.2f" % (rest.yaw, rest.pitch, rest.roll))
check(abs(rest.roll) < TOL, "the view is level at rest (roll %.2f)" % rest.roll)

rc.call_method("Orbit", (YAW_STEP, 0.0))
after_yaw = rot()
rc.call_method("Orbit", (-YAW_STEP, 0.0))

d_yaw = ML.normalize_axis(after_yaw.yaw - rest.yaw)
bleed_pitch = ML.normalize_axis(after_yaw.pitch - rest.pitch)
print("[orbit] yaw %+.0f -> world dyaw=%+.2f dpitch=%+.2f" % (YAW_STEP, d_yaw, bleed_pitch))
check(abs(d_yaw - YAW_STEP) < TOL, "yaw moves world yaw by the amount asked for")
check(abs(bleed_pitch) < TOL, "yaw does not bleed into pitch")
check(abs(after_yaw.roll) < TOL, "yaw does not roll the view (roll %.2f)" % after_yaw.roll)

rc.call_method("Orbit", (0.0, PITCH_STEP))
after_pitch = rot()
rc.call_method("Orbit", (0.0, -PITCH_STEP))

d_pitch = ML.normalize_axis(after_pitch.pitch - rest.pitch)
bleed_yaw = ML.normalize_axis(after_pitch.yaw - rest.yaw)
print("[orbit] pitch %+.0f -> world dpitch=%+.2f dyaw=%+.2f" % (PITCH_STEP, d_pitch, bleed_yaw))
check(abs(d_pitch - PITCH_STEP) < TOL, "pitch moves world pitch by the amount asked for")
check(abs(bleed_yaw) < TOL, "pitch does not bleed into yaw")
check(abs(after_pitch.roll) < TOL, "pitch does not roll the view (roll %.2f)" % after_pitch.roll)

print("[orbit] %s (%d failing)" % ("ALL GREEN" if not fails else "FAILURES", len(fails)))
if fails:
    raise SystemExit(1)
