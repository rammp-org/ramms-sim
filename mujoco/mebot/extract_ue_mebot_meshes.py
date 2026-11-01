"""Split the MeBot's skeletal mesh into per-bone, per-material visual meshes, for build_mebot_mjcf.py.

    python Scripts/editor_remote_exec.py --file mujoco/mebot/extract_ue_mebot_meshes.py

Run in the editor (read-only: nothing is saved). The skeletal mesh is rigid -- every vertex has one bone at full
weight -- so each triangle belongs to one bone. Writes, next to this file:

  meshes/<bone>__<material>.stl   binary STL, in metres and MuJoCo's axes (X forward, Y left, Z up), in the
                                  skeletal mesh's component space (the bones' reference pose), wound outward;
                                  parts over MAX_TRIANGLES are simplified to MAX_TRIANGLES or a quarter of theirs,
                                  whichever is more
  source/mebot_meshes.json        each part's file, bone, material, colour (the material's DiffuseColor, sRGB)
                                  and triangle counts

The source is the public ramms-assets MeBot skeletal mesh.
"""
import json
import os
import struct

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
SKELETAL_MESH = "/RammsAssets/Robots/RAMMP/Base/SkeletalMeshes/mebot"
MAX_TRIANGLES = 3000
UE_TO_M = 0.01

GS = unreal.GeometryScript_AssetUtils
BW = unreal.GeometryScript_BoneWeights
Q = unreal.GeometryScript_MeshQueries
L = unreal.GeometryScript_List
MAT = unreal.GeometryScript_Materials


def srgb(c):
    return round((12.92 * c) if c <= 0.0031308 else (1.055 * c ** (1 / 2.4) - 0.055), 4)


def write_stl(path, verts, tris):
    """verts in Unreal component space (cm); written in metres, MuJoCo axes (Y flipped), wound outward. Unreal's
    front faces are clockwise in its left-handed axes; flipping Y mirrors them into right-handed counter-clockwise
    ones, so the triangles keep their order (reversing it turned every part inside out)."""
    v = [(p.x * UE_TO_M, -p.y * UE_TO_M, p.z * UE_TO_M) for p in verts]
    with open(path + ".tmp", "wb") as f:
        f.write(b"mebot visual mesh".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            a, b, c = v[t.x], v[t.y], v[t.z]
            u = [b[i] - a[i] for i in range(3)]
            w = [c[i] - a[i] for i in range(3)]
            n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
            ln = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5 or 1.0
            f.write(struct.pack("<12fH", *[x / ln for x in n], *a, *b, *c, 0))
    os.replace(path + ".tmp", path)


sk = unreal.load_asset(SKELETAL_MESH)
dm = unreal.DynamicMesh()
dm, outcome = GS.copy_mesh_from_skeletal_mesh(sk, dm, unreal.GeometryScriptCopyMeshFromAssetOptions(), unreal.GeometryScriptMeshReadLOD())
if outcome != unreal.GeometryScriptOutcomePins.SUCCESS:
    raise RuntimeError("could not copy the skeletal mesh")
_, bones = BW.get_all_bones_info(dm)
bone_name = {b.get_editor_property("index"): str(b.get_editor_property("name")) for b in bones}
materials, _ = GS.get_material_list_from_skeletal_mesh(sk)
MEL = unreal.MaterialEditingLibrary
mat_info = []
for m in materials:
    rgba = [0.5, 0.5, 0.5, 1.0]
    if isinstance(m, unreal.MaterialInstance) and "DiffuseColor" in [str(p) for p in MEL.get_vector_parameter_names(m)]:
        c = MEL.get_material_instance_vector_parameter_value(m, "DiffuseColor")
        rgba = [srgb(c.r), srgb(c.g), srgb(c.b), 1.0]
    mat_info.append((m.get_name() if m else "none", rgba))

_, _, has_gaps = Q.get_all_vertex_positions(dm, False)
if has_gaps:
    raise RuntimeError("the copied mesh has vertex id gaps")
n_verts = Q.get_vertex_count(dm)
vertex_bone = []
for vid in range(n_verts):
    _, bw, ok = BW.get_largest_vertex_bone_weight(dm, vid)
    vertex_bone.append(bw.get_editor_property("bone_index") if ok else 0)
_, tri_list, _ = Q.get_all_triangle_indices(dm, False)
tris = L.convert_triangle_list_to_array(tri_list)
_, mat_ids, _ = MAT.get_all_triangle_material_i_ds(dm)
mat_ids = L.convert_index_list_to_array(mat_ids)

# One part per (bone, material); each triangle's bone is its first vertex's (the mesh is rigidly skinned).
parts, part_tris = {}, {}
for tid, t in enumerate(tris):
    key = (bone_name[vertex_bone[t.x]], mat_ids[tid])
    parts.setdefault(key, len(parts))
    part_tris.setdefault(parts[key], []).append(tid)
for key, pid in parts.items():
    idx = L.convert_array_to_index_list(part_tris[pid])
    MAT.set_material_id_on_triangles(dm, idx, pid)
_, meshes, ids = unreal.GeometryScript_MeshDecomposition.split_mesh_by_material_i_ds(dm, unreal.DynamicMeshPool())

out_dir = os.path.join(HERE, "meshes")
os.makedirs(out_dir, exist_ok=True)
by_pid = {pid: key for key, pid in parts.items()}
manifest = []
for mesh, pid in zip(meshes, ids):
    bone, mid = by_pid[pid]
    n_src = Q.get_num_triangle_i_ds(mesh)
    if n_src > MAX_TRIANGLES:
        unreal.GeometryScript_MeshSimplification.apply_simplify_to_triangle_count(
            mesh, max(MAX_TRIANGLES, n_src // 4), unreal.GeometryScriptSimplifyMeshOptions())
    _, pos, _ = Q.get_all_vertex_positions(mesh, False)
    _, tl, _ = Q.get_all_triangle_indices(mesh, False)
    t_arr = L.convert_triangle_list_to_array(tl)
    name = "%s__%s.stl" % (bone, mat_info[mid][0])
    write_stl(os.path.join(out_dir, name), L.convert_vector_list_to_array(pos), t_arr)
    manifest.append({"file": "meshes/" + name, "bone": bone, "material": mat_info[mid][0], "rgba": mat_info[mid][1],
                     "triangles": len(t_arr), "triangles_source": n_src})
manifest.sort(key=lambda p: p["file"])

out = os.path.join(HERE, "source", "mebot_meshes.json")
with open(out + ".tmp", "w", encoding="utf-8", newline="\n") as f:
    json.dump({"source": SKELETAL_MESH, "units": "m, MuJoCo axes (X forward, Y left, Z up), component space",
               "max_triangles": MAX_TRIANGLES, "parts": manifest}, f, indent=1)
os.replace(out + ".tmp", out)
print("[mebot] wrote %d meshes (%d triangles, from %d) and %s" % (
    len(manifest), sum(p["triangles"] for p in manifest), sum(p["triangles_source"] for p in manifest), out))
