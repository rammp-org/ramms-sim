"""Give BP_Mebot_Ramms keyboard drive and the UI camera system.

The Mebot already drives through the control surface -- its RobotBase runs the
Chaos backend off DT_Mebot_ChaosMotors, and RammsDifferentialDriveController
already commands those motors. What it never had was anything to *feed* the
surface from the keyboard, and its cameras are the old
IntrinsicSceneCaptureComponent2D path, which the UI does not know about.

Both gaps are components, and both are pawn-agnostic, so neither needs the
vehicle template taken away first:

  - URammsKeyboardTeleopComponent polls the possessing player controller and
    writes the drive axes. It names no controller class, so it works against
    whatever the surface offers. BP_Mebot_Ramms is BP_MebotGameMode's default
    pawn, so a controller is there to poll.
  - URammsRobotCameraComponent cycles the pawn's UCameraComponents and orbits
    the spring arms they hang from. The Mebot already has Front/Back Camera and
    both arms.

The third change is the one that would otherwise fight the first.
ARammsPawn::bUseLegacyVehicleInput binds throttle / steering / brake straight
to the Chaos movement component, so with it on, one key drives both the vehicle
movement and the surface and the surface's arbitration is bypassed. Its own
comment names this pawn as the reason it exists.

Run inside the editor, with PIE stopped:
    python3 Scripts/editor_remote_exec.py \
        --file Scripts/mebot_add_teleop_and_camera.py
"""

import unreal

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; re-run this script")

SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
B = unreal.SubobjectDataBlueprintFunctionLibrary

PAWN = "/Game/Robots/BP_Mebot_Ramms"

WANTED = [
    (unreal.RammsKeyboardTeleopComponent, "RammsKeyboardTeleopComponent", "KeyboardTeleop"),
    (unreal.RammsRobotCameraComponent, "RammsRobotCameraComponent", "RobotCamera"),
]


def load_bp(path):
    return unreal.load_object(None, "%s.%s" % (path, path.rsplit("/", 1)[-1]))


bp = load_bp(PAWN)
if bp is None:
    raise RuntimeError("missing %s" % PAWN)


def existing(class_name):
    """A component of this class already on the Blueprint, or None.

    By class rather than by name: the point is that the pawn has one, and a
    second would mean two things polling the same keys and writing the same
    axes. The gather also hands back each subobject more than once, so this
    cannot count handles.
    """
    for h in SDS.k2_gather_subobject_data_for_blueprint(bp):
        o = B.get_object_for_blueprint(SDS.k2_find_subobject_data_from_handle(h), bp)
        if o is not None and o.get_class().get_name() == class_name:
            return o
    return None


def add(cls, class_name, name):
    found = existing(class_name)
    if found is not None:
        print("[mebot] %-32s already present as '%s'" % (class_name, found.get_name()))
        return found
    handles = SDS.k2_gather_subobject_data_for_blueprint(bp)
    params = unreal.AddNewSubobjectParams()
    params.set_editor_property("parent_handle", handles[0])
    params.set_editor_property("new_class", cls)
    params.set_editor_property("blueprint_context", bp)
    handle, fail = SDS.add_new_subobject(params)
    if not fail.is_empty():
        raise RuntimeError("adding %s failed: %s" % (class_name, fail))
    SDS.rename_subobject(handle, unreal.Text(name))
    print("[mebot] %-32s added as '%s'" % (class_name, name))
    return B.get_object_for_blueprint(SDS.k2_find_subobject_data_from_handle(handle), bp)


for cls, class_name, name in WANTED:
    add(cls, class_name, name)

# The `b` prefix is stripped for booleans on the Python side, which is why
# reading `b_use_legacy_vehicle_input` reports no such property.
cdo = unreal.get_default_object(bp.generated_class())
cdo.set_editor_property("use_legacy_vehicle_input", False)
print("[mebot] use_legacy_vehicle_input -> %s" % cdo.get_editor_property("use_legacy_vehicle_input"))

unreal.BlueprintEditorLibrary.compile_blueprint(bp)
if not unreal.EditorAssetLibrary.save_loaded_asset(bp):
    raise RuntimeError("could not save %s" % PAWN)

# Compiling rebuilds the templates and the CDO, so everything is read back off
# the saved asset rather than trusted from before the compile.
fresh = load_bp(PAWN)
fresh_cdo = unreal.get_default_object(fresh.generated_class())
missing = []
for _, class_name, _ in WANTED:
    present = any(
        (lambda o: o is not None and o.get_class().get_name() == class_name)(
            B.get_object_for_blueprint(SDS.k2_find_subobject_data_from_handle(h), fresh))
        for h in SDS.k2_gather_subobject_data_for_blueprint(fresh))
    if not present:
        missing.append(class_name)
if missing:
    raise RuntimeError("compile/save dropped: %s" % ", ".join(missing))
if fresh_cdo.get_editor_property("use_legacy_vehicle_input"):
    raise RuntimeError("compile/save dropped the legacy-input change")

print("[mebot] verified on the saved asset: both components present, legacy vehicle input off")
