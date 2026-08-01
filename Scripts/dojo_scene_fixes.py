"""dojo_scene_fixes.py -- run INSIDE Blender on the dojo scene (Scripting
tab, or headless: blender dojo.blend --python dojo_scene_fixes.py -- --save).

One-time scene repairs to match the current export pipeline (2026-07-31):
  1. CabinetB's hand-separated glass panes are french DOORS hinged on their
     outer edges.
  2. microwave_3's door pivot is corrected to the measured hinge edge (the
     authored pivot sits mid-panel).
  3. microwave_4 (single merged mesh, door posed open ~46 deg, front faces
     +X) gets its door faces split into a child mesh under a hinge empty
     with close-angle props; textures are PACKED into the .blend.
  4. microwave_5's nested door-named empties (glass/edges/wire under
     Door_Control_12) are tagged STATIC so only the control empty -- whose
     position IS the hinge -- becomes the door mover.
  5. fridge doors get per-door hinge pivots + close angles (the door
     empties were collapsed onto shared positions when posed open); the
     phantom trim mover goes STATIC; egg tray parts weld to the upper door.

All dojo_pivot values are in the ASSET ROOT's local frame.
Pass --save (after --) to save the file when done; otherwise just modifies
the open scene.
"""
import bpy
import os
import sys

# Door-close fits (2026-08-01, dominant-plane method): close angle rotates
# the door panel's dominant face plane EXACTLY parallel to the front;
# pivot solved so the door seats correctly (face/handle proud, seal inside
# the opening). Tune by hand via the dojo_* props on the door empties.
# (user-verified in UE 2026-08-01: angles exact; pivots shifted so the
# doors seat against the body -- mw2 back 2cm, mw4 back 4.5cm + 2cm off
# its left-side overhang)
MW4_DOOR_PIVOT = (0.2055, -0.2907, 0.175)
MW4_CLOSE_ANGLE = 50.0
MW2_DOOR_PIVOT = (0.1300, -0.2020, 0.0)
MW2_CLOSE_ANGLE = 55.4


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


def fix_microwave_2():
    # The door's authored empty sits at the asset origin (useless as a
    # hinge) and carries stale world-frame props. The FRONT is the +X face
    # (42cm wide: cavity + knob column; -X back is solid). Write the fitted
    # hinge + close angle as props -- edit these by hand to fine-tune.
    o = bpy.data.objects.get("Door")
    if o is None or "microwave_2" not in [p.name for p in _ancestors(o)]:
        print("  MISSING: microwave_2 Door empty")
        return
    if "dojo_limits" in o:
        del o["dojo_limits"]
    o["dojo_kind"] = "DOOR"
    o["dojo_pivot"] = list(MW2_DOOR_PIVOT)
    o["dojo_axis"] = [0.0, 0.0, 1.0]
    o["dojo_close_angle"] = MW2_CLOSE_ANGLE
    print("  microwave_2 Door: hinge props set", list(MW2_DOOR_PIVOT),
          MW2_CLOSE_ANGLE)


def fix_microwave_3():
    # The authored door pivot sits mid-panel; the true hinge is the door's
    # LEFT edge. Compute it from the door mesh in ROOT-LOCAL coordinates at
    # run time so rearranging the scene never stales the value (a previous
    # hardcoded pivot broke when the asset was moved).
    root = bpy.data.objects.get("microwave_3")
    o = bpy.data.objects.get("Door.001")
    if root is None or o is None or root.name not in [
            p.name for p in _ancestors(o)]:
        o = None
        if root:
            for c in root.children_recursive:
                if c.type == "EMPTY" and c.name.startswith("Door"):
                    o = c
                    break
    if o is None:
        print("  MISSING: microwave_3 door empty")
        return
    from mathutils import Vector
    meshes = [c for c in [o] + list(o.children_recursive) if c.type == "MESH"]
    pts = [m.matrix_world @ Vector(co) for m in meshes for co in m.bound_box]
    mn = Vector((min(p[i] for p in pts) for i in range(3)))
    mx = Vector((max(p[i] for p in pts) for i in range(3)))
    rt = root.matrix_world.translation
    piv = [round(mn.x - rt.x, 4),                 # hinge = left edge,
           round((mn.y + mx.y) / 2 - rt.y, 4),    # door mid-depth,
           round((mn.z + mx.z) / 2 - rt.z, 4)]    # mid-height (root-local)
    o["dojo_pivot"] = piv
    o["dojo_axis"] = [0.0, 0.0, 1.0]
    print("  set hinge pivot on", o.name, "->", piv)


