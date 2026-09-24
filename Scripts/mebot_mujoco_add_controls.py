"""Bring BP_Mebot_Mujoco up to the control wiring BP_Mebot_Ramms has.

The Mujoco Mebot had none of the RAMMS control stack: no RobotBase, no control
surface, no teleop, no camera component. That is why it shows no UI panels --
the UI finds a robot through the control-surface registry, and this pawn
registered nothing -- and why its RammsDifferentialDriveController did nothing,
since a drive controller with no base has no motors to command. It drove only
through the Chaos vehicle template's own input bindings.

Which is why this cannot be the same edit as the one made to BP_Mebot_Ramms.
Turning off bUseLegacyVehicleInput there was safe because the surface path
already reached the wheels; doing it here first would have left the pawn with
no way to move at all. So the base and the surface go on first, and the flag
goes off last.

The base is configured by COPYING BP_Mebot_Ramms rather than by hardcoding:
both pawns carry the same Chaos wheeled base and the same skeletal mesh, so the
backend, motor table and drive geometry that work on one are the ones that work
on the other -- and copying means they cannot drift apart silently.

Note this leaves the ARM alone. The arm is a separate actor (an ArmActor child
actor spawning gen3_2f85), and a control surface only gathers contributors from
its own actor, so nothing done here can reach it. See the notes in the PR.

Run inside the editor, with PIE stopped:
    python3 Scripts/editor_remote_exec.py \
        --file Scripts/mebot_mujoco_add_controls.py
"""

import unreal

les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; re-run this script")

SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
B = unreal.SubobjectDataBlueprintFunctionLibrary

SOURCE = "/Game/Robots/BP_Mebot_Ramms"
TARGET = "/Game/Robots/BP_Mebot_Mujoco"

# Order matters: the base and the surface have to exist before anything that
# feeds them, and the flag comes off only once they do.
WANTED = [
    (unreal.RammsRobotBaseComponent, "RammsRobotBaseComponent", "RobotBase"),
    (unreal.RammsRobotControlSurfaceComponent, "RammsRobotControlSurfaceComponent", "ControlSurface"),
    (unreal.RammsKeyboardTeleopComponent, "RammsKeyboardTeleopComponent", "KeyboardTeleop"),
    (unreal.RammsRobotCameraComponent, "RammsRobotCameraComponent", "RobotCamera"),
]

BASE_PROPS = ["backend", "motor_table"]
DRIVE_PROPS = ["left_motor_id", "right_motor_id", "wheel_radius", "track_width",
               "skeletal_mesh_component_name", "left_wheel_bone_name", "right_wheel_bone_name"]


def load_bp(path):
    return unreal.load_object(None, "%s.%s" % (path, path.rsplit("/", 1)[-1]))


def component_of(bp, class_name):
    for h in SDS.k2_gather_subobject_data_for_blueprint(bp):
        o = B.get_object_for_blueprint(SDS.k2_find_subobject_data_from_handle(h), bp)
        if o is not None and o.get_class().get_name() == class_name:
            return o
    return None


src = load_bp(SOURCE)
dst = load_bp(TARGET)
if src is None or dst is None:
    raise RuntimeError("missing %s or %s" % (SOURCE, TARGET))


def add(cls, class_name, name):
    found = component_of(dst, class_name)
    if found is not None:
        print("[mujoco] %-36s already present as '%s'" % (class_name, found.get_name()))
        return found
    handles = SDS.k2_gather_subobject_data_for_blueprint(dst)
    params = unreal.AddNewSubobjectParams()
    params.set_editor_property("parent_handle", handles[0])
    params.set_editor_property("new_class", cls)
    params.set_editor_property("blueprint_context", dst)
    handle, fail = SDS.add_new_subobject(params)
    if not fail.is_empty():
        raise RuntimeError("adding %s failed: %s" % (class_name, fail))
    SDS.rename_subobject(handle, unreal.Text(name))
    print("[mujoco] %-36s added as '%s'" % (class_name, name))
    return B.get_object_for_blueprint(SDS.k2_find_subobject_data_from_handle(handle), dst)


def copy_props(from_comp, to_comp, names, label):
    if from_comp is None or to_comp is None:
        return
    for n in names:
        try:
            value = from_comp.get_editor_property(n)
        except Exception:
            continue
        try:
            to_comp.set_editor_property(n, value)
            print("[mujoco]   %s.%-28s <- %s" % (label, n, value))
        except Exception as e:
            print("[mujoco]   %s.%-28s SKIPPED (%s)" % (label, n, e))


for cls, class_name, name in WANTED:
    add(cls, class_name, name)

copy_props(component_of(src, "RammsRobotBaseComponent"),
           component_of(dst, "RammsRobotBaseComponent"), BASE_PROPS, "RobotBase")
copy_props(component_of(src, "RammsDifferentialDriveController"),
           component_of(dst, "RammsDifferentialDriveController"), DRIVE_PROPS, "DiffDrive")

# Last, once there is a surface path to drive through.
cdo = unreal.get_default_object(dst.generated_class())
cdo.set_editor_property("use_legacy_vehicle_input", False)
print("[mujoco] use_legacy_vehicle_input -> %s" % cdo.get_editor_property("use_legacy_vehicle_input"))

unreal.BlueprintEditorLibrary.compile_blueprint(dst)
if not unreal.EditorAssetLibrary.save_loaded_asset(dst):
    raise RuntimeError("could not save %s" % TARGET)

fresh = load_bp(TARGET)
for _, class_name, _ in WANTED:
    if component_of(fresh, class_name) is None:
        raise RuntimeError("compile/save dropped %s" % class_name)
if unreal.get_default_object(fresh.generated_class()).get_editor_property("use_legacy_vehicle_input"):
    raise RuntimeError("compile/save dropped the legacy-input change")
base = component_of(fresh, "RammsRobotBaseComponent")
print("[mujoco] verified: base backend=%s table=%s, all four components present, legacy input off"
      % (base.get_editor_property("backend"), base.get_editor_property("motor_table")))
