"""
dojo_articulated_export.py
==========================
Adapted copy of kitchen_skeletal_export.py for dojo.blend: rig every household
asset (dressers, kitchen cabinets, microwaves, minifridge, fridges, stoves...)
as a UE-ready *skeletal mesh* and export one FBX per physical object.

Differences from the kitchen-pack script this was copied from:
  - The scene is built from Sketchfab/Collada imports: every top-level object
    is an EMPTY wrapper (Materials/Meshes/Sketchfab_model/...), and each
    articulable part is a NAMED empty (Model_1_Door_01, Refrigerator_drawer,
    FridgeUpperDoor, ...) holding its meshes. Classification is therefore
    NAME-DRIVEN first, with the old geometric logic as fallback.
  - Many part empties carry a REAL pivot at the hinge (kitchen_cabinets,
    fridge, electronics_kitchen, minifridge). The bone is placed on that
    pivot; whether the door swings about a vertical axis (cabinet/fridge
    doors) or a horizontal one (stove/oven flip-down doors, the fridge's egg
    tray lid) is inferred from where the pivot sits on the door's bbox.
    The 'cabinets' root has all pivots at the world origin, so drawers/doors
    there fall back to bbox-derived pivots like the original script.
  - Doors POSED OPEN in the scene (two kitchen cabinet doors, the minifridge
    door) are auto-closed on the work copy by trying hinge rotations and
    keeping the one that minimises the asset's bounds.
  - A root may contain several separate physical objects; CONFIG['split']
    breaks it into one asset per object (prefix mode: cabinets -> CabinetA /
    CabinetB / ShelveA; children mode: electronics_kitchen -> one asset per
    appliance / prop, with stray flat door empties merged into the appliance
    whose bounds they overlap).
  - The 'microwave' root is ALREADY skinned to an armature ("skeleton",
    bones n4/n5). Its per-vertex weights are kept: vertex groups are renamed
    to our bone names, the old armature is discarded, and new bones are laid
    on the old bone pivots.
  - Materials are Sketchfab image textures whose node graphs (metallic-
    roughness via SeparateColor etc.) cannot cross FBX — so every asset's
    materials are BAKED to a BaseColor/ORM/Normal PNG set written next to
    its FBX and replaced by one clean textured material (same pipeline as
    the kitchen-pack script). Small props bake at bake_resolution_small.
  - Assets are true real-world scale (fridge ~1.9 m), so global_scale = 1.0.

Per asset the pipeline is the same as the original:
  duplicate hierarchy -> bake modifiers -> close open doors -> analyze ->
  build bones -> flatten transforms -> fix normals -> armature + rigid skin
  -> export FBX (one folder per asset) -> cleanup, plus a JSON manifest.

Usage inside Blender (Scripting tab > Run), or via the MCP bridge.
Set CONFIG['visualize']=True for a dry run (rig + pivot empties, no export).
Tested against: dojo.blend (Blender 5.1).
"""

import bpy
import bmesh
import json
import os
import re
from math import radians
from mathutils import Matrix, Vector

# ===========================================================================
# CONFIG
# ===========================================================================
CONFIG = {
    # Top-level roots to process. None => all top-level objects that have
    # children (in dojo.blend: cabinets, electronics_kitchen, fridge,
    # kitchen_cabinets, microwave, minifridge).
    "roots": None,
    "skip_roots": set(),

    # How to break a root into separate physical assets:
    #   "whole"            -> one asset for the whole root (default)
    #   ("prefix", [...])  -> group part nodes by name prefix, one asset each
    #   ("children", None) -> one asset per child of the deepest container
    #                         empty; flat door/drawer groups are merged into
    #                         the overlapping non-mover group
    "split": {
        "cabinets": ("prefix", ["CabinetA", "CabinetB", "ShelveA"]),
        "kitchen_cabinets": ("prefix", ["Model_1", "Model_2"]),
        "electronics_kitchen": ("children", None),
    },
    # Skip assets whose (post-split) name matches any of these regexes.
    # e.g. [r"Knife", r"Spoon", r"Fork"] to drop the cutlery props.
    "skip_assets": [],

    "export": True,
    # "skeletal": bone-rigged FBX per asset (original pipeline).
    # "static_parts": one static FBX per rigid part (root + each mover) with
    #   UCX box collision from mesh islands, origin at the joint pivot, plus
    #   USD (UsdPhysics joints) and MJCF emitters -- for Blueprint assembly
    #   and robotics engines (MuJoCo / Newton / Isaac).
    "export_mode": "skeletal",
    "ucx_max_boxes": 48,                    # per part; largest islands win
    "ucx_min_size": 0.006,                  # m; thinner box sides get padded
    "ucx_dust_volume": 2e-6,                # m^3; smaller islands are junk
                                            # (screws, trims) and get pruned
                                            # BEFORE the cap, so handles stay
    "emit_usd": True,                       # static_parts only
    "emit_mjcf": True,                      # static_parts only
    "output_dir": r"C:\Users\waemf\data\UE_VAULT_EXPORT\dojo",
    "per_asset_folder": True,               # <output_dir>/<asset>/<asset>.fbx
    "visualize": False,                     # True = rig + pivot empties, no export/cleanup
    "cleanup": True,

    # Close doors that are posed open in the scene (rotate the work copy
    # about the door's own pivot to the angle minimising the asset bounds).
    "close_open_doors": True,

    # FBX / unit options. These models are true real-world scale.
    "apply_unit_scale": True,
    "global_scale": 1.0,
    "axis_forward": "-Z",
    "axis_up": "Y",
    "add_leaf_bones": False,

    # Materials: baked per asset into a BaseColor + ORM + Normal PNG set
    # written next to the FBX (same pipeline as the kitchen-pack script).
    # Embedding the Sketchfab materials instead does NOT survive UE import:
    # their metallicRoughness node graphs can't cross FBX, so everything
    # comes in untextured.
    "bake_materials": True,
    # NOTE the atlas is shared by ALL of an asset's meshes (grid cells), so
    # each mesh only gets ~res/sqrt(n_meshes) texels across -- size up.
    "bake_resolution": 4096,                # assets bigger than ~1.2 m
    "bake_resolution_small": 2048,          # small props (knives, pots, ...)
    "bake_samples": 16,                     # emit bakes are noise-free; plenty
    "bake_maps": ("base", "rough", "metal", "normal"),
    # Material-group split: every normalized source-material name (Sketchfab
    # names are semantic: Doors_Drawers_01, FridgeHandles, CabinetA_handles...)
    # becomes its OWN atlas set + material slot, so UE can swap / tint each
    # group independently for programmatic variants. Aliases merge families
    # of names into one group (regex on the .NNN-stripped name -> group).
    "material_group_aliases": [
        # keep the glass shelves OUT of the opaque interior group -- a group
        # is translucent if ANY member is, so mixing would glass the interior
        (r"^FridgeInside(?!Glass)", "FridgeInterior"),
        (r"^ZenUV_Generic_Material", "FridgeInterior"),
    ],
    # Per-group atlas resolution is share-scaled from bake_resolution by the
    # group's world-surface area (keeps total texel count ~constant); this is
    # the floor so tiny groups (hinges, handles) stay usable.
    "bake_resolution_min": 512,
    "embed_textures": False,
    "path_mode": "RELATIVE",                # textures already sit beside the FBX

    "write_manifest": True,
}

# ---------------------------------------------------------------------------
# OVERRIDES, keyed by ORIGINAL object name (as in the outliner).
#   kind:         DOOR / DRAWER / DOOR_SLIDE / STATIC
#   split_meshes: True -> each mesh child of the empty becomes its own unit
#                 (used for the sliding glass panes of CabinetB)
#   bone_of:      "<mover name>" -> force-attach this static part to a mover
#   hinge:        "MIN"/"MAX" -> pin a no-pivot door's hinge side
#   close_swing:  max auto-close rotation in degrees (default 120; raise for
#                 doors posed open wider than that)
# ---------------------------------------------------------------------------
OVERRIDES = {
    # Egg-tray flip lid mounted on the big fridge's upper door: the name
    # contains "Holder" which the exclusion regex would keep static.
    "FridgeUpperHolderPlasticDoor": {"kind": "DOOR"},
    # Tall bottle shelf on the fridge door's inner face; no "door" in the
    # name, so the association heuristics would weld it to the body.
    "FridgePlasticHolder": {"bone_of": "FridgeUpperDoor"},
    # microwave_2's door config moved to dojo_* props on its 'Door' empty
    # (written by dojo_scene_fixes.py) so it can be hand-tuned in Blender;
    # an OVERRIDES entry here would shadow those props.
}

AI = {"X": 0, "Y": 1, "Z": 2}


def mover_cfg(orig, obj=None):
    """Per-part config: dojo_* custom properties on the object (written by
    the annotate pass, or edited by hand in Object Properties > Custom
    Properties), overlaid by OVERRIDES -- which always win. Recognized
    properties: dojo_kind (DOOR/DRAWER/DOOR_SLIDE/STATIC), dojo_joint
    (revolute/prismatic/fixed), dojo_pivot, dojo_axis, dojo_limits,
    dojo_close_angle, dojo_close_swing, dojo_bone_of, dojo_hinge."""
    cfg = {}
    if obj is not None:
        for key in ("kind", "pivot", "axis", "limits", "close_angle",
                    "close_swing", "bone_of", "hinge", "mass"):
            v = obj.get("dojo_" + key)
            if v is None:
                continue
            cfg[key] = (list(v) if hasattr(v, "__len__")
                        and not isinstance(v, str) else v)
        if "kind" not in cfg:
            j = obj.get("dojo_joint")
            if j is not None:
                cfg["kind"] = {"revolute": "DOOR",
                               "prismatic": "DRAWER"}.get(str(j), "STATIC")
    cfg.update(OVERRIDES.get(orig, {}))
    return cfg

# name-driven classification (matched against the ORIGINAL name, .NNN stripped)
MOVER_EXCLUDE = re.compile(r"hinge|hinger|rail|structure|holder|track", re.I)
PAT_DOOR = re.compile(r"door", re.I)
PAT_HANDLE = re.compile(r"handle|knob|pull|grip", re.I)
PAT_DRAWER = re.compile(r"drawer", re.I)


# ===========================================================================
# geometry helpers
# ===========================================================================
def base_name(name):
    """Strip Blender's numeric suffix for pattern matching ('x.001' -> 'x').
    NOTE: original scene names may legitimately end in .001 (Sketchfab
    duplicates); matching uses the stripped form, OVERRIDES use exact names."""
    return re.sub(r"\.\d+$", "", name)


def descendants(obj):
    out = []
    for c in obj.children:
        out.append(c)
        out.extend(descendants(c))
    return out


def aabb(points):
    mn = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    mx = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return mn, mx


def obj_points(obj):
    """World-space bbox corners (call after baking, so bound_box is real)."""
    if obj.type == "MESH" and obj.data and len(obj.data.vertices):
        return [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return [obj.matrix_world.translation]


def subtree_points(obj):
    pts = []
    for n in [obj] + descendants(obj):
        pts += obj_points(n)
    return pts


def bbox_gap(amn, amx, bmn, bmx):
    """Distance between two AABBs (0 when they overlap)."""
    g = Vector((0.0, 0.0, 0.0))
    for i in range(3):
        g[i] = max(bmn[i] - amx[i], amn[i] - bmx[i], 0.0)
    return g.length


def is_mover_name(bn):
    """DOOR/DRAWER from a part name, or None. Exclusions keep rails, hinge
    hardware, door-mounted holders and the cabinet 'Structure' static."""
    if MOVER_EXCLUDE.search(bn):
        return None
    if PAT_DRAWER.search(bn):
        return "DRAWER"
    if PAT_DOOR.search(bn):
        return "DOOR"
    return None


# ===========================================================================
# root splitting: one root -> one or more assets
# ===========================================================================
def split_root(root):
    """Return a list of assets: dicts with name + the subtree nodes that make
    up one physical object + the root's world matrix as the asset's ANCHOR:
    process_asset re-bases the work copies into this local frame, so every
    pivot/override/dojo_* property is ROOT-LOCAL and survives moving or
    re-arranging assets in the scene."""
    mode = CONFIG["split"].get(root.name, "whole")
    if mode == "whole":
        return [dict(name=root.name, nodes=[root],
                     anchor=root.matrix_world.copy())]

    kind, arg = mode
    if kind == "prefix":
        groups = {p: [] for p in arg}
        claimed = set()
        for d in descendants(root):
            if d.name in claimed:
                continue
            for p in arg:
                if base_name(d.name).startswith(p):
                    groups[p].append(d)
                    claimed.update(x.name for x in [d] + descendants(d))
                    break
        return [dict(name=f"{root.name}__{p}", nodes=objs,
                     anchor=root.matrix_world.copy())
                for p, objs in groups.items() if objs]

    if kind == "children":
        # deepest container = the empty with the most direct children
        cands = [root] + [d for d in descendants(root) if d.type == "EMPTY"]
        container = max(cands, key=lambda o: len(o.children))
        groups = []
        for c in container.children:
            mover = is_mover_name(base_name(c.name)) is not None
            groups.append(dict(node=c, mover=mover, bb=aabb(subtree_points(c))))
        # merge flat door/drawer groups into the overlapping non-mover group
        solids = [g for g in groups if not g["mover"]]
        assets = {id(g): [g["node"]] for g in solids}
        for g in groups:
            if not g["mover"]:
                continue
            best, bd = None, 1e18
            for s in solids:
                d = bbox_gap(g["bb"][0], g["bb"][1], s["bb"][0], s["bb"][1])
                if d < bd:
                    bd, best = d, s
            if best is not None:
                assets[id(best)].append(g["node"])
            else:
                assets[id(g)] = [g["node"]]
        return [dict(name=f"{root.name}__{safe_name(nodes[0].name)}",
                     nodes=nodes, anchor=root.matrix_world.copy())
                for nodes in assets.values()]

    raise ValueError(f"unknown split mode for {root.name}: {mode!r}")


# ===========================================================================
# non-destructive duplicate + bake  (from the original script)
# ===========================================================================
def ensure_collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def duplicate_hierarchy(node, work_col, name_map):
    """Deep-copy node + descendants into work_col, preserving parenting.
    Extends name_map {original_name -> copy}."""
    originals = [node] + descendants(node)
    old_to_new = {}
    for o in originals:
        n = o.copy()
        if o.data:
            n.data = o.data.copy()
        work_col.objects.link(n)
        old_to_new[o] = n
    for o in originals:
        n = old_to_new[o]
        n.parent = old_to_new.get(o.parent) if o.parent in old_to_new else None
        n.matrix_parent_inverse = o.matrix_parent_inverse.copy()
        n.matrix_world = o.matrix_world.copy()
    for o in originals:
        name_map[o.name] = old_to_new[o]
    return old_to_new[node]


def bake_object(obj):
    """Apply all modifiers / convert curve to mesh in place. Armature
    modifiers are REMOVED first (never applied): pre-skinned meshes keep
    their vertex groups and get re-driven by our new armature instead."""
    for m in list(obj.modifiers):
        if m.type == "ARMATURE":
            obj.modifiers.remove(m)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target="MESH")


