"""(Re)import the MeBot MJCF (powered-front variant) as a URLab articulation.

Step 1 of 3; the importer replaces the articulation, so what is built on it is rebuilt after:

    import_mebot_mjcf.py      <- here: the articulation, from mujoco/mebot in this repository
    make_mebot_pawn.py        the pawn on it (motor table, drive, lifts, input, cameras)
    make_mebot_curb_map.py    the game mode and the curb level

Import from the in-repo MJCF, never a copy elsewhere: MjMesh components record each mesh file's
path and MuJoCo reads those files when the scene compiles at BeginPlay, so an import from a scratch
folder resolves only on the machine that did it. URLab imports the .glb beside each mesh; they are
generated (and committed) by its converter, from a Python with trimesh, numpy, scipy, networkx and
Pillow:

    python -I Plugins/unreal-robotics-lab/Scripts/clean_meshes.py mujoco/mebot/mebot_powered_front.xml --out-dir Saved/URLabPrep

Run inside the editor, with PIE stopped:
    python Scripts/editor_remote_exec.py --file Scripts/mebot_mujoco/import_mebot_mjcf.py
"""

import os

import unreal

SRC_REL = "mujoco/mebot/mebot_powered_front.xml"
DEST = "/Game/Robots/MeBot/URL"
NAME = "mebot_powered_front"
ASSET = DEST + "/" + NAME
PAWN = "/Game/Robots/MeBot/BP_MebotPoweredFront_Ramms"
MESHES = "/Game/MuJoCoImports/%s_Assets" % NAME

EAL = unreal.EditorAssetLibrary
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)

if ues.get_game_world() is not None:
    les.editor_request_end_play()
    raise RuntimeError("PIE was running -- stopped it; re-run this script")

PROJECT_DIR = os.path.normpath(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()))
src = os.path.normpath(os.path.join(PROJECT_DIR, SRC_REL))
if not os.path.exists(src):
    raise RuntimeError("missing %s" % src)
model_dir = os.path.dirname(src)
missing = [f for f in os.listdir(os.path.join(model_dir, "meshes")) if f.endswith(".stl")
           and not os.path.exists(os.path.join(model_dir, "meshes", f[:-4] + ".glb"))
           and ("__caster_rubber" not in f)]
if missing:
    raise RuntimeError("%d meshes have no .glb beside them (e.g. %s): run clean_meshes.py first" % (len(missing), missing[0]))
print("[import] source: %s" % src)

# The factory refuses to overwrite an existing Blueprint, so clear the way: the pawn (a child
# Blueprint of the articulation, rebuilt by make_mebot_pawn.py) first, then the articulation.
for path in (PAWN, ASSET):
    if EAL.does_asset_exist("%s.%s" % (path, path.rsplit("/", 1)[-1])):
        unreal.SystemLibrary.collect_garbage()
        if not EAL.delete_asset(path):
            raise RuntimeError("could not delete %s to make way for the import" % path)
        print("[import] removed the previous %s" % path)
# And the previous import's meshes: URLab hands back any mesh already at its destination untouched,
# so a stale one would stay on screen while MuJoCo simulates the new geometry.
if EAL.does_directory_exist(MESHES):
    unreal.SystemLibrary.collect_garbage()
    if not EAL.delete_directory(MESHES):
        raise RuntimeError("could not delete %s to make way for the import" % MESHES)
    print("[import] removed the previous meshes in %s" % MESHES)

task = unreal.AssetImportTask()
task.set_editor_property("filename", src)
task.set_editor_property("destination_path", DEST)
task.set_editor_property("destination_name", NAME)
task.set_editor_property("automated", True)   # no dialog; unanswered = cancel
task.set_editor_property("replace_existing", True)
task.set_editor_property("save", True)
unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
imported = list(task.get_editor_property("imported_object_paths") or [])
if not imported:
    raise RuntimeError("import produced nothing -- check the log")
print("[import] imported: %s" % imported)

path = imported[0].split(".")[0]
bp = unreal.load_object(None, "%s.%s" % (path, path.rsplit("/", 1)[-1]))

# Provenance relative to the project, so the articulation names no one machine's folders; then the
# saved bytes are checked for this machine's paths.
fixed = unreal.MjProvenanceLibrary.make_provenance_project_relative(bp)
if fixed:
    print("[import] recorded %d provenance paths relative to the project" % fixed)
if not EAL.save_loaded_asset(bp, False):
    raise RuntimeError("could not save %s" % path)
saved = unreal.SystemLibrary.get_system_path(bp)
with open(saved, "rb") as fh:
    blob = fh.read()
for marker in {PROJECT_DIR.replace(os.sep, "/"), PROJECT_DIR, os.path.expanduser("~").replace(os.sep, "/")}:
    if marker.encode() in blob or marker.encode("utf-16-le") in blob:
        raise RuntimeError("%s still records '%s'; it would not be portable" % (saved, marker))
print("[import] %s records no machine-specific paths" % os.path.basename(saved))

# Every mesh path must resolve, the way URLab resolves it, to a file in this repository's mujoco/ folder: the robot's
# own in mujoco/mebot, the arm's in mujoco/gen3_2f85.
mujoco_dir = os.path.dirname(model_dir)
SDS = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
B = unreal.SubobjectDataBlueprintFunctionLibrary
outside, total = [], 0
for h in SDS.k2_gather_subobject_data_for_blueprint(bp):
    o = B.get_object_for_blueprint(SDS.k2_find_subobject_data_from_handle(h), bp)
    if o is None or o.get_class().get_name() != "MjMesh":
        continue
    total += 1
    f = o.get_file()
    source = o.get_editor_property("source_file")
    base = os.path.dirname(source if os.path.isabs(source) else os.path.join(PROJECT_DIR, source))
    where = os.path.normpath(f if os.path.isabs(f) else os.path.join(base, f))
    if not where.startswith(mujoco_dir + os.sep) or not os.path.exists(where):
        outside.append("%s -> %s" % (f, where))
if outside:
    raise RuntimeError("%d of %d mesh paths do not resolve to a file in %s, e.g. %s" % (len(outside), total, mujoco_dir, outside[0]))
print("[import] all %d mesh paths resolve to files in %s" % (total, mujoco_dir))
meshes = EAL.list_assets(MESHES, recursive=True) if EAL.does_directory_exist(MESHES) else []
print("[import] %d mesh assets in %s" % (len(meshes), MESHES))
