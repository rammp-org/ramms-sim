"""
Compose a combined Kinova Gen3 + Robotiq 2F-85 MJCF for URLab import.

Loads the two MuJoCo Menagerie models, attaches the gripper to the arm's tool
flange (the `pinch_site` on bracelet_link) with a name prefix (so the gripper's
default classes / names don't collide with the arm's), flattens all referenced
meshes into one `assets/` folder, and writes a self-contained `gen3_2f85.xml`.

Run with the .mjtools venv python (has mujoco 3.10):
    .mjtools/Scripts/python.exe mujoco/compose_gen3_2f85.py
"""
import os, shutil, mujoco

MEN = os.environ.get("MUJOCO_MENAGERIE_DIR")
if not MEN:
    raise SystemExit("Set MUJOCO_MENAGERIE_DIR to your mujoco_menagerie checkout")
ARM_XML, GRIP_XML = os.path.join(MEN, "kinova_gen3", "gen3.xml"), os.path.join(MEN, "robotiq_2f85", "2f85.xml")
ARM_ASSETS, GRP_ASSETS = os.path.join(MEN, "kinova_gen3", "assets"), os.path.join(MEN, "robotiq_2f85", "assets")

OUTDIR = os.environ.get("RAMMS_MUJOCO_OUTDIR", os.path.join(os.path.dirname(__file__), "gen3_2f85"))
ASSETS = os.path.join(OUTDIR, "assets")
PREFIX = "2f85_"

# Two variants are written:
#
#   gen3_2f85.xml        tracking base — base_link is a real free body welded to a mocap
#                        "base_target" that Unreal drives from the Chaos chair mount. ONLY stable
#                        with RammsMjEndEffectorController owning/smoothing the mocap: simulated
#                        bare, any mocap-vs-base mismatch detonates the stiff weld (50 cm of error
#                        diverges the model in ~60 steps). A kinematic mocap base teleports with
#                        zero velocity, which shakes grasped objects loose when the chair moves; a
#                        welded free base has genuine velocity/momentum so the arm (and anything it
#                        holds) accelerates smoothly with the chair.
#
#   gen3_2f85_fixed.xml  rigid base — no free joint, no mocap, no weld. base_link is fixed to its
#                        parent, so the model is unconditionally stable standalone. This is the
#                        variant for plain MuJoCo simulation in UE, RL scenes, and for composing
#                        onto other robots via <attach>/<model> (an attached sub-model should have
#                        a rigid root; the mount provides its motion).
#
# Near-rigid weld: the controller smooths base_target across physics substeps, so the weld can stay
# stiff (no arm springiness / no wobble from arm motion) without ringing on per-frame target steps.
BASE_WELD_SOLREF  = [0.005, 1.0]        # timeconst 5ms, dampratio 1
BASE_WELD_SOLIMP  = [0.98, 0.999, 0.001, 0.5, 2.0] # near-rigid impedance (dmin,dmax,width,mid,power)
# Damp + add virtual inertia to the free base's 6 DOFs. Without this, the arm's position actuators
# react against the free base and self-excite a low-frequency limit cycle (the EE wobbles at rest).
BASE_FREE_DAMPING  = 30.0
BASE_FREE_ARMATURE = 0.5


def abspath_meshes(spec, assets_dir):
    """Pin every mesh to an absolute source path so it resolves regardless of meshdir."""
    for m in spec.meshes:
        m.file = os.path.join(assets_dir, os.path.basename(m.file))
    spec.meshdir = ""


