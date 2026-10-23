"""Make /Game/Maps/Map_RampTest: two straight ramps for the Chaos chair's stop-on-a-slope test.

From the engine's default template (floor, sun, sky, PlayerStart): lane A is a 1:12 ramp
(4.76 deg, the ADA maximum) and lane B a 1:8 ramp (7.13 deg), each 140 cm wide with a flat
landing at the top. Both rise along +X from x = 0; lane A is at y = 0, lane B at y = 400.
The project's default game mode (BP_MebotGameMode) spawns BP_Mebot_Ramms at the PlayerStart,
placed on lane A's approach; ramp_test.py teleports it to each lane. Idempotent: an existing
map is rebuilt in place.

Run in the editor via Scripts/editor_remote_exec.py --file <this file>.
"""
import math
import unreal

MAP = "/Game/Maps/Map_RampTest"
TEMPLATE = "/Engine/Maps/Templates/Template_Default"
CUBE = "/Engine/BasicShapes/Cube.Cube"
WIDTH = 140.0      # cm
THICK = 40.0       # ramp slab thickness, cm
LANDING = 250.0    # flat top, cm
# (label, y, rise over run), both rising along +X from x = 0
LANES = [("Ramp_1in12", 0.0, 30.0, 360.0), ("Ramp_1in8", 400.0, 40.0, 320.0)]
TAG = "RammsRampTest"


def log(s):
    unreal.log("[make_ramp_map] " + str(s))


les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
if unreal.EditorAssetLibrary.does_asset_exist(MAP):
    les.load_level(MAP)
else:
    les.new_level_from_template(MAP, TEMPLATE)
    log("created %s from %s" % (MAP, TEMPLATE))

# Rebuild the ramps from scratch.
for a in eas.get_all_level_actors():
    if TAG in [str(t) for t in a.tags]:
        eas.destroy_actor(a)

floor_top = 0.0
for a in eas.get_all_level_actors():
    if a.get_actor_label() == "Floor":
        o, e = a.get_actor_bounds(False)
        floor_top = o.z + e.z
log("floor top z = %.1f" % floor_top)

cube = unreal.load_asset(CUBE)


def box(label, center, size, pitch):
    a = eas.spawn_actor_from_class(unreal.StaticMeshActor, center, unreal.Rotator(roll=0.0, pitch=pitch, yaw=0.0))
    a.set_actor_label(label)
    a.tags = [TAG]
    c = a.static_mesh_component
    c.set_static_mesh(cube)
    a.set_actor_scale3d(unreal.Vector(size[0] / 100.0, size[1] / 100.0, size[2] / 100.0))
    a.set_folder_path("RampTest")
    return a


for label, y, rise, run in LANES:
    th = math.atan2(rise, run)
    slope_len = math.hypot(rise, run)
    # Top face centre at (run/2, y, floor_top + rise/2); the slab hangs THICK/2 below it,
    # along the face normal (-sin th, 0, cos th). Its low end dips under the floor.
    n = (-math.sin(th), math.cos(th))
    cx = run / 2.0 - n[0] * THICK / 2.0
    cz = floor_top + rise / 2.0 - n[1] * THICK / 2.0
    box(label, unreal.Vector(cx, y, cz), (slope_len + 2.0, WIDTH, THICK), math.degrees(th))
    box(label + "_Landing", unreal.Vector(run + LANDING / 2.0, y, floor_top + rise / 2.0), (LANDING, WIDTH, rise), 0.0)
    log("%s: %.2f deg, rise %.0f cm over %.0f cm at y=%.0f" % (label, math.degrees(th), rise, run, y))

# PlayerStart on lane A's approach, facing up the ramp.
starts = [a for a in eas.get_all_level_actors() if a.get_class().get_name() == "PlayerStart"]
ps = starts[0] if starts else eas.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0, 0, 0))
ps.set_actor_location_and_rotation(unreal.Vector(-350.0, 0.0, floor_top + 100.0), unreal.Rotator(0, 0, 0), False, True)

world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
ws = world.get_world_settings()
gm = unreal.load_asset("/Game/BP_MebotGameMode")
ws.set_editor_property("default_game_mode", gm.generated_class())
saved = unreal.EditorLoadingAndSavingUtils.save_current_level()
log("map saved=%s" % saved)
