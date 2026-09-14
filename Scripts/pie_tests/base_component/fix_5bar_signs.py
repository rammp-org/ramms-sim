import json, unreal
dt = unreal.EditorAssetLibrary.load_asset("/Game/Robots/Data/DT_LiftDriveLinkage_5Bar")
def fivebar(name, ma, mb, pa, pb, zda, sa, eua, zdb, sb, eub, flip):
    return {"Name": name, "ProximalMotorA": ma, "ProximalMotorB": mb,
            "PivotA": {"X": pa[0], "Y": pa[1]}, "PivotB": {"X": pb[0], "Y": pb[1]},
            "ProximalLengthA": 16.0, "DistalLengthA": 22.5, "ProximalLengthB": 16.0, "DistalLengthB": 22.5,
            "ZeroDirA": zda, "AngleSignA": sa, "ZeroDirB": zdb, "AngleSignB": sb,
            "bElbowUpA": eua, "bElbowUpB": eub, "bFlipEndpointSide": flip}
# MuJoCo hinge about +Y rotates +X toward -Z: link angle (atan2(z,x)) = ZeroDir - q  => Sign = -1 for axis +Y, +1 for axis -Y.
rows = [
    fivebar("left_center",  "left_center_hip_a",  "left_center_hip_b",  (6.5, 20.993), (-6.5, 20.992), -0.2397, -1.0, True,  -2.9019,  1.0, False, False),  # hip_a +Y, hip_b -Y
    fivebar("right_center", "right_center_hip_a", "right_center_hip_b", (-6.5, 20.993), (6.5, 20.993), -2.9019,  1.0, False, -0.2397, -1.0, True,  True),   # hip_a -Y, hip_b +Y
]
ok = unreal.DataTableFunctionLibrary.fill_data_table_from_json_string(dt, json.dumps(rows))
unreal.EditorAssetLibrary.save_loaded_asset(dt)
unreal.log("[fix5] refilled=%s rows=%s" % (ok, [str(n) for n in unreal.DataTableFunctionLibrary.get_data_table_row_names(dt)]))
