"""Dump the MeBot's geometry from its Unreal assets, for build_mebot_mjcf.py.

    python Scripts/editor_remote_exec.py --file mujoco/mebot/extract_ue_mebot.py

Run in the editor (read-only: nothing is saved). Writes source/mebot_ue.json next to this file:

  bones        every bone's reference pose in component space (cm, Unreal axes: X forward, Y right, Z up)
  bodies       each physics-asset body's primitives (boxes, spheres, capsules) and, for convex hulls, the
               hull's axis-aligned extent and centre in the bone's frame (the wheels are hulls)
  constraints  each physics-asset constraint's bones, frame in the parent body (Pos2 / PriAxis2 / SecAxis2)
               and which motions are free, limited or locked, with their limits
  sockets      the skeletal mesh's sockets (the seat mount)

The source is the public ramms-assets MeBot (skeletal mesh + physics asset). Its kinematics are what
build_mebot_mjcf.py takes; its masses and drives are Unreal defaults and are not used.

The physics asset's body setups are reached through ObjectIterator, and its constraints through a T3D export
(their DefaultInstance is not exposed to Python): that text is parsed here and not kept.
"""
import json
import os
import re
import tempfile

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "source", "mebot_ue.json")
SKELETAL_MESH = "/RammsAssets/Robots/RAMMP/Base/SkeletalMeshes/mebot"
PHYSICS_ASSET = "/RammsAssets/Robots/RAMMP/Base/SkeletalMeshes/mebot_PhysicsAsset"


def v3(v):
    return [round(v.x, 4), round(v.y, 4), round(v.z, 4)]


def rot3(r):
    return [round(r.roll, 4), round(r.pitch, 4), round(r.yaw, 4)]


def xf(t):
    return {"loc": v3(t.translation), "rpy": rot3(t.rotation.rotator()),
            "quat_xyzw": [round(t.rotation.x, 6), round(t.rotation.y, 6), round(t.rotation.z, 6), round(t.rotation.w, 6)]}


def t3d_vec(s, key):
    m = re.search(key + r'=\(X=([-\d.e]+),Y=([-\d.e]+),Z=([-\d.e]+)\)', s)
    return [float(m.group(i)) for i in (1, 2, 3)] if m else None


def t3d_constraints(text):
    """Each constraint template's DefaultInstance, from the T3D export. Unset fields are Unreal's defaults:
    frames at the origin with axes X / Y, angular motions free, linear motions locked, limits 45 deg / 0 cm."""
    out = []
    for m in re.finditer(r'^\s*DefaultInstance=\((.*)\)\s*$', text, re.M):
        s = m.group(1)

        def field(k):
            mm = re.search(k + r'="?([^",)]+)"?', s)
            return mm.group(1) if mm else None

        def group(k):
            mm = re.search(k + r'=\(([^()]*(?:\([^()]*\)[^()]*)*)\)', s)
            return mm.group(1) if mm else ""

        lin, cone, twist = group("LinearLimit"), group("ConeLimit"), group("TwistLimit")

        def motion(g, k, default):
            mm = re.search(k + r'=(\w+)', g)
            return (mm.group(1) if mm else default).split("_", 1)[1]

        def num(g, k, default):
            mm = re.search(k + r'=([-\d.e]+)', g)
            return float(mm.group(1)) if mm else default

        if not field("JointName"):
            continue
        out.append({
            "name": field("JointName"), "child": field("ConstraintBone1"), "parent": field("ConstraintBone2"),
            "pos_in_parent": t3d_vec(s, "Pos2") or [0.0, 0.0, 0.0],
            "pri_axis_in_parent": t3d_vec(s, "PriAxis2") or [1.0, 0.0, 0.0],
            "sec_axis_in_parent": t3d_vec(s, "SecAxis2") or [0.0, 1.0, 0.0],
            "pos_in_child": t3d_vec(s, "Pos1") or [0.0, 0.0, 0.0],
            "linear": {"x": motion(lin, "XMotion", "LCM_Locked"), "y": motion(lin, "YMotion", "LCM_Locked"),
                       "z": motion(lin, "ZMotion", "LCM_Locked"), "limit_cm": num(lin, "Limit", 0.0)},
            "swing1": {"motion": motion(cone, "Swing1Motion", "ACM_Free"), "limit_deg": num(cone, "Swing1LimitDegrees", 45.0)},
            "swing2": {"motion": motion(cone, "Swing2Motion", "ACM_Free"), "limit_deg": num(cone, "Swing2LimitDegrees", 45.0)},
            "twist": {"motion": motion(twist, "TwistMotion", "ACM_Free"), "limit_deg": num(twist, "TwistLimitDegrees", 45.0)},
            "disable_collision": "bDisableCollision=True" in s,
        })
    return out


