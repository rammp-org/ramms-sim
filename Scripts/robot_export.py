"""robot_export.py -- static-parts exporter for the RAMMP robot (arm,
gripper, mobile base). Successor to skeletal export; sibling of
dojo_articulated_export.py (whose helpers it reuses).

Reads the dojo_* articulation props stamped by robot_annotate.py:
every object with a dojo_joint prop is a rigid PART jointed to its nearest
ancestor part (pivot = object origin unless dojo_pivot). 'fixed' parts are
merged into their parent. Loop-closure EMPTIES (dojo_connect) become
manifest "closures".

COLLISION (per part, first match wins):
  1. Authored meshes named UBX_/UCX_/USP_/UCP_<part object name> anywhere
     in the scene (numeric suffixes ok) -- passed through verbatim.
  2. dojo_collision prop: cylinder | box | boxes | convex | sphere | none.
  3. Auto: continuous joints get a CYLINDER fitted about the joint axis
     (wheels); everything else gets dojo island boxes.
UE gets UCX_/UBX_ meshes in the part FBX; the manifest carries parametric
shapes (box/cylinder/sphere/convex) for MJCF + USD.

Outputs per root under CONFIG output_dir/<root>/:
  <root>__<part>.fbx    one static mesh + collision per part
  <root>.mjcf.xml       MuJoCo model (motors, springs, mimics, closures)
  <root>.usda           UsdPhysics rigid bodies + joints + drives
  manifest in rammp_manifest.json (all roots merged by the orchestrator)

Run headless:
  blender <file>.blend --python robot_export.py
Env: ROBOT_ROOTS=mebot,base_link,base  ROBOT_OUT=<dir>  ROBOT_MANIFEST=<json>
"""
import json
import math
import os
import re
import sys

import bpy
from mathutils import Matrix, Vector

CONFIG = {
    "roots": os.environ.get("ROBOT_ROOTS", "mebot").split(","),
    "output_dir": os.environ.get(
        "ROBOT_OUT", r"C:\Users\waemf\data\UE_VAULT_EXPORT\rammp_parts"),
    "manifest": os.environ.get("ROBOT_MANIFEST", ""),
    "merge_fixed": True,          # fixed-joint parts weld into their parent
    "cyl_segments": 24,           # UE convex cylinder resolution
    "ucx_max_boxes": 24,
    "ucx_dust_volume": 2e-6,
    "cleanup": True,
}

COLL_PREFIXES = ("UBX_", "UCX_", "USP_", "UCP_")

# --------------------------------------------------------------------------
# reuse dojo helpers (bake_object, duplicate_hierarchy, ensure_collection,
# island_boxes, make_ucx, export_fbx_static, safe_name...). The dojo module
# only DEFINES main() (drivers invoke it), so a plain exec is side-effect
# free.
# --------------------------------------------------------------------------
_DOJO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__))
                          if "__file__" in globals() else r"C:\Users\waemf\data",
                          "dojo_articulated_export.py")
_src = open(_DOJO_PATH, encoding="utf-8").read()
dojo = {}
exec(compile(_src, _DOJO_PATH, "exec"), dojo)
bake_object = dojo["bake_object"]
duplicate_hierarchy = dojo["duplicate_hierarchy"]
ensure_collection = dojo["ensure_collection"]
island_boxes = dojo["island_boxes"]
make_ucx = dojo["make_ucx"]
export_fbx_static = dojo["export_fbx_static"]
safe_name = dojo["safe_name"]
descendants = dojo["descendants"]
dojo["CONFIG"]["ucx_max_boxes"] = CONFIG["ucx_max_boxes"]
dojo["CONFIG"]["ucx_dust_volume"] = CONFIG["ucx_dust_volume"]


def base_name(name):
    return re.sub(r"\.\d+$", "", name)


def get_prop(o, key, default=None):
    v = o.get("dojo_" + key)
    if v is None:
        return default
    if hasattr(v, "__len__") and not isinstance(v, str):
        return list(v)
    return v


