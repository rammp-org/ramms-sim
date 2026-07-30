"""dojo_scene_fixes.py -- run INSIDE Blender on the dojo scene (Scripting
tab, or headless: blender dojo.blend --python dojo_scene_fixes.py -- --save).

One-time scene repairs to match the current export pipeline (2026-07-29):
  1. CabinetB's hand-separated sliding glass panes (CabinetB_Glass_low_8_left/
     _right) are tagged as DOOR_SLIDE movers with sideways travel.
  2. microwave_3's door pivot is corrected to the measured hinge edge (the
     authored pivot sits mid-panel).
  3. microwave_4 is REPLACED with a rebuild from the consistent skeletal
     export (its previous copy referenced texture files that were later
     overwritten with a different UV layout -> black bakes). Textures are
     PACKED into the .blend so this cannot happen again.

Pass --save (after --) to save the file when done; otherwise just modifies
the open scene.
"""
import bpy
import os
import sys

MW4_FBX = r"C:\Users\waemf\data\UE_VAULT_EXPORT\dojo\microwave_4\microwave_4.fbx"
MW4_DOOR_PIVOT = (0.184, -0.296, 0.175)       # hinge in the RECENTERED
                                              # mesh frame (the manifest
                                              # bone was pre-recenter)


def fix_cabinet_b():
    # The hand-separated glass panes are side-by-side FRENCH DOORS hinged on
    # their OUTER edges (knobs sit on the inner edges), not track sliders.
    for name, hinge_x in (("CabinetB_Glass_low_8_left", -0.39),
                          ("CabinetB_Glass_low_8_right", 0.39)):
        o = bpy.data.objects.get(name)
        if o is None:
            print("  MISSING:", name)
            continue
        for stale in ("dojo_joint", "dojo_limits"):
            if stale in o:
                del o[stale]
        o["dojo_kind"] = "DOOR"
        o["dojo_pivot"] = [hinge_x, -0.485, 1.47]
        o["dojo_axis"] = [0.0, 0.0, 1.0]
        print("  tagged", name, "DOOR hinge x=", hinge_x)


def fix_microwave_3():
    o = bpy.data.objects.get("Door.001")
    if o is None or "microwave_3" not in [p.name for p in _ancestors(o)]:
        o = None
        mw3 = bpy.data.objects.get("microwave_3")
        if mw3:
            for c in mw3.children_recursive:
                if c.type == "EMPTY" and c.name.startswith("Door"):
                    o = c
                    break
    if o is None:
        print("  MISSING: microwave_3 door empty")
        return
    o["dojo_pivot"] = [-0.241, 1.352, 0.137]   # measured hinge (left edge)
    o["dojo_axis"] = [0.0, 0.0, 1.0]
    print("  set hinge pivot on", o.name)


def _ancestors(o):
    out = []
    p = o.parent
    while p:
        out.append(p)
        p = p.parent
    return out