def compose(tracking_base):
    arm = mujoco.MjSpec.from_file(ARM_XML)
    grip = mujoco.MjSpec.from_file(GRIP_XML)

    abspath_meshes(arm, ARM_ASSETS)
    abspath_meshes(grip, GRP_ASSETS)

    # The arm's home keyframe sizes qpos to the 7 arm joints; adding the gripper's
    # joints would break it. Drop keyframes (a home pose can be re-added later).
    for k in list(arm.keys):
        arm.delete(k)

    # Attach the gripper worldbody at the arm flange site.
    site = arm.site("pinch_site")
    arm.attach(grip, prefix=PREFIX, site=site)

    # The attach kept the arm's <option> (pyramidal cone, impratio 1), which throws away the
    # gripper's grasping-critical contact settings. Restore elliptic friction cone + high
    # impratio so finger/object contact is stable (this is what makes MuJoCo grasping work).
    arm.option.cone = mujoco.mjtCone.mjCONE_ELLIPTIC
    arm.option.impratio = 10.0

    # Menagerie leaves ctrlrange off the continuous joints' actuators (1/3/5/7), so their
    # compiled actuator_ctrlrange is [0,0] — any UI that builds a control slider from it
    # (URLab's simulate widget does) pins those joints at zero. They're position servos, so
    # author a generous +-2*pi setpoint range.
    for act in arm.actuators:
        if act.name in ("joint_1", "joint_3", "joint_5", "joint_7"):
            act.ctrlrange = [-6.28319, 6.28319]

    # Rigid base: with base_link welded into the world, MuJoCo's parent-child
    # contact filter no longer covers base_link<->shoulder_link (the filter is
    # deliberately disabled when the parent is the world weld, so things can
    # rest on the floor). The menagerie collision hulls overlap ~12 mm there by
    # design, and without the exclude that contact exactly cancels joint_1's
    # servo torque (the joint creeps instead of moving).
    if not tracking_base:
        ex = arm.add_exclude()
        ex.name = "base_shoulder"
        ex.bodyname1 = "base_link"
        ex.bodyname2 = "shoulder_link"

    # Dynamic tracking base (see notes at top). Adds 7 qpos (free joint) at the front of qpos.
    base_free_qpos = []
    if tracking_base:
        base = arm.body("base_link")
        fj = base.add_freejoint()
        fj.damping = [BASE_FREE_DAMPING] * 3  # damp base DOFs to kill the arm-reaction resonance
        fj.armature = BASE_FREE_ARMATURE      # virtual inertia for actuator-loop stability

        target = arm.worldbody.add_body()
        target.name = "base_target"
        target.mocap = True
        target.pos = base.pos  # coincident at compile so the weld starts satisfied

        eq = arm.add_equality()
        eq.name = "base_weld"
        eq.type = mujoco.mjtEq.mjEQ_WELD
        eq.objtype = mujoco.mjtObj.mjOBJ_BODY
        eq.name1 = "base_target"
        eq.name2 = "base_link"
        eq.solref = BASE_WELD_SOLREF
        eq.solimp = BASE_WELD_SOLIMP
        # weld data = anchor(3), relpose pos(3), relpose quat(4), torquescale(1)
        eq.data = [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1.0]
        base_free_qpos = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]

    model = arm.compile()
    print(f"composed OK: nbody={model.nbody} njnt={model.njnt} nu={model.nu} ngeom={model.ngeom}")
    print("actuators:", [a.name for a in arm.actuators])

    # Home keyframe: Gen3 home pose (7 arm joints) + gripper open (remaining joints 0).
    arm_home = [0.0, 0.26179939, 3.14159265, -2.26892803, 0.0, 0.95993109, 1.57079633]
    key = arm.add_key()
    key.name = "home"
    key.qpos = base_free_qpos + arm_home + [0.0] * (model.nq - len(base_free_qpos) - len(arm_home))
    key.ctrl = arm_home + [0.0] * (model.nu - len(arm_home))

    # Flatten meshes into one assets folder and rewrite refs to basenames.
    os.makedirs(ASSETS, exist_ok=True)
    for m in arm.meshes:
        src = m.file
        base = os.path.basename(src)
        dst = os.path.join(ASSETS, base)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy(src, dst)
        # to_xml opens the file string relative to CWD, so bake the subfolder into file
        m.file = "assets/" + base
    arm.meshdir = ""
    name = "gen3_2f85" if tracking_base else "gen3_2f85_fixed"
    arm.modelname = name

    out_xml = os.path.join(OUTDIR, name + ".xml")
    os.chdir(OUTDIR)  # so "assets/<mesh>" resolves during to_xml() validation
    with open(out_xml, "w") as f:
        f.write(arm.to_xml())
    print(f"wrote {out_xml}  ({len(arm.meshes)} meshes in assets/)")
    print(f"cone={arm.option.cone}  impratio={arm.option.impratio}")


def main():
    compose(tracking_base=True)   # chair-riding variant (needs RammsMjEndEffectorController)
    compose(tracking_base=False)  # rigid-base variant (standalone sim / <attach> composition)


if __name__ == "__main__":
    main()