# --------------------------------------------------------------------------
# part tree
# --------------------------------------------------------------------------
def build_parts(root, name_map):
    """Parts from the WORK COPY hierarchy. Returns (parts, closures).
    parts: dict keyed by ORIGINAL object name -> {name, obj(copy),
    parent(part name), jtype, meshes}. A part = the root, or any object
    with dojo_joint. merge_fixed folds fixed parts into their parent."""
    copy_of = {orig: c for orig, c in name_map.items()}
    orig_of = {c.name: orig for orig, c in name_map.items()}
    root_c = copy_of[root.name]

    def is_part(o):
        return o is root_c or o.get("dojo_joint") is not None

    part_objs = [o for o in [root_c] + descendants(root_c) if is_part(o)]

    def nearest_part_ancestor(o):
        p = o.parent
        while p is not None and p not in part_objs:
            p = p.parent
        return p

    parts = {}
    closures = []
    for o in part_objs:
        jtype = str(get_prop(o, "joint", "fixed")) if o is not root_c else "root"
        connect = get_prop(o, "connect")
        if connect is not None and o.type == "EMPTY":
            closures.append({"empty": o, "other": str(connect)})
            continue
        onm = orig_of.get(o.name, o.name)
        parts[onm] = {
            "obj": o, "name": onm, "jtype": jtype,
            "parent_obj": nearest_part_ancestor(o),
        }

    # merge fixed parts (and the root has no joint) into their parents
    if CONFIG["merge_fixed"]:
        changed = True
        while changed:
            changed = False
            for nm, p in list(parts.items()):
                if p["jtype"] == "fixed" and p["parent_obj"] is not None:
                    parts.pop(nm)
                    for q in parts.values():
                        if q["parent_obj"] is p["obj"]:
                            q["parent_obj"] = p["parent_obj"]
                    changed = True
                    break

    live_objs = {p["obj"] for p in parts.values()}

    def owner_of(o):
        cur = o
        while cur is not None and cur not in live_objs:
            cur = cur.parent
        return cur

    for p in parts.values():
        own = []
        for o in [p["obj"]] + descendants(p["obj"]):
            if o.type == "MESH" and len(o.data.polygons) and owner_of(o) is p["obj"]:
                if base_name(o.name).startswith(COLL_PREFIXES):
                    continue
                own.append(o)
        p["meshes"] = own
        pp = p["parent_obj"]
        p["parent"] = None
        if pp is not None:
            for q in parts.values():
                if q["obj"] is pp:
                    p["parent"] = q["name"]
    return parts, closures


# --------------------------------------------------------------------------
# collision
# --------------------------------------------------------------------------
def authored_collision(part_orig_name):
    """Scene meshes named <PFX><part name>[.NNN | _NN] (original names)."""
    out = []
    pat = re.compile(
        r"^(UBX|UCX|USP|UCP)_" + re.escape(part_orig_name) + r"([._]\d+)?$")
    for o in bpy.data.objects:
        if o.type == "MESH" and pat.match(o.name):
            out.append(o)
    return out


def fit_cylinder(meshes, pivot, axis):
    a = Vector(axis).normalized()
    tmin, tmax, r2 = 1e18, -1e18, 0.0
    for m in meshes:
        mw = m.matrix_world
        for v in m.data.vertices:
            d = (mw @ v.co) - pivot
            t = d.dot(a)
            tmin, tmax = min(tmin, t), max(tmax, t)
            r2 = max(r2, (d - t * a).length_squared)
    r = math.sqrt(r2)
    center = pivot + a * ((tmin + tmax) / 2.0)
    return {"shape": "cylinder", "axis": [round(v, 5) for v in a],
            "center": [round(v, 5) for v in center],
            "radius": round(r, 5), "height": round(tmax - tmin, 5)}


def cylinder_mesh(name, spec, col):
    """UCX convex cylinder mesh for UE, in WORLD coords."""
    import bmesh
    a = Vector(spec["axis"])
    c = Vector(spec["center"])
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm, cap_ends=True, segments=CONFIG["cyl_segments"],
        radius1=spec["radius"], radius2=spec["radius"], depth=spec["height"])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    col.objects.link(o)
    o.matrix_world = (Matrix.Translation(c)
                      @ a.to_track_quat("Z", "Y").to_matrix().to_4x4())
    return o


