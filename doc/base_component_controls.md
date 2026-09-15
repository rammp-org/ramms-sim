# Robot base component — assets and how to control them

The shared-base-component architecture (rammp-org/ramms-core#22,
ramms-mujoco-support#3) lets one set of controllers drive a robot on either
physics engine. A robot actor carries **one `RammsRobotBaseComponent`**, which
loads a **motor registry DataTable** and resolves a **physics backend** once
(Chaos skeletal bodies, or a URLab/MuJoCo articulation). Every drive / linkage
controller then addresses motors **by Id** through that component and never
touches physics itself.

```
 controller (diff-drive, 5-bar, …)        motor registry (DataTable)
        │  SetMotorCommand(Id, v)                 │ Id, Type, ChaosName,
        │  GetMotorVelocity(Id) …                 │ ControlRange, Direction
        ▼                                         ▼
 ┌──────────────────────── RammsRobotBaseComponent ───────────────────────┐
 │  clamp to ControlRange · apply Direction · route to the backend        │
 └───────────────┬────────────────────────────────────┬───────────────────┘
       Chaos backend (RammsCore)              MuJoCo backend (RammsMujocoSupport)
       bone torque on a skeletal mesh         actuator ctrl on an AMjArticulation
```

Validated live on 2026-09-12 (see [Reproducing the validation](#reproducing-the-validation)): the Chaos chair drives
exactly as before; the MuJoCo lift_drive linkage base drives and its centre
5-bar legs extend/retract on command.

## Assets

**Where the lift-drive content lives.** The lift-drive robot's CAD is private,
so everything derived from it — the imported MuJoCo articulations and their
meshes (`MuJoCoImports/lift_drive_*`), the `BP_LiftDrive*` pawns, their
`DT_LiftDrive*` tables, `BP_LiftDriveTestGameMode` and `Map_BaseTest_URL` —
lives in the **`RammsPrivateAssets`** content-only plugin (repo
`rammp-org/ramms-private-assets`, mounted at `/RammsPrivateAssets/`). It is an
*optional* submodule at `Plugins/RammsPrivateAssets`: `git submodule update
--init --recursive` skips it (`update = none`), so the public project builds and
runs without it and nothing public references it; with access, run
`git submodule update --init --checkout Plugins/RammsPrivateAssets` and restart
the editor. The code (base component, 5-bar linkage, teleop, camera, test game
mode) is public in `ramms-core` / `ramms-mujoco-support`; the chair
(`BP_Mebot_Ramms`, `DT_Mebot_ChaosMotors`) stays in `/Game`.

| Asset | Backend | Components (in the Blueprint) | Tables |
|---|---|---|---|
| `/Game/Robots/BP_Mebot_Ramms` (the powered chair pawn) | Chaos — `RobotBase` (Backend=**Chaos**, `ChaosSkeletalMeshComponentName=VehicleMesh`) | `RammsDifferentialDriveController` (`LeftMotorId=left_motor`, `RightMotorId=right_motor`), `MebotController` (elevators / translators / caster arms, routed through the base), `RammsAccessInput`, `KinovaGen3Controller`, … | `DT_Mebot_ChaosMotors` (wheels + 6 constraint Position motors) |
| `/RammsPrivateAssets/Robots/BP_LiftDriveLinkage_Ramms` (**pawn**, child of the imported `lift_drive_linkage` articulation, so a reimport doesn't clobber it; `AutoPossessPlayer=Player0`) | MuJoCo — `RobotBase` (Backend=**Mujoco**) | `DifferentialDrive` (centre wheels, radius 12.7 cm, measured track), `LeftCenterLinkage`, `RightCenterLinkage` (`Ramms5BarLinkageController`), `KeyboardTeleop`, `FollowArm`+`FollowCamera` on `base_link` | `DT_LiftDriveLinkage_Motors`, `DT_LiftDriveLinkage_5Bar` |
| `/RammsPrivateAssets/Robots/BP_LiftDriveHolonomic_Ramms` (**pawn**, child of `lift_drive_holonomic`; `AutoPossessPlayer=Player0`) | MuJoCo — `RobotBase` (Backend=**Mujoco**) | `DifferentialDrive` (centre wheels), `KeyboardTeleop` (hips R/F T/G, cranks Y/H U/J), `FollowArm`+`FollowCamera` | `DT_LiftDriveHolonomic_Motors` (all 14 actuators parsed from the MJCF) |
| `/Game/Robots/BP_Mebot_Mujoco` | *not migrated* — a Chaos chair carrying a MuJoCo arm child actor. If it gets a base component, set Backend=**Chaos** explicitly: `Auto` would find the arm articulation attached under it. | | |

All tables live in `/Game/Robots/Data`. `Scripts/pie_tests/base_component/make_assets.py`
(re)creates the chair setup and the linkage tables; `make_pawns.py` builds both
MuJoCo pawns. Both are idempotent.

### Motor registries (`FRammsMotorSpec` rows)

`DT_Mebot_ChaosMotors` — the chair's wheels by their physical side (see *Turn
mixing and joint signs* below for the swap that used to be here) and the six
constraint-driven position motors:

| Id | Type | ChaosName | Drives | ControlRange | Direction |
|---|---|---|---|---|---|
| `left_motor` | Torque | `drive_wheel_l` (bone) | wheel spin | (0,0) = defer | +1 |
| `right_motor` | Torque | `drive_wheel_r` (bone) | wheel spin | (0,0) = defer | +1 |
| `left_elevator`, `right_elevator` | Position | `motor_swing_arm_l/_r` (constraint) | drive-motor elevator swing arms, **rad** | defer to constraint limits | +1 |
| `left_translator`, `right_translator` | Position | `dw_main_plate_l/_r` (constraint) | drive-plate linear actuators fore/aft, **cm** | defer | +1 |
| `front_caster_elevator`, `rear_caster_elevator` | Position | `front/rear_caster_swing_arm` (constraint) | caster arm elevation, **rad** | defer | +1 |

On Chaos a **Position** motor's `ChaosName` is a physics-asset *constraint*
(the same six `UMebotControllerComponent` lists): the backend drives its
target and infers the degree of freedom from the constraint's first non-locked
axis — a linear axis → linear actuator in cm, else an angular one (twist = X,
swing2 = Y, swing1 = Z) in radians; reads come back the same way. Drive
stiffness / damping / force limit are the base component's
`ChaosPositionDrive*` settings (defaults match `MebotController`).

`UMebotControllerComponent` (the chair's rate-limited lift/linkage targets:
`SetAngularMotorTarget(constraint, degrees)`, `SetLinearMotorTarget(constraint,
cm)`, the getters) now **routes through the robot base** when the owner has one
with a backend (`bUseRobotBase`, default on): each entry maps to the registry
motor whose `ChaosName` is its constraint (or an explicit `MotorId`), the
interpolated target becomes a `SetMotorCommand` (radians / cm) and the getters
read the base — so the same API drives a MuJoCo chair's position actuators. An
entry the registry doesn't list keeps driving its constraint directly, and a
`MebotController` with `bUseRobotBase` off is disabled per constraint on the
first base command so the two never fight over a drive target.

**Turn mixing and joint signs.** `JoystickToDifferentialDrive` used to mix
`Left = throttle − steering`, the opposite of its own comment, so joystick
X = +1 slowed the *left* wheel and every honestly-named robot turned left. The
chair Blueprint had compensated by swapping its wheel bones
(`LeftWheelBoneName = drive_wheel_r`, although `drive_wheel_l` sits at
component Y = −30 cm, the UE left). Both are fixed together: the mixing is
`Left = throttle + steering` (and the over-speed turn damping opposes the
turn accordingly), and the chair's bone names / `ChaosName`s are the honest
ones — so the chair still turns right on X = +1 and the MuJoCo bases now do
too (`run_chaos.sh` / `run_mj_full.sh` assert yaw increases). The library's
kinematics helpers and the odometry use the same sense: a positive angular
velocity / heading change is clockwise (UE yaw increasing), so
`GetOdometry().Orientation.Yaw` tracks the actor's yaw. On MuJoCo the
other sign lives per joint: `lift_drive_holonomic`'s centre-wheel hinges are
authored about **−Y** (the linkage's about +Y), so a positive ctrl rolled them
backwards — `DT_LiftDriveHolonomic_Motors` carries `Direction = −1` for them
(`make_pawns.py` derives it from the joint axis) and forward is forward.

`DT_LiftDriveLinkage_Motors` — one row per MJCF actuator, ranges from
`lift_drive_linkage_ue.xml`:

| Ids | Type | ControlRange (rad or N·m) |
|---|---|---|
| `left_front_crank`, `right_front_crank` | Position | −0.029 … 2.308 |
| `left_rear_crank`, `right_rear_crank` | Position | 0 … 2.246 |
| `left_center_hip_a`, `right_center_hip_b` | Position | −0.764 … 0.813 |
| `left_center_hip_b`, `right_center_hip_a` | Position | 0 … 1.717 |
| `{left,right}_{front,rear,center}_wheel` | Torque | −30 … 30 |

Notes on the row schema: `Id` is the canonical (and MuJoCo actuator) name and
defaults to the row name; a `ControlRange` with min ≥ max means "no clamp here,
defer to the backend's own range"; `Direction` (±1) maps the robot's positive
sense onto the engine's joint sign for both commands and reads.

### 5-bar kinematics (`FRamms5BarLinkageSpec` rows, `DT_LiftDriveLinkage_5Bar`)

Each lift_drive centre leg is a parallel 5-bar: two grounded hip position
actuators drive two 2-link chains that meet at the centre-wheel mount. The
table holds only the geometry (cm, in the leg's local x-z plane) — the motor
registry deliberately doesn't:

| Row | Motors (A, B) | PivotA / PivotB | Links (prox, dist) | ZeroDir A/B | Sign A/B | Elbow A/B | Flip |
|---|---|---|---|---|---|---|---|
| `left_center` | `left_center_hip_a`, `left_center_hip_b` | (6.5, 20.99) / (−6.5, 20.99) | 16.0, 22.5 | −0.240 / −2.902 | **−1 / +1** | up / down | no |
| `right_center` | `right_center_hip_a`, `right_center_hip_b` | (−6.5, 20.99) / (6.5, 20.99) | 16.0, 22.5 | −2.902 / −0.240 | **+1 / −1** | down / up | yes |

Sign convention: a MuJoCo hinge about **+Y** rotates +X toward −Z, so the link
angle is `ZeroDir − q` (Sign −1) for a `0 1 0` axis and `+1` for `0 -1 0`.
Getting it backwards makes the leg move the opposite way (this was found live).
At the reference pose (q = 0) the endpoint is 12.7 cm below the pivots and
`hip_b` sits on its range floor, so **the reference pose is the most-retracted
one**: targets above ~12.7 cm are refused as unreachable; lowering the endpoint
(6–12 cm) extends the leg and lifts the body.

## Control surfaces

### 0. The robot's control surface (`RammsRobotControlSurfaceComponent`)

Every robot actor carries one `ControlSurface` component. On BeginPlay it
gathers every sibling component that implements `IRammsControlContributor`
(differential drive, MeBot lift controller, 5-bar linkages, camera control),
merges the controls they describe into one `FRammsControlSurface` (the shared
model from the ramms-ui `RammsControl` module), and appends a raw **Motors**
group for every RobotBase registry motor no contributor claims — so a freshly
imported robot with only a `RobotBase` is already controllable. Nothing is
wired by name: add a contributor to the actor and its controls appear.

| Control id | Contributor | Kind / units | Notes |
|---|---|---|---|
| `drive.forward`, `drive.turn` | `RammsDifferentialDriveController` | Continuous, normalized ±1 | paired (joystick); refused while an external hold is active |
| `lift.<constraint>` | `MebotControllerComponent` | Position, deg / cm | groups Lift / Casters; range from the registry, else the constraint limits |
| `linkage.<name>.height` | `Ramms5BarLinkageController` | Position, cm | range derived from the IK + motor ControlRanges (`GetReachableHeightRange`) unless `EndpointHeightRange` is authored |
| `camera.next`, `camera.reset` | `RammsRobotCameraComponent` | Action | |
| `camera.orbit_yaw`, `camera.orbit_pitch`, `camera.zoom` | `RammsRobotCameraComponent` | Continuous rate | integrated per tick |
| `motor.<id>` | *(unclaimed registry motors)* | from `FRammsMotorSpec` | Position → rad, Velocity → rad/s, Torque → backend units |

API (`BlueprintCallable`, also the `IRammsControlSurfaceProvider` /
`IRammsControlSink` interfaces): `DescribeControlSurface()`,
`SetControl(Id, Value, Source)`, `TriggerControl(Id, Source)`,
`ReleaseControl(Id, Source)`, `GetControlValue(Id)`, `GetControlSurfaceJson()`.
Values are clamped to the axis range; unknown ids are refused. Sources are
arbitrated: Autonomy > Remote > local (Keyboard / Gamepad / Touch) > Script,
and a Remote / Autonomy command holds its axis over local input for
`ExternalHoldSeconds` (0.3 s). Releasing a Continuous axis springs it to its
default; releasing a Position axis stops holding the target (`ReleaseMotor`).

```python
cs = pawn.get_component_by_class(unreal.RammsRobotControlSurfaceComponent)
for a in cs.describe_control_surface().get_editor_property("axes"): print(a.get_editor_property("id"))
cs.set_control("drive.forward", 1.0, unreal.RammsControlSource.SCRIPT)
cs.set_control("linkage.LeftCenterLinkage.height", -9.0, unreal.RammsControlSource.SCRIPT)
cs.release_control("drive.forward", unreal.RammsControlSource.SCRIPT)
```

The sections below describe the underlying components; scripts and panels
should prefer the surface.

### 1. Blueprint / C++ (the same functions everywhere)

`URammsDifferentialDriveController` (public API unchanged by the migration):

| Function | Meaning |
|---|---|
| `SetDriveInput(FVector2D)` | player path — X turn, Y forward, ±1; the pawn writes this every tick from Enhanced Input |
| `SetExternalDriveInput(FVector2D)` | access devices / autonomy; wins over the player path for `ExternalInputHoldSeconds` (0.3 s) after each call |
| `IsExternalDriveActive()` | true while that hold is live |
| `GetOdometry()` / `ResetOdometry(pos, rot)` | integrated from wheel velocity |
| `GetLeftWheelState()` / `GetRightWheelState()` | angular velocity, applied torque, … |
| `SetControlMode(Torque\|Velocity)`, `SetSlipModelingEnabled(bool)` | |

`URamms5BarLinkageController` (one per leg):

| Function | Meaning |
|---|---|
| `SetEndpointTarget(FVector2D XZ)` | IK → commands both hips; **false** (nothing commanded) when unreachable or outside a motor's `ControlRange` |
| `SetEndpointHeight(float Z)` | keeps the current X |
| `SetJointAngles(FVector2D AB)` | direct joint command |
| `GetCurrentEndpoint()` / `GetCurrentJointAngles()` / `GetLastTarget()` | FK from live joint reads |
| `SolveTarget(XZ, out bReachable)` | IK preview |

`URammsRobotBaseComponent` (for new controllers or ad-hoc control):
`SetMotorCommand(Id, v)`, `GetMotorValue(Id)`, `GetMotorVelocity(Id)`,
`GetMotorTransform(Id, out)`, `GetMotorSeparation(IdA, IdB)`, `HasMotor`,
`GetMotorType`, `HasBackend`.

### 2. Player input (keyboard / gamepad / touch, incl. Pixel Streaming)

The chair pawn's Enhanced Input mapping feeds `SetDriveInput` every tick, so
WASD / a gamepad stick — or the touch sticks on the Pixel Streaming player page
(`http://<host>/`, embedded signalling on `:80`/`:8888`) — drive it with no
changes. The MuJoCo bases are keyboard-driveable pawns too — see §2b, and
§2c for the ready-made test map.


### 2b. Player-controlled pawns for the MuJoCo bases (keyboard)

`BP_LiftDriveLinkage_Ramms` and `BP_LiftDriveHolonomic_Ramms` are **pawns**
(the imported URLab articulation is an `APawn`) with `AutoPossessPlayer =
Player 0`, a follow camera on `base_link` (spring arm, yaw-only inheritance so
the view stays level), a top-down camera, a **`RammsRobotCameraComponent`**
(N to switch cameras, mouse to orbit/zoom — see *Cameras* below) and a
**`RammsKeyboardTeleopComponent`**. Place one in a
level and PIE / launch: the player possesses it and drives it with the keyboard
— locally or through the Pixel Streaming page. The component polls keys
(`APlayerController::IsInputKeyDown`), so no input-mapping assets are needed and
it coexists with Enhanced Input; everything is data on the component (keys,
motor Ids, rates), created by `Scripts/pie_tests/base_component/make_pawns.py`.

| Key | Linkage pawn | Holonomic pawn |
|---|---|---|
| W / S | drive forward / back (centre wheels) | same |
| A / D | turn left / right | same |
| E / Q | centre 5-bar legs: endpoint up (retract) / down (extend) | — |
| Y / H | front cranks + / − | front hips + / − |
| T / B | rear cranks + / − | rear hips + / − |
| Z / X | — | front cranks + / − |
| C / V | — | rear cranks + / − |

Keys are chosen around what else listens on the same player controller:
URLab's `UMjInputHandler` owns **1–7** (debug toggles), **P** (pause), **R**
(reset simulation), **O** (orbit cameras) and **F** (launchers), its simulate
widget uses **Tab** (input-mode toggle), and the arm teleops own
I/K/J/L/U/O/M/./arrows/[/]/G/R — so none of those are used here (R/F, T/G,
U/J and Tab were, until the R = reset collision showed up).

Position-motor keys move a *target* at `RatePerSecond` (rad/s) clamped to each
motor's `ControlRange`; the 5-bar keys move the endpoint target at
`RateCmPerSecond` and only advance when the linkage accepts it (so holding a key
at a limit doesn't wind the target off into the unreachable). The MuJoCo pawns
use `MaxTorque 20 N·m / MaxRPM 150` on the drive (the actuators allow ±30): the
chair's 7 N·m default barely moves a base with four undriven, damped wheels and
position-servo legs.

Validated live (2026-09-12): held keys through the editor and through the
Pixel Streaming player page drive both pawns, turn them, extend/retract the
linkage legs and move the cranks/hips. Two gotchas: the project's
`ARammsPlayerController::OnPossess` used to `CastChecked` the pawn to the chair
class and crashed on any other pawn (fixed in rammp-org/ramms-sim#40); and for
the *player page*, keyboard input only reaches the game viewport after a click
on the video (the forwarded click focuses it).

**Cameras.** Each pawn carries three cameras and a **`RammsRobotCameraComponent`**
(`CameraControl`) that switches between them and orbits/zooms the active one:

| Camera | Where | Notes |
|---|---|---|
| `FollowCamera` on `FollowArm` | `base_link`, pitch −18°, 320 cm, inherits yaw only | default; orbit/zoom target |
| `TopCamera` on `TopArm` | `base_link`, straight down, 550 cm, inherits nothing (north-up map view) | orbit/zoom target |
| `PossessCamera` on `PossessCameraArm` | added by URLab `AMjArticulation::PossessedBy`, attached to `Bodies[0]` — the static `worldbody` in these scenes, so it **stays at the spawn point** | excluded from the cycle (`CameraNames`) |

| Input | Action |
|---|---|
| **N** | next camera (Follow → Top → …); `CameraNames` lists the cycle in order and `[0]` is the start camera (without it: authored cameras first, runtime-added last) |
| **Right-drag** (or left-drag, `bAlsoOrbitWithLeftDrag`) | orbit: yaw / pitch the active camera's spring arm (`OrbitSensitivity` °/px, pitch clamped to `[MinPitch, MaxPitch]` = [−85°, 15°]) |
| **Mouse wheel** | zoom: one wheel click = one step of `ZoomStepFraction` (8 %) of the current arm length (or a fixed `ZoomStep` with `bZoomProportional` off) × `ZoomSensitivity`; the arm eases toward it at `ZoomInterpSpeed` (10/s; 0 = instant) within `[MinArmLength, MaxArmLength]` = [60, 1500] cm. A physical click arrives as a burst of wheel events (macOS smooth scrolling: ~16 for one line), so a burst counts as one step: a new step starts after the wheel was idle for `ZoomIdleGap` (0.08 s), or when `ZoomRepeatDelay` (0.3 s) has passed since the last step (a held wheel repeats at ~3 steps/s) — that burst is why the old 40 cm-per-event zoom jumped metres per click. Tune `ZoomSensitivity` / `ZoomStepFraction` / `ZoomRepeatDelay` on the `CameraControl` component |
| **Home** | reset the active arm to its authored rotation/length |

Everything is also a Blueprint/Python call on the component — `NextCamera()`,
`ActivateCamera(Name)`, `Orbit(DeltaYaw°, DeltaPitch°)`, `Zoom(DeltaCm)`,
`ResetOrbit()`, `GetActiveCamera()` — so a touch UI or a gamepad stick can drive
the same arm. Validated live (2026-09-13, when the key was still Tab): camera cycling, wheel zoom and Home through the
Pixel Streaming page; orbit and zoom through `Orbit()`/`Zoom()` from Python;
and a real mouse drag on the editor's PIE viewport orbits *while* dragging.

How the mouse is read (matters in the editor): in a PIE viewport the press
that starts a drag is taken by the viewport itself (focus / capture) and never
reaches `PlayerInput`, while the drag's movement does — so a plain
`IsInputKeyDown(RightMouseButton)` gate only fires at release and the view
jumps once. The component therefore also reads Slate's pressed-button set
(only while the cursor is over the game viewport, so dragging an editor panel
doesn't orbit) and Slate's cursor position as the movement fallback; the raw
`MouseX/MouseY` axes are used whenever they moved (captured / hidden cursor).


### 2c. Test-drive map: `Map_BaseTest_URL` + `BP_LiftDriveTestGameMode`

`Map_BaseTest_URL` (in the RammsPrivateAssets plugin) has a **GameMode Override** of
`BP_LiftDriveTestGameMode` (child of `ARammsMujocoTestGameMode`, RammsMujocoSupport)
and a `PlayerStart`; the raw placed articulations were removed (the game mode
spawns the robot). Press **Play**: the chosen lift-drive pawn is spawned at the
PlayerStart *before* the MuJoCo scene compiles (a pawn spawned at player login
would never be simulated), a plain `PlayerController` possesses it, the engine
is unpaused as soon as the manager is up (it starts paused by design), and the
simulate widget is hidden. Then drive with the keys in §2b.

- **Pick the robot**: `BP_LiftDriveTestGameMode` → `DefaultPawnClass`
  (`BP_LiftDriveHolonomic_Ramms` by default; set `BP_LiftDriveLinkage_Ramms` for
  the linkage base). Or override the game mode per map in World Settings.
- Options on the game mode: `bStartSimulationOnBeginPlay`,
  `SimulationStartTimeoutSeconds`, `bHideSimulateWidget`,
  `bSpawnDefaultPawnBeforeCompile`.
- `Scripts/pie_tests/base_component/make_test_map.py` (re)creates the game mode
  and rewrites the map.

### 3. Python remote execution (editor)

`Scripts/editor_remote_exec.py --file <script>` runs a script in the open
editor (Remote Execution enabled; on macOS the helper unicasts discovery to
`127.0.0.1:6766`). In PIE:

```python
import unreal
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()

# MuJoCo linkage base
robot = next(a for a in unreal.GameplayStatics.get_all_actors_of_class(w, unreal.Actor)
             if a.get_component_by_class(unreal.RammsRobotBaseComponent))
robot.get_component_by_class(unreal.RammsDifferentialDriveController).set_drive_input(unreal.Vector2D(0.0, 1.0))
for leg in robot.get_components_by_class(unreal.Ramms5BarLinkageController):
    leg.set_endpoint_target(unreal.Vector2D(0.0, 8.0))   # extend: lifts the body
base = robot.get_component_by_class(unreal.RammsRobotBaseComponent)
base.get_motor_velocity("left_center_wheel"); base.set_motor_command("left_front_crank", 0.5)

# Chaos chair (the pawn writes the joystick every tick; the external path wins for 0.3 s per call)
pawn = unreal.GameplayStatics.get_player_pawn(w, 0)
pawn.get_component_by_class(unreal.RammsDifferentialDriveController).set_external_drive_input(unreal.Vector2D(0.0, 1.0))
```

Rules learned the hard way: each remote command runs synchronously on the game
thread (sequence short scripts with local sleeps, from bash); **never
`set_editor_property` on a live PIE component** — use the `Set*` UFUNCTIONs;
the MuJoCo scene in `Map_BaseTest_URL` starts **paused** — call
`manager.set_paused(False)` on the `AMjManager` actor; the chair's
`RammsAccessInputComponent` re-zeroes external input every tick (disable its
tick for scripted driving). Ready-made chains: `Scripts/pie_tests/base_component/`.

### 4. Remote Control API (HTTP, `:30010`; Web UI on `:30000`)

Every function above is `BlueprintCallable`, so it is callable through the
Remote Control API on a running PIE / `-game` instance:

```http
PUT http://127.0.0.1:30010/remote/object/call
{
  "objectPath": "/Game/Maps/UEDPIE_0_Map_Demo.Map_Demo:PersistentLevel.BP_Mebot_Ramms_C_0.RammsDifferentialDriveController",
  "functionName": "SetExternalDriveInput",
  "parameters": { "Input": { "X": 0.0, "Y": 1.0 } }
}
```

or, preferably, through the control surface (`GetControlSurfaceJson` lists
the ids and ranges):

```http
PUT http://127.0.0.1:30010/remote/object/call
{
  "objectPath": "/Game/Maps/UEDPIE_0_Map_Demo.Map_Demo:PersistentLevel.BP_Mebot_Ramms_C_0.ControlSurface",
  "functionName": "SetControl",
  "parameters": { "Id": "drive.forward", "Value": 1.0, "Source": "Remote" }
}
```

Call the `Set*` functions; do not write properties of live components through
`/remote/object/property` (array-valued `TOptional`s and live URLab components
get cleared). Object paths differ between PIE (`UEDPIE_0_` prefix) and
`-game`.

### 5. URLab bridge (ZMQ, `:5559`) — coexistence

When the base component drives a MuJoCo articulation it selects that
articulation's **UI control slot** (`ControlSource = 1`); the bridge's network
slot is then not applied to `d->ctrl`. Drive the base from UE (this
architecture) *or* from the bridge, not both. Known limitation: if an enabled
`UMjArticulationController` (e.g. the arm's end-effector controller) is on the
**same** articulation, URLab applies only that controller's `ctrl` — the base
component warns; the fix belongs in URLab's `ApplyControls` (see the roadmap).

## Reproducing the validation

Screenshots and GIFs of these runs are not versioned (`doc/media/` is ignored).
To see them again: Play `Map_BaseTest_URL` (or `Map_Demo` for the chair) and
drive with the keys in §2b, or run the scripted checks in
`Scripts/pie_tests/base_component/` (`run_chaos.sh`, `run_mj_full.sh`), which
assert forward drive, turn direction, the 5-bar retract/extend and the chair's
position motors and print what they measured.