# ===========================================================================
# pre-skinned assets (the microwave): harvest the source armature
# ===========================================================================
def harvest_preskinned(name_map):
    """For meshes skinned to a source armature: keep their vertex groups,
    rename the old ROOT bone's group to 'root', and return one mover def per
    remaining deform bone (pivot = old bone head). The copied armature
    objects are then deleted from the work set."""
    arms = [(k, o) for k, o in name_map.items() if o.type == "ARMATURE"]
    preskinned = set()          # original names of meshes that keep weights
    harvested = []              # per-bone: dict(group, head, users)
    for _, arm in arms:
        bones = {b.name: b for b in arm.data.bones}
        root_names = {b.name for b in bones.values() if b.parent is None}
        users = []
        for k, o in name_map.items():
            if o.type == "MESH" and any(g.name in bones for g in o.vertex_groups):
                users.append((k, o))
        if not users:
            continue
        for bname, b in bones.items():
            if not b.use_deform or bname in root_names:
                continue
            wusers = []
            for k, o in users:
                g = o.vertex_groups.get(bname)
                if g is None:
                    continue
                gi = g.index
                pts = [o.matrix_world @ v.co for v in o.data.vertices
                       for ge in v.groups if ge.group == gi and ge.weight >= 0.5]
                if pts:
                    wusers.append((k, o, pts))
            if wusers:
                harvested.append(dict(group=bname,
                                      head=arm.matrix_world @ b.head_local,
                                      users=wusers))
        for k, o in users:
            preskinned.add(k)
            for g in o.vertex_groups:
                if g.name in root_names:
                    g.name = "root"
    for k, arm in arms:
        bpy.data.objects.remove(arm, do_unlink=True)
        del name_map[k]
    return preskinned, harvested


# ===========================================================================
# analysis: movers, kinds, pivots, front axis  (operates on the WORK COPY)
# ===========================================================================
def find_movers(name_map):
    """Mover units from part names/overrides. Only EMPTY part nodes are
    matched by name (mesh names often carry material suffixes like
    '..._Doors_Drawers_01_0' that would misfire); meshes become movers only
    via OVERRIDES/split_meshes."""
    movers = []
    by_obj = {}
    for orig, obj in name_map.items():
        ov = mover_cfg(orig, obj)
        kind = ov.get("kind")
        if kind is None and obj.type == "EMPTY":
            kind = is_mover_name(base_name(orig))
        if kind in ("DOOR", "DRAWER", "DOOR_SLIDE"):
            u = dict(orig=orig, obj=obj, kind=kind,
                     split=bool(ov.get("split_meshes")), parent_mover=None)
            movers.append(u)
            by_obj[obj] = u
    for u in movers:
        p = u["obj"].parent
        while p is not None:
            if p in by_obj:
                u["parent_mover"] = by_obj[p]
                break
            p = p.parent
    return movers


def mover_meshes(u, movers):
    """Meshes of a mover = subtree meshes minus nested sub-movers' meshes."""
    inner = set()
    for m in movers:
        if m is not u and m["parent_mover"] is u:
            inner.update(x.name for x in [m["obj"]] + descendants(m["obj"]))
    return [o for o in [u["obj"]] + descendants(u["obj"])
            if o.type == "MESH" and o.name not in inner]


def analyze_asset(asset, name_map, harvested):
    """Geometry + classification for one asset's work copy."""
    meshes = [o for o in name_map.values() if o.type == "MESH"]
    pts = [p for m in meshes for p in obj_points(m)]
    cmn, cmx = aabb(pts)
    cdim = cmx - cmn
    cctr = (cmn + cmx) / 2
    maxh = max(cdim.x, cdim.y)

    movers = find_movers(name_map)
    for u in movers:
        ms = mover_meshes(u, movers)
        upts = [p for m in ms for p in obj_points(m)]
        if not upts:
            upts = [u["obj"].matrix_world.translation]
        u["mn"], u["mx"] = aabb(upts)
        u["meshes"] = ms
        u["objs"] = [u["obj"]]
        u["raw_pivot"] = u["obj"].matrix_world.translation.copy()
        # effective pivot (prop/override wins) drives BOTH merging and the
        # hinge: the fridge's door empties are co-located in the scene, so
        # only the annotated per-door pivots keep the doors distinct
        ovp = mover_cfg(u["orig"], u["obj"]).get("pivot")
        u["pivot_explicit"] = ovp is not None
        if ovp is not None:
            u["raw_pivot"] = Vector(ovp)

    # merge movers that share one REAL pivot: Sketchfab splits a single door
    # into panel + trim + handle empties, all pivoted on the same hinge. The
    # shared pivot must sit on the union of the two parts (tight pad) —
    # otherwise every part of an import with all pivots parked at the origin
    # (the 'cabinets' root) would fuse into one mover.
    def pivot_on_pair(piv, a, b):
        umn, umx = aabb([a["mn"], a["mx"], b["mn"], b["mx"]])
        pad = 0.1 * max((umx - umn).length, 0.05)
        return all(umn[i] - pad <= piv[i] <= umx[i] + pad for i in range(3))

    merged = []
    for u in sorted(movers, key=lambda u: -(u["mx"] - u["mn"]).length):
        host = None
        if not u["split"]:
            for v in merged:
                if not v["split"] and v["kind"] == u["kind"] \
                        and (v["raw_pivot"] - u["raw_pivot"]).length < 0.02 \
                        and pivot_on_pair(v["raw_pivot"], v, u):
                    host = v
                    break
        if host is None:
            merged.append(u)
        else:
            host["meshes"] += u["meshes"]
            host["objs"] += u["objs"]
            host["mn"], host["mx"] = aabb([host["mn"], host["mx"], u["mn"], u["mx"]])
            u["host"] = host
    for u in merged:                        # re-route parents of merged units
        p = u["parent_mover"]
        while p is not None and "host" in p:
            p = p["host"]
        u["parent_mover"] = None if p is u else p
    movers = merged

    for u in movers:
        u["ctr"] = (u["mn"] + u["mx"]) / 2
        u["dim"] = u["mx"] - u["mn"]
        # a REAL pivot sits on/near the part; origin-parked pivots don't.
        # EXPLICIT pivots (props/OVERRIDES) are trusted outright: the part's
        # bare subtree may sit nowhere near the true hinge.
        piv = u["raw_pivot"]
        if u.get("pivot_explicit"):
            u["pivot"] = piv.copy()
        else:
            pad = 0.35 * max(u["dim"].length, 0.05)
            near = all(u["mn"][i] - pad <= piv[i] <= u["mx"][i] + pad
                       for i in range(3))
            u["pivot"] = piv.copy() if near else None

    # a tiny mover riding a much bigger one articulates relative to it
    # (egg-tray lid on the fridge door): parent it to that mover's bone
    for u in movers:
        if u["parent_mover"] is not None or u["split"]:
            continue
        for v in movers:
            if v is u or v["split"] or v["parent_mover"] is u:
                continue
            uv = u["dim"].x * u["dim"].y * u["dim"].z
            vv = v["dim"].x * v["dim"].y * v["dim"].z
            if uv < 0.2 * vv and bbox_gap(u["mn"], u["mx"], v["mn"], v["mx"]) < 0.03:
                u["parent_mover"] = v
                break

    # harvested (pre-skinned) bones become door movers: in this scene the
    # only such asset is the microwave, whose child bone drives the door
    for h in harvested:
        pts = [p for _, _, ps in h["users"] for p in ps]
        mn, mx = aabb(pts)
        movers.append(dict(orig=f"<bone:{h['group']}>", obj=None, kind="DOOR",
                           split=False, parent_mover=None, mn=mn, mx=mx,
                           ctr=(mn + mx) / 2, dim=mx - mn, meshes=[],
                           pivot=h["head"].copy(), group=h["group"],
                           users=h["users"]))

    # front axis: doors vote with their thin (facing) axis, else the drawer
    # face flush with the asset's outer face, else -Y. The door side is
    # judged against the STATIC-only centre: posed-open movers skew the
    # full-asset centre enough to flip the sign.
    mover_mesh_names = {m.name for u in movers for m in u.get("meshes", [])}
    static_pts_ = [p for m in meshes if m.name not in mover_mesh_names
                   for p in obj_points(m)]
    sctr = (lambda b: (b[0] + b[1]) / 2)(aabb(static_pts_)) if static_pts_ else cctr
    votes = {}
    for u in movers:
        if u["kind"] != "DOOR" or u["dim"].length < 1e-6:
            continue
        dims = sorted([(u["dim"].x, "X"), (u["dim"].y, "Y"), (u["dim"].z, "Z")])
        thin = dims[0][1]
        if thin not in ("X", "Y"):
            continue
        a = AI[thin]
        sign = 1 if u["ctr"][a] > sctr[a] else -1
        votes[(thin, sign)] = votes.get((thin, sign), 0) + 1
    if votes:
        front_axis, front_sign = max(votes, key=votes.get)
    else:
        best = None
        for u in movers:
            if u["kind"] != "DRAWER":
                continue
            for ax in ("X", "Y"):
                a = AI[ax]
                for sign, uface, cface in ((1, u["mx"][a], cmx[a]),
                                           (-1, u["mn"][a], cmn[a])):
                    d = abs(uface - cface)
                    if best is None or d < best[0]:
                        best = (d, ax, sign)
        front_axis, front_sign = (best[1], best[2]) if best else ("Y", -1)

    return dict(name=asset["name"], cmn=cmn, cmx=cmx, cdim=cdim, cctr=cctr,
                maxh=maxh, movers=movers,
                front_axis=front_axis, front_sign=front_sign)