def aabb_box_spec(meshes):
    pts = []
    for m in meshes:
        mw = m.matrix_world
        pts += [mw @ Vector(c) for c in m.bound_box]
    mn = Vector((min(p[i] for p in pts) for i in range(3)))
    mx = Vector((max(p[i] for p in pts) for i in range(3)))
    return {"shape": "box", "center": [round(v, 5) for v in (mn + mx) / 2],
            "size": [round(v, 5) for v in (mx - mn)]}


def resolve_collision(p, orig_name, work_col, ainv, notes):
    """Returns (list of (ue_object, name_prefix), manifest_shapes) in the
    RE-BASED root-local frame, or (None, None) -> island-box fallback."""
    obj = p["obj"]
    # 1. authored (originals live in SCENE coords: re-base with ainv)
    authored = authored_collision(orig_name)
    if authored:
        out, shapes = [], []
        for src in authored:
            c = src.copy()
            c.data = src.data.copy()
            work_col.objects.link(c)
            bake_object(c)
            c.parent = None
            c.matrix_world = ainv @ c.matrix_world
            pfx = base_name(src.name)[:4]
            out.append((c, pfx))
            if pfx == "UBX_":
                shapes.append(aabb_box_spec([c]))
            else:
                shapes.append({"shape": "convex", "mesh": base_name(src.name)})
        notes.append("part %s: %d authored collision meshes" % (p["name"], len(authored)))
        return out, shapes
    mode = str(get_prop(obj, "collision", "auto"))
    if mode == "none":
        return [], []
    # 2/3. parametric
    if mode == "cylinder" or (mode == "auto" and p["jtype"] == "continuous"):
        spec = fit_cylinder(p["meshes"], p["pivot_w"], p["axis"])
        ue = cylinder_mesh("ucx_tmp", spec, work_col)
        notes.append("part %s: auto cylinder r=%.3f h=%.3f" % (
            p["name"], spec["radius"], spec["height"]))
        return [(ue, "UCX_")], [spec]
    if mode == "box":
        spec = aabb_box_spec(p["meshes"])
        boxes = [(Vector(spec["center"]), Vector(spec["size"]))]
        ue = make_ucx("tmp_" + safe_name(p["name"]), boxes, work_col)
        return [(o, "UBX_") for o in ue], [spec]
    if mode == "boxes":
        return None, "boxes"     # island boxes on the joined part
    # auto default for non-wheel parts / mode == "convex": single hull
    return None, "hull"


# --------------------------------------------------------------------------
# per-root export
# --------------------------------------------------------------------------
def spec_to_part_local(shapes, origin):
    for s in shapes:
        if "center" in s:
            s["center"] = [round(s["center"][i] - origin[i], 5) for i in range(3)]
    return shapes


