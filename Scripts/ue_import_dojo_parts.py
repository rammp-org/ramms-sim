"""
ue_import_dojo_parts.py  --  run INSIDE Unreal Engine 5 (Tools > Execute
Python Script, or push with:  py ue_send.py ue_import_dojo_parts.py).

Importer for the STATIC-PARTS dojo export (dojo_articulated_export.py with
export_mode="static_parts"): every asset folder holds one static FBX per
rigid part (<asset>__root.fbx, <asset>__door_1.fbx, ...) with UCX box
collision baked in (per-mesh-island boxes -- drawers are real containers),
per-group textures, and rig_manifest.json carrying an engine-neutral joint
spec per part (type / axis / pivot / limits).

Per asset this script:
  * imports every part FBX as a Static Mesh (UCX collision, no auto-gen),
  * imports the per-group textures and creates MI_<asset>_<group> instances
    of M_Dojo_Master / M_Dojo_Master_Glass (created if missing), bound to
    slots by name,
  * builds BP_<asset>: an Actor Blueprint with one simulated
    StaticMeshComponent per part and a PhysicsConstraintComponent per joint,
    configured from the manifest:
      revolute  -> twist limited to the joint's range (frame X = hinge axis)
      prismatic -> linear X limited to the travel (frame shifted half-range)

Coordinate note: the exporter writes meters, Z-up, -Y forward; through FBX
that lands in UE as  ue = (x, -y, z) * 100 cm.  Manifest positions/axes are
converted with the same mapping here.
"""

import json
import os
import re
import unreal

# --------------------------------------------------------------------------- config
SOURCE_DIR = r"C:\Users\waemf\data\UE_VAULT_EXPORT\dojo_parts"
DEST_DIR   = "/Game/DojoParts"
MAT_DIR    = DEST_DIR + "/Materials"
MASTER_NAME = "M_Dojo_Master"
GLASS_MASTER_NAME = "M_Dojo_Master_Glass"
MASKED_MASTER_NAME = "M_Dojo_Master_Masked"
SKIP = []                    # regexes on the asset folder name
SIMULATE = True              # parts simulate physics (constraints hold them)

assets = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
SDBFL = unreal.SubobjectDataBlueprintFunctionLibrary


def ue_pos(v):
    """Exporter asset-space (m, Z up) -> UE (cm)."""
    return unreal.Vector(v[0] * 100.0, -v[1] * 100.0, v[2] * 100.0)


def ue_dir(v):
    d = unreal.Vector(v[0], -v[1], v[2])
    return d.normal()


# --------------------------------------------------------------------------- discovery
def load_manifest():
    p = os.path.join(SOURCE_DIR, "rig_manifest.json")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def find_assets(manifest):
    out = []
    pats = [re.compile(p) for p in SKIP]
    for name, entry in sorted(manifest.items()):
        if "error" in entry or "skipped" in entry or not entry.get("parts"):
            continue
        if any(p.search(name) for p in pats):
            continue
        if not os.path.isdir(os.path.join(SOURCE_DIR, name)):
            unreal.log_warning("manifest asset without folder: " + name)
            continue
        out.append(name)
    return out


# --------------------------------------------------------------------------- imports
def _run_import(path, dest, options=None):
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", path)
    task.set_editor_property("destination_path", dest)
    task.set_editor_property("automated", True)
    task.set_editor_property("save", True)
    task.set_editor_property("replace_existing", True)
    if options is not None:
        task.set_editor_property("options", options)
    assets.import_asset_tasks([task])
    objs = list(task.get_objects())
    return objs[0] if objs else None


def import_texture(path, srgb, is_normal):
    if not os.path.exists(path):
        unreal.log_warning("  missing texture: " + path)
        return None
    tex = _run_import(path, DEST_DIR + "/Textures")
    if not tex:
        return None
    tex.set_editor_property("srgb", srgb)
    if is_normal:
        tex.set_editor_property("compression_settings",
                                unreal.TextureCompressionSettings.TC_NORMALMAP)
    elif not srgb:
        tex.set_editor_property("compression_settings",
                                unreal.TextureCompressionSettings.TC_MASKS)
    EAL.save_loaded_asset(tex)
    return tex


