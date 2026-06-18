"""
Build a measured item catalog over Remote Control. Folder enumeration doesn't work
over the RC CDO, but GetBoundingBox on a direct asset path does — so we probe a
generous candidate list and keep whatever measures. For each StaticMesh we store
real bounds (size + bottom offset + pivot->centre offset) so items rest exactly on
boards, and classify graspable (min horizontal side <= gripper opening) vs clutter.

Output: item_catalog.json  (used by the scene filler / randomizer).
Run any time (reads assets only — safe during PIE):  python catalog_items.py
"""
from __future__ import annotations
import json, os
from ramms_tools.unreal_remote import UnrealRemote, UnrealRemoteError

GRIPPER_OPEN = 8.5
OUT = os.path.join(os.path.dirname(__file__), "item_catalog.json")
CS = "/Game/ConvenienceStore/Mesh/"
BK = "/Game/BookStackBPV2/Meshes/"


def candidates():
    names = []
    # convenience-store products (graspable + clutter; classified by measured bounds)
    bases = {
        "SM_potatochips_01": 4, "SM_chip": 4, "SM_milk": 4, "SM_wineglass": 3,
        "SM_handsoap": 3, "SM_soapliquid": 3, "SM_candy_01": 9, "SM_cigarette": 5,
        "SM_lighter": 5, "SM_medicinal": 6, "SM_batteries": 4, "SM_toothpaste": 3,
        "SM_beerbottle": 3, "SM_bottledwater": 3, "SM_beancan": 3, "SM_cancond": 3,
        "SM_canfish": 3, "SM_wine": 4, "SM_box": 4, "SM_cardbox": 3, "SM_beerbox": 3,
        "SM_ball": 4, "SM_jar": 4, "SM_bowl": 3, "SM_cup": 4, "SM_bread": 3,
    }
    for b, n in bases.items():
        names.append(CS + b)                                  # bare name
        for i in range(1, n + 1):
            names.append(f"{CS}{b}_{i:02d}")                  # SM_x_01
            names.append(f"{CS}{b}_01_{i:02d}")               # SM_x_01_01 style
    books = [BK + "P_GenBook01", BK + "P_SingleBook01", BK + "P_GenBook02", BK + "P_GenBook03"]
    return names + books


def main():
    ue = UnrealRemote(timeout=60)
    if not ue.ping():
        raise SystemExit("RC unreachable")
    seen, items = set(), []
    for p in candidates():
        name = p.split("/")[-1]
        obj = f"{p}.{name}"
        if obj in seen:
            continue
        seen.add(obj)
        try:
            bb = ue.actor(obj).call("GetBoundingBox")
        except UnrealRemoteError:
            continue
        if not isinstance(bb, dict) or "Min" not in bb or not bb.get("IsValid", True):
            continue
        mn, mx = bb["Min"], bb["Max"]
        sx, sy, sz = mx["X"] - mn["X"], mx["Y"] - mn["Y"], mx["Z"] - mn["Z"]
        if min(sx, sy, sz) <= 0:
            continue
        is_big = max(sx, sy) > 60 or sz > 70
        graspable = (min(sx, sy) <= GRIPPER_OPEN) and sz < 45 and max(sx, sy) < 45 and not is_big
        items.append({
            "name": name, "path": obj,
            "sx": round(sx, 1), "sy": round(sy, 1), "sz": round(sz, 1),
            "min_z": round(mn["Z"], 2),
            "off_x": round((mn["X"] + mx["X"]) / 2, 2),
            "off_y": round((mn["Y"] + mx["Y"]) / 2, 2),
            "graspable": bool(graspable), "big": bool(is_big),
        })
    json.dump(items, open(OUT, "w"), indent=1)
    g = [i["name"] for i in items if i["graspable"]]
    c = [i["name"] for i in items if not i["graspable"] and not i["big"]]
    big = [i["name"] for i in items if i["big"]]
    print(f"measured {len(items)} meshes -> {OUT}")
    print(f"  graspable ({len(g)}): {g}")
    print(f"  clutter   ({len(c)}): {c}")
    print(f"  big/props ({len(big)}): {big}")


if __name__ == "__main__":
    main()