def export_root(root_name, out_dir, report):
    root = bpy.data.objects.get(root_name)
    if root is None:
        report[root_name] = {"error": "root not found"}
        return
    work = ensure_collection("EXPORT_WORK")
    name_map = {}
    duplicate_hierarchy(root, work, name_map)
    for o in list(name_map.values()):
        if o.type in {"MESH", "CURVE"}:
            bake_object(o)
    copy_to_orig = {c.name: orig for orig, c in name_map.items()}

    # re-base to root-local (translation only, like the dojo pipeline)
    anchor = root.matrix_world.translation.copy()
    ainv = Matrix.Translation(-anchor)
    copies = set(name_map.values())
    for o in name_map.values():
        if o.parent not in copies:
            o.matrix_world = ainv @ o.matrix_world
    bpy.context.view_layer.update()

    parts, closures = build_parts(root, name_map)
    notes = []

    # joint data (root-local)
    for p in parts.values():
        obj = p["obj"]
        piv = get_prop(obj, "pivot")
        p["pivot_w"] = Vector(piv) if piv else obj.matrix_world.translation.copy()
        p["axis"] = get_prop(obj, "axis", [0, 0, 1])
        p["limits"] = get_prop(obj, "limits")
        p["mass"] = float(get_prop(obj, "mass", 0.0) or 0.0)
        p["motor"] = {"torque": float(get_prop(obj, "motor_torque", 0.0) or 0.0),
                      "velocity": float(get_prop(obj, "motor_velocity", 0.0) or 0.0)}
        p["spring"] = {"stiffness": float(get_prop(obj, "spring_stiffness", 0.0) or 0.0),
                       "damping": float(get_prop(obj, "spring_damping", 0.0) or 0.0),
                       "rest": float(get_prop(obj, "spring_rest", 0.0) or 0.0)}
        p["friction"] = float(get_prop(obj, "friction", 0.0) or 0.0)
        p["mimic"] = str(get_prop(obj, "mimic", "") or "")
        p["mimic_ratio"] = float(get_prop(obj, "mimic_ratio", 1.0) or 1.0)

    # detach every part object from the hierarchy (world-preserving) BEFORE
    # any joining: a join consumes its source objects, and a part parented
    # under a consumed object would be orphaned and jump to a stale frame
    for p in parts.values():
        o = p["obj"]
        wm = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = wm
    bpy.context.view_layer.update()

    nm = safe_name(root_name)
    folder = os.path.join(out_dir, nm)
    os.makedirs(folder, exist_ok=True)
    manifest_parts = {}

    for pname, p in sorted(parts.items()):
        orig_name = copy_to_orig.get(pname, pname)
        ue_coll, shapes = resolve_collision(p, orig_name, work, ainv, notes)

        # join the part meshes into one object
        bpy.ops.object.select_all(action="DESELECT")
        for m in p["meshes"]:
            m.select_set(True)
        if not p["meshes"]:
            notes.append("part %s: NO meshes" % pname)
            continue
        bpy.context.view_layer.objects.active = p["meshes"][0]
        if len(p["meshes"]) > 1:
            bpy.ops.object.join()
        joined = bpy.context.view_layer.objects.active
        joined.name = "%s__%s" % (nm, safe_name(pname))
        joined.data.name = joined.name
        wm = joined.matrix_world.copy()
        joined.parent = None
        joined.matrix_world = wm
        bpy.ops.object.select_all(action="DESELECT")
        joined.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        origin = p["pivot_w"]
        joined.data.transform(Matrix.Translation(-origin))
        joined.data.update()

        if shapes == "boxes":                   # island boxes (part-local)
            boxes = island_boxes(joined)
            if len(boxes) > CONFIG["ucx_max_boxes"]:
                notes.append("part %s: dropped %d collision islands" % (
                    pname, len(boxes) - CONFIG["ucx_max_boxes"]))
                boxes = boxes[:CONFIG["ucx_max_boxes"]]
            coll_objs = make_ucx(joined.name, boxes, work)
            shapes = [{"shape": "box",
                       "center": [round(v, 5) for v in c],
                       "size": [round(v, 5) for v in s]} for c, s in boxes]
        elif shapes == "hull":                  # convex hull (part-local)
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(joined.data)
            res = bmesh.ops.convex_hull(bm, input=bm.verts)
            doomed = {e for e in res["geom_unused"] + res["geom_interior"]
                      if isinstance(e, bmesh.types.BMVert)}
            bmesh.ops.delete(bm, geom=list(doomed), context="VERTS")
            hme = bpy.data.meshes.new("UCX_" + joined.name)
            bm.to_mesh(hme)
            bm.free()
            hob = bpy.data.objects.new("UCX_%s_00" % joined.name, hme)
            work.objects.link(hob)
            coll_objs = [hob]
            hmn = [min(v.co[i] for v in hme.vertices) for i in range(3)]
            hmx = [max(v.co[i] for v in hme.vertices) for i in range(3)]
            shapes = [{"shape": "convex", "mesh": "%s_hull" % safe_name(pname),
                       "box_approx": {
                           "center": [round((hmn[i] + hmx[i]) / 2, 5) for i in range(3)],
                           "size": [round(hmx[i] - hmn[i], 5) for i in range(3)]}}]
            notes.append("part %s: convex hull (%d verts)" % (
                pname, len(hme.vertices)))
        else:
            # root-local collision objects -> part-local; UE requires the
            # collision object name to embed the render mesh name exactly
            coll_objs = []
            for i, (o, pfx) in enumerate(ue_coll):
                o.parent = None
                o.matrix_world = Matrix.Translation(-origin) @ o.matrix_world
                o.name = "%s%s_%02d" % (pfx, joined.name, i)
                coll_objs.append(o)
            shapes = spec_to_part_local(shapes, origin)

        fp = os.path.join(folder, "%s.fbx" % joined.name)
        export_fbx_static([joined] + coll_objs, fp)
        for o in coll_objs:
            bpy.data.objects.remove(o, do_unlink=True)

        j = None
        if p["parent"] is not None:
            j = {"type": ("revolute" if p["jtype"] in ("revolute", "continuous")
                          else "prismatic"),
                 "continuous": p["jtype"] == "continuous",
                 "axis": [round(float(v), 5) for v in p["axis"]],
                 "pivot": [round(float(v), 5) for v in origin],
                 "limits": ([round(float(v), 4) for v in p["limits"]]
                            if p["limits"] else None),
                 "parent": safe_name(p["parent"]),
                 "motor": p["motor"], "spring": p["spring"],
                 "friction": p["friction"],
                 "mimic": ({"of": safe_name(p["mimic"]),
                            "ratio": p["mimic_ratio"]} if p["mimic"] else None)}
        manifest_parts[safe_name(pname)] = {
            "fbx": os.path.basename(fp),
            "origin": [round(float(v), 5) for v in origin],
            "mass": p["mass"] if p["mass"] > 0 else None,
            "joint": j,
            "collision": shapes,
        }

    man_closures = []
    for c in closures:
        e = c["empty"]
        host = None
        cur = e.parent
        live = {p["obj"]: p for p in parts.values()}
        while cur is not None and cur not in live:
            cur = cur.parent
        if cur is None:
            notes.append("closure %s: no host part" % e.name)
            continue
        other_copy = name_map.get(c["other"])
        other_part = None
        if other_copy is not None:
            cur2 = other_copy
            while cur2 is not None and cur2 not in live:
                cur2 = cur2.parent
            other_part = live.get(cur2)
        if other_part is None:
            notes.append("closure %s: other body '%s' not found" % (e.name, c["other"]))
            continue
        man_closures.append({
            "name": safe_name(base_name(e.name)),
            "body_a": safe_name(live[cur]["name"]),
            "body_b": safe_name(other_part["name"]),
            "pivot": [round(float(v), 5) for v in e.matrix_world.translation],
            "axis": [round(float(v), 5) for v in get_prop(e, "axis", [0, 0, 1])],
        })

    entry = {"parts": manifest_parts, "closures": man_closures,
             "anchor": [round(float(v), 5) for v in anchor], "notes": notes}
    write_mjcf(nm, folder, entry)
    write_usd(nm, folder, entry, notes)
    report[nm] = entry

    if CONFIG["cleanup"]:
        for o in list(ensure_collection("EXPORT_WORK").objects):
            bpy.data.objects.remove(o, do_unlink=True)


