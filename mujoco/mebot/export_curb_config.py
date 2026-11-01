#!/usr/bin/env python3
"""Write the MeBot curb controller's configuration from the model: curb_config_<variant>.json next to this file.

    python mujoco/mebot/export_curb_config.py [--variant powered_front|standard]

URammsMebotCurbController (ramms-core) runs curb_sequence.py's crossing in Unreal; it needs what that script
reads from the model, which Unreal's Python cannot compute (it has no MuJoCo):

  - each support's height table: how far its wheels' bottom rises (cm, chassis level) from the reference
    pose as its joint turns (rad) -- the drive wheels and front omni wheels from the kinematics, the sprung
    rear through its linkage, unloaded (curb_sequence.Crossing.support_tables);
  - the wheels' radii, the frame's clearance, the lift speeds;
  - the mass model for the rear-lift rule: the chassis-fixed mass (rider included) and its centre of mass
    ahead of the chassis origin, and each drive assembly (its translator's subtree) and its centre of mass
    ahead of its wheel's hub, at the reference pose.

Scripts/mebot_mujoco/make_mebot_pawn.py writes the file's fields onto the pawn's controller (property names
in snake case, as Unreal's Python names FRammsMebotCurbConfig's). Needs the mujoco Python package.
"""
import argparse
import json
import os
import sys

import mujoco
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import curb_sequence as S  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--variant", choices=("powered_front", "standard"), default="powered_front")
    args = ap.parse_args()
    cx = S.Crossing(args.variant, "up", 0.15, 0.03)   # the tables do not depend on the curb
    m, d = cx.m, mujoco.MjData(cx.m)
    mujoco.mj_forward(m, d)

    def table(key):
        qs, bs = cx.tables[key]
        order = np.argsort(qs)
        return {"angle_rad": [round(float(q), 6) for q in np.asarray(qs)[order]],
                "height_cm": [round(float(b) * 100.0, 4) for b in np.asarray(bs)[order]]}

    chassis = m.body("chassis").id
    total = float(m.body_subtreemass[chassis])
    com_total = d.subtree_com[chassis].copy()
    assemblies = []
    for side in ("l", "r"):
        b = m.body("translator_" + side).id
        assemblies.append((float(m.body_subtreemass[b]), d.subtree_com[b].copy(), d.body("drive_wheel_" + side).xpos.copy()))
    drive_mass = sum(a[0] for a in assemblies) / 2.0
    fixed_mass = total - sum(a[0] for a in assemblies)
    fixed_com = (com_total * total - sum(a[0] * a[1] for a in assemblies)) / fixed_mass
    R = d.body("chassis").xmat.reshape(3, 3)
    fixed_ahead = float((R.T @ (fixed_com - d.body("chassis").xpos))[0])
    fwd = R[:, 0]
    assembly_ahead = float(np.mean([(a[1] - a[2]) @ fwd for a in assemblies]))

    num = lambda n: float(m.numeric(n).data[0])
    cfg = {
        "drive_wheel_radius_cm": round(num("drive_wheel_radius") * 100.0, 3),
        "front_omni_radius_cm": round(num("front_omni_radius") * 100.0, 3),
        "rear_omni_radius_cm": round(num("rear_omni_radius") * 100.0, 3),
        "belly_clearance_cm": round(cx.belly * 100.0, 3),
        "drive_table": table("elevator_l"),
        "front_table": table("front_arm"),
        "rear_table": table("rear_lift"),
        "fixed_mass_kg": round(fixed_mass, 3),
        "fixed_com_ahead_cm": round(fixed_ahead * 100.0, 3),
        "drive_assembly_mass_kg": round(drive_mass, 3),
        "drive_assembly_com_from_hub_cm": round(assembly_ahead * 100.0, 3),
        "elevator_speed_deg_s": num("elevator_speed_deg_s"),
        "front_arm_speed_deg_s": num("caster_arm_speed_deg_s"),
        "rear_lift_speed_deg_s": num("rear_lift_speed_deg_s"),
        "translator_speed_cm_s": num("translator_speed_cm_s"),
    }
    if args.variant != "powered_front":
        cfg["front_omni_left"] = cfg["front_omni_right"] = "None"
    out = os.path.join(HERE, "curb_config_%s.json" % args.variant)
    with open(out + ".tmp", "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"variant": args.variant, "generated_by": "export_curb_config.py", "config": cfg}, fh, indent=1)
    os.replace(out + ".tmp", out)
    print("wrote %s: tables %d / %d / %d points, mass %.1f kg fixed (centre of mass %.1f cm ahead of the chassis origin) + 2 x %.1f kg "
          "drive assemblies (%.1f cm from their hubs), frame clearance %.1f cm" % (
              os.path.basename(out), len(cfg["drive_table"]["angle_rad"]), len(cfg["front_table"]["angle_rad"]),
              len(cfg["rear_table"]["angle_rad"]), fixed_mass, fixed_ahead * 100, drive_mass, assembly_ahead * 100, cx.belly * 100))


if __name__ == "__main__":
    main()
