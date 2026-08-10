"""
Compose the RAMMP mobile manipulator: MeBot base + Kinova Gen3 + 2F-85.

Rigidly mounts the arm's base_link onto the MeBot chassis (deleting the
arm's tracking-base machinery: free joint, base_target mocap, base_weld —
that indirection exists for riding a Chaos chair in UE; here the chair IS
the MuJoCo model). Inputs are the two existing composed models:

- mujoco/mebot/mebot_scene.xml   (run compose_mebot_scene.py first)
- mujoco/gen3_2f85/gen3_2f85.xml

Output: mujoco/mebot/mebot_gen3_scene.xml — nu = 6 (base) + 8 (arm+gripper).

ARM_MOUNT_POS is provisional (front-left of the chassis top, roughly where
rammp_mount_arm sits) — replace with the surveyed mount transform.

Run:
    Plugins/RammsNewtonPhysics/Scripts/.venv/Scripts/python.exe mujoco/compose_mebot_gen3.py
"""
import os

import mujoco

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_XML = os.path.join(HERE, "mebot", "mebot.xml")  # robot-only base (no floor)
ARM_XML = os.path.join(HERE, "gen3_2f85", "gen3_2f85.xml")
OUT_ROBOT = os.path.join(HERE, "mebot", "mebot_gen3.xml")        # robot only — import THIS into UE maps
OUT = os.path.join(HERE, "mebot", "mebot_gen3_scene.xml")         # robot + floor — standalone CLI/viewer

ARM_MOUNT_POS = [0.40, 0.18, 0.33]  # provisional; chassis-frame metres
PREFIX = "arm_"


def main() -> None:
    base = mujoco.MjSpec.from_file(BASE_XML)
    arm = mujoco.MjSpec.from_file(ARM_XML)

    # Two mesh sources after the merge (base visuals in mebot/assets, arm
    # meshes in gen3_2f85/assets) — one meshdir cannot serve both, so leave
    # meshdir unset (paths resolve from mujoco/mebot/) and point each arm
    # mesh at its home directory explicitly.
    for mesh in arm.meshes:
        mesh.file = "../gen3_2f85/assets/" + os.path.basename(mesh.file)

    # Strip the UE tracking-base machinery: mocap target, weld, free base.
    for eq in list(arm.equalities):
        if eq.name == "base_weld":
            arm.delete(eq)
    for body in list(arm.bodies):
        if body.name == "base_target":
            arm.delete(body)
    for joint in list(arm.joints):
        if joint.type == mujoco.mjtJoint.mjJNT_FREE:
            arm.delete(joint)
    # Keyframes were sized for the free-base layout; drop them.
    for key in list(arm.keys):
        arm.delete(key)

    # Grasp-relevant solver options from the arm model.
    base.option.impratio = 10
    base.option.cone = mujoco.mjtCone.mjCONE_ELLIPTIC

    chassis = base.body("mebot")
    site = chassis.add_site(name="arm_mount", pos=ARM_MOUNT_POS)
    base.attach(arm, prefix=PREFIX, site=site)

    model = base.compile()
    print(f"compiled: nq={model.nq} nv={model.nv} nu={model.nu} "
          f"nbody={model.nbody} mass={sum(model.body_mass):.1f}kg")

    with open(OUT_ROBOT, "w", encoding="utf-8") as f:
        f.write(base.to_xml())
    print(f"wrote {OUT_ROBOT} (robot only — use for UE import)")

    # Standalone variant: same model plus a ground plane for CLI/viewer use.
    # Never import this one into a populated UE map (the 40x40 m plane
    # collides with the whole level).
    floor = base.worldbody.add_geom(name="floor")
    import mujoco as _mj
    floor.type = _mj.mjtGeom.mjGEOM_PLANE
    floor.size = [20, 20, 0.1]
    floor.contype = 1
    floor.conaffinity = 1
    base.compile()
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(base.to_xml())
    print(f"wrote {OUT} (with floor — standalone CLI/viewer)")

    # Round-trip check from the saved files.
    mujoco.MjModel.from_xml_path(OUT_ROBOT)
    m = mujoco.MjModel.from_xml_path(OUT)
    print(f"round-trip ok: nu={m.nu} actuators="
          f"{[mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_ACTUATOR, i) for i in range(m.nu)]}")


if __name__ == "__main__":
    main()