# --------------------------------------------------------------------------
# MJCF
# --------------------------------------------------------------------------
def write_mjcf(nm, folder, entry):
    import xml.etree.ElementTree as ET
    parts = entry["parts"]
    kids = {}
    for pn, pe in parts.items():
        j = pe.get("joint")
        kids.setdefault(j["parent"] if j else None, []).append(pn)

    mj = ET.Element("mujoco", model=nm)
    ET.SubElement(mj, "compiler", angle="degree", autolimits="true")
    ET.SubElement(mj, "option", timestep="0.002")
    world = ET.SubElement(mj, "worldbody")
    actuators = ET.SubElement(mj, "actuator")
    equality = ET.SubElement(mj, "equality")

    def geoms(body, pe):
        for s in pe["collision"]:
            if s["shape"] == "cylinder":
                a = Vector(s["axis"])
                q = a.to_track_quat("Z", "Y")
                ET.SubElement(body, "geom", type="cylinder",
                              size="%.5f %.5f" % (s["radius"], s["height"] / 2),
                              pos="%.5f %.5f %.5f" % tuple(s["center"]),
                              quat="%.5f %.5f %.5f %.5f" % (q.w, q.x, q.y, q.z))
            elif s["shape"] == "box":
                ET.SubElement(body, "geom", type="box",
                              size="%.5f %.5f %.5f" % tuple(v / 2 for v in s["size"]),
                              pos="%.5f %.5f %.5f" % tuple(s["center"]))
            elif s["shape"] == "convex" and s.get("box_approx"):
                ba = s["box_approx"]
                ET.SubElement(body, "geom", type="box",
                              size="%.5f %.5f %.5f" % tuple(v / 2 for v in ba["size"]),
                              pos="%.5f %.5f %.5f" % tuple(ba["center"]))
            else:
                ET.SubElement(body, "geom", type="box", size="0.01 0.01 0.01",
                              pos="0 0 0")    # authored convex: TODO obj export

    def emit(pn, parent_el, parent_origin):
        pe = parts[pn]
        org = pe["origin"]
        rel = [org[i] - parent_origin[i] for i in range(3)]
        body = ET.SubElement(parent_el, "body", name=pn,
                             pos="%.5f %.5f %.5f" % tuple(rel))
        j = pe.get("joint")
        if j:
            attrs = dict(name=pn, pos="0 0 0",
                         axis="%.5f %.5f %.5f" % tuple(j["axis"]),
                         type="slide" if j["type"] == "prismatic" else "hinge")
            if j["limits"]:
                attrs["range"] = "%.4f %.4f" % tuple(j["limits"])
            sp = j["spring"]
            if sp["stiffness"]:
                attrs["stiffness"] = "%.5f" % sp["stiffness"]
                attrs["springref"] = "%.5f" % sp["rest"]
            if sp["damping"]:
                attrs["damping"] = "%.5f" % sp["damping"]
            if j["friction"]:
                attrs["frictionloss"] = "%.5f" % j["friction"]
            ET.SubElement(body, "joint", **attrs)
            m = j["motor"]
            if m["torque"] and not j.get("mimic"):
                ET.SubElement(actuators, "motor", name=pn, joint=pn,
                              ctrlrange="-1 1",
                              gear="%.4f" % m["torque"])
            if j.get("mimic"):
                ET.SubElement(equality, "joint", joint1=pn,
                              joint2=j["mimic"]["of"],
                              polycoef="0 %.5f 0 0 0" % j["mimic"]["ratio"])
        if pe["mass"]:
            ET.SubElement(body, "inertial",
                          pos="0 0 0", mass="%.4f" % pe["mass"],
                          diaginertia="0.01 0.01 0.01")
        geoms(body, pe)
        for c in sorted(kids.get(pn, [])):
            emit(c, body, org)

    roots = sorted(kids.get(None, []))
    for r in roots:
        emit(r, world, [0, 0, 0])
    for cl in entry["closures"]:
        ET.SubElement(equality, "connect", body1=cl["body_a"],
                      body2=cl["body_b"],
                      anchor="%.5f %.5f %.5f" % tuple(cl["pivot"]))
    ET.indent(mj)
    ET.ElementTree(mj).write(os.path.join(folder, nm + ".mjcf.xml"))


