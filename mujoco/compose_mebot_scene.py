"""
Compose a driveable MuJoCo scene from the robot_export.py MeBot artifact.

The raw exporter output (`UE_VAULT_EXPORT/rammp_parts/mebot/mebot.mjcf.xml`)
compiles but cannot drive; this script applies the fixes found during the
2026-08-07 validation (see doc/rammp_robot_pipeline.md "MJCF validation
findings"):

- Free-floating base (freejoint) + ground plane.
- Self-collision off via contype/conaffinity (the dense CAD boxes all
  interpenetrate — unfiltered, internal contacts jam the mechanism solid).
- Provisional suspension springs (dojo_spring_* are still FILL-ME in the
  blend; passive linkages otherwise collapse to their limits).
- Omniwheel "casters": the front/rear wheels are omniwheels (single roll
  axis, exactly as exported — no swivel), approximated with low sliding
  friction so the rollers' free lateral slip is captured without simulating
  the rollers themselves. Note for any future extra joints: keep ONE joint
  per body — newton's importer fuses multi-joint bodies into renamed
  compound joints, breaking name-based state mapping.
- 60 N.m drive gear: with the placeholder 20 N.m gear and 224 kg auto-mass
  the drive wheels cannot overcome the passive wheels' grip, so
  differential turning stalls.

PROVISIONAL values (marked *): springs*, caster friction*, drive gear* —
replace with measured values via the Blender dojo_* annotations, then
regenerate. Masses are still exporter auto-density (~224 kg total).

Run with any python that has mujoco (e.g. the Newton plugin venv):
    Plugins/RammsNewtonPhysics/Scripts/.venv/Scripts/python.exe mujoco/compose_mebot_scene.py

Validated 2026-08-07 (plain MuJoCo): settles static, drives +3.4 m/3 s
straight, differential-turns ~44 deg/3 s. Under Newton SolverMuJoCo (GPU)
the same scene loads and steps finite but the contact response diverges
(spin-out during straight driving) — the known upstream contact-set
translation issue; see Plugins/RammsNewtonPhysics/README.md Known issues.
"""
import os
import xml.etree.ElementTree as ET
from pathlib import Path

SRC = Path(os.environ.get(
    "MEBOT_EXPORT_XML",
    r"C:\Users\waemf\data\UE_VAULT_EXPORT\rammp_parts\mebot\mebot.mjcf.xml"))
OUT_ROBOT = Path(__file__).parent / "mebot" / "mebot.xml"        # robot only — import THIS into UE maps
OUT = Path(__file__).parent / "mebot" / "mebot_scene.xml"         # robot + floor — standalone CLI/viewer use

DRIVE_GEAR = "60.0"          # * placeholder-upgrade; real motor spec TBD
ROD_GEAR = "2500.0"          # * leadscrew linear actuators (kN-class); real spec TBD
ROD_LEADSCREW_DAMPING = "20000"  # * leadscrew self-locking approximation
CASTER_FRICTION = "0.12 0.002 0.0002"  # * omniwheel: low but enough tangential force to ROLL (0.05 + 0.2 axle frictionloss left them skidding on ramps)
SUSPENSION_STIFFNESS = "20000"        # * FILL-ME in blend; holds rest pose
SUSPENSION_DAMPING = "500"