def import_static_mesh(fbx_path, dest):
    opts = unreal.FbxImportUI()
    opts.set_editor_property("import_mesh", True)
    opts.set_editor_property("import_as_skeletal", False)
    opts.set_editor_property("import_materials", False)
    opts.set_editor_property("import_textures", False)
    opts.set_editor_property("import_animations", False)
    opts.set_editor_property("mesh_type_to_import",
                             unreal.FBXImportType.FBXIT_STATIC_MESH)
    smd = opts.static_mesh_import_data
    smd.set_editor_property("combine_meshes", True)
    smd.set_editor_property("auto_generate_collision", False)
    smd.set_editor_property("one_convex_hull_per_ucx", True)
    smd.set_editor_property("remove_degenerates", True)
    # the legacy importer defaults this OFF and reads the meter-unit FBX as
    # centimeters -- everything lands 100x too small without it
    smd.set_editor_property("convert_scene_unit", True)
    obj = _run_import(fbx_path, dest, opts)
    if isinstance(obj, unreal.StaticMesh):
        return obj
    for ap in EAL.list_assets(dest, recursive=False):
        a = EAL.load_asset(ap)
        if isinstance(a, unreal.StaticMesh) and \
                a.get_name() == os.path.splitext(os.path.basename(fbx_path))[0]:
            return a
    return None


# --------------------------------------------------------------------------- materials
def _tex_param(mat, name, x, y, sampler, default_tex):
    n = MEL.create_material_expression(
        mat, unreal.MaterialExpressionTextureSampleParameter2D, x, y)
    n.set_editor_property("parameter_name", name)
    n.set_editor_property("sampler_type", sampler)
    if default_tex:
        n.set_editor_property("texture", default_tex)
    return n


def _vec_param(mat, name, x, y, default):
    n = MEL.create_material_expression(
        mat, unreal.MaterialExpressionVectorParameter, x, y)
    n.set_editor_property("parameter_name", name)
    n.set_editor_property("default_value", unreal.LinearColor(*default))
    return n


def _scalar_param(mat, name, x, y, default):
    n = MEL.create_material_expression(
        mat, unreal.MaterialExpressionScalarParameter, x, y)
    n.set_editor_property("parameter_name", name)
    n.set_editor_property("default_value", default)
    return n


def _mul(mat, x, y, a_expr, a_out, b_expr, b_out):
    n = MEL.create_material_expression(mat, unreal.MaterialExpressionMultiply, x, y)
    MEL.connect_material_expressions(a_expr, a_out, n, "A")
    MEL.connect_material_expressions(b_expr, b_out, n, "B")
    return n


def build_master_material(def_base, def_orm, def_normal):
    path = MAT_DIR + "/" + MASTER_NAME
    if EAL.does_asset_exist(path):
        return EAL.load_asset(path)
    mat = assets.create_asset(MASTER_NAME, MAT_DIR, unreal.Material,
                              unreal.MaterialFactoryNew())
    mat.set_editor_property("two_sided", True)
    base = _tex_param(mat, "BaseColor", -1100, -300,
                      unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, def_base)
    tint = _vec_param(mat, "Tint", -1100, -80, (1.0, 1.0, 1.0, 1.0))
    basem = _mul(mat, -650, -250, base, "RGB", tint, "")
    MEL.connect_material_property(basem, "", unreal.MaterialProperty.MP_BASE_COLOR)
    orm = _tex_param(mat, "ORM", -1100, 120,
                     unreal.MaterialSamplerType.SAMPLERTYPE_MASKS, def_orm)
    MEL.connect_material_property(orm, "R", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    rs = _scalar_param(mat, "RoughnessScale", -1100, 330, 1.0)
    rough = _mul(mat, -650, 120, orm, "G", rs, "")
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    ms = _scalar_param(mat, "MetallicScale", -1100, 430, 1.0)
    metal = _mul(mat, -650, 260, orm, "B", ms, "")
    MEL.connect_material_property(metal, "", unreal.MaterialProperty.MP_METALLIC)
    nrm = _tex_param(mat, "Normal", -1100, 550,
                     unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, def_normal)
    MEL.connect_material_property(nrm, "RGB", unreal.MaterialProperty.MP_NORMAL)
    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat)
    return mat