def fix_minifridge():
    # Door_1 carries stale WORLD-frame dojo_pivot/axis/limits from an old
    # annotate era; interpreted as root-local they park the hinge ~1.5m off.
    # The empty itself sits exactly on the hinge, so inference is correct --
    # just drop the stale props.
    o = bpy.data.objects.get("Door_1")
    if o is None:
        print("  MISSING: minifridge Door_1")
        return
    for k in ("dojo_pivot", "dojo_axis", "dojo_limits"):
        if k in o:
            del o[k]
    # the bounds-metric close trial lands on -96 (6 deg past flush); the
    # numerically fitted flush close about the door empty is exactly -90
    o["dojo_close_angle"] = -90.0
    print("  minifridge Door_1 stale props cleared, close pinned -90")


def fix_door_glass_tint():
    # User-authored DoorGlass materials default to a near-white base color;
    # baked + 35% translucency in UE that reads as milky/frosted, unlike the
    # dark smoked glass of the other microwaves. Darken to match.
    for m in bpy.data.materials:
        if not m.name.startswith("DoorGlass") or not m.use_nodes:
            continue
        for nd in m.node_tree.nodes:
            if nd.type == "BSDF_PRINCIPLED":
                bc = nd.inputs["Base Color"]
                if not bc.links and sum(bc.default_value[:3]) > 0.9:
                    bc.default_value = (0.02, 0.022, 0.025, 1.0)
                    print("  darkened", m.name)


def _ancestors(o):
    out = []
    p = o.parent
    while p:
        out.append(p)
        p = p.parent
    return out