# ===========================================================================
# close doors that are posed open (work copy only)
# ===========================================================================
def _best_close_angle(u, all_meshes, exclude=None):
    """Best hinge angle (deg) closing this door, and score ratio vs staying.
    Score = union bounds volume + a penalty for the door's centre sitting
    deep INSIDE the static bounds (union volume alone is minimised by a door
    swallowed into the cabinet; a closed door hugs a face). Swing is capped
    at 120 deg: anything larger flips the panel to the wrong hinge side."""
    door_names = {m.name for m in u["meshes"]} | (exclude or set())
    static_pts = [p for m in all_meshes if m.name not in door_names
                  for p in obj_points(m)]
    door_pts = [p for m in u["meshes"] for p in obj_points(m)]
    if not door_pts or not static_pts:
        return 0, 1.0
    # doors posed open BEYOND the default cap (microwave_2's Door sits ~160
    # deg open) can raise it per-mover via {"close_swing": deg}
    cap = int(mover_cfg(u.get("orig"), u.get("obj")).get("close_swing", 120))
    piv = u["pivot"]
    smn, smx = aabb(static_pts)
    dd0 = (lambda b: b[1] - b[0])(aabb(door_pts))
    faces = sorted([dd0.x, dd0.y, dd0.z])
    face_area = faces[1] * faces[2]

    def rotated(ang):
        rot = (Matrix.Translation(piv) @ Matrix.Rotation(radians(ang), 4, "Z")
               @ Matrix.Translation(-piv))
        return [rot @ p for p in door_pts]

    # True panel thickness = the smallest horizontal extent over all trial
    # angles (the current pose of an OPEN door may show no thin axis).
    thickness = 1e9
    for ang in range(-cap, cap + 1, 15):
        dmn, dmx = aabb(rotated(ang))
        thickness = min(thickness, dmx.x - dmn.x, dmx.y - dmn.y)
    # A closed door's centre legitimately sits ~half its thickness inside
    # the static bounds (thick fridge doors with shelves, siblings sharing
    # the front plane); only deeper than that counts as "swallowed".
    grace = max(0.5 * thickness, 0.05)

    def score(ang):
        dpts = rotated(ang)
        mn, mx = aabb(static_pts + dpts)
        d = mx - mn
        dmn, dmx = aabb(dpts)
        c = (dmn + dmx) / 2
        inside = min(min(smx[i] - c[i], c[i] - smn[i]) for i in range(3))
        return d.x * d.y * d.z + 3.0 * max(0.0, inside - grace) * face_area

    v0 = score(0)
    best_a, best_v = 0, v0
    for ang in range(-cap, cap + 1, 15):
        if ang == 0:
            continue
        v = score(ang)
        if v < best_v:
            best_a, best_v = ang, v
    if best_a:                              # refine: pose angles aren't
        for off in range(-14, 15, 2):       # always multiples of 15 deg
            if abs(best_a + off) > cap:
                continue
            v = score(best_a + off)
            if v < best_v:
                best_a, best_v = best_a + off, v
    return best_a, (best_v / v0 if v0 > 1e-12 else 1.0)


def fill_mover_meshes_from_skin(an, bones, skin, name_map):
    """Doors modeled as bare pivot EMPTIES (the big fridge) own no meshes;
    the close passes need the meshes the rig associates by name."""
    p_of = part_of_bone(bones)
    by_bone = {}
    for o in name_map.values():
        if o.type == "MESH" and o.name in skin:
            by_bone.setdefault(p_of.get(skin[o.name], "root"), []).append(o)
    for u in an["movers"]:
        bn = u.get("bone")
        if u["split"] or not bn:
            continue
        # UNION of subtree meshes and skin-associated meshes: door panels
        # may be name-associated while trays are parented under the empty
        # (or vice versa) -- the close must rotate ALL of them together
        have = {m.name for m in u["meshes"]}
        ms = [m for m in by_bone.get(bn, []) if m.name not in have]
        if not ms:
            continue
        u["meshes"] = u["meshes"] + ms
        u["objs"] = list(dict.fromkeys(u["objs"] + ms))
        u["mn"], u["mx"] = aabb([p for m in u["meshes"]
                                 for p in obj_points(m)])
        u["ctr"] = (u["mn"] + u["mx"]) / 2
        u["dim"] = u["mx"] - u["mn"]


def close_open_doors(an, name_map, notes):
    """Close posed-open doors on the work copy, most-improving door first.
    Greedy one-at-a-time matters: an open sibling door inflates the asset
    bounds, which would otherwise let already-closed doors drift outward
    'for free'. Once the genuinely open doors are shut, the remaining doors
    show no >2% improvement and stay put. Flip-down oven doors are
    unaffected (a Z-rotation only ever grows their bounds)."""
    all_meshes = [o for o in name_map.values() if o.type == "MESH"]
    doors = [u for u in an["movers"]
             if u["kind"] == "DOOR" and u["pivot"] is not None
             and u["obj"] is not None and not u["split"]]

    def carry_nested(u, rot):
        """Movers mounted ON u (egg lid on the fridge door) ride its close:
        rotate their meshes/empties and their pivots too."""
        stack, nested = [u], []
        while stack:
            cur = stack.pop()
            for v in an["movers"]:
                if v is not cur and v.get("parent_mover") is cur:
                    nested.append(v)
                    stack.append(v)
        for v in nested:
            # a nested mover that closes on its own (close_angle prop or
            # already closed) must NOT also inherit the parent's rotation
            if v.get("closed") or                     mover_cfg(v["orig"], v.get("obj")).get("close_angle") is not None:
                continue
            for ob in v.get("objs", []):
                p, carried = ob.parent, False
                while p is not None:
                    if p in v["objs"] or p in u["objs"]:
                        carried = True
                        break
                    p = p.parent
                if not carried:
                    ob.matrix_world = rot @ ob.matrix_world
            if v.get("pivot") is not None:
                v["pivot"] = rot @ v["pivot"]
            v["raw_pivot"] = rot @ v["raw_pivot"]
            if v["meshes"]:
                bpy.context.view_layer.update()
                v["mn"], v["mx"] = aabb([p for m in v["meshes"]
                                         for p in obj_points(m)])
                v["ctr"] = (v["mn"] + v["mx"]) / 2
                v["dim"] = v["mx"] - v["mn"]

    # Pass 0 — explicit override: rotate by OVERRIDES["close_angle"] as-is,
    # for doors whose geometry defeats the bounds metric (microwave_2's door
    # tucks into the open cavity at +89 with a smaller union volume than the
    # true +150 close).
    for u in doors:
        deg = mover_cfg(u["orig"], u["obj"]).get("close_angle")
        if deg is None:
            continue
        rot = (Matrix.Translation(u["pivot"]) @ Matrix.Rotation(radians(deg), 4, "Z")
               @ Matrix.Translation(-u["pivot"]))
        objs = u.get("objs", [u["obj"]])
        for ob in objs:
            p, carried = ob.parent, False
            while p is not None:
                if p in objs:
                    carried = True
                    break
                p = p.parent
            if not carried:
                ob.matrix_world = rot @ ob.matrix_world
        carry_nested(u, rot)
        bpy.context.view_layer.update()
        upts = [p for m in u["meshes"] for p in obj_points(m)]
        u["mn"], u["mx"] = aabb(upts)
        u["ctr"] = (u["mn"] + u["mx"]) / 2
        u["dim"] = u["mx"] - u["mn"]
        u["closed"] = True
        u["closed_by"] = float(deg)
        notes.append(f"closed '{u['orig']}' by {deg:+.0f} deg (override)")

    def flush_open_drawers():
        """Push posed-open DRAWERS back flush. Movers' front faces cluster
        on shared planes; a drawer ALONE on its own plane, sticking out past
        the plane other movers share, is pulled open. Must run after the
        door-alignment pass (an open door's front plane would capture the
        drawer's snap target) and before the trial pass (an open drawer
        masks the union bounds the trials rely on)."""
        fa = AI[an["front_axis"]]
        sign = an["front_sign"]
        fronts = []
        for u in an["movers"]:
            if u["obj"] is None or u["split"] or u["kind"] not in ("DOOR", "DRAWER"):
                continue
            fronts.append((u, u["mx"][fa] if sign > 0 else u["mn"][fa]))
        planes = []                         # [(coord, [users])]
        for u, f in fronts:
            for pl in planes:
                if abs(f - pl[0]) < 0.02:
                    pl[1].append(u)
                    break
            else:
                planes.append((f, [u]))
        for u, f in fronts:
            if u["kind"] != "DRAWER":
                continue
            mine = next(pl for pl in planes if u in pl[1])
            if len(mine[1]) > 1:            # shares a plane => already flush
                continue
            others = [pl for pl in planes if u not in pl[1]]
            if not others:
                continue
            target = min(others, key=lambda pl: abs(pl[0] - f))[0]
            shift = (target - f) * sign     # negative = push inward
            depth = u["dim"][fa] or 1e-6
            if not (-depth < shift < -0.03):
                continue
            off = Vector((0, 0, 0))
            off[fa] = target - f
            for ob in u["objs"]:
                ob.matrix_world = Matrix.Translation(off) @ ob.matrix_world
            bpy.context.view_layer.update()
            upts = [p for m in u["meshes"] for p in obj_points(m)]
            u["mn"], u["mx"] = aabb(upts)
            u["ctr"] = (u["mn"] + u["mx"]) / 2
            u["dim"] = u["mx"] - u["mn"]
            notes.append(f"pushed drawer '{u['orig']}' flush by {abs(shift):.3f} m")

    # Pass 1 — sibling-rotation clustering. When several same-asset doors
    # share one world rotation and a couple differ by a hinge-axis turn, the
    # majority IS the closed pose (bounds-based trials are blind here: two
    # open doors mask each other's improvement). Align the minority, but
    # only for pure Z-rotations that don't grow the asset's bounds (a legit
    # perpendicular corner door would grow them and is left alone).
    if len(doors) >= 3:
        quats = [(u["meshes"][0] if u["meshes"] else u["objs"][0])
                 .matrix_world.to_quaternion() for u in doors]
        clusters = []
        for i, q in enumerate(quats):
            for cl in clusters:
                if abs(q.rotation_difference(quats[cl[0]]).angle) < radians(10):
                    cl.append(i)
                    break
            else:
                clusters.append([i])
        clusters.sort(key=len, reverse=True)
        if len(clusters) > 1 and len(clusters[0]) > len(clusters[1]):
            q_major = quats[clusters[0][0]]
            for cl in clusters[1:]:
                for i in cl:
                    u = doors[i]
                    dq = q_major @ quats[i].inverted()
                    axis, ang = dq.axis, dq.angle
                    if abs(axis.z) < 0.95 or not radians(5) < ang < radians(150):
                        continue
                    deg = ang * 57.29578 * (1 if axis.z > 0 else -1)
                    rot = (Matrix.Translation(u["pivot"])
                           @ Matrix.Rotation(radians(deg), 4, "Z")
                           @ Matrix.Translation(-u["pivot"]))
                    other = [p for m in all_meshes for p in obj_points(m)
                             if m.name not in {x.name for x in u["meshes"]}]
                    door_pts = [p for m in u["meshes"] for p in obj_points(m)]
                    d0 = (lambda b: b[1] - b[0])(aabb(other + door_pts))
                    d1 = (lambda b: b[1] - b[0])(aabb(other + [rot @ p for p in door_pts]))
                    if d1.x * d1.y * d1.z > 1.001 * d0.x * d0.y * d0.z:
                        continue
                    for ob in u["objs"]:
                        ob.matrix_world = rot @ ob.matrix_world
                    bpy.context.view_layer.update()
                    upts = [p for m in u["meshes"] for p in obj_points(m)]
                    u["mn"], u["mx"] = aabb(upts)
                    u["ctr"] = (u["mn"] + u["mx"]) / 2
                    u["dim"] = u["mx"] - u["mn"]
                    u["closed"] = True
                    u["closed_by"] = float(deg)
                    notes.append(f"closed '{u['orig']}' by {deg:+.0f} deg "
                                 "(aligned to sibling doors)")

    # Pass 2 — drawers flush, then bounds-based trial for remaining doors
    flush_open_drawers()
    all_door_meshes = {m.name for d in doors for m in d["meshes"]}
    for _ in range(len(doors)):
        best = None
        for u in doors:
            if u.get("closed"):
                continue
            ang, ratio = _best_close_angle(u, all_meshes, all_door_meshes)
            if ang and ratio < 0.98 and (best is None or ratio < best[2]):
                best = (u, ang, ratio)
        if best is None:
            break
        u, ang, _ = best
        rot = (Matrix.Translation(u["pivot"]) @ Matrix.Rotation(radians(ang), 4, "Z")
               @ Matrix.Translation(-u["pivot"]))
        objs = u.get("objs", [u["obj"]])
        for ob in objs:                     # skip empties another one carries
            p, carried = ob.parent, False
            while p is not None:
                if p in objs:
                    carried = True
                    break
                p = p.parent
            if not carried:
                ob.matrix_world = rot @ ob.matrix_world
        carry_nested(u, rot)
        bpy.context.view_layer.update()
        upts = [p for m in u["meshes"] for p in obj_points(m)]
        u["mn"], u["mx"] = aabb(upts)
        u["ctr"] = (u["mn"] + u["mx"]) / 2
        u["dim"] = u["mx"] - u["mn"]
        u["closed"] = True
        u["closed_by"] = float(ang)
        notes.append(f"closed '{u['orig']}' by {ang:+d} deg about its hinge")
    # asset bounds may have shrunk
    pts = [p for m in all_meshes for p in obj_points(m)]
    an["cmn"], an["cmx"] = aabb(pts)
    an["cdim"] = an["cmx"] - an["cmn"]
    an["cctr"] = (an["cmn"] + an["cmx"]) / 2


