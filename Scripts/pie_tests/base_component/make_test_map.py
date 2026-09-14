"""Make Map_BaseTest_URL a keyboard test-drive map for the lift_drive pawns.

- Creates /Game/Robots/BP_LiftDriveTestGameMode (parent ARammsMujocoTestGameMode)
  with DefaultPawnClass = BP_LiftDriveHolonomic_Ramms. Change that one property
  (or the map's GameMode Override) to drive the linkage base instead.
- In Map_BaseTest_URL: removes the placed raw lift_drive articulations (the game
  mode spawns the chosen pawn, and it must not coexist with a placed copy), adds
  a PlayerStart where the linkage used to sit, sets the GameMode Override, and
  saves the map.

Run in the editor via Scripts/editor_remote_exec.py --file <this file>.
"""
import unreal

EAL = unreal.EditorAssetLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
MAP = "/Game/Maps/URL/Map_BaseTest_URL"


def log(s):
    unreal.log("[make_test_map] " + str(s))


# --- game mode blueprint ------------------------------------------------------
gm_path = "/Game/Robots/BP_LiftDriveTestGameMode"
if EAL.does_asset_exist(gm_path):
    gm_bp = EAL.load_asset(gm_path)
else:
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.RammsMujocoTestGameMode)
    gm_bp = AT.create_asset("BP_LiftDriveTestGameMode", "/Game/Robots", unreal.Blueprint, factory)
    log("created %s" % gm_path)
holo = EAL.load_asset("/Game/Robots/BP_LiftDriveHolonomic_Ramms").generated_class()
cdo = unreal.get_default_object(gm_bp.generated_class())
cdo.set_editor_property("default_pawn_class", holo)
cdo.set_editor_property("player_controller_class", unreal.PlayerController)
cdo.set_editor_property("hud_class", None)
cdo.set_editor_property("start_simulation_on_begin_play", True)
cdo.set_editor_property("hide_simulate_widget", True)
unreal.BlueprintEditorLibrary.compile_blueprint(gm_bp)
EAL.save_loaded_asset(gm_bp)
log("game mode: pawn=%s pc=%s" % (cdo.get_editor_property("default_pawn_class").get_name(), cdo.get_editor_property("player_controller_class").get_name()))

# --- the map ------------------------------------------------------------------
les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
if unreal.EditorLevelLibrary.get_editor_world().get_path_name() != MAP + "." + MAP.split("/")[-1]:
    les.load_level(MAP)
world = unreal.EditorLevelLibrary.get_editor_world()

start_xf = None
for a in list(unreal.EditorLevelLibrary.get_all_level_actors()):
    cn = a.get_class().get_name()
    if cn.startswith("lift_drive_linkage") or cn.startswith("BP_LiftDriveLinkage_Ramms"):
        start_xf = a.get_actor_transform()
    if cn.startswith("lift_drive_") or cn.startswith("BP_LiftDrive"):
        log("removing placed %s (%s)" % (a.get_name(), cn))
        unreal.EditorLevelLibrary.destroy_actor(a)

starts = [a for a in unreal.EditorLevelLibrary.get_all_level_actors() if a.get_class().get_name() == "PlayerStart"]
if not starts:
    loc = start_xf.translation if start_xf else unreal.Vector(270, 700, -195)
    loc = unreal.Vector(loc.x, loc.y, loc.z + 5.0)
    ps = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.PlayerStart, loc, unreal.Rotator(0, 0, 0))
    ps.set_actor_label("PlayerStart_LiftDrive")
    log("added PlayerStart at %s" % loc)
else:
    log("PlayerStart already present: %s" % [a.get_name() for a in starts])

ws = world.get_world_settings()
ws.set_editor_property("default_game_mode", gm_bp.generated_class())
log("GameMode Override -> %s" % ws.get_editor_property("default_game_mode").get_name())

saved = unreal.EditorLoadingAndSavingUtils.save_current_level()
log("map saved=%s" % saved)
