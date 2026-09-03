"""Post-import fixup for URLab-imported mebot blueprints.

The URLab importer currently drops the MJCF `armature` and `frictionloss`
joint attributes (templates land with 0 and the override flags unset), so
the anti-jitter retuning in mujoco/compose_mebot_scene.py reaches the
Newton worker (which loads the XML directly) but not the in-editor
blueprint. Run this after every re-import, before/after "Generate Chaos
Rig" (order does not matter — it only touches Mj joint templates):

    py Scripts/editor_remote_exec.py --file Scripts/fixup_mebot_import.py

Values mirror compose_mebot_scene.py: armature 0.005 on linkage hinges,
damping/frictionloss 2/0.1 on drive wheels and 5/0.2 on caster wheels.
Remove once URLab imports these attrs natively (upstream note filed in
doc/physics_backend_unification_plan.md section 6.6).
"""
import unreal

BP_PATH = "/Game/Maps/URL/NewtonTest/mebot_gen3"

bp = unreal.EditorAssetLibrary.load_asset(BP_PATH)
sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
hs = sds.k2_gather_subobject_data_for_blueprint(bp)
seen = set()
hinges = wheels = 0
for h in hs:
    o = unreal.SubobjectDataBlueprintFunctionLibrary.get_object(
        sds.k2_find_subobject_data_from_handle(h))
    if o is None or o.get_name() in seen:
        continue
    seen.add(o.get_name())
    if "HingeJoint" not in o.get_class().get_name():
        continue
    base = o.get_name().replace("_GEN_VARIABLE", "")
    if "wheel" in base:
        drive = "drive_wheel" in base
        try:
            o.set_editor_property("b_override_damping", True)
        except Exception:
            pass
        try:
            o.set_editor_property("damping", [2.0 if drive else 5.0])
            for flag in ("b_override_frictionloss", "override_frictionloss"):
                try:
                    o.set_editor_property(flag, True)
                    break
                except Exception:
                    pass
            o.set_editor_property("frictionloss", 0.1 if drive else 0.2)
            wheels += 1
        except Exception as e:
            print("WHEEL ERR %s: %s" % (base, e))
    elif not base.startswith("arm_"):
        try:
            for flag in ("b_override_armature", "override_armature"):
                try:
                    o.set_editor_property(flag, True)
                    break
                except Exception:
                    pass
            o.set_editor_property("armature", 0.005)
            hinges += 1
        except Exception as e:
            print("HINGE ERR %s: %s" % (base, e))
print("FIXUP hinges=%d wheels=%d" % (hinges, wheels))
if hinges or wheels:
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    unreal.EditorAssetLibrary.save_asset(BP_PATH, only_if_is_dirty=True)
    print("SAVED %s" % BP_PATH)