# ===========================================================================
# bone computation
# ===========================================================================
def door_bone(u, an, notes):
    """Head/tail for a hinged door. With a real pivot the hinge passes
    through it: pivot near a width-extreme => vertical hinge (swing door);
    pivot near top/bottom + width-centre => horizontal hinge (oven door,
    flip lid). Without a pivot: vertical hinge on the outer edge."""
    dims = sorted([(u["dim"].x, "X"), (u["dim"].y, "Y"), (u["dim"].z, "Z")])
    thin = dims[0][1]
    if thin == "Z":                          # lying flat: face the smaller span
        thin = "X" if u["dim"].x < u["dim"].y else "Y"
    fa = AI[thin]
    wa = 1 - fa                              # the other horizontal axis
    wdim = u["dim"][wa] or 1e-6

    piv = u["pivot"]
    ov = mover_cfg(u["orig"], u.get("obj"))
    if piv is not None:
        dw = min(abs(piv[wa] - u["mn"][wa]), abs(piv[wa] - u["mx"][wa])) / wdim
        zdim = u["dim"].z or 1e-6
        dz = min(abs(piv.z - u["mn"].z), abs(piv.z - u["mx"].z)) / zdim
        if dw < 0.25:                        # vertical hinge through the pivot
            return (Vector((piv.x, piv.y, u["mn"].z)),
                    Vector((piv.x, piv.y, u["mx"].z)), "swing_vertical")
        if dz < 0.25:                        # horizontal hinge (flip door)
            head, tail = piv.copy(), piv.copy()
            head[wa], tail[wa] = u["mn"][wa], u["mx"][wa]
            return head, tail, "swing_horizontal"
        notes.append(f"'{u['orig']}': pivot not on an edge; vertical hinge at pivot")
        return (Vector((piv.x, piv.y, u["mn"].z)),
                Vector((piv.x, piv.y, u["mx"].z)), "swing_vertical")

    # no pivot: hinge on the cabinet-outer vertical edge (or override)
    wmin, wmax = u["mn"][wa], u["mx"][wa]
    if ov.get("hinge") == "MIN":
        hx = wmin
    elif ov.get("hinge") == "MAX":
        hx = wmax
    else:
        cc = an["cctr"][wa]
        hx = wmin if abs(wmin - cc) > abs(wmax - cc) else wmax
        notes.append(f"'{u['orig']}': no pivot; hinged on outer edge (override with 'hinge')")
    head = Vector((0, 0, 0))
    head[wa] = hx
    head[fa] = u["ctr"][fa]
    head.z = u["mn"].z
    tail = head.copy()
    tail.z = u["mx"].z
    return head, tail, "swing_vertical"


def drawer_bone(u, an):
    fa = AI[an["front_axis"]]
    sign = an["front_sign"]
    front_face = u["mx"][fa] if sign > 0 else u["mn"][fa]
    head = u["ctr"].copy()
    head[fa] = front_face
    tail = head.copy()
    tail[fa] = front_face + sign * max(an["cdim"][fa] * 0.25, 0.03)
    return head, tail


def bar_meshes(meshes, maxh):
    """Bar-shaped (handle) meshes among a mover's meshes."""
    out = []
    for m in meshes:
        mn, mx = aabb(obj_points(m))
        dd = sorted(mx - mn)
        if dd[0] < 0.04 and dd[1] < 0.08 and dd[2] < 0.5 * maxh:
            out.append((m, mn, mx))
    return out


def split_slide_units(u, maxh):
    """Explode a split_meshes mover: each non-bar mesh child is a sliding
    pane; bar meshes become handles attached to the nearest pane."""
    meshes = [o for o in [u["obj"]] + descendants(u["obj"]) if o.type == "MESH"]
    panes, bars = [], []
    for m in meshes:
        mn, mx = aabb(obj_points(m))
        dd = sorted(mx - mn)
        if dd[0] < 0.04 and dd[1] < 0.08 and dd[2] < 0.5 * maxh:
            bars.append((m, (mn + mx) / 2))
        else:
            panes.append(dict(obj=m, mn=mn, mx=mx, ctr=(mn + mx) / 2, bars=[]))
    for m, c in bars:
        if panes:
            min(panes, key=lambda p: (p["ctr"] - c).length)["bars"].append(m)
    return panes


def compute_rig(an, name_map, notes, split_panes=True, reuse_skin=None):
    """Bones (world space) + skin map {copy_mesh_name: bone} + vertex-group
    renames for pre-skinned meshes."""
    cmn, cctr, cdim = an["cmn"], an["cctr"], an["cdim"]
    up = max(cdim.z * 0.12, 0.02)
    bones = [dict(name="root", head=Vector((cctr.x, cctr.y, cmn.z)),
                  tail=Vector((cctr.x, cctr.y, cmn.z + up)), parent=None)]
    skin = {}                               # copy-object name -> bone name
    group_rename = {}                       # (mesh copy name, old vg) -> new vg
    counters = {"DOOR": 0, "DRAWER": 0, "DOOR_SLIDE": 0}
    prefix = {"DOOR": "door", "DRAWER": "drawer", "DOOR_SLIDE": "slide"}
    mover_bone = {}

    # parents before children so a nested mover can reference its parent bone
    movers = [u for u in an["movers"] if u["parent_mover"] is None] + \
             [u for u in an["movers"] if u["parent_mover"] is not None]

    for u in movers:
        if u["split"]:
            continue                        # handled below (slide panes)
        counters[u["kind"]] += 1
        bn = f"{prefix[u['kind']]}_{counters[u['kind']]}"
        if u["kind"] == "DOOR":
            head, tail, u["motion"] = door_bone(u, an, notes)
        elif u["kind"] == "DOOR_SLIDE":
            # sliding pane: prismatic ALONG its width (drawer_bone would
            # point it out the front)
            wa = 0 if u["dim"].x >= u["dim"].y else 1
            head = u["ctr"].copy()
            tail = head.copy()
            tail[wa] += max(0.25 * u["dim"][wa], 0.05)
            u["motion"] = "slide"
        else:
            head, tail = drawer_bone(u, an)
            u["motion"] = "slide"
        parent = mover_bone.get(id(u["parent_mover"]), "root") if u["parent_mover"] else "root"
        bones.append(dict(name=bn, head=head, tail=tail, parent=parent))
        mover_bone[id(u)] = bn
        u["bone"] = bn

        if u.get("users"):                  # pre-skinned (harvested bone)
            for k, o, _ in u["users"]:
                group_rename[(o.name, u["group"])] = bn
            continue

        # handle peel: bar meshes get their own bone for a graspable body
        hb = bar_meshes(u["meshes"], an["maxh"])
        peel = {m.name for m, _, _ in hb} if len(hb) < len(u["meshes"]) else set()
        for m in u["meshes"]:
            skin[m.name] = bn
        k = 0
        for m, mn, mx in hb:
            if m.name not in peel:
                continue
            k += 1
            hbn = f"{bn}_handle" if len(peel) == 1 else f"{bn}_handle_{k}"
            c = (mn + mx) / 2
            ax = max(range(3), key=lambda i: (mx - mn)[i])
            h, t = c.copy(), c.copy()
            h[ax], t[ax] = mn[ax], mx[ax]
            if (t - h).length < 1e-4:
                t = h + Vector((0, 0, 0.02))
            bones.append(dict(name=hbn, head=h, tail=t, parent=bn))
            skin[m.name] = hbn

    # sliding panes (split_meshes movers; physically splits the mesh, so
    # the preliminary rig pass skips it)
    for u in [u for u in an["movers"] if u["split"] and split_panes]:
        for pane in split_slide_units(u, an["maxh"]):
            counters["DOOR_SLIDE"] += 1
            bn = f"slide_{counters['DOOR_SLIDE']}"
            dim = pane["mx"] - pane["mn"]
            ax = 0 if dim.x >= dim.y else 1          # slide along its width
            head = pane["ctr"].copy()
            tail = head.copy()
            tail[ax] += max(0.25 * dim[ax], 0.05)
            bones.append(dict(name=bn, head=head, tail=tail, parent="root"))
            skin[pane["obj"].name] = bn
            for b in pane["bars"]:
                skin[b.name] = bn
        u["bone"] = "(split into slide bones)"
        u["motion"] = "slide"

    # statics: mover-subtree membership first, then name association, then root
    movers_flat = [u for u in an["movers"]
                   if not u["split"] and u.get("bone") and u["obj"] is not None]
    copy_to_orig = {o.name: orig for orig, o in name_map.items()}

    def associate(obj):
        p = obj
        while p is not None:                # 1) inside a mover's subtree?
            for u in movers_flat:
                if u["obj"] is p:
                    return u["bone"], None
            p = p.parent
        omn, omx = aabb(obj_points(obj))
        # walk name candidates upward: meshes are often 'defaultMaterial.NNN'
        # and only the parent part-empty carries a meaningful name
        names, p = [], obj
        while p is not None:
            if p.name in copy_to_orig:
                names.append((base_name(copy_to_orig[p.name]), p))
            p = p.parent
        for nm, nobj in names:
            ov = mover_cfg(nm, nobj)
            if "bone_of" in ov:
                for u in movers_flat:
                    if base_name(u["orig"]) == ov["bone_of"]:
                        return u["bone"], f"override bone_of -> {u['orig']}"
            # 2) static named as a SPECIALIZATION of a mover it touches
            # (mover base name + suffix: FridgeUpperDoorGlass -> the
            # FridgeUpperDoor mover). Common-prefix scoring is NOT enough:
            # 'Microwave' scored 0.64 against its own door 'Microwave_door'
            # and welded the whole body (and five fridges' bodies) to it.
            for u in sorted(movers_flat,
                            key=lambda u: -len(base_name(u["orig"]))):
                ub = base_name(u["orig"])
                if nm != ub and nm.startswith(ub) \
                        and bbox_gap(omn, omx, u["mn"], u["mx"]) < 0.08:
                    return u["bone"], f"name prefix -> {u['orig']}"
            # 3) door/drawer token in a static's name -> nearest such mover
            for pat, kind in ((PAT_DOOR, "DOOR"), (PAT_DRAWER, "DRAWER")):
                if not pat.search(nm):
                    continue
                cands = [u for u in movers_flat if u["kind"] == kind
                         and bbox_gap(omn, omx, u["mn"], u["mx"]) < 0.15]
                if cands:
                    octr = (omn + omx) / 2
                    u = min(cands, key=lambda u: (u["ctr"] - octr).length)
                    return u["bone"], f"'{kind.lower()}' in name -> {u['orig']}"
            # 3b) handles/knobs/pulls attach to the nearest mover they touch
            # (microwave_3's part empty is literally named 'Handle')
            if PAT_HANDLE.search(nm):
                cands = [u for u in movers_flat
                         if bbox_gap(omn, omx, u["mn"], u["mx"]) < 0.15]
                if cands:
                    octr = (omn + omx) / 2
                    u = min(cands, key=lambda u: (u["ctr"] - octr).length)
                    return u["bone"], f"handle name -> {u['orig']}"
        return "root", None

    if reuse_skin:
        known = {b["name"] for b in bones}
        for mname, bone in reuse_skin.items():
            if mname not in skin and bone in known:
                skin[mname] = bone
    for orig, obj in name_map.items():
        if obj.type != "MESH" or obj.name in skin:
            continue
        bone, why = associate(obj)
        skin[obj.name] = bone
        if why:
            notes.append(f"static '{orig}' -> bone {bone} ({why})")

    return bones, skin, group_rename


# ===========================================================================
# flatten / normals  (from the original script)
# ===========================================================================
def flatten_meshes(name_map, center_base):
    """Detach parenting, bake transforms into geometry, recentre on the
    asset's center-base. Skinned-mesh FBX export needs identity transforms
    (the FBX exporter drops matrix_parent_inverse on skinned meshes)."""
    meshes = [o for o in name_map.values() if o.type == "MESH"]
    if not meshes:
        return
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for m in meshes:
        m.location = -center_base
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)


def fix_normals(name_map):
    """Recalculate outward normals on inside-out (negative signed volume)
    meshes; leaves planes (zero volume, e.g. glass panes) untouched."""
    for o in name_map.values():
        if o.type != "MESH" or not len(o.data.polygons):
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        vol = 0.0
        for f in bm.faces:
            v = f.verts
            vol += v[0].co.dot(v[1].co.cross(v[2].co)) / 6.0
        bm.free()
        if vol < -1e-9:
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
            bm.to_mesh(o.data)
            bm.free()
            o.data.update()


