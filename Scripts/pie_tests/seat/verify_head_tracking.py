"""Does the seat component put a camera on the occupant's actual head?

Builds the whole case in the EDITOR world rather than touching BP_Mebot_Ramms:
a bare actor with a RammsSeatComponent and a camera, head tracking configured,
occupant spawned on demand. Then it MEASURES -- the camera's world location
against the occupant mesh's head bone -- because "it looks about right" is how a
camera ends up a head's width out of place in the first place.

    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/seat/verify_head_tracking.py

Run with PIE stopped.
"""

import unreal

LABEL = "SeatHeadTrackTest"

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
B = unreal.SubobjectDataBlueprintFunctionLibrary

if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; re-run this script")

fails = []


def check(ok, what):
    print("[head] %s  %s" % ("pass" if ok else "FAIL", what))
    if not ok:
        fails.append(what)


for a in list(actors.get_all_level_actors()):
    if a.get_actor_label().startswith(LABEL):
        actors.destroy_actor(a)

actor = actors.spawn_actor_from_class(unreal.Actor, unreal.Vector(0, 0, 200), unreal.Rotator(0, 0, 0))
actor.set_actor_label(LABEL)
handles = SDS.k2_gather_subobject_data_for_instance(actor)


def add(cls, name):
    params = unreal.AddNewSubobjectParams()
    params.set_editor_property("parent_handle", handles[0])
    params.set_editor_property("new_class", cls)
    handle, fail = SDS.add_new_subobject(params)
    if not fail.is_empty():
        raise RuntimeError("adding %s failed: %s" % (name, fail))
    SDS.rename_subobject(handle, unreal.Text(name))
    return B.get_object(SDS.k2_find_subobject_data_from_handle(handle))


cam = add(unreal.CameraComponent, "TestEyeCam")
seat = add(unreal.RammsSeatComponent, "TestSeat")

seat.set_editor_property("spawn_on_begin_play", False)
seat.set_editor_property("track_occupant_head", True)
seat.set_editor_property("tracked_component_name", "TestEyeCam")
# This test asserts the FULL transform, rotation included, so it has to ask for
# the rotation. The shipped default drives location only and deliberately leaves
# rotation to the vehicle and the controls -- the separate controls test covers
# that mode. Without this the rotation assertion below could only pass by
# coincidence of the bone's pose.
seat.set_editor_property("track_head_rotation", True)
print("[head] configured seat to track 'TestEyeCam'")

seat.call_method("SpawnOccupant")
occ = seat.get_occupant()
check(occ is not None, "occupant spawned")
if occ is None:
    raise SystemExit(1)

attached = seat.call_method("AttachTrackedComponentToHead")
check(bool(attached), "AttachTrackedComponentToHead reported success")
bone = str(seat.get_resolved_head_bone())
print("[head] resolved bone: %s" % bone)
check(bone not in ("None", ""), "a head bone was resolved on this skeleton")

mesh = None
root = occ.get_editor_property("root_component")
if isinstance(root, unreal.SkeletalMeshComponent):
    mesh = root
else:
    for m in occ.get_components_by_class(unreal.SkeletalMeshComponent):
        mesh = m
        break
check(mesh is not None, "occupant has a skeletal mesh")
if mesh is None:
    raise SystemExit(1)

bone_loc = mesh.get_socket_location(bone)
cam_loc = cam.get_world_location()
dist = (cam_loc - bone_loc).length()
print("[head] head bone at %s" % bone_loc)
print("[head] camera    at %s" % cam_loc)
print("[head] separation: %.2f cm" % dist)
check(dist < 40.0, "camera sits on the head, not where it was authored (%.1f cm)" % dist)

# The component's job is to place the tracked component at bone x offset. Check
# exactly that, rather than whether the result looks upright: uprightness depends
# on the offset matching the occupant's POSE, and this test spawns an unposed
# occupant while the shipped default is tuned for the seat's seated pose. Testing
# the placement is testing the component; testing the pose is testing the tuning.
bone_t = unreal.Transform(mesh.get_socket_location(bone), mesh.get_socket_rotation(bone), unreal.Vector(1, 1, 1))
offset = seat.get_editor_property("head_socket_offset")
expected = unreal.MathLibrary.compose_transforms(offset, bone_t)
el, al = expected.translation, cam.get_world_location()
er = expected.rotation.rotator()
ar = cam.get_world_rotation()
pos_err = (al - el).length()
rot_err = max(abs(unreal.MathLibrary.normalize_axis(ar.pitch - er.pitch)),
              abs(unreal.MathLibrary.normalize_axis(ar.yaw - er.yaw)),
              abs(unreal.MathLibrary.normalize_axis(ar.roll - er.roll)))
print("[head] placement error: %.3f cm, %.3f deg" % (pos_err, rot_err))
check(pos_err < 0.1, "camera is exactly at bone x HeadSocketOffset (%.3f cm off)" % pos_err)
check(rot_err < 0.5, "camera orientation is exactly bone x HeadSocketOffset (%.3f deg off)" % rot_err)

# Nothing is re-parented any more: the component is DRIVEN, not attached, so
# that its rotation stays the vehicle's business. Assert that explicitly --
# an earlier version asserted the opposite and would have passed a design that
# broke the camera controls.
parent = cam.get_attach_parent()
check(parent != mesh,
      "camera is NOT re-parented onto the occupant (parent=%s)"
      % (parent.get_name() if parent else None))
check(cam.get_owner() == actor,
      "camera is still OWNED by the seat's actor, so camera discovery still finds it")

seat.call_method("DetachTrackedComponentFromHead")
check(cam.get_world_location() != cam_loc,
      "detaching returns the camera to its authored place rather than the last head pose")

seat.call_method("ClearOccupant")
actors.destroy_actor(actor)
print("[head] %s (%d failing)" % ("ALL GREEN" if not fails else "FAILURES", len(fails)))
# Remote exec reports the command's success, not the script's conclusions.
if fails:
    raise SystemExit(1)
