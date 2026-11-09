"""Build (or rebuild) the kit's assets from rig.json, in this plugin's content (/RammpGen1FisheyeKit/):

  Robots/BP_RammpGen1_Fisheye    child Blueprint of /Game/Robots/BP_RammpGen1_Ramms (RAMMP Gen1, formerly the MeBot) with the six TN_* fisheyes
                                 (FisheyeSceneCaptureComponent, Kannala-Brandt lens) and an RMSS_Stream source
                                 that starts the RMSS server and a disk-free capture on Play
  BP_RammpGen1FisheyeGameMode    child of /Game/BP_RammpGen1GameMode spawning BP_RammpGen1_Fisheye
  Sensors/TechNexion_AR0234_S191_Intrinsics   the lens' intrinsics

BP_RammpGen1_Ramms and the maps are never modified: the cameras live in the child, and the parent's Orbbec
Gemini cameras (which sit where the front fisheyes mount) are switched off through the child's override of
those inherited components. Run headless from the ramms-sim root (Play must not be running in an editor):

  UnrealEditor-Cmd "$PWD/Ramms.uproject" -run=pythonscript -script="$PWD/Plugins/RammpGen1FisheyeKit/Scripts/build_kit.py"
"""
import hashlib
import json
import os

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
RIG = json.load(open(os.path.join(os.path.dirname(HERE), "rig.json")))
ROOT = "/RammpGen1FisheyeKit"
PARENT_BP = "/Game/Robots/BP_RammpGen1_Ramms"
PARENT_GM = "/Game/BP_RammpGen1GameMode"
PAWN = (f"{ROOT}/Robots", "BP_RammpGen1_Fisheye")
GM = (ROOT, "BP_RammpGen1FisheyeGameMode")
INTR = (f"{ROOT}/Sensors", "TechNexion_AR0234_S191_Intrinsics")
MOUNT = "Mesh"  # the parent's base mesh; rig.json poses are relative to it
PREFIX, STREAM = "TN_", "RMSS_Stream"
GEMINI = ("Gemini", "SM_Gemini")  # name prefixes of the parent's Orbbec Gemini 336L units

sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
lib = unreal.SubobjectDataBlueprintFunctionLibrary
tools = unreal.AssetToolsHelpers.get_asset_tools()
eal = unreal.EditorAssetLibrary


def log(msg):
    unreal.log(f"[fisheye kit] {msg}")


def existing(path):
    """The asset at path, or None (the kit folder is scanned first, see below)."""
    return unreal.load_asset(path) if eal.does_asset_exist(path) else None


def child_blueprint(folder, name, parent_path):
    path = f"{folder}/{name}"
    bp = existing(path)
    if bp is not None:
        return bp
    f = unreal.BlueprintFactory()
    f.set_editor_property("parent_class", unreal.load_asset(parent_path).generated_class())
    bp = tools.create_asset(name, folder, unreal.Blueprint, f)
    log(f"created {path} (child of {parent_path})")
    return bp


def intrinsics():
    folder, name = INTR
    path = f"{folder}/{name}"
    asset = existing(path)
    if asset is None:
        f = unreal.DataAssetFactory()
        f.set_editor_property("data_asset_class", unreal.CameraIntrinsicsAsset)
        asset = tools.create_asset(name, folder, unreal.CameraIntrinsicsAsset, f)
    lens = RIG["lens"]
    intr = asset.get_editor_property("intrinsics")
    for k, v in {"focal_length_x": lens["fx"], "focal_length_y": lens["fy"], "principal_point_x": lens["cx"],
                 "principal_point_y": lens["cy"], "image_width": lens["width"], "image_height": lens["height"],
                 "preset_name": "TechNexion VLS-GM2-AR0234-C-S191 (Kannala-Brandt fisheye)"}.items():
        intr.set_editor_property(k, v)
    asset.set_editor_property("intrinsics", intr)
    eal.save_loaded_asset(asset)
    return asset


def handles(bp):
    out = {}
    for h in sub.k2_gather_subobject_data_for_blueprint(bp):
        d = lib.get_data(h)
        out.setdefault(str(lib.get_variable_name(d)), (h, d))
    return out


def add(bp, parent, cls, name):
    h, fail = sub.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=parent, new_class=cls, blueprint_context=bp))
    if not fail.is_empty():
        raise RuntimeError(f"adding {name}: {fail}")
    sub.rename_subobject(h, unreal.Text(name))
    return h, lib.get_object(lib.get_data(h))