# ===========================================================================
# armature build + skin  (extended for pre-skinned meshes)
# ===========================================================================
def build_armature(name, bones, skin, name_map, center_base, group_rename,
                   preskinned, visualize=False):
    arm_data = bpy.data.armatures.new(name + "_arm")
    arm_obj = bpy.data.objects.new(name + "_Armature", arm_data)
    bpy.context.scene.collection.objects.link(arm_obj)
    arm_obj.location = (0.0, 0.0, 0.0)
    arm_obj.show_in_front = True

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_data.edit_bones
    made = {}
    for b in bones:
        bone = eb.new(b["name"])
        bone.head = b["head"] - center_base
        bone.tail = b["tail"] - center_base
        bone.use_deform = True
        made[b["name"]] = bone
    for b in bones:
        if b["parent"]:
            made[b["name"]].parent = made[b["parent"]]
            made[b["name"]].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")

    if visualize:
        for b in bones:
            e = bpy.data.objects.new("PIV_" + b["name"], None)
            e.empty_display_type = "ARROWS"
            e.empty_display_size = 0.08
            e.location = b["head"] - center_base
            bpy.context.scene.collection.objects.link(e)

    meshes = [o for o in name_map.values() if o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.parent_set(type="ARMATURE")

    # rename harvested vertex groups to our bone names
    for (mesh_name, old), new in group_rename.items():
        o = bpy.data.objects.get(mesh_name)
        g = o.vertex_groups.get(old) if o else None
        if g:
            g.name = new

    for orig, obj in name_map.items():
        if obj.type != "MESH":
            continue
        if orig in preskinned:
            continue                        # keeps its per-vertex weights
        bone = skin.get(obj.name, "root")
        vg = obj.vertex_groups.get(bone) or obj.vertex_groups.new(name=bone)
        vg.add(range(len(obj.data.vertices)), 1.0, "REPLACE")

    return arm_obj


# ===========================================================================
# export  (from the original script)
# ===========================================================================
def joint_specs(an, bones, center_base):
    """Engine-neutral joint spec per mover bone, positions relative to
    center_base (pass a zero vector for scene/world space). Handle bones are
    fixed welds and get no joint. {bone: {type, axis, pivot, limits,
    parent}}; limits are degrees (revolute) or meters (prismatic), signed so
    positive motion opens AWAY from the asset front."""
    bone_by = {b["name"]: b for b in bones}
    u_by_bone = {u.get("bone"): u for u in an["movers"] if u.get("bone")}
    fa, fs = AI[an["front_axis"]], an["front_sign"]
    joints = {}
    for b in bones:
        bn = b["name"]
        if bn == "root" or "_handle" in bn:
            continue
        head = Vector(b["head"]) - center_base
        tail = Vector(b["tail"]) - center_base
        axis = tail - head
        axis = axis.normalized() if axis.length > 1e-8 else Vector((0, 0, 1))
        u = u_by_bone.get(bn)
        cfg = mover_cfg(u["orig"], u.get("obj")) if u else {}
        if cfg.get("axis"):
            axis = Vector(cfg["axis"]).normalized()
        prismatic = bn.startswith(("drawer", "slide")) or \
            (u is not None and u.get("motion") == "slide")
        if prismatic:
            if u is not None and not u.get("split"):
                travel = 0.8 * sum(abs(u["dim"][i] * axis[i]) for i in range(3))
            else:                       # split slide pane: bone len = w/4
                travel = 2.0 * (tail - head).length
            limits = [0.0, round(max(travel, 0.05), 4)]
            jtype = "prismatic"
        else:
            jtype = "revolute"
            limits = [0.0, 120.0]
            cb = u.get("closed_by") if u is not None else None
            if cb:
                # the door was auto-closed by cb degrees, so it OPENS the
                # other way -- the most reliable sign source there is
                limits = [0.0, 120.0] if cb < 0 else [-120.0, 0.0]
            elif u is not None:
                # heuristic: +20 deg should move the door centre OUT the
                # front; otherwise the hinge opens the other way
                c = (Vector(u["ctr"]) - center_base) - head
                gain = ((Matrix.Rotation(radians(20), 3, axis) @ c) - c)[fa] * fs
                if gain < 0:
                    limits = [-120.0, 0.0]
        if cfg.get("limits"):
            limits = [float(x) for x in cfg["limits"]]
        joints[bn] = {"type": jtype,
                      "axis": [round(v, 4) for v in axis],
                      "pivot": [round(v, 4) for v in head],
                      "limits": limits,
                      "parent": b.get("parent") or "root"}
    return joints


def export_fbx(arm_obj, meshes, filepath):
    bpy.ops.object.select_all(action="DESELECT")
    arm_obj.select_set(True)
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=filepath,
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        use_armature_deform_only=True,
        add_leaf_bones=CONFIG["add_leaf_bones"],
        bake_anim=False,
        mesh_smooth_type="FACE",
        use_mesh_modifiers=True,
        apply_unit_scale=CONFIG["apply_unit_scale"],
        global_scale=CONFIG["global_scale"],
        # FBX_SCALE_UNITS puts the m->cm factor into the FBX unit header.
        # FBX_SCALE_NONE writes it as local scale 100 on the armature node,
        # which UE turns into a scale-100 root body that breaks physics
        # asset / collision generation.
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward=CONFIG["axis_forward"],
        axis_up=CONFIG["axis_up"],
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        path_mode=CONFIG["path_mode"],
        embed_textures=CONFIG["embed_textures"],
    )


# ===========================================================================
# static-parts export  (rigid part FBXs + UCX collision + USD + MJCF)
# ===========================================================================
def part_of_bone(bones):
    """bone name -> rigid part name. Handle bones are fixed welds, so they
    collapse into their parent mover's part."""
    parent = {b["name"]: b.get("parent") for b in bones}
    out = {}
    for b in bones:
        bn = b["name"]
        while "_handle" in bn:
            bn = parent.get(bn) or "root"
        out[b["name"]] = bn
    return out


def island_boxes(obj):
    """Deduped AABBs [(center, size)] of the mesh's connected islands, in
    LOCAL space, largest first. This furniture is panel-built, so per-island
    boxes are a near-perfect convex decomposition: a drawer becomes bottom +
    four walls -- a container that can actually hold objects."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    seen, boxes = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, isl = [v], set()
        while stack:
            u = stack.pop()
            if u.index in isl:
                continue
            isl.add(u.index)
            for e in u.link_edges:
                w = e.other_vert(u)
                if w.index not in isl:
                    stack.append(w)
        seen |= isl
        mn, mx = aabb([bm.verts[i].co for i in isl])
        boxes.append(((mn + mx) / 2, mx - mn))
    bm.free()
    ms = CONFIG["ucx_min_size"]
    padded = [(c, Vector((max(s.x, ms), max(s.y, ms), max(s.z, ms))))
              for c, s in boxes]
    zmin = min((c.z - s.z / 2) for c, s in padded) if padded else 0.0
    out, keys = [], set()
    for c, s in padded:
        # islands touching the part's bottom are FEET -- support-critical,
        # exempt from the dust filter and sorted first so the cap keeps them
        foot = (c.z - s.z / 2) <= zmin + 0.02
        if not foot and s.x * s.y * s.z < CONFIG["ucx_dust_volume"]:
            continue                        # physically irrelevant junk
        key = tuple(round(v, 3) for v in (*c, *s))
        if key in keys:                     # coincident duplicate shells
            continue
        keys.add(key)
        out.append((foot, c, s))
    out.sort(key=lambda t: (not t[0], -(t[2].x * t[2].y * t[2].z)))
    return [(c, s) for _, c, s in out]


def make_ucx(name, boxes, coll):
    """UCX_<name>_## box meshes (UE FBX collision convention)."""
    objs = []
    for i, (c, s) in enumerate(boxes):
        me = bpy.data.meshes.new(f"UCX_{name}_{i:02d}")
        h = s / 2
        vs = [(c.x + dx * h.x, c.y + dy * h.y, c.z + dz * h.z)
              for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)]
        me.from_pydata(vs, [], [(0, 1, 3, 2), (4, 6, 7, 5), (0, 2, 6, 4),
                                (1, 5, 7, 3), (0, 4, 5, 1), (2, 3, 7, 6)])
        ob = bpy.data.objects.new(me.name, me)
        coll.objects.link(ob)
        objs.append(ob)
    return objs


def export_fbx_static(objs, filepath):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=filepath,
        use_selection=True,
        object_types={"MESH"},
        bake_anim=False,
        mesh_smooth_type="FACE",
        use_mesh_modifiers=True,
        apply_unit_scale=CONFIG["apply_unit_scale"],
        global_scale=CONFIG["global_scale"],
        apply_scale_options="FBX_SCALE_UNITS",
        axis_forward=CONFIG["axis_forward"],
        axis_up=CONFIG["axis_up"],
        path_mode=CONFIG["path_mode"],
        embed_textures=CONFIG["embed_textures"],
    )


def _preskin_bone_map(o, group_rename):
    """vertex-group index -> part bone for a pre-skinned mesh. Renamed
    groups map to their mover bone; the merged 'root' group counts as root
    (ignoring it made every slightly-door-weighted mesh join the door)."""
    idx_to_bone = {}
    for vg in o.vertex_groups:
        bn = group_rename.get((o.name, vg.name))
        if bn:
            idx_to_bone[vg.index] = bn
        elif vg.name == "root":
            idx_to_bone[vg.index] = "root"
    return idx_to_bone


def dominant_bone(o, group_rename):
    """Part bone of a pre-skinned mesh: the vertex group carrying the most
    total weight (static parts need a hard assignment)."""
    idx_to_bone = _preskin_bone_map(o, group_rename)
    if not any(b != "root" for b in idx_to_bone.values()):
        return None
    tally = {}
    for v in o.data.vertices:
        for g in v.groups:
            bn = idx_to_bone.get(g.group)
            if bn:
                tally[bn] = tally.get(bn, 0.0) + g.weight
    return max(tally, key=tally.get) if tally else None


def split_preskinned_by_bone(o, group_rename, notes):
    """A pre-skinned mesh whose weights span SEVERAL part bones (the old
    microwave: one mesh holds body(n4) + door(n5) faces) must be split so
    each rigid part gets its own faces. Faces move by per-face majority of
    their verts' dominant groups. Returns {object_name: bone} for the
    resulting objects (o keeps the majority bone's faces)."""
    idx_to_bone = _preskin_bone_map(o, group_rename)
    if len({b for b in idx_to_bone.values()}) < 2:
        return None
    vb = {}
    for v in o.data.vertices:
        best, bw = None, 0.0
        for g in v.groups:
            bn = idx_to_bone.get(g.group)
            if bn is not None and g.weight > bw:
                best, bw = bn, g.weight
        vb[v.index] = best
    face_bone = {}
    counts = {}
    for p in o.data.polygons:
        tal = {}
        for vi in p.vertices:
            bn = vb.get(vi)
            if bn:
                tal[bn] = tal.get(bn, 0) + 1
        fb = max(tal, key=tal.get) if tal else "root"
        face_bone[p.index] = fb
        counts[fb] = counts.get(fb, 0) + 1
    if len(counts) < 2:
        return None
    major = max(counts, key=counts.get)
    forced = {}
    for bone in [b for b in counts if b != major]:
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for p in o.data.polygons:
            p.select = face_bone.get(p.index) == bone
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.separate(type="SELECTED")
        bpy.ops.object.mode_set(mode="OBJECT")
        newo = next(x for x in bpy.context.selected_objects if x is not o)
        forced[newo.name] = bone
        # face indices shift after separation: recompute for the remainder
        remaining = [i for i, p in enumerate(o.data.polygons)]
        face_bone = {}
        vb2 = {}
        for v in o.data.vertices:
            best, bw = None, 0.0
            for g in v.groups:
                bn = idx_to_bone.get(g.group)
                if bn is not None and g.weight > bw:
                    best, bw = bn, g.weight
            vb2[v.index] = best
        for p in o.data.polygons:
            tal = {}
            for vi in p.vertices:
                bn = vb2.get(vi)
                if bn:
                    tal[bn] = tal.get(bn, 0) + 1
            face_bone[p.index] = max(tal, key=tal.get) if tal else major
        notes.append(f"pre-skinned mesh split: {len(forced)} extra part(s) "
                     f"from '{o.name}'")
    forced[o.name] = major
    return forced


def part_masses(an, asset, bones):
    """{part: mass_kg} from dojo_mass custom properties: a mover's mass
    lives on its part empty/mesh; the root part's mass on any of the
    asset's top-level nodes."""
    p_of = part_of_bone(bones)
    masses = {}
    for u in an["movers"]:
        bn = u.get("bone")
        if not bn:
            continue
        m = mover_cfg(u["orig"], u.get("obj")).get("mass")
        if m is not None:
            masses[p_of.get(bn, "root")] = float(m)
    for node in asset["nodes"]:
        src = bpy.data.objects.get(node.name) or node
        m = src.get("dojo_mass")
        if m is not None:
            masses["root"] = float(m)
            break
    return masses


