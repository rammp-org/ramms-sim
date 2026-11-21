"""The public robots' definitions (URammsRobotDefinition), which ARammsRobotGameMode starts a level with.

    UnrealEditor-Cmd Ramms.uproject -run=pythonscript -script="Scripts/robots/make_robot_definitions.py"

A plugin with robots of its own writes its definitions under its own mount point with ensure_definition (import this
module); a definition is found through the asset registry, so a plugin's robots are offered only while it is mounted.
Writes and saves only the definitions named here; run it again after changing them.
"""

import unreal

ASSET_TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary


def ensure_definition(package_path, robot_id, pawn_class_path, display_name, description="", aliases=(), tags=(),
                      spawn_offset=(0.0, 0.0, 0.0), sort_order=0, hidden=False, player_controller_class_path=None):
    """Create (or update) the definition at package_path (/Game/Robots/X/DA_Robot_X) and save it; returns it."""
    folder, name = package_path.rsplit("/", 1)
    if EAL.does_asset_exist(package_path):
        definition = EAL.load_asset(package_path)
    else:
        factory = unreal.DataAssetFactory()
        factory.set_editor_property("data_asset_class", unreal.RammsRobotDefinition)
        definition = ASSET_TOOLS.create_asset(name, folder, unreal.RammsRobotDefinition, factory)
    if definition is None:
        raise RuntimeError("could not create %s" % package_path)
    pawn = unreal.load_class(None, pawn_class_path)
    if pawn is None:
        raise RuntimeError("%s: pawn class %s does not load" % (robot_id, pawn_class_path))
    definition.set_editor_property("robot_id", robot_id)
    definition.set_editor_property("aliases", [unreal.Name(a) for a in aliases])
    definition.set_editor_property("display_name", display_name)
    definition.set_editor_property("description", description)
    definition.set_editor_property("pawn_class", pawn)
    if player_controller_class_path:
        definition.set_editor_property("player_controller_class", unreal.load_class(None, player_controller_class_path))
    definition.set_editor_property("tags", [unreal.Name(t) for t in tags])
    definition.set_editor_property("spawn_offset", unreal.Vector(*spawn_offset))
    definition.set_editor_property("sort_order", sort_order)
    definition.set_editor_property("hidden", hidden)
    if not EAL.save_loaded_asset(definition, only_if_is_dirty=False):
        raise RuntimeError("could not save %s" % package_path)
    print("[robots] %s: %s (%s), pawn %s" % (package_path, robot_id, display_name, pawn_class_path))
    return definition


def main():
    ensure_definition(
        "/Game/Robots/RammpGen1/DA_Robot_RammpGen1", "rammp_gen1",
        "/Game/Robots/RammpGen1/BP_RammpGen1PoweredFront_Ramms.BP_RammpGen1PoweredFront_Ramms_C",
        "RAMMP Gen1",
        "The differential-drive base with a powered-front linkage and a sprung rear (MuJoCo), as on its own curb map "
        "(Map_RammpGen1Curb_URL).",
        aliases=("Gen1", "RammpGen1"), tags=("mobile", "curb", "mujoco"),
        # Its own map starts it 20 cm over the floor; the curb maps' start is 5 cm over the road.
        spawn_offset=(0.0, 0.0, 15.0), sort_order=10)


if __name__ == "__main__":
    main()