def fix_microwave_4():
    # The asset is one merged MESH at the origin, door posed OPEN ~46 deg.
    # Front (cavity opening + control knobs) faces +X. Door = the mesh
    # islands that swing past x=0.30 (the body ends at x=0.2627). Split
    # them into a child mesh under a hinge empty so the export pipeline
    # can close and articulate the door.
    root = bpy.data.objects.get("microwave_4")
    if root is None:
        print("  MISSING: microwave_4")
        return
    if root.type != "MESH":
        # already split: still refresh the hinge props (the fitted pivot /
        # close angle have been refined since the first split)
        # NOTE: do NOT move the empty itself -- that would drag the child
        # door mesh with it. The explicit dojo_pivot prop is authoritative.
        de = bpy.data.objects.get("Microwave4_door")
        if de is not None:
            de["dojo_kind"] = "DOOR"
            de["dojo_pivot"] = list(MW4_DOOR_PIVOT)
            de["dojo_axis"] = [0.0, 0.0, 1.0]
            de["dojo_close_angle"] = MW4_CLOSE_ANGLE
            print("  microwave_4 already restructured; hinge props refreshed")
        return
    mesh_obj = root
    me = mesh_obj.data
    mw = mesh_obj.matrix_world

    parent = list(range(len(me.vertices)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for e in me.edges:
        ra, rb = find(e.vertices[0]), find(e.vertices[1])
        if ra != rb:
            parent[ra] = rb
    isl = {}
    for v in me.vertices:
        isl.setdefault(find(v.index), []).append(v.index)
    door_v = set()
    for r, vids in isl.items():
        if max((mw @ me.vertices[i].co).x for i in vids) > 0.30:
            door_v.update(vids)
    if not door_v:
        print("  no open-door islands found (already closed?); aborting")
        return

    bpy.ops.object.select_all(action="DESELECT")
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.context.tool_settings.mesh_select_mode = (False, False, True)
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    for p in me.polygons:
        p.select = all(vi in door_v for vi in p.vertices)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.separate(type="SELECTED")
    bpy.ops.object.mode_set(mode="OBJECT")
    door_mesh = next(o for o in bpy.context.selected_objects
                     if o is not mesh_obj)

    mesh_obj.name = "Microwave4_body_mesh"
    root_e = bpy.data.objects.new("microwave_4", None)
    bpy.context.scene.collection.objects.link(root_e)
    door_e = bpy.data.objects.new("Microwave4_door", None)
    bpy.context.scene.collection.objects.link(door_e)
    door_e.parent = root_e
    door_e.location = MW4_DOOR_PIVOT
    # empties are freshly created: their cached matrix_world is stale until
    # a depsgraph update, and the matrix_world SETTER on a child solves the
    # basis against that stale value (displacing the mesh by +pivot). Update
    # first, then write the basis explicitly.
    bpy.context.view_layer.update()
    from mathutils import Matrix
    for o, par in ((mesh_obj, root_e), (door_mesh, door_e)):
        wm = o.matrix_world.copy()
        o.parent = par
        o.matrix_parent_inverse = Matrix.Identity(4)
        o.matrix_basis = par.matrix_world.inverted() @ wm
    door_mesh.name = "Microwave4_door_mesh"
    door_e["dojo_kind"] = "DOOR"
    door_e["dojo_pivot"] = list(MW4_DOOR_PIVOT)
    door_e["dojo_axis"] = [0.0, 0.0, 1.0]
    door_e["dojo_close_angle"] = MW4_CLOSE_ANGLE
    bpy.context.view_layer.update()
    from mathutils import Vector
    pts = [door_mesh.matrix_world @ Vector(c) for c in door_mesh.bound_box]
    mn = [round(min(p[i] for p in pts), 3) for i in range(3)]
    mx = [round(max(p[i] for p in pts), 3) for i in range(3)]
    print("  door mesh world bbox:", mn, "..", mx,
          "(expect x ~0.20..0.60, y ~-0.32..0.03)")

    # pack the textures INTO the blend: immune to files changing on disk
    packed = 0
    for o in (mesh_obj, door_mesh):
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
    print("  microwave_4 door split ({} verts), {} textures packed".format(
        len(door_v), packed))


def fix_microwave_4_normal_map():
    # the re-imported material points its normal map at
    # Texture\Microwave_Normal_OpenGL.png, which does not exist on disk;
    # the folder has Microwave_Normal.png -- retarget and pack
    want = r"C:\Users\waemf\data\cad\furniture\microwave_4\Microwave_Normal.png"
    if not os.path.exists(want):
        print("  MISSING on disk:", want)
        return
    for img in bpy.data.images:
        if ("Microwave_Normal" in img.name and not img.packed_file
                and not os.path.exists(bpy.path.abspath(img.filepath))):
            img.filepath = want
            try:
                img.reload()
                img.pack()
                print("  retargeted + packed", img.name)
            except Exception as e:
                print("  retarget failed:", img.name, e)


def fix_microwave_5():
    # Only Door_Control_12 (positioned ON the hinge) should be a mover; its
    # nested door-named empties would fragment into phantom doors with
    # wrong pivots. Their meshes ride the control empty's subtree.
    for name in ("Door_Glass_4", "Door_Upper_edges_5", "Transp_Door_Plane_11"):
        o = bpy.data.objects.get(name)
        if o is None:
            print("  MISSING:", name)
            continue
        o["dojo_kind"] = "STATIC"
        print("  STATIC:", name)


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
fix_microwave_2()
fix_microwave_3()
fix_microwave_4()
fix_microwave_4_normal_map()
fix_microwave_5()
fix_minifridge()
fix_door_glass_tint()
fix_fridge()
if "--save" in sys.argv:
    bpy.ops.wm.save_mainfile()
    print("saved", bpy.data.filepath)
sys.stdout.flush()