def export_static_parts(nm, folder, bones, skin, joints, name_map,
                        group_rename, notes, masses=None):
    """Join each rigid part's meshes, shift the part origin onto its joint
    pivot, generate UCX island boxes, export one static FBX per part.
    Returns (parts_manifest, {part: joined_object})."""
    p_of = part_of_bone(bones)
    meshes_in = [o for o in name_map.values()
                 if o.type == "MESH" and len(o.data.polygons)]
    forced_bone = {}
    for o in list(meshes_in):
        forced = split_preskinned_by_bone(o, group_rename, notes)
        if forced:
            forced_bone.update(forced)
            for nm2 in forced:
                ob2 = bpy.data.objects.get(nm2)
                if ob2 is not None and ob2 not in meshes_in:
                    meshes_in.append(ob2)
    groups = {}
    for o in meshes_in:
        bone = forced_bone.get(o.name) or dominant_bone(o, group_rename) \
            or skin.get(o.name) or "root"
        groups.setdefault(p_of.get(bone, "root"), []).append(o)

    work = ensure_collection("EXPORT_WORK")
    parts, part_objs = {}, {}
    for part, objs in sorted(groups.items()):
        bpy.ops.object.select_all(action="DESELECT")
        for o in objs:
            o.select_set(True)
        bpy.context.view_layer.objects.active = objs[0]
        if len(objs) > 1:
            bpy.ops.object.join()
        joined = bpy.context.view_layer.objects.active
        joined.name = f"{nm}__{part}"
        joined.data.name = joined.name
        piv = Vector(joints[part]["pivot"]) if part in joints \
            else Vector((0.0, 0.0, 0.0))
        if piv.length > 1e-9:               # part origin = joint pivot
            joined.data.transform(Matrix.Translation(-piv))
            joined.data.update()
        boxes = island_boxes(joined)
        if len(boxes) > CONFIG["ucx_max_boxes"]:
            notes.append(f"part {part}: dropped "
                         f"{len(boxes) - CONFIG['ucx_max_boxes']} smallest "
                         "collision islands (ucx_max_boxes)")
            boxes = boxes[:CONFIG["ucx_max_boxes"]]
        ucx = make_ucx(joined.name, boxes, work)
        fp = os.path.join(folder, f"{nm}__{part}.fbx")
        export_fbx_static([joined] + ucx, fp)
        for o in ucx:
            bpy.data.objects.remove(o, do_unlink=True)
        parts[part] = {
            "fbx": os.path.basename(fp),
            "origin": [round(v, 4) for v in piv],
            "mass": (masses or {}).get(part),
            "joint": joints.get(part),
            "collision_boxes": [[[round(v, 4) for v in c],
                                 [round(v, 4) for v in s]] for c, s in boxes],
        }
        part_objs[part] = joined
    return parts, part_objs


def write_usd(nm, folder, parts, part_objs, baked_info, notes):
    """Author <asset>.usda: rigid bodies + box colliders + revolute/
    prismatic joints with limits (UsdPhysics), render meshes with
    UsdPreviewSurface materials fed by the baked BaseColor/ORM/Normal."""
    try:
        from pxr import Usd, UsdGeom, UsdShade, UsdPhysics, Sdf, Gf
    except Exception as e:                  # pxr missing in this Blender
        notes.append("usd emit skipped: " + repr(e))
        return None
    fp = os.path.join(folder, nm + ".usda")
    if os.path.exists(fp):
        os.remove(fp)
    stage = Usd.Stage.CreateNew(fp)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/" + nm)
    stage.SetDefaultPrim(root.GetPrim())
    UsdPhysics.ArticulationRootAPI.Apply(root.GetPrim())

    # materials (shared by all parts)
    mat_prims = {}
    for g, info in (baked_info or {}).items():
        mp = f"/{nm}/materials/{safe_name(g)}"
        mat = UsdShade.Material.Define(stage, mp)
        sh = UsdShade.Shader.Define(stage, mp + "/pbr")
        sh.CreateIdAttr("UsdPreviewSurface")
        tex = info.get("textures", {})

        def reader(tag, fname, srgb):
            t = UsdShade.Shader.Define(stage, f"{mp}/{tag}")
            t.CreateIdAttr("UsdUVTexture")
            t.CreateInput("file", Sdf.ValueTypeNames.Asset).Set("./" + fname)
            t.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set(
                "sRGB" if srgb else "raw")
            return t

        if tex.get("BaseColor"):
            t = reader("base", tex["BaseColor"], True)
            sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f
                           ).ConnectToSource(t.CreateOutput(
                               "rgb", Sdf.ValueTypeNames.Float3))
            if info.get("masked"):
                sh.CreateInput("opacity", Sdf.ValueTypeNames.Float
                               ).ConnectToSource(t.CreateOutput(
                                   "a", Sdf.ValueTypeNames.Float))
                sh.CreateInput("opacityThreshold",
                               Sdf.ValueTypeNames.Float).Set(0.5)
        if tex.get("ORM"):
            t = reader("orm", tex["ORM"], False)
            sh.CreateInput("roughness", Sdf.ValueTypeNames.Float
                           ).ConnectToSource(t.CreateOutput(
                               "g", Sdf.ValueTypeNames.Float))
            sh.CreateInput("metallic", Sdf.ValueTypeNames.Float
                           ).ConnectToSource(t.CreateOutput(
                               "b", Sdf.ValueTypeNames.Float))
        if info.get("translucent"):
            sh.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(0.35)
        mat.CreateSurfaceOutput().ConnectToSource(
            sh.CreateOutput("surface", Sdf.ValueTypeNames.Token))
        mat_prims[info.get("slot", g)] = mat

    body_path = {p: f"/{nm}/{safe_name(p)}" for p in parts}
    for part, entry in parts.items():
        x = UsdGeom.Xform.Define(stage, body_path[part])
        UsdPhysics.RigidBodyAPI.Apply(x.GetPrim())
        if entry.get("mass"):
            UsdPhysics.MassAPI.Apply(x.GetPrim()).CreateMassAttr(
                float(entry["mass"]))
        x.AddTranslateOp().Set(Gf.Vec3d(*entry["origin"]))

        # render mesh (visual only -- no collision API)
        o = part_objs[part]
        me = o.data
        mesh = UsdGeom.Mesh.Define(stage, body_path[part] + "/render")
        mesh.CreatePointsAttr([Gf.Vec3f(*v.co) for v in me.vertices])
        mesh.CreateFaceVertexCountsAttr([p.loop_total for p in me.polygons])
        mesh.CreateFaceVertexIndicesAttr(
            [me.loops[li].vertex_index for li in range(len(me.loops))])
        if me.uv_layers.active:
            uvd = me.uv_layers.active.data
            pv = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
                "st", Sdf.ValueTypeNames.TexCoord2fArray,
                UsdGeom.Tokens.faceVarying)
            pv.Set([Gf.Vec2f(*uvd[li].uv) for li in range(len(me.loops))])
        # material binding via GeomSubsets (joined parts are multi-material)
        for si, slot in enumerate(me.materials):
            if slot is None or slot.name not in mat_prims:
                continue
            faces = [p.index for p in me.polygons if p.material_index == si]
            if not faces:
                continue
            sub = UsdGeom.Subset.CreateGeomSubset(
                mesh, safe_name(slot.name), UsdGeom.Tokens.face, faces,
                "materialBind")
            UsdShade.MaterialBindingAPI.Apply(sub.GetPrim()).Bind(
                mat_prims[slot.name])

        for i, (c, s) in enumerate(entry["collision_boxes"]):
            cp = body_path[part] + f"/col_{i:02d}"
            cube = UsdGeom.Cube.Define(stage, cp)
            cube.GetSizeAttr().Set(1.0)
            cx = UsdGeom.Xformable(cube.GetPrim())
            cx.AddTranslateOp().Set(Gf.Vec3d(*c))
            cx.AddScaleOp().Set(Gf.Vec3f(*s))
            UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
            cube.CreatePurposeAttr(UsdGeom.Tokens.guide)  # not rendered

    for part, entry in parts.items():
        j = entry.get("joint")
        if not j:
            continue
        cls = UsdPhysics.RevoluteJoint if j["type"] == "revolute" \
            else UsdPhysics.PrismaticJoint
        joint = cls.Define(stage, f"/{nm}/joints/{safe_name(part)}")
        parent = j["parent"] if j["parent"] in parts else "root"
        joint.CreateBody0Rel().SetTargets([body_path[parent]])
        joint.CreateBody1Rel().SetTargets([body_path[part]])
        o0 = Vector(parts[parent]["origin"])
        piv = Vector(entry["origin"])
        joint.CreateLocalPos0Attr().Set(Gf.Vec3f(*(piv - o0)))
        joint.CreateLocalPos1Attr().Set(Gf.Vec3f(0, 0, 0))
        a = Vector(j["axis"])
        dom = max(range(3), key=lambda i: abs(a[i]))
        if abs(a[dom]) < 0.98:
            notes.append(f"{part}: joint axis {j['axis']} snapped to "
                         f"{'XYZ'[dom]} in USD/MJCF")
        lo, hi = float(j["limits"][0]), float(j["limits"][1])
        if a[dom] < 0:                      # snapped to the negative axis
            lo, hi = -hi, -lo
        joint.CreateAxisAttr().Set("XYZ"[dom])
        joint.CreateLowerLimitAttr().Set(lo)
        joint.CreateUpperLimitAttr().Set(hi)

    stage.GetRootLayer().Save()
    return fp


def write_mjcf(nm, folder, parts, part_objs, notes):
    """Author <asset>_mjcf.xml plus one OBJ per part: bodies + box collision
    geoms + hinge/slide joints with ranges; the OBJ meshes are visual-only
    geoms (contype 0). Degrees + meters, Z up -- MuJoCo native."""
    import xml.etree.ElementTree as ET
    objdir = folder
    for part, o in part_objs.items():
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.wm.obj_export(
            filepath=os.path.join(objdir, f"{nm}__{part}.obj"),
            export_selected_objects=True, export_materials=False,
            forward_axis="Y", up_axis="Z", apply_modifiers=True)

    mj = ET.Element("mujoco", model=nm)
    ET.SubElement(mj, "compiler", angle="degree", meshdir=".", texturedir=".")
    asset = ET.SubElement(mj, "asset")
    for part in parts:
        ET.SubElement(asset, "mesh", name=f"{nm}__{part}",
                      file=f"{nm}__{part}.obj")
    wb = ET.SubElement(mj, "worldbody")

    children = {}
    for part, entry in parts.items():
        j = entry.get("joint")
        parent = (j["parent"] if j and j["parent"] in parts else "root") \
            if part != "root" else None
        children.setdefault(parent, []).append(part)

    def emit(parent_el, part, parent_origin):
        entry = parts[part]
        org = Vector(entry["origin"])
        rel = org - parent_origin
        body = ET.SubElement(parent_el, "body", name=part,
                             pos=f"{rel.x:.4f} {rel.y:.4f} {rel.z:.4f}")
        if entry.get("mass"):
            bmn = [min(c[i] - sz[i] / 2 for c, sz in entry["collision_boxes"])
                   for i in range(3)]
            bmx = [max(c[i] + sz[i] / 2 for c, sz in entry["collision_boxes"])
                   for i in range(3)]
            m = float(entry["mass"])
            d = [max(bmx[i] - bmn[i], 1e-3) for i in range(3)]
            ctr = [(bmx[i] + bmn[i]) / 2 for i in range(3)]
            iner = [m / 12.0 * (d[(i + 1) % 3] ** 2 + d[(i + 2) % 3] ** 2)
                    for i in range(3)]
            ET.SubElement(body, "inertial",
                          pos=f"{ctr[0]:.4f} {ctr[1]:.4f} {ctr[2]:.4f}",
                          mass=f"{m:.4f}",
                          diaginertia=f"{iner[0]:.6f} {iner[1]:.6f} {iner[2]:.6f}")
        j = entry.get("joint")
        if j:
            a = Vector(j["axis"])
            lo, hi = j["limits"]
            ET.SubElement(body, "joint", name=part,
                          type="hinge" if j["type"] == "revolute" else "slide",
                          pos="0 0 0",
                          axis=f"{a.x:.4f} {a.y:.4f} {a.z:.4f}",
                          range=f"{lo:.4f} {hi:.4f}", limited="true",
                          damping="0.5")
        ET.SubElement(body, "geom", type="mesh", mesh=f"{nm}__{part}",
                      contype="0", conaffinity="0", group="2",
                      rgba="0.75 0.75 0.75 1")
        for c, s in entry["collision_boxes"]:
            ET.SubElement(body, "geom", type="box",
                          pos=f"{c[0]:.4f} {c[1]:.4f} {c[2]:.4f}",
                          size=f"{max(s[0]/2, 1e-3):.4f} "
                               f"{max(s[1]/2, 1e-3):.4f} "
                               f"{max(s[2]/2, 1e-3):.4f}")
        for ch in children.get(part, []):
            emit(body, ch, org)

    emit(wb, "root", Vector((0.0, 0.0, 0.0)))
    ET.indent(mj)
    fp = os.path.join(folder, nm + "_mjcf.xml")
    ET.ElementTree(mj).write(fp, encoding="unicode", xml_declaration=False)
    return fp


# ===========================================================================
# material baking  (ported from kitchen_skeletal_export.py)
# ===========================================================================
def norm_group(mat_name):
    """Material-group key for a source material: strip Blender's .NNN copy
    suffix, run CONFIG['material_group_aliases'], sanitize for filenames."""
    base = re.sub(r"\.\d+$", "", mat_name)
    for pat, grp in CONFIG["material_group_aliases"]:
        if re.search(pat, base):
            base = grp
            break
    return safe_name(base) or "Default"