def fix_microwave_4():
    # remove the stale copy (references overwritten texture files)
    doomed = []
    root = bpy.data.objects.get("microwave_4")
    if root is not None:
        doomed = [root] + list(root.children_recursive)
    for o in doomed:
        bpy.data.objects.remove(o, do_unlink=True)
    for coll in (bpy.data.materials, bpy.data.images, bpy.data.meshes,
                 bpy.data.armatures):
        for blk in list(coll):
            if blk.users == 0 and not blk.use_fake_user:
                try:
                    coll.remove(blk)
                except Exception:
                    pass
    if not os.path.exists(MW4_FBX):
        print("  MISSING fbx:", MW4_FBX)
        return

    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=MW4_FBX)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next((o for o in new if o.type == "ARMATURE"), None)
    meshes = {o.name.split(".")[0]: o for o in new if o.type == "MESH"}
    for o in meshes.values():
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        o.vertex_groups.clear()
        for m in list(o.modifiers):
            o.modifiers.remove(m)
    if arm is not None:
        bpy.data.objects.remove(arm, do_unlink=True)
    bpy.context.view_layer.update()

    def empty(name, loc, parent):
        e = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(e)
        e.location = loc
        if parent:
            e.parent = parent
        bpy.context.view_layer.update()
        return e

    root = empty("microwave_4", (0, 0, 0), None)
    body_e = empty("Microwave4_body", (0, 0, 0), root)
    door_e = empty("Microwave4_door", MW4_DOOR_PIVOT, root)
    for key, par in (("Microwave4_body_mesh", body_e),
                     ("Microwave4_tray_glass", body_e),
                     ("Microwave4_door_mesh", door_e)):
        o = meshes.get(key)
        if o is None:
            print("  MISSING mesh:", key)
            continue
        mw = o.matrix_world.copy()
        o.parent = par
        o.matrix_world = mw
        o.name = key
    for m in bpy.data.materials:
        if m.name.startswith("microwave_4_"):
            m.name = m.name[len("microwave_4_"):]
    # pack the textures INTO the blend: immune to files changing on disk
    packed = 0
    for o in meshes.values():
        for ms in o.material_slots:
            if not ms.material or not ms.material.use_nodes:
                continue
            for nd in ms.material.node_tree.nodes:
                if nd.type == "TEX_IMAGE" and nd.image and not nd.image.packed_file:
                    try:
                        nd.image.pack()
                        packed += 1
                    except Exception as e:
                        print("  pack failed:", nd.image.name, e)
    print("  microwave_4 rebuilt,", packed, "textures packed")
    # the gen-2 FBX carries a spurious +37 deg door tuck (the skeletal
    # exporter auto-closed the already-closed door) -- undo it about the
    # tuck pivot and pin the close angle so it never happens again
    from math import radians
    from mathutils import Matrix, Vector
    dm = bpy.data.objects.get("Microwave4_door_mesh")
    if dm is not None:
        p2 = Vector((0.184, -0.296, 0.0))
        rot = (Matrix.Translation(p2) @ Matrix.Rotation(radians(-37), 4, "Z")
               @ Matrix.Translation(-p2))
        dm.matrix_world = rot @ dm.matrix_world
    de = bpy.data.objects.get("Microwave4_door")
    if de is not None:
        de["dojo_close_angle"] = 0.0
    print("  microwave_4 door un-tucked (-37 deg) and close pinned")


def fix_fridge():
    # The four main doors are posed open by exactly +90 deg; the bounds
    # metric cannot see the closed pose (door-mounted trays pollute the
    # static bounds), so pin the close rotation directly.
    # the door empties were collapsed onto shared positions when the doors
    # were posed open -- restore per-door hinges (root-local frame; values
    # recovered from the original export before the collapse)
    hinges = {"FridgeUpperDoor": [0.412, -0.562, -0.326],
              "FridgeLowerDoor": [0.412, -0.562, -0.964],
              "FridgeLowerDoor_001": [0.413, -0.562, -0.666],
              "FridgeUpperDoor_001": [0.413, -0.562, 0.263]}
    for name, piv in hinges.items():
        o = bpy.data.objects.get(name)
        if o is None:
            print("  MISSING:", name)
            continue
        o["dojo_close_angle"] = -90.0
        o["dojo_pivot"] = piv
        o["dojo_axis"] = [0.0, 0.0, 1.0]
        print("  close_angle -90 + hinge on", name)
    # the phantom trim mover shares a hinge with a real door: make it
    # static so it welds to its door by name instead of splitting panels
    o = bpy.data.objects.get("FridgeUpperDoor_002")
    if o is not None:
        o["dojo_kind"] = "STATIC"
        print("  FridgeUpperDoor_002 -> STATIC")
    # egg lid: authored pivot is good; clear any stale frame-corrupted props
    lid = bpy.data.objects.get("FridgeUpperHolderPlasticDoor")
    if lid is not None:
        for k in ("dojo_pivot", "dojo_axis", "dojo_limits"):
            if k in lid:
                del lid[k]
        print("  egg lid props cleared")
    # egg tray + rod live on the upper door's interior but have no door-ish
    # names -- weld them to the door explicitly
    for name in ("defaultMaterial.008", "defaultMaterial.040",
                 "defaultMaterial.013", "defaultMaterial.014"):
        o = bpy.data.objects.get(name)
        if o is None:
            print("  MISSING:", name)
            continue
        o["dojo_bone_of"] = "FridgeUpperDoor"
        print("  bone_of FridgeUpperDoor on", name)


print("== dojo scene fixes ==")
fix_cabinet_b()
fix_microwave_3()
fix_microwave_4()
fix_fridge()
if "--save" in sys.argv:
    bpy.ops.wm.save_mainfile()
    print("saved", bpy.data.filepath)
sys.stdout.flush()