def build_pawn(lens_asset):
    bp = child_blueprint(*PAWN, PARENT_BP)
    hs = handles(bp)
    root = sub.k2_gather_subobject_data_for_blueprint(bp)[0]
    # the kit's own components from an earlier build (housings before their cameras)
    for body_first in (True, False):
        for n, (h, d) in handles(bp).items():
            if (n.startswith(PREFIX) and n.endswith("_Body") == body_first or n == STREAM) and not lib.is_inherited_component(d):
                sub.delete_subobject(root, h, bp)
    hs = handles(bp)
    # the parent's Orbbec Gemini units: hidden and not capturing, through this child's override templates
    for n, (h, d) in hs.items():
        if lib.is_inherited_component(d) and n.startswith(GEMINI):
            o = lib.get_object_for_blueprint(d, bp)
            if isinstance(o, unreal.SceneComponent):
                o.set_editor_property("visible", False)
                o.set_editor_property("hidden_in_game", True)
            if isinstance(o, unreal.SceneCaptureComponent):
                o.set_editor_property("capture_every_frame", False)
                o.set_editor_property("capture_on_movement", False)
                o.set_editor_property("auto_activate", False)
            log(f"switched off inherited {n} ({o.get_class().get_name()})")
    mount = hs[MOUNT][0]
    cube = unreal.load_asset("/Engine/BasicShapes/Cube")
    lens = RIG["lens"]
    for name, (loc, rot) in RIG["cameras"].items():
        h, cam = add(bp, mount, unreal.FisheyeSceneCaptureComponent, name)
        cam.set_editor_property("relative_location", unreal.Vector(*loc))
        cam.set_editor_property("relative_rotation", unreal.Rotator(*rot))
        cam.set_editor_property("use_custom_intrinsics", True)
        cam.set_editor_property("use_intrinsics_asset", True)
        cam.set_editor_property("intrinsics_asset", lens_asset)
        cam.set_editor_property("distortion_k", unreal.Vector4(*lens["k"]))
        cam.set_editor_property("max_field_of_view", lens["max_fov_deg"])
        # 24.5 x 24.5 x 30 mm housing behind the lens, so the mount is visible; hidden from the cameras
        _, body = add(bp, h, unreal.StaticMeshComponent, f"{name}_Body")
        body.set_editor_property("static_mesh", cube)
        body.set_editor_property("relative_location", unreal.Vector(-1.5, 0, 0))
        body.set_editor_property("relative_scale3d", unreal.Vector(0.030, 0.0245, 0.0245))
        body.set_collision_profile_name("NoCollision")
        body.set_editor_property("hidden_in_scene_capture", True)
        body.set_editor_property("cast_shadow", False)
        log(f"mounted {name} at {loc} rot {rot}")
    st = RIG["stream"]
    _, src = add(bp, root, unreal.RammsStreamSourceComponent, STREAM)
    # cameras sorted by name -> Front, Rear, Side pairs: one pair per capture frame, each L/R pair synced
    for k, v in {"channel_id": 0, "stream_rgb": True, "stream_depth": False, "stream_rgbd": False,
                 "auto_start_server": True, "server_port": st["port"], "auto_start_capture": True,
                 "capture_every_n_frames": st["capture_every_n_frames"], "capture_groups": st["capture_groups"]}.items():
        src.set_editor_property(k, v)
    unreal.BlueprintEditorLibrary.compile_blueprint(bp)
    eal.save_loaded_asset(bp)
    log(f"saved {PAWN[0]}/{PAWN[1]}: {len(RIG['cameras'])} fisheyes + {STREAM}")
    return bp


def build_game_mode(pawn_bp):
    gm = child_blueprint(*GM, PARENT_GM)
    unreal.BlueprintEditorLibrary.compile_blueprint(gm)
    cdo = unreal.get_default_object(gm.generated_class())
    cdo.set_editor_property("default_pawn_class", pawn_bp.generated_class())
    unreal.BlueprintEditorLibrary.compile_blueprint(gm)
    eal.save_loaded_asset(gm)
    log(f"saved {GM[0]}/{GM[1]} (default pawn {PAWN[1]})")


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


# a headless run starts before the registry has scanned this plugin's content
unreal.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous([ROOT], True)
# nothing here may change ramms-sim's own robot: compare its .uasset before and after
parent_file = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir()),
                           PARENT_BP[len("/Game/"):] + ".uasset")
before = file_hash(parent_file)
build_game_mode(build_pawn(intrinsics()))
if file_hash(parent_file) != before:
    raise RuntimeError(f"{parent_file} changed: restore it from git and report this")
log(f"done; {PARENT_BP} unchanged")