def mat_is_translucent(mat):
    """Should this source material get a translucent shader in UE? (The bake
    flattens everything to opaque, so the tag travels via the manifest.)
    Name check is on the LAST word token only: 'CabinetB_Glass' is glass,
    'CabinetB_Glass_wood' is the wood OF the glass cabinet."""
    toks = [t.lower() for t in re.findall(r"[A-Za-z][a-z]*", mat.name)]
    if toks and toks[-1] in {"glass", "glas", "vidrio", "trans",
                             "transparent", "clear"}:
        return True
    if not mat.use_nodes:
        return False
    for nd in mat.node_tree.nodes:
        if nd.type == "BSDF_PRINCIPLED":
            a = nd.inputs["Alpha"]
            if not a.is_linked and a.default_value < 0.95:
                return True
            for key in ("Transmission Weight", "Transmission"):
                ti = nd.inputs.get(key)
                if ti is not None and not ti.is_linked and ti.default_value > 0.2:
                    return True
    return False


def mat_is_masked(mat):
    """Alpha-cutout material (cutlery silhouettes on flat planes): the
    Principled Alpha input is fed by a texture. Baked as BaseColor alpha +
    a masked shader, instead of being flattened opaque."""
    if not mat.use_nodes:
        return False
    for nd in mat.node_tree.nodes:
        if nd.type == "BSDF_PRINCIPLED" and nd.inputs["Alpha"].is_linked:
            return True
    return False