# --------------------------------------------------------------------------
# USD (UsdPhysics; skipped with a note if pxr is unavailable)
# --------------------------------------------------------------------------
def write_usd(nm, folder, entry, notes):
    try:
        from pxr import Usd, UsdGeom, UsdPhysics, Gf, Sdf
    except Exception as e:
        notes.append("usd emit skipped: " + repr(e))
        return
    fp = os.path.join(folder, nm + ".usda")
    if os.path.exists(fp):
        os.remove(fp)
    stage = Usd.Stage.CreateNew(fp)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/" + nm)
    stage.SetDefaultPrim(root.GetPrim())
    UsdPhysics.ArticulationRootAPI.Apply(root.GetPrim())
    parts = entry["parts"]
    path = {pn: "/%s/%s" % (nm, pn) for pn in parts}
    for pn, pe in parts.items():
        x = UsdGeom.Xform.Define(stage, path[pn])
        UsdPhysics.RigidBodyAPI.Apply(x.GetPrim())
        if pe["mass"]:
            UsdPhysics.MassAPI.Apply(x.GetPrim()).CreateMassAttr(float(pe["mass"]))
        x.AddTranslateOp().Set(Gf.Vec3d(*pe["origin"]))
        for i, s in enumerate(pe["collision"]):
            gp = "%s/col_%d" % (path[pn], i)
            if s["shape"] == "cylinder":
                g = UsdGeom.Cylinder.Define(stage, gp)
                g.CreateRadiusAttr(s["radius"])
                g.CreateHeightAttr(s["height"])
                g.CreateAxisAttr("Z")
                gx = UsdGeom.Xformable(g.GetPrim())
                gx.AddTranslateOp().Set(Gf.Vec3d(*s["center"]))
                a = Vector(s["axis"])
                q = a.to_track_quat("Z", "Y")
                gx.AddOrientOp().Set(Gf.Quatf(q.w, q.x, q.y, q.z))
            elif s["shape"] == "box":
                g = UsdGeom.Cube.Define(stage, gp)
                g.CreateSizeAttr(1.0)
                gx = UsdGeom.Xformable(g.GetPrim())
                gx.AddTranslateOp().Set(Gf.Vec3d(*s["center"]))
                gx.AddScaleOp().Set(Gf.Vec3f(*[v / 2 for v in s["size"]]))
            else:
                continue
            UsdPhysics.CollisionAPI.Apply(stage.GetPrimAtPath(Sdf.Path(gp)))
    for pn, pe in parts.items():
        j = pe.get("joint")
        if not j:
            continue
        jp = "/%s/joints/%s" % (nm, pn)
        cls = UsdPhysics.PrismaticJoint if j["type"] == "prismatic" \
            else UsdPhysics.RevoluteJoint
        joint = cls.Define(stage, jp)
        joint.CreateBody0Rel().SetTargets([Sdf.Path(path[j["parent"]])])
        joint.CreateBody1Rel().SetTargets([Sdf.Path(path[pn])])
        porg = parts[j["parent"]]["origin"]
        joint.CreateLocalPos0Attr(
            Gf.Vec3f(*[j["pivot"][i] - porg[i] for i in range(3)]))
        joint.CreateLocalPos1Attr(Gf.Vec3f(0, 0, 0))
        ax = Vector(j["axis"])
        dom = max(range(3), key=lambda i: abs(ax[i]))
        joint.CreateAxisAttr("XYZ"[dom])
        if j["limits"]:
            joint.CreateLowerLimitAttr(float(j["limits"][0]))
            joint.CreateUpperLimitAttr(float(j["limits"][1]))
        m, sp = j["motor"], j["spring"]
        if m["torque"] or sp["stiffness"] or sp["damping"]:
            dtype = "linear" if j["type"] == "prismatic" else "angular"
            drv = UsdPhysics.DriveAPI.Apply(joint.GetPrim(), dtype)
            if m["torque"]:
                drv.CreateMaxForceAttr(float(m["torque"]))
            drv.CreateStiffnessAttr(float(sp["stiffness"]))
            drv.CreateDampingAttr(float(sp["damping"]))
            drv.CreateTargetPositionAttr(float(sp["rest"]))
    for cl in entry["closures"]:
        jp = "/%s/joints/%s" % (nm, cl["name"])
        joint = UsdPhysics.SphericalJoint.Define(stage, jp)
        joint.CreateBody0Rel().SetTargets([Sdf.Path(path[cl["body_a"]])])
        joint.CreateBody1Rel().SetTargets([Sdf.Path(path[cl["body_b"]])])
        aorg = parts[cl["body_a"]]["origin"]
        borg = parts[cl["body_b"]]["origin"]
        joint.CreateLocalPos0Attr(
            Gf.Vec3f(*[cl["pivot"][i] - aorg[i] for i in range(3)]))
        joint.CreateLocalPos1Attr(
            Gf.Vec3f(*[cl["pivot"][i] - borg[i] for i in range(3)]))
    stage.GetRootLayer().Save()


# --------------------------------------------------------------------------
def main():
    report = {}
    for r in CONFIG["roots"]:
        r = r.strip()
        if r:
            export_root(r, CONFIG["output_dir"], report)
    if CONFIG["manifest"]:
        with open(CONFIG["manifest"], "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=repr)
    mp = os.path.join(CONFIG["output_dir"], "rammp_manifest.json")
    merged = {}
    if os.path.exists(mp):
        try:
            merged = json.load(open(mp, encoding="utf-8"))
        except Exception:
            merged = {}
    merged.update(report)
    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, default=repr)
    print("=== robot export done:",
          ", ".join("%s(%d parts)" % (k, len(v.get("parts", {})))
                    for k, v in report.items()), "===")
    for k, v in report.items():
        for n in v.get("notes", []):
            print("   ", k, "|", n)
    sys.stdout.flush()


main()