def t3d_hulls(text):
    """Each body setup's convex hulls: extent and centre of their vertices, in the bone's frame."""
    hulls = {}
    for m in re.finditer(r'Begin Object Name="SkeletalBodySetup_\d+".*?End Object', text, re.S):
        blk = m.group(0)
        bn = re.search(r'BoneName="([^"]+)"', blk)
        if not bn:
            continue
        for vd in re.finditer(r'VertexData=\(((?:\(X=[-\d.e]+,Y=[-\d.e]+,Z=[-\d.e]+\),?)+)\)', blk):
            pts = [tuple(float(x) for x in p) for p in re.findall(r'\(X=([-\d.e]+),Y=([-\d.e]+),Z=([-\d.e]+)\)', vd.group(1))]
            if not pts:
                continue
            lo = [min(p[i] for p in pts) for i in range(3)]
            hi = [max(p[i] for p in pts) for i in range(3)]
            hulls.setdefault(bn.group(1), []).append({"n": len(pts), "min": [round(x, 4) for x in lo], "max": [round(x, 4) for x in hi]})
    return hulls


sk = unreal.load_asset(SKELETAL_MESH)
pa = unreal.load_asset(PHYSICS_ASSET)
skel = sk.get_editor_property("skeleton")
out = {"source": {"skeletal_mesh": SKELETAL_MESH, "physics_asset": PHYSICS_ASSET}, "units": "cm, Unreal axes (X forward, Y right, Z up)"}

pose = unreal.AnimPoseExtensions.get_reference_pose(skel)
out["bones"] = [{"name": str(b), "parent": str(sk.get_bone_parent(b)),
                 "component": xf(unreal.AnimPoseExtensions.get_bone_pose(pose, b, unreal.AnimPoseSpaces.WORLD))}
                for b in unreal.AnimPoseExtensions.get_bone_names(pose)]

out["sockets"] = []
for i in range(sk.num_sockets()):
    s = sk.get_socket_by_index(i)
    out["sockets"].append({"name": str(s.get_editor_property("socket_name")), "bone": str(s.get_editor_property("bone_name")),
                           "loc": v3(s.get_editor_property("relative_location")), "rpy": rot3(s.get_editor_property("relative_rotation"))})

fd, t3d_path = tempfile.mkstemp(suffix=".t3d")
os.close(fd)
task = unreal.AssetExportTask()
task.set_editor_property("object", pa)
task.set_editor_property("filename", t3d_path)
task.set_editor_property("automated", True)
task.set_editor_property("prompt", False)
task.set_editor_property("replace_identical", True)
if not unreal.Exporter.run_asset_export_task(task):
    raise RuntimeError("the physics asset's T3D export failed")
with open(t3d_path, encoding="utf-8", errors="replace") as f:
    text = f.read()
os.remove(t3d_path)
hulls = t3d_hulls(text)

out["bodies"] = []
for bs in unreal.ObjectIterator(unreal.BodySetup):
    if bs.get_outer() != pa:
        continue
    bone = str(bs.get_editor_property("bone_name"))
    agg = bs.get_editor_property("agg_geom")
    prims = []
    for b in agg.get_editor_property("box_elems"):
        prims.append({"type": "box", "center": v3(b.get_editor_property("center")), "rpy": rot3(b.get_editor_property("rotation")),
                      "size": [round(b.get_editor_property(k), 4) for k in ("x", "y", "z")]})
    for s in agg.get_editor_property("sphere_elems"):
        prims.append({"type": "sphere", "center": v3(s.get_editor_property("center")), "radius": round(s.get_editor_property("radius"), 4)})
    for c in agg.get_editor_property("sphyl_elems"):
        prims.append({"type": "capsule", "center": v3(c.get_editor_property("center")), "rpy": rot3(c.get_editor_property("rotation")),
                      "radius": round(c.get_editor_property("radius"), 4), "length": round(c.get_editor_property("length"), 4)})
    for h in hulls.get(bone, []):
        prims.append(dict({"type": "hull"}, **h))
    out["bodies"].append({"bone": bone, "primitives": prims})
out["bodies"].sort(key=lambda b: b["bone"])

out["constraints"] = t3d_constraints(text)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT + ".tmp", "w", encoding="utf-8", newline="\n") as f:
    json.dump(out, f, indent=1)
os.replace(OUT + ".tmp", OUT)
print("[mebot] wrote %s: %d bones, %d bodies, %d constraints, %d hulls" % (
    OUT, len(out["bones"]), len(out["bodies"]), len(out["constraints"]), sum(len(v) for v in hulls.values())))
