# Curb test maps

`Content/Maps/Curb/` holds 23 curb crossings for any robot:
- `Map_Curb_<id>_URL`: one map per terrain in `curb_terrain.py`.
- `Map_Curb_Flat_URL`: a straight 6 in curb on a flat road.

The maps name no robot. Their GameMode Override is the C++ `ARammsRobotGameMode` (RammsMujocoSupport), which spawns the robot chosen at start at the PlayerStart.

| Id | Terrain |
|---|---|
| S0 | flat road, straight on (15.24 cm, 6 in) |
| A15, A30, A30N | 15 and 30 deg approaches, from either side |
| X6, X6P | 6 deg gutters: roads falling toward both curbs, or rising toward them |
| G6 | 6 deg street grade along the curb |
| T6, TN6 | sidewalk rising, or falling, 6 deg away from the road |
| W6 | sidewalk twisted 6 deg: the curb taller at one track |
| A30_G6, A30_X6, A30N_G4X4, A30_G4X4_W2 | approaches on graded, guttered and twisted roads |
| S4, S8 | 4 in (10.16 cm) and 8 in (20.32 cm) curbs |
| X6P_G | road rising 6 deg into the curb, sidewalk 6 deg along it |
| BUMP | a 2.5 cm ridge across the sidewalk 25 cm past the edge (climb only) |
| R_A40, R_NARROW, R_RAMP, R_KINK | a 40 deg approach, an 80 cm sidewalk, a 10 deg curb cut, an edge kinked 20 deg: past what a curb controller should try |

The frame:
- Units are centimetres. The floor top is at z = -200.
- The robot starts 5 cm over the near road at (270, 700), heading +X.
- The near curb edge crosses its path at (450, 700).
- `curb_terrain.py` documents the planes and boxes, and `Layout.expected()` gives each crossing's steps.

## Test your robot on them

`Scripts/curb_runner/run_curb.py` runs a robot's crossings on these maps, measures each one the same way for every robot, and records it in the robot's history. See `Scripts/curb_runner/README.md`. To add your robot, write a profile and an editor-side adapter for it.

To start a map by hand, a robot is chosen by, first that decides:

1. `?Robot=<id>` on the map URL, for example `UnrealEditor Ramms.uproject /Game/Maps/Curb/Map_Curb_A30_URL?Robot=rammp_gen1 -game`;
2. the `ramms.Robot` console variable, set before Play in the editor (`-RammsRobot=<id>` sets it at startup);
3. the project's default, `[/Script/RammsCore.RammsRobotSettings] DefaultRobotId` in `Config/DefaultGame.ini` (`rammp_gen1`). A mounted plugin may set its own in its `Config/Game.ini`;
4. the only robot there is;
5. otherwise, the picker: a control surface whose `sim.robot` control chooses a robot and whose `sim.robot.load` action restarts the level with it. On the picker the D-pad or the arrow keys step the choice, and A or Enter starts it.

Any of these takes:
- **a robot definition's id or alias.** A definition is a `URammsRobotDefinition` data asset: the pawn, the names it answers to, tags, and a spawn offset. `Scripts/robots/make_robot_definitions.py` writes the public ones; `ensure_definition` there writes yours. A definition anywhere under `/Game/Robots` is found and cooked. Elsewhere, add your folder to the `Directories` of the `RammsRobot` entry in `[/Script/Engine.AssetManagerSettings] PrimaryAssetTypesToScan` (`Config/DefaultGame.ini`). That array is keyed on the type, so a plugin's `Config/Game.ini` entry replaces the project's rather than adding to it: restate the whole entry there with `/Game/Robots` kept.
- **or a pawn class path**, with no definition at all: `?Robot=/Game/MyRobot/BP_MyRobot.BP_MyRobot_C`.

Every robot started this way also gets the `sim.robot` / `sim.robot.load` controls on its control surface, so the HUD, Remote Control (`URammsRobotBridge`: `ListRobots`, `SetNextRobot`, `RestartWithRobot`, `OpenMapWithRobot`) and ramms-tools can switch robots.

The maps set no MuJoCo scene options: each robot's own MJCF `<option>` (timestep, friction cone, impratio) is adopted as it attaches. A MuJoCo robot is spawned in `InitGame`, before the scene compiles; a Chaos pawn works too.

## Building the maps

```
UnrealEditor-Cmd Ramms.uproject -run=pythonscript -script="Scripts/curb_maps/make_curb_maps.py"
```

`RAMMS_CURB_MAPS=A30,Flat` builds only those. From Git Bash, also set `MSYS_NO_PATHCONV=1` for any `/Game/...` value.

Each map is built from an empty level, never from another map. Before it is kept:
- line traces find the surfaces its terrain puts there;
- neither its dependencies nor its bytes mention `/RammsPrivateAssets/`, an optional private submodule that public content must never need.

Change a terrain in `curb_terrain.py` and build its map again. Don't edit the maps by hand.