def build_glass_master(def_base):
    path = MAT_DIR + "/" + GLASS_MASTER_NAME
    if EAL.does_asset_exist(path):
        return EAL.load_asset(path)
    mat = assets.create_asset(GLASS_MASTER_NAME, MAT_DIR, unreal.Material,
                              unreal.MaterialFactoryNew())
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    mat.set_editor_property("translucency_lighting_mode",
                            unreal.TranslucencyLightingMode.TLM_SURFACE)
    mat.set_editor_property("two_sided", True)
    base = _tex_param(mat, "BaseColor", -1100, -300,
                      unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, def_base)
    tint = _vec_param(mat, "Tint", -1100, -80, (1.0, 1.0, 1.0, 1.0))
    basem = _mul(mat, -650, -250, base, "RGB", tint, "")
    MEL.connect_material_property(basem, "", unreal.MaterialProperty.MP_BASE_COLOR)
    op = _scalar_param(mat, "Opacity", -1100, 120, 0.35)
    MEL.connect_material_property(op, "", unreal.MaterialProperty.MP_OPACITY)
    rough = _scalar_param(mat, "Roughness", -1100, 220, 0.08)
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat)
    return mat


def build_masked_master(def_base, def_orm, def_normal):
    """Opaque graph + BaseColor.A as opacity mask (alpha-cutout cutlery)."""
    path = MAT_DIR + "/" + MASKED_MASTER_NAME
    if EAL.does_asset_exist(path):
        return EAL.load_asset(path)
    mat = assets.create_asset(MASKED_MASTER_NAME, MAT_DIR, unreal.Material,
                              unreal.MaterialFactoryNew())
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    mat.set_editor_property("two_sided", True)
    base = _tex_param(mat, "BaseColor", -1100, -300,
                      unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, def_base)
    tint = _vec_param(mat, "Tint", -1100, -80, (1.0, 1.0, 1.0, 1.0))
    basem = _mul(mat, -650, -250, base, "RGB", tint, "")
    MEL.connect_material_property(basem, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(base, "A", unreal.MaterialProperty.MP_OPACITY_MASK)
    orm = _tex_param(mat, "ORM", -1100, 120,
                     unreal.MaterialSamplerType.SAMPLERTYPE_MASKS, def_orm)
    MEL.connect_material_property(orm, "R", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    rs = _scalar_param(mat, "RoughnessScale", -1100, 330, 1.0)
    rough = _mul(mat, -650, 120, orm, "G", rs, "")
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    ms = _scalar_param(mat, "MetallicScale", -1100, 430, 1.0)
    metal = _mul(mat, -650, 260, orm, "B", ms, "")
    MEL.connect_material_property(metal, "", unreal.MaterialProperty.MP_METALLIC)
    nrm = _tex_param(mat, "Normal", -1100, 550,
                     unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, def_normal)
    MEL.connect_material_property(nrm, "RGB", unreal.MaterialProperty.MP_NORMAL)
    MEL.recompile_material(mat)
    EAL.save_loaded_asset(mat)
    return mat


def make_instance(inst_name, master, base_tex, orm_tex, normal_tex, translucent):
    path = MAT_DIR + "/" + inst_name
    mic = EAL.load_asset(path) if EAL.does_asset_exist(path) else \
        assets.create_asset(inst_name, MAT_DIR, unreal.MaterialInstanceConstant,
                            unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(mic, master)
    params = [("BaseColor", base_tex)] if translucent else \
        [("BaseColor", base_tex), ("ORM", orm_tex), ("Normal", normal_tex)]
    for pname, tex in params:
        if tex:
            MEL.set_material_instance_texture_parameter_value(mic, pname, tex)
    EAL.save_loaded_asset(mic)
    return mic


def assign_materials_sm(sm, mic_by_slot):
    mats = sm.get_editor_property("static_materials")
    new = []
    for m in mats:
        slot = str(m.get_editor_property("material_slot_name"))
        nsm = unreal.StaticMaterial()
        nsm.set_editor_property("material_slot_name",
                                m.get_editor_property("material_slot_name"))
        nsm.set_editor_property(
            "material_interface",
            mic_by_slot.get(slot, m.get_editor_property("material_interface")))
        if slot not in mic_by_slot:
            unreal.log_warning("    no MI for slot '{}'".format(slot))
        new.append(nsm)
    sm.set_editor_property("static_materials", new)
    sm.modify()
    EAL.save_loaded_asset(sm)


# --------------------------------------------------------------------------- blueprint assembly
def add_component(bp, parent_handle, cls, name):
    params = unreal.AddNewSubobjectParams(parent_handle=parent_handle,
                                          new_class=cls, blueprint_context=bp)
    handle, fail = SDS.add_new_subobject(params)
    if not SDBFL.is_handle_valid(handle):
        raise RuntimeError("add_new_subobject failed: {}".format(fail))
    SDS.rename_subobject(handle, unreal.Text(name))
    data = SDS.k2_find_subobject_data_from_handle(handle)
    return handle, SDBFL.get_object(data)


def set_simulated(comp, simulate, mass_kg=None):
    bi = comp.get_editor_property("body_instance")
    bi.set_editor_property("simulate_physics", simulate)
    if mass_kg:
        try:
            bi.set_editor_property("override_mass", True)
            bi.set_editor_property("mass_in_kg_override", float(mass_kg))
        except Exception as e:
            unreal.log_warning("    mass override failed: " + repr(e))
    comp.set_editor_property("body_instance", bi)


def _cc_name(n):
    s = unreal.ConstrainComponentPropName()
    s.set_editor_property("component_name", n)
    return s


def _rotator(roll=0.0, pitch=0.0, yaw=0.0):
    r = unreal.Rotator()
    r.set_editor_property("roll", roll)
    r.set_editor_property("pitch", pitch)
    r.set_editor_property("yaw", yaw)
    return r


def configure_constraint(comp, child_name, parent_name, joint):
    comp.set_editor_property("component_name1", _cc_name(child_name))
    comp.set_editor_property("component_name2", _cc_name(parent_name))
    ci = comp.get_editor_property("constraint_instance")
    pi = ci.get_editor_property("profile_instance")
    pi.set_editor_property("disable_collision", True)

    lo, hi = float(joint["limits"][0]), float(joint["limits"][1])
    # NOTE: empirically (CabinetB french doors) UE's twist angle about the
    # make_rot_from_x frame matches the Blender-space rotation sign directly
    # -- do NOT negate the revolute range here.
    # The closed rest pose sits at angle 0, which for one-sided ranges like
    # [-120, 0] is exactly ON the limit boundary; UE's limit enforcement
    # then nudges the door a few degrees open over time. Pad the closed
    # side so the rest pose is strictly interior.
    if joint["type"] == "prismatic":
        if lo == 0.0:
            lo = -0.01           # 1 cm interior margin for closed drawers
    else:
        if hi == 0.0:
            hi = 3.0
        if lo == 0.0:
            lo = -3.0
    half = (hi - lo) / 2.0
    mid = (hi + lo) / 2.0
    ll = pi.get_editor_property("linear_limit")
    cone = pi.get_editor_property("cone_limit")
    twist = pi.get_editor_property("twist_limit")
    LCM = unreal.LinearConstraintMotion
    ACM = unreal.AngularConstraintMotion
    if joint["type"] == "prismatic":
        # travel [lo, hi] m: UE linear limits are symmetric, so the frame
        # sits mid-range (component offset done by the caller) with +/- half
        ll.set_editor_property("x_motion", LCM.LCM_LIMITED)
        ll.set_editor_property("y_motion", LCM.LCM_LOCKED)
        ll.set_editor_property("z_motion", LCM.LCM_LOCKED)
        ll.set_editor_property("limit", max(half * 100.0, 0.5))
        for prop in ("swing1_motion", "swing2_motion"):
            cone.set_editor_property(prop, ACM.ACM_LOCKED)
        twist.set_editor_property("twist_motion", ACM.ACM_LOCKED)
    else:
        ll.set_editor_property("x_motion", LCM.LCM_LOCKED)
        ll.set_editor_property("y_motion", LCM.LCM_LOCKED)
        ll.set_editor_property("z_motion", LCM.LCM_LOCKED)
        for prop in ("swing1_motion", "swing2_motion"):
            cone.set_editor_property(prop, ACM.ACM_LOCKED)
        twist.set_editor_property("twist_motion", ACM.ACM_LIMITED)
        twist.set_editor_property("twist_limit_degrees", max(half, 1.0))
        ci.set_editor_property("angular_rotation_offset", _rotator(roll=mid))
    pi.set_editor_property("linear_limit", ll)
    pi.set_editor_property("cone_limit", cone)
    pi.set_editor_property("twist_limit", twist)
    ci.set_editor_property("profile_instance", pi)
    comp.set_editor_property("constraint_instance", ci)
    return mid


def clear_components(bp):
    """Remove previously-added components so an existing Blueprint can be
    rebuilt in place (deleting the asset fails once instances are placed in
    a level; reusing it updates those instances on compile instead)."""
    gather = SDS.k2_gather_subobject_data_for_blueprint(bp)
    if not gather:
        return
    doomed = []
    for h in gather[1:]:
        d = SDS.k2_find_subobject_data_from_handle(h)
        obj = SDBFL.get_object(d)
        if isinstance(obj, (unreal.StaticMeshComponent,
                            unreal.PhysicsConstraintComponent)):
            doomed.append(h)
    if doomed:
        try:
            SDS.delete_subobjects(gather[0], doomed, bp)
        except Exception as e:
            unreal.log_warning("    clear_components: " + repr(e))


def build_blueprint(name, entry, meshes):
    bp_dir = DEST_DIR + "/Blueprints"
    bp_path = bp_dir + "/BP_" + name
    if EAL.does_asset_exist(bp_path):
        bp = EAL.load_asset(bp_path)
        clear_components(bp)
    else:
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", unreal.Actor)
        bp = assets.create_asset("BP_" + name, bp_dir, unreal.Blueprint, factory)

    gather = SDS.k2_gather_subobject_data_for_blueprint(bp)
    actor_root = gather[0]

    parts = entry["parts"]
    comp_name = {p: ("body" if p == "root" else p) for p in parts}
    handles, comps = {}, {}

    order = ["root"] + [p for p in parts if p != "root"]
    for part in order:
        pentry = parts[part]
        j = pentry.get("joint")
        parent_part = (j["parent"] if j and j["parent"] in parts else "root") \
            if part != "root" else None
        parent_handle = handles[parent_part] if parent_part else actor_root
        h, comp = add_component(bp, parent_handle, unreal.StaticMeshComponent,
                                comp_name[part])
        handles[part], comps[part] = h, comp
        if meshes.get(part):
            comp.set_editor_property("static_mesh", meshes[part])
        org = pentry["origin"]
        if parent_part:
            porg = parts[parent_part]["origin"]
            rel = [org[0] - porg[0], org[1] - porg[1], org[2] - porg[2]]
        else:
            rel = org
        comp.set_editor_property("relative_location", ue_pos(rel))
        set_simulated(comp, SIMULATE, pentry.get("mass"))

    for part in order:
        j = parts[part].get("joint")
        if not j:
            continue
        parent_part = j["parent"] if j["parent"] in parts else "root"
        h, ccomp = add_component(bp, handles[part],
                                 unreal.PhysicsConstraintComponent,
                                 "joint_" + part)
        mid = configure_constraint(ccomp, comp_name[part],
                                   comp_name[parent_part], j)
        axis = ue_dir(j["axis"])
        rot = unreal.MathLibrary.make_rot_from_x(axis)
        ccomp.set_editor_property("relative_rotation",
                                  rot)  # frame X = joint axis
        if j["type"] == "prismatic":
            off = axis * (mid * 100.0)
            ccomp.set_editor_property("relative_location", off)
        else:
            ccomp.set_editor_property("relative_location", unreal.Vector(0, 0, 0))

    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    EAL.save_loaded_asset(bp)
    return bp


# --------------------------------------------------------------------------- run
def main():
    # Importing while Play-In-Editor/Simulate is active breaks asset checks
    # (a modal "Overwrite Existing Object" dialog for the master materials
    # deadlocks the editor). Refuse to run until play has ended.
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les.is_in_play_in_editor():
            les.editor_request_end_play()
            unreal.log_error("=== editor was in PIE/Simulate: play end "
                             "requested, RE-RUN the import ===")
            return
    except Exception:
        pass
    # UE 5.7 routes FBX through Interchange by default, which ignores the
    # legacy FbxImportUI options AND the UCX_ collision meshes -- route these
    # imports through the legacy FBX importer instead (session-scoped).
    unreal.SystemLibrary.execute_console_command(
        None, "Interchange.FeatureFlags.Import.FBX 0")
    manifest = load_manifest()
    names = find_assets(manifest)
    unreal.log("=== Importing {} static-part dojo assets ===".format(len(names)))

    first_opaque = first_glass = None
    tex = {}
    for name in names:
        folder = os.path.join(SOURCE_DIR, name)
        for g, info in sorted(manifest[name].get("materials", {}).items()):
            t = info.get("textures", {})
            b = import_texture(os.path.join(folder, t.get("BaseColor", "")), True, False)
            o = import_texture(os.path.join(folder, t.get("ORM", "")), False, False)
            n = import_texture(os.path.join(folder, t.get("Normal", "")), False, True)
            tex[(name, g)] = (b, o, n)
            if info.get("translucent"):
                first_glass = first_glass or b
            elif first_opaque is None and b and o and n:
                first_opaque = (b, o, n)

    master = build_master_material(*(first_opaque or (None, None, None)))
    glass = build_glass_master(first_glass)
    masked = build_masked_master(*(first_opaque or (None, None, None)))
    unreal.log("masters: {} / {} / {}".format(
        master.get_name(), glass.get_name(), masked.get_name()))

    ok = 0
    for name in names:
        unreal.log(name + ":")
        entry = manifest[name]
        mic_by_slot = {}
        for g, info in sorted(entry.get("materials", {}).items()):
            b, o, n = tex[(name, g)]
            trans = bool(info.get("translucent"))
            parent = glass if trans else (
                masked if info.get("masked") else master)
            mic = make_instance("MI_{}_{}".format(name, g),
                                parent, b, o, n, trans)
            mic_by_slot[info.get("slot", "{}_{}".format(name, g))] = mic

        meshes = {}
        fail = False
        for part, pentry in entry["parts"].items():
            fbx = os.path.join(SOURCE_DIR, name, pentry["fbx"])
            sm = import_static_mesh(fbx, DEST_DIR + "/Meshes/" + name)
            if not sm:
                unreal.log_warning("    part import FAILED: " + pentry["fbx"])
                fail = True
                continue
            assign_materials_sm(sm, mic_by_slot)
            meshes[part] = sm
        try:
            build_blueprint(name, entry, meshes)
            unreal.log("    BP_{} built ({} parts, {} joints)".format(
                name, len(meshes),
                sum(1 for p in entry["parts"].values() if p.get("joint"))))
            if not fail:
                ok += 1
        except Exception as e:
            unreal.log_error("    blueprint FAILED: " + repr(e))
    unreal.log("=== Done: {}/{} assets ===".format(ok, len(names)))


main()