def main() -> None:
    tree = ET.parse(SRC)
    root = tree.getroot()
    wb = root.find("worldbody")
    mebot = wb.find("body")
    assert mebot is not None and mebot.get("name") == "mebot", "unexpected export layout"

    # Floating base slightly above ground; settles onto the wheels.
    mebot.insert(0, ET.Element("freejoint", {"name": "mebot_root"}))
    mebot.set("pos", "0 0 0.05")

    # Robot-robot contacts off, robot-floor/world on. Skip geoms that
    # declare contype="0" (the exporter's non-colliding visual meshes).
    for g in mebot.iter("geom"):
        if g.get("contype") == "0":
            continue
        g.set("contype", "1")
        g.set("conaffinity", "2")

    # With the loop closures authored (2026-08-07) the mechanism holds itself
    # kinematically; springs belong ONLY on the real spring-damper elements
    # (the *dampener* joints). Everything else gets light damping so the
    # closed linkages don't ring. Skip joints whose stiffness the exporter
    # authored (dojo_spring_*) — those are authoritative.
    for j in mebot.iter("joint"):
        n = j.get("name", "")
        # Rest-state jitter (headless bench 2026-08-14): reflected rotor
        # inertia on the linkage hinges kills the closure micro-oscillation
        # (qvel RMS 0.085 -> 0.0018); damping+frictionloss stops the wheels
        # rocking perpetually on their near-frictionless contacts.
        if j.get("type") != "slide" and "wheel" not in n:
            j.set("armature", "0.005")
        if "wheel" in n:
            # Anti-rock via ARMATURE (rotor inertia — no steady-state brake),
            # tiny damping only. damping=5 on the casters sustained barely
            # ~1 rad/s against the available contact torque: they skidded
            # down ramps instead of rolling (rolled 0.4 m of a 4.9 m slide).
            j.set("armature", "0.005")
            if "drive_wheel" in n:
                j.set("damping", "0.5")
                j.set("frictionloss", "0.05")
            else:
                j.set("damping", "0.3")
                j.set("frictionloss", "0.02")
        elif j.get("stiffness") is not None:
            # Authored dojo_spring values are kept. (2026-08-14: the rear
            # strut was briefly softened to 300 because the chain "froze"
            # with the authored 20000 — user then saw the soft strut absorb
            # the whole rod stroke instead of rotating the swing arm. Root
            # cause was ROD SERVO FORCE STARVATION: the rod drives the
            # suspension arm through a ~1.1 cm anchor lever, so kp=6e4
            # tops out at ~35 N.m vs the ~80 N.m needed to articulate the
            # wheel-carrier swing arm against ground load. Strut stays
            # authored-stiff; rod kp raised instead — see actuator block.)
            if n in ("rear_caster_dampener", "rear_caster_dampener_rod"):
                j.set("damping", "500")
        elif "rod_link" in n:
            # small connecting links windmill about their pins otherwise
            j.set("damping", "50")
        elif n.startswith("dw_main_plate"):
            # * carriage-lock stand-in: the drive-wheel carriage slides in X
            # for adjustment and is mechanically locked in operation.
            j.set("stiffness", "100000")
            j.set("damping", "2000")
        elif j.get("type") == "slide" and "dampener" not in n:
            j.set("damping", "500")
        elif "dampener" in n:
            if "pivot" in n:
                # motor_dampener_pivot is a linkage PIVOT that merely
                # carries the strut — name-matching "dampener" gave it the
                # full 2e4 suspension spring and it became the 5.1 kN wall
                # freezing the rear chain (eq11 force probe). Spring
                # belongs in the strut, not the pivot. 2026-08-14: even the
                # 200/200 stand-in was too much for the CHAOS side — its
                # iterative solver leaks pin force, and a 200 N.m/rad hold
                # on the bell crank froze the pivot (aux moved 16 deg,
                # pivot 1 deg, swing arm dead). A bell crank needs no
                # spring; light damping only.
                j.set("stiffness", "20")
                j.set("damping", "50")
            elif j.get("type") == "slide":
                # 2026-08-16 (user decision): model the gas dampeners as
                # FIXED-LENGTH struts — a rigid link. (A 1e6 spring was
                # tried first and is dt-unstable in MuJoCo: NaN in 1.7 s.)
                # Removing the slide joint makes the dampener_rod body a
                # rigid child of the dampener: MuJoCo welds jointless
                # bodies; the Chaos generator emits a weld constraint for
                # them. Marked for removal below (can't mutate while
                # iterating).
                j.set("dojo_remove", "1")
            else:
                # dampener HINGES are the strut's end pivots: a rigid strut
                # still pivots there. No spring, light damping.
                j.set("stiffness", "0")
                j.set("damping", "50")
        elif n in ("motor_elevator_l", "motor_elevator_r"):
            # Elevator trunnions carry the robot's weight during lifts:
            # damping 500 (bench: ringing RMS 2.96 -> 0.04; lighter rings
            # and slides the base >1 m; 1500 raised REST jitter to 0.15 —
            # the trunnions are on the closure loop and over-damping them
            # fights the pins).
            j.set("damping", "500")
        elif n.endswith("caster_motor"):
            # Caster trunnions carry no lift load — heavy damping froze the
            # caster chains (mobility bench); 50 keeps them quick and quiet.
            j.set("damping", "50")
        elif n in ("front_caster_swing_arm", "rear_caster_swing_arm"):
            # * stand-in: the front caster has no dampener chain in the
            # export; the elevator/rear are held by their REAL dampener
            # closures (user-confirmed attachment, 2026-08-09).
            j.set("stiffness", "200")
            j.set("damping", "200")
        elif n in ("motor_elevator_pivot_l", "motor_elevator_pivot_r"):
            # * gas-spring PRELOAD stand-in: the real dampener closure is
            # authored (dampener_link->pivot, ~1.8 cm arm) but holding
            # ~250 N.m of chassis load through that arm needs the gas
            # spring's preload (~14 kN-class), which a linear rest-spring
            # emulates until measured specs land.
            j.set("stiffness", "1000")
            j.set("damping", "200")
        elif n in ("motor_swing_arm_l", "motor_swing_arm_r"):
            # Load-path joint during lifts — 5 let the carriage bounce
            # indefinitely (12 rad/s ringing); 150 with the kp=6e5 rods.
            j.set("damping", "150")
        else:
            j.set("damping", "5")

    # Remove joints marked above (dampener rod slides -> rigid struts).
    for body in mebot.iter("body"):
        for j in list(body.findall("joint")):
            if j.get("dojo_remove") == "1":
                body.remove(j)
                print("  rigid strut: removed slide joint", j.get("name"))

    # The front/rear "caster" wheels are OMNIWHEELS, not swivel casters: one
    # roll axis (as exported), with the rollers letting the contact patch
    # slide sideways. Until the rollers themselves are simulated, approximate
    # that with low sliding friction on the wheel geoms — they carry vertical
    # load but contribute little tangential force, so the drive wheels own
    # traction and yaw.
    # priority=1: MuJoCo pairwise friction is the elementwise MAX of the two
    # geoms unless one has higher priority — without it the floor's default
    # friction=1 silently wins and the low omniwheel friction is a no-op.
    for b in mebot.iter("body"):
        if "caster_wheel" in b.get("name", ""):
            for g in b.iter("geom"):
                if g.get("contype") != "0":
                    g.set("friction", CASTER_FRICTION)
                    g.set("priority", "1")

    for mtr in list(root.find("actuator")):
        if "drive_wheel" in mtr.get("name", ""):
            mtr.set("gear", DRIVE_GEAR)
        elif "rod" in mtr.get("name", ""):
            # Leadscrew rods are POSITION SERVOS: they hold commanded
            # extension when idle (self-locking) and ctrl = target
            # extension in metres — the natural control API. Force capacity
            # Micro electro-hydraulic (user-confirmed): high-force class,
            # provisional 15 kN capacity until measured specs land. Servo
            # stiffness is dt-limited: kp=1e6 (with kv=6e3) rang at ~1.4 kHz
            # on the light rods and pogo-sticked the robot after impacts.
            # BUT kp=6e4 force-starves the rear chain: the rod pin sits
            # ~1.1 cm from the suspension-arm axis, so max servo torque
            # there is kp*stroke*0.011 — not enough to move the wheel-
            # carrier swing arm against ground load (bench 2026-08-14:
            # swing arm 0.000 rad at any strut stiffness). kp=6e5 with
            # PROPORTIONAL kv=6e4 (the old ring had kv 100x under kp)
            # articulates the swing arm 0.30 rad with zero ring — but ONLY
            # with dampratio=1 (critical kv from the REFLECTED inertia,
            # which the tiny anchor levers make enormous; any fixed kv is
            # orders under-damped and the whole robot rocks at rest,
            # qvel RMS 1.36). Verified: rest 0.003 / drop / whack stable.
            name = mtr.get("name")
            jnt = mtr.get("joint")
            parent = root.find("actuator")
            parent.remove(mtr)
            import xml.etree.ElementTree as _ET
            _ET.SubElement(parent, "position", name=name, joint=jnt,
                           kp="600000", dampratio="1",
                           ctrlrange="-0.08 0.08", forcerange="-20000 20000")

    root.find("option").set("integrator", "implicitfast")

    # Robot-only artifact FIRST (no floor): this is what gets imported into
    # UE maps — the map supplies its own ground/world. Importing the *_scene
    # variant into a populated level plants an invisible 40x40 m collision
    # plane through everything (observed: instant local instability).
    OUT_ROBOT.parent.mkdir(parents=True, exist_ok=True)
    OUT_ROBOT.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    print(f"wrote {OUT_ROBOT} (robot only — use for UE import)")

    ET.SubElement(wb, "geom", {
        "name": "floor", "type": "plane", "size": "20 20 0.1",
        "contype": "1", "conaffinity": "1"})
    OUT.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")
    print(f"wrote {OUT} (with floor — standalone CLI/viewer)")

    # Carry the exporter's visual meshes (assets/*.obj, ~18 MB) alongside the
    # scene so its relative refs resolve from mujoco/mebot/.
    src_assets = SRC.parent / "assets"
    if src_assets.is_dir():
        import shutil

        shutil.copytree(src_assets, OUT.parent / "assets", dirs_exist_ok=True)
        print(f"copied {sum(1 for _ in (OUT.parent / 'assets').iterdir())} visual meshes")

    import mujoco

    for path in (OUT_ROBOT, OUT):
        m = mujoco.MjModel.from_xml_path(str(path))
        print(f"{path.name}: nq={m.nq} nv={m.nv} nu={m.nu} nbody={m.nbody} "
              f"mass={sum(m.body_mass):.1f}kg")


if __name__ == "__main__":
    main()
