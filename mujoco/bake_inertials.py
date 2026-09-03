"""Bake MuJoCo-computed <inertial> into every body of the mebot_gen3 XMLs.

Why: only the 20 arm/gripper bodies carry authored inertials; MuJoCo
auto-computes the base's ~190 kg from collision primitives, but the Chaos
rig generator (and any other consumer) cannot reproduce that and fell back
to crude volume estimates — the base simulated far too light and a 9 kg arm
motion could tip it. Baking the computed values is an identity change for
MuJoCo and gives every other importer the exact mass distribution.

Also restores the mesh .obj files from their committed .glb sidecars when
missing: `.gitignore`'s `*.obj` ("compiled object files") pattern has been
eating the exporter's mesh OBJs, so a fresh clone cannot compile these
models with plain MuJoCo at all. The OBJs are visual-only for the mebot
(group=2, density=0), so trimesh's GLB->OBJ conversion is fidelity-safe
for physics.

Run from the repo root:
    Plugins/RammsNewtonPhysics/Scripts/.venv/Scripts/python.exe mujoco/bake_inertials.py
"""
import os
import re
import xml.etree.ElementTree as ET

import mujoco

HERE = os.path.dirname(os.path.abspath(__file__))
TARGETS = [
    os.path.join(HERE, "mebot", "mebot_gen3_ue.xml"),   # UE import source
    os.path.join(HERE, "mebot", "mebot_gen3.xml"),
    os.path.join(HERE, "mebot", "mebot_gen3_scene.xml"),
]


def restore_objs_from_glb(xml_path: str, force: bool = False) -> int:
    """Recreate missing .obj mesh files from .glb sidecars.

    The sidecars were produced by URLab's clean_meshes.py, which applies a
    -90 deg X rotation ("GLTF Y-up -> Unreal Z-up") before GLB export, and
    trimesh's GLB-load/OBJ-export chain adds its own convention rotation.
    Empirically (verified against the parts' collision AABBs in the body
    frame): a +180 deg X rotation on the loaded mesh makes the round trip
    land in the original MuJoCo body frame. Without it every restored
    visual came back rotated out of its body frame (observed: the whole
    mebot base's visuals misaligned with collision while the arm, whose
    original meshes survived, was fine).
    """
    import numpy as np
    import trimesh

    xml_dir = os.path.dirname(xml_path)
    text = open(xml_path, encoding="utf-8").read()
    restored = 0
    undo_gltf = trimesh.transformations.rotation_matrix(np.radians(180), [1, 0, 0])
    for ref in set(re.findall(r'file="([^"]+\.obj)"', text)):
        obj_path = os.path.normpath(os.path.join(xml_dir, ref))
        if os.path.exists(obj_path) and not force:
            continue
        glb_path = os.path.splitext(obj_path)[0] + ".glb"
        if not os.path.exists(glb_path):
            print(f"  MISSING with no sidecar: {ref}")
            continue
        mesh = trimesh.load(glb_path, force="mesh")
        mesh.apply_transform(undo_gltf)
        mesh.export(obj_path)
        restored += 1
    return restored


def fmt(vals) -> str:
    return " ".join(f"{float(v):.8g}" for v in vals)


def bake(xml_path: str) -> None:
    restored = restore_objs_from_glb(xml_path)
    model = mujoco.MjModel.from_xml_path(xml_path)
    pre = {model.body(i).name: float(model.body_mass[i]) for i in range(model.nbody)}

    tree = ET.parse(xml_path)
    root = tree.getroot()
    baked = skipped = 0
    for body in root.iter("body"):
        name = body.get("name")
        if not name:
            continue
        if body.find("inertial") is not None:
            skipped += 1
            continue
        bid = model.body(name).id
        if model.body_mass[bid] <= 0:
            continue
        inertial = ET.Element("inertial")
        inertial.set("pos", fmt(model.body_ipos[bid]))
        inertial.set("quat", fmt(model.body_iquat[bid]))
        inertial.set("mass", f"{float(model.body_mass[bid]):.8g}")
        inertial.set("diaginertia", fmt(model.body_inertia[bid]))
        body.insert(0, inertial)
        baked += 1
    ET.indent(tree, space="  ")
    tree.write(xml_path, encoding="unicode", xml_declaration=False)

    # Verify: recompiles and every body mass is unchanged.
    m2 = mujoco.MjModel.from_xml_path(xml_path)
    for i in range(m2.nbody):
        n = m2.body(i).name
        assert abs(float(m2.body_mass[i]) - pre[n]) < 1e-6, (
            f"{xml_path}: bake changed mass of {n}: {pre[n]} -> {m2.body_mass[i]}")
    tot = sum(m2.body_mass)
    arm = sum(m2.body_mass[i] for i in range(m2.nbody)
              if (m2.body(i).name or "").startswith("arm_"))
    print(f"{os.path.basename(xml_path)}: baked {baked} bodies "
          f"(kept {skipped} authored), restored {restored} objs, "
          f"total={tot:.1f} kg arm={arm:.1f} base={tot - arm:.1f}")


def main() -> None:
    for target in TARGETS:
        bake(target)


if __name__ == "__main__":
    main()