def bake_materials(meshes, asset_nm, tex_dir, res):
    """Bake an asset's materials into one PBR atlas set (BaseColor / ORM /
    DirectX Normal PNGs beside the FBX) PER MATERIAL GROUP (norm_group of the
    source-material name) and assign one clean textured material per group --
    the look survives FBX export into UE *and* every group remains its own
    named material slot there, independently swappable for variants.

    Works on COPIES of the materials (never the originals). Each (object,
    group) face set is smart-projected into its own cell of the group's
    atlas -- per-object cells are robust headless, where multi-object packing
    is not. Base/Roughness/Metallic are baked by routing each channel
    through an Emission shader (the DIFFUSE/ROUGHNESS passes silently fail
    on linked inputs); Normal uses the NORMAL pass. All groups bake in the
    same Cycles passes: the bake writes each face through its own material's
    target image node. Returns {group: {"slot", "textures": {map: filename},
    "translucent", "resolution"}}."""
    import math
    maps = set(CONFIG["bake_maps"])
    meshes = [m for m in meshes if m.type == "MESH" and len(m.data.polygons)]
    if not meshes:
        return {}
    for m in meshes:
        m.hide_render = False

    sc = bpy.context.scene
    prev_engine = sc.render.engine
    # Cycles occasionally fails to register in headless runs (observed: whole
    # roots erroring with 'enum "CYCLES" not found') -- force-enable it here.
    try:
        import addon_utils
        addon_utils.enable("cycles", default_set=False)
    except Exception:
        pass
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = CONFIG["bake_samples"]
    sc.render.bake.use_selected_to_active = False

    # private copies of every material so baking never touches the source.
    # EVERY baked material must use nodes and get an image target, or the
    # bake errors with "No active image found" -- so node-ify solids and fill
    # empty slots / material-less meshes with a default material too.
    default_mat = [None]

    def get_default():
        if default_mat[0] is None:
            dm = bpy.data.materials.new(asset_nm + "_default")
            dm.use_nodes = True
            default_mat[0] = dm
        return default_mat[0]

    matmap = {}
    src_of = {}                             # copy name -> source material
    for m in meshes:
        if len(m.data.materials) == 0:
            m.data.materials.append(get_default())
        for i, ms in enumerate(m.data.materials):
            if ms is None:
                m.data.materials[i] = get_default()
                continue
            if ms.name not in matmap:
                c = ms.copy()
                if not c.use_nodes:
                    c.use_nodes = True
                matmap[ms.name] = c
                src_of[c.name] = ms
            m.data.materials[i] = matmap[ms.name]
    mats = list(matmap.values())
    if default_mat[0] is not None:
        mats.append(default_mat[0])
    if not mats:
        sc.render.engine = prev_engine
        return {}

    # material groups: copy name -> group, and each face's group recorded NOW
    # (slot indices still point at the copies; they get remapped at the end)
    group_of = {c.name: norm_group(sn) for sn, c in matmap.items()}
    if default_mat[0] is not None:
        group_of[default_mat[0].name] = "Default"
    face_group = {}
    for o in meshes:
        slot_g = [group_of[s.name] for s in o.data.materials]
        face_group[o.name] = [slot_g[p.material_index] for p in o.data.polygons]
    groups = sorted({g for fg in face_group.values() for g in fg})

    translucent = {g: False for g in groups}
    for cname, g in group_of.items():
        src = src_of.get(cname)
        if src is not None and mat_is_translucent(src):
            translucent[g] = True
    masked = {g: False for g in groups}
    for cname, g in group_of.items():
        src = src_of.get(cname)
        if src is not None and not translucent[g] and mat_is_masked(src):
            masked[g] = True

    # per-group atlas resolution: share the texel budget by world-space
    # surface area, power-of-two, floored at bake_resolution_min, capped at res
    area = {g: 0.0 for g in groups}
    for o in meshes:
        s2 = o.matrix_world.median_scale ** 2
        for p, g in zip(o.data.polygons, face_group[o.name]):
            area[g] += p.area * s2
    total_area = sum(area.values()) or 1.0
    res_of = {}
    for g in groups:
        share = area[g] / total_area
        r = res * math.sqrt(share) if share > 0 else 1.0
        p2 = 2 ** math.ceil(math.log2(max(r, 1.0)))
        res_of[g] = int(min(max(p2, CONFIG["bake_resolution_min"]), res))
    # the bake margin is scene-global; keep it inside the smallest atlas's
    # 0.008-UV cell margin so small atlases don't bleed across cells
    sc.render.bake.margin = max(2, min(res_of.values()) // 256)

    # grid-pack UVs: unwrap each (object, group) face set into a NEW "__bake"
    # layer, scaled into its own cell of the GROUP's atlas. Faces of
    # different groups may overlap in UV space -- they rasterize into
    # different images. The bake writes over the ACTIVE (selected) UV layer,
    # while source image-texture nodes sample through the RENDER-ACTIVE
    # layer -- so the original UV layer must stay render-active or the bake
    # reads the source textures through the new scrambled mapping.
    # (The kitchen pack got away with a single layer only because its
    # materials were procedural and never sampled UVs.)
    cells = {g: [] for g in groups}         # group -> ordered object names
    for o in meshes:
        for g in sorted(set(face_group[o.name])):
            cells[g].append(o.name)
    grid = {}
    for g in groups:
        cols = math.ceil(math.sqrt(len(cells[g])))
        grid[g] = (cols, math.ceil(len(cells[g]) / cols))

    for o in meshes:
        ml = o.data.uv_layers
        orig_render = next((l.name for l in ml if l.active_render), None)
        ml.new(name="__bake")               # adding a layer can reallocate --
        ml = o.data.uv_layers               # re-fetch, address by name only
        ml.active = ml["__bake"]            # bake target + smart_project target
        if orig_render:                     # keep sources sampling original UVs
            ml[orig_render].active_render = True
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        og = face_group[o.name]
        for g in sorted(set(og)):
            # select only this group's faces (indices, not references --
            # mode switches reallocate mesh data) and unwrap just them
            gidx = [i for i, pg in enumerate(og) if pg == g]
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.context.tool_settings.mesh_select_mode = (False, False, True)
            bpy.ops.mesh.select_all(action="DESELECT")
            bpy.ops.object.mode_set(mode="OBJECT")
            for i in gidx:
                o.data.polygons[i].select = True
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
            bpy.ops.object.mode_set(mode="OBJECT")
            uvl = o.data.uv_layers["__bake"].data
            lis = [li for i in gidx for li in o.data.polygons[i].loop_indices]
            us = [uvl[li].uv[0] for li in lis]
            vs = [uvl[li].uv[1] for li in lis]
            umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
            uw = (umax - umin) or 1e-6
            vh = (vmax - vmin) or 1e-6
            cols, rows = grid[g]
            cw, ch, mg = 1.0 / cols, 1.0 / rows, 0.008
            idx = cells[g].index(o.name)
            tx, ty = (idx % cols) * cw + mg, (idx // cols) * ch + mg
            tw, th = cw - 2 * mg, ch - 2 * mg
            for li in lis:
                d = uvl[li]
                d.uv[0] = tx + ((d.uv[0] - umin) / uw) * tw
                d.uv[1] = ty + ((d.uv[1] - vmin) / vh) * th

    def newimg(g, suffix, noncolor, use_alpha=False):
        im = bpy.data.images.new(f"{asset_nm}_{g}_{suffix}",
                                 res_of[g], res_of[g], alpha=use_alpha)
        im.colorspace_settings.name = "Non-Color" if noncolor else "sRGB"
        return im

    img = {g: {} for g in groups}
    for g in groups:
        if "base" in maps:
            img[g]["base"] = newimg(g, "basecolor", False, use_alpha=True)
        if "rough" in maps:
            img[g]["rough"] = newimg(g, "roughness", True)
        if "metal" in maps:
            img[g]["metal"] = newimg(g, "metallic", True)
        if "normal" in maps:
            img[g]["normal"] = newimg(g, "normal", True)

    tnode = {mat.name: mat.node_tree.nodes.new("ShaderNodeTexImage") for mat in mats}

    def set_target(key):
        for mat in mats:
            nd = tnode[mat.name]
            nd.image = img[group_of[mat.name]][key]
            nd.select = True
            mat.node_tree.nodes.active = nd

    def select_meshes():
        bpy.ops.object.select_all(action="DESELECT")
        for m in meshes:
            m.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]

    os.makedirs(tex_dir, exist_ok=True)
    paths = {}

    def emit_bake(channel, key):
        saved = []
        for mat in mats:
            nt = mat.node_tree
            out = next((nd for nd in nt.nodes if nd.type == "OUTPUT_MATERIAL"), None)
            bsdf = next((nd for nd in nt.nodes if nd.type == "BSDF_PRINCIPLED"), None)
            if not out or not bsdf:
                continue
            emit = nt.nodes.new("ShaderNodeEmission")
            ci = bsdf.inputs[channel]
            if ci.is_linked:
                nt.links.new(ci.links[0].from_socket, emit.inputs["Color"])
            else:
                v = ci.default_value
                emit.inputs["Color"].default_value = (
                    tuple(v) if hasattr(v, "__len__") else (v, v, v, 1.0))
            orig = out.inputs["Surface"].links[0].from_socket \
                if out.inputs["Surface"].is_linked else None
            nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
            saved.append((nt, emit, out, orig, bsdf))
        set_target(key)
        select_meshes()
        sc.cycles.bake_type = "EMIT"
        bpy.ops.object.bake(type="EMIT")
        for nt, emit, out, orig, bsdf in saved:
            if orig:
                nt.links.new(orig, out.inputs["Surface"])
            else:
                nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
            nt.nodes.remove(emit)

    if "base" in maps:
        emit_bake("Base Color", "base")
    if "rough" in maps:
        emit_bake("Roughness", "rough")
    if "metal" in maps:
        emit_bake("Metallic", "metal")
    if "base" in maps and any(masked.values()):
        for g in groups:
            img[g]["alpha"] = newimg(g, "alphamask", True)
        emit_bake("Alpha", "alpha")
    if "normal" in maps:
        set_target("normal")
        select_meshes()
        sc.cycles.bake_type = "NORMAL"
        bpy.ops.object.bake(type="NORMAL")

    # baking done: drop the original UV layers so "__bake" is the ONLY layer
    # -- it then exports as UV channel 0, which is what UE samples (and what
    # the baked material's default sampling uses).
    for o in meshes:
        ml = o.data.uv_layers
        for lname in [l.name for l in ml if l.name != "__bake"]:
            ml.remove(ml[lname])
        ml["__bake"].name = "UVMap"
        ml.active = ml["UVMap"]
        ml["UVMap"].active_render = True

    # ---- write UE-ready textures: BaseColor (sRGB), ORM (Occlusion/Rough/
    # Metal), Normal (DirectX, green flipped). One set per GROUP.
    import numpy as np

    def arr_of(im):
        w, h = im.size
        a = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(a)
        return a.reshape(h, w, 4), w, h

    def save_im(im, g, suffix):
        p = os.path.join(tex_dir, f"{asset_nm}_{g}_{suffix}.png")
        im.filepath_raw = p
        im.file_format = "PNG"
        im.save()
        paths[g][suffix] = os.path.basename(p)
        # free the float buffer NOW (~res*res*16 B; ~268 MB at 4096) and
        # re-point the datablock at the PNG just written, so anything that
        # samples it later reloads identical pixels from disk. Without this
        # the buffers of every asset pile up and Blender dies mid-run.
        im.source = "FILE"
        im.filepath = p
        im.buffers_free()

    paths = {g: {} for g in groups}
    orm_of, normal_of = {}, {}
    for g in groups:
        gi = img[g]
        if "base" in maps:
            ba, w, h = arr_of(gi["base"])
            if masked.get(g) and "alpha" in gi:
                aa, _, _ = arr_of(gi["alpha"])
                ba[..., 3] = aa[..., 0]
            else:
                ba[..., 3] = 1.0
            gi["base"].pixels.foreach_set(ba.reshape(-1))
            save_im(gi["base"], g, "BaseColor")
            if "alpha" in gi:
                bpy.data.images.remove(gi.pop("alpha"))
        if "rough" in maps and "metal" in maps:
            ra, w, h = arr_of(gi["rough"])
            ma, _, _ = arr_of(gi["metal"])
            a = np.ones((h, w, 4), dtype=np.float32)
            a[..., 1] = ra[..., 0]             # Roughness -> G
            a[..., 2] = ma[..., 0]             # Metallic  -> B  (R = 1.0 occlusion)
            orm = bpy.data.images.new(f"{asset_nm}_{g}_ORM", w, h, alpha=False)
            orm.colorspace_settings.name = "Non-Color"
            orm.pixels.foreach_set(a.reshape(-1))
            save_im(orm, g, "ORM")
            orm_of[g] = orm
            # rough/metal only existed to feed the ORM pack -- drop them here
            bpy.data.images.remove(gi.pop("rough"))
            bpy.data.images.remove(gi.pop("metal"))
        if "normal" in maps:
            na, w, h = arr_of(gi["normal"])
            na[..., 1] = 1.0 - na[..., 1]      # OpenGL -> DirectX
            gi["normal"].pixels.foreach_set(na.reshape(-1))
            save_im(gi["normal"], g, "Normal")
            normal_of[g] = gi["normal"]

    # build one textured material per group (BaseColor + ORM-split + DX
    # Normal); the material NAME becomes the UE slot name.
    baked_of = {}
    for g in groups:
        baked = bpy.data.materials.new(f"{asset_nm}_{g}")
        baked.use_nodes = True
        nt = baked.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

        def tex(image, y):
            t = nt.nodes.new("ShaderNodeTexImage")
            t.image = image
            t.location = (-820, y)
            return t

        if "base" in maps:
            bt = tex(img[g]["base"], 300)
            nt.links.new(bt.outputs["Color"], bsdf.inputs["Base Color"])
            if masked.get(g):
                nt.links.new(bt.outputs["Alpha"], bsdf.inputs["Alpha"])
                try:
                    baked.blend_method = "CLIP"
                except Exception:
                    pass
        if g in orm_of:
            sep = nt.nodes.new("ShaderNodeSeparateColor")
            sep.location = (-470, 0)
            nt.links.new(tex(orm_of[g], 0).outputs["Color"], sep.inputs["Color"])
            nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
            nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        if g in normal_of:
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nmap.location = (-300, -420)
            nt.links.new(tex(normal_of[g], -420).outputs["Color"],
                         nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        baked_of[g] = baked

    # remap every mesh's slots to the per-group baked materials
    for o in meshes:
        og = face_group[o.name]
        used = sorted(set(og))
        o.data.materials.clear()
        slot_idx = {}
        for g in used:
            slot_idx[g] = len(o.data.materials)
            o.data.materials.append(baked_of[g])
        for p, g in zip(o.data.polygons, og):
            p.material_index = slot_idx[g]

    sc.render.engine = prev_engine
    return {g: {"slot": f"{asset_nm}_{g}",
                "textures": paths[g],
                "translucent": translucent[g],
                "masked": masked[g],
                "resolution": res_of[g]} for g in groups}


# ===========================================================================
# orchestration
# ===========================================================================
def safe_name(s):
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")


def cleanup_work(names):
    """Remove work-copy objects and purge the datablock cascade."""
    bpy.ops.object.select_all(action="DESELECT")
    doomed = set(names)
    for o in list(bpy.data.objects):
        if o.name in doomed:
            bpy.data.objects.remove(o, do_unlink=True)
    # iterate to a fixpoint: removing a mesh frees its materials, which
    # frees their images -- a single pass leaves those cascades alive and
    # at 4K bake sizes the leftovers add up to a crash over a long run.
    removed = True
    while removed:
        removed = False
        for coll in (bpy.data.materials, bpy.data.images, bpy.data.meshes,
                     bpy.data.armatures):
            for blk in list(coll):
                if blk.users == 0 and not blk.use_fake_user:
                    try:
                        coll.remove(blk)
                        removed = True
                    except Exception:
                        pass


def process_asset(asset, report, annotate=False):
    notes = []
    work = ensure_collection("EXPORT_WORK")
    name_map = {}
    for node in asset["nodes"]:
        duplicate_hierarchy(node, work, name_map)
    for obj in list(name_map.values()):
        if obj.type in {"MESH", "CURVE"}:
            bake_object(obj)

    # re-base the work copies into the asset root's LOCAL frame: pivots,
    # OVERRIDES and dojo_* props are root-relative from here on, so moving
    # an asset around the scene does not invalidate them
    anchor = asset.get("anchor")
    if anchor is not None:
        # TRANSLATION only: pivots/props become root-relative so assets can
        # be moved around the scene freely. Root rotations/scales (Collada
        # wrappers carry both) keep flowing through the normal flatten path
        # -- inverting them would reorient or rescale the export.
        ainv = Matrix.Translation(-anchor.translation)
        copies = set(name_map.values())
        for o in name_map.values():
            if o.parent not in copies:
                o.matrix_world = ainv @ o.matrix_world
        bpy.context.view_layer.update()

    preskinned, harvested = harvest_preskinned(name_map)
    if not any(o.type == "MESH" for o in name_map.values()):
        raise RuntimeError("asset has no meshes")
    an = analyze_asset(asset, name_map, harvested)
    prelim_skin = None
    if CONFIG["close_open_doors"]:
        pb, prelim_skin, _pg = compute_rig(an, name_map, [], split_panes=False)
        fill_mover_meshes_from_skin(an, pb, prelim_skin, name_map)
        close_open_doors(an, name_map, notes)
    bones, skin, group_rename = compute_rig(an, name_map, notes,
                                            reuse_skin=prelim_skin)
    center_base = Vector((an["cctr"].x, an["cctr"].y, an["cmn"].z))
    joints = joint_specs(an, bones, center_base)

    if annotate:
        # write the inferred joint data back onto the ORIGINAL part empties
        # as dojo_* custom properties (world space; editable in the UI, and
        # preferred over inference on subsequent export runs)
        jw = joint_specs(an, bones, Vector((0.0, 0.0, 0.0)))
        wrote = {}
        for u in an["movers"]:
            bn = u.get("bone")
            src = bpy.context.scene.objects.get(u["orig"])
            if src is None or not bn or bn not in jw:
                continue
            s = jw[bn]
            src["dojo_joint"] = s["type"]
            src["dojo_kind"] = u["kind"]
            src["dojo_pivot"] = [float(v) for v in s["pivot"]]
            src["dojo_axis"] = [float(v) for v in s["axis"]]
            src["dojo_limits"] = [float(v) for v in s["limits"]]
            wrote[u["orig"]] = "{} {}".format(s["type"], s["limits"])
        report[asset["name"]] = dict(annotated=wrote, notes=notes)
        if CONFIG["cleanup"]:
            cleanup_work([o.name for o in name_map.values()])
        return

    nm = safe_name(asset["name"])
    folder = os.path.join(CONFIG["output_dir"], nm) if CONFIG["per_asset_folder"] \
        else CONFIG["output_dir"]
    baked_info = {}
    if CONFIG["bake_materials"] and CONFIG["export"] and not CONFIG["visualize"]:
        res = CONFIG["bake_resolution"] if an["cdim"].length >= 1.2 \
            else CONFIG["bake_resolution_small"]
        baked_info = bake_materials([o for o in name_map.values()
                                     if o.type == "MESH"], nm, folder, res)
    flatten_meshes(name_map, center_base)
    fix_normals(name_map)
    copy_to_orig = {o.name: orig for orig, o in name_map.items()}
    report[asset["name"]] = dict(
        front=f"{an['front_sign']:+d}{an['front_axis']}",
        center_base=[round(v, 4) for v in center_base],
        movers=[{"name": u["orig"], "kind": u["kind"],
                 "bone": u.get("bone"), "motion": u.get("motion"),
                 "pivot": ([round(v, 4) for v in u["pivot"]] if u["pivot"] is not None else None)}
                for u in an["movers"]],
        bones=[{"name": b["name"], "parent": b["parent"],
                "head": [round(v, 4) for v in b["head"]],
                "tail": [round(v, 4) for v in b["tail"]]} for b in bones],
        skin={copy_to_orig.get(k, k): v for k, v in skin.items() if v != "root"},
        joints=joints,
        materials=baked_info,
        notes=notes,
    )

    if CONFIG["export_mode"] == "static_parts" and not CONFIG["visualize"]:
        work = ensure_collection("EXPORT_WORK")
        work_names = list({o.name for o in name_map.values()}
                          | {o.name for o in work.objects})
        if CONFIG["export"]:
            parts, part_objs = export_static_parts(
                nm, folder, bones, skin, joints, name_map, group_rename,
                notes, masses=part_masses(an, asset, bones))
            report[asset["name"]]["parts"] = parts
            if CONFIG["emit_usd"]:
                write_usd(nm, folder, parts, part_objs, baked_info, notes)
            if CONFIG["emit_mjcf"]:
                write_mjcf(nm, folder, parts, part_objs, notes)
            work_names = list({*work_names,
                               *[o.name for o in part_objs.values()]})
        if CONFIG["cleanup"]:
            cleanup_work(work_names)
        return

    arm = build_armature(nm, bones, skin, name_map, center_base,
                         group_rename, preskinned,
                         visualize=CONFIG["visualize"])
    meshes = [o for o in name_map.values() if o.type == "MESH"]

    if CONFIG["export"] and not CONFIG["visualize"]:
        fp = os.path.join(folder, nm + ".fbx")
        export_fbx(arm, meshes, fp)
        report[asset["name"]]["fbx"] = fp

    if CONFIG["cleanup"] and not CONFIG["visualize"]:
        cleanup_work([o.name for o in name_map.values()] + [arm.name])


def main(annotate=False):
    """annotate=True: no export -- just write dojo_* custom properties with
    the analyzer's inferences onto the original part empties."""
    if CONFIG["export"]:
        import addon_utils
        try:
            addon_utils.enable("io_scene_fbx", default_set=False)
        except Exception:
            pass
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    scene = bpy.context.scene
    if CONFIG["roots"]:
        roots = [scene.objects[n] for n in CONFIG["roots"] if n in scene.objects]
    else:
        roots = [o for o in scene.objects
                 if o.parent is None and o.children
                 and o.name not in CONFIG["skip_roots"]]

    skip_pats = [re.compile(p) for p in CONFIG["skip_assets"]]
    report = {}
    for r in roots:
        try:
            assets = split_root(r)
        except Exception as e:
            report[r.name] = {"error": repr(e)}
            continue
        for asset in assets:
            if any(p.search(asset["name"]) for p in skip_pats):
                report[asset["name"]] = {"skipped": True}
                continue
            try:
                process_asset(asset, report, annotate=annotate)
            except Exception as e:
                import traceback
                report[asset["name"]] = {"error": repr(e),
                                         "trace": traceback.format_exc()}

    if CONFIG["write_manifest"] and not annotate:
        os.makedirs(CONFIG["output_dir"], exist_ok=True)
        with open(os.path.join(CONFIG["output_dir"], "rig_manifest.json"),
                  "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
    done = sum(1 for v in report.values() if "error" not in v)
    errs = [k for k, v in report.items() if "error" in v]
    print(f"[dojo_export] {done}/{len(report)} assets OK; errors: {errs or 'none'}")
    return report


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# Unreal import notes
# ---------------------------------------------------------------------------
# - Import each FBX as a Skeletal Mesh ("Geometry and Skinning Weights",
#   Skeleton: None -> one skeleton per asset).
# - In each Physics Asset constrain, per bone:
#     door_N  (motion "swing_vertical")   -> Angular Swing about the bone's
#                                            length (the bone IS the hinge
#                                            line, bottom -> top)
#     door_N  (motion "swing_horizontal") -> Angular Swing about the bone's
#                                            length (runs along the bottom
#                                            edge: oven doors, flip lids)
#     drawer_N                            -> Linear (prismatic) along the
#                                            bone's length (front-center,
#                                            pointing out of the cabinet)
#     slide_N                             -> Linear along the bone's length
#                                            (sliding glass pane, sideways)
#     *_handle                            -> Fixed to its parent bone; gives
#                                            a robot gripper a dedicated
#                                            small collision body to grasp
# - Check rig_manifest.json: every asset lists its movers, pivots and notes
#   (auto-closed doors, guessed hinges, static->door attachments); fix odd
#   ones via OVERRIDES at the top of this file and re-run.
# - Models are true real-world scale, global_scale=1.0. If something imports
#   100x off, toggle "Apply Unit Scale" here / Import Uniform Scale in UE.
