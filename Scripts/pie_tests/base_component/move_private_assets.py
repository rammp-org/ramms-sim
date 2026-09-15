"""Move the lift-drive assets from /Game into the RammsPrivateAssets plugin.

One-shot migration (kept for the record / to redo after a re-import). Uses the
editor's rename so every referencer is fixed up, then deletes the redirectors
left behind so nothing public points into the private plugin. Requires the
plugin to be present under Plugins/ and the editor restarted so it is mounted.

Run in the editor via Scripts/editor_remote_exec.py --file <this file>.
"""
import unreal

EAL = unreal.EditorAssetLibrary
SRC, DST = "/Game", "/RammsPrivateAssets"
DIRS = ["/MuJoCoImports/lift_drive_holonomic_ue_Assets", "/MuJoCoImports/lift_drive_linkage_ue_Assets"]
ASSETS = ["/Robots/URL/lift_drive_holonomic", "/Robots/URL/lift_drive_linkage",
          "/Robots/Data/DT_LiftDriveLinkage_Motors", "/Robots/Data/DT_LiftDriveLinkage_5Bar", "/Robots/Data/DT_LiftDriveHolonomic_Motors",
          "/Robots/BP_LiftDriveLinkage_Ramms", "/Robots/BP_LiftDriveHolonomic_Ramms", "/Robots/BP_LiftDriveTestGameMode",
          "/Maps/URL/Map_BaseTest_URL"]


def log(s):
    unreal.log("[move] " + str(s))


if not EAL.does_directory_exist(DST + "/"):
    raise RuntimeError("%s is not mounted — is Plugins/RammsPrivateAssets present and the editor restarted?" % DST)

# The map must not be the open level while it is renamed.
world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
if "Map_BaseTest_URL" in world.get_path_name():
    unreal.EditorLoadingAndSavingUtils.load_map("/Game/Maps/Map_Demo")
    log("switched the open level to Map_Demo")

for d in DIRS:
    if EAL.does_directory_exist(SRC + d + "/"):
        ok = EAL.rename_directory(SRC + d, DST + d)
        log("dir %s -> %s : %s" % (SRC + d, DST + d, ok))
for a in ASSETS:
    if EAL.does_asset_exist(SRC + a):
        ok = EAL.rename_asset(SRC + a, DST + a)
        log("asset %s -> %s : %s" % (SRC + a, DST + a, ok))

# Redirectors left at the old locations: nothing should reference them any
# more (the rename fixed every referencer up), so drop them.
redirectors = []
for root in ["/Game/Robots", "/Game/MuJoCoImports", "/Game/Maps/URL"]:
    for path in EAL.list_assets(root, True, False):
        data = EAL.find_asset_data(path)
        if str(data.asset_class_path.asset_name) == "ObjectRedirector":
            refs = [str(r) for r in EAL.find_package_referencers_for_asset(path, False)]
            if refs:
                log("WARNING redirector %s still referenced by %s — kept" % (path, refs))
                continue
            redirectors.append(path)
for r in redirectors:
    EAL.delete_asset(r)
log("deleted %d redirectors" % len(redirectors))
for d in DIRS:
    if EAL.does_directory_exist(SRC + d + "/") and not EAL.list_assets(SRC + d, True, False):
        EAL.delete_directory(SRC + d)
        log("removed empty %s" % (SRC + d))

EAL.save_directory(DST, True, True)

# Verify: nothing outside the private plugin references the moved content.
bad = []
for path in EAL.list_assets(DST, True, False):
    for r in EAL.find_package_referencers_for_asset(path, False):
        if not str(r).startswith(DST):
            bad.append((path, str(r)))
log("public referencers of private content: %s" % (bad if bad else "none"))
log("private assets: %d" % len(EAL.list_assets(DST, True, False)))
log("left in /Game/Robots: %s" % [p for p in EAL.list_assets("/Game/Robots", True, False) if "LiftDrive" in p or "lift_drive" in p])
