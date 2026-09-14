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

Validated live on 2026-09-12 (see [media](#media)): the Chaos chair drives
exactly as before; the MuJoCo lift_drive linkage base drives and its centre
5-bar legs extend/retract on command.

## Assets

| Asset | Backend | Components (in the Blueprint) | Tables |
|---|---|---|---|
| `/Game/Robots/BP_Mebot_Ramms` (the powered chair pawn) | Chaos — `RobotBase` (Backend=**Chaos**, `ChaosSkeletalMeshComponentName=VehicleMesh`) | `RammsDifferentialDriveController` (`LeftMotorId=left_motor`, `RightMotorId=right_motor`), `RammsAccessInput`, `MebotController`, `KinovaGen3Controller`, … | `DT_Mebot_ChaosMotors` |
| `/Game/Robots/BP_LiftDriveLinkage_Ramms` (**pawn**, child of the imported `lift_drive_linkage` articulation, so a reimport doesn't clobber it; `AutoPossessPlayer=Player0`) | MuJoCo — `RobotBase` (Backend=**Mujoco**) | `DifferentialDrive` (centre wheels, radius 12.7 cm, measured track), `LeftCenterLinkage`, `RightCenterLinkage` (`Ramms5BarLinkageController`), `KeyboardTeleop`, `FollowArm`+`FollowCamera` on `base_link` | `DT_LiftDriveLinkage_Motors`, `DT_LiftDriveLinkage_5Bar` |
| `/Game/Robots/BP_LiftDriveHolonomic_Ramms` (**pawn**, child of `lift_drive_holonomic`; `AutoPossessPlayer=Player0`) | MuJoCo — `RobotBase` (Backend=**Mujoco**) | `DifferentialDrive` (centre wheels), `KeyboardTeleop` (hips R/F T/G, cranks Y/H U/J), `FollowArm`+`FollowCamera` | `DT_LiftDriveHolonomic_Motors` (all 14 actuators parsed from the MJCF) |
| `/Game/Robots/BP_Mebot_Mujoco` | *not migrated* — a Chaos chair carrying a MuJoCo arm child actor. If it gets a base component, set Backend=**Chaos** explicitly: `Auto` would find the arm articulation attached under it. | | |

All tables live in `/Game/Robots/Data`. `Scripts/pie_tests/base_component/make_assets.py`
(re)creates the chair setup and the linkage tables; `make_pawns.py` builds both
MuJoCo pawns. Both are idempotent.

### Motor registries (`FRammsMotorSpec` rows)

`DT_Mebot_ChaosMotors` — the chair's diff-drive was authored with **left → bone
`drive_wheel_r`** and **right → `drive_wheel_l`**; the table preserves that via
`ChaosName`:

| Id | Type | ChaosName | Drives | ControlRange | Direction |
|---|---|---|---|---|---|
| `left_motor` | Torque | `drive_wheel_r` (bone) | wheel spin | (0,0) = defer | +1 |
| `right_motor` | Torque | `drive_wheel_l` (bone) | wheel spin | (0,0) = defer | +1 |
| `left_elevator`, `right_elevator` | Position | `motor_swing_arm_l/_r` (constraint) | drive-motor elevator swing arms, **rad** | defer to constraint limits | +1 |
| `left_translator`, `right_translator` | Position | `dw_main_plate_l/_r` (constraint) | drive-plate linear actuators fore/aft, **cm** | defer | +1 |
| `front_caster_elevator`, `rear_caster_elevator` | Position | `front/rear_caster_swing_arm` (constraint) | caster arm elevation, **rad** | defer | +1 |

On Chaos a **Position** motor's `ChaosName` is a physics-asset *constraint*
(the same six `UMebotControllerComponent` lists): the backend drives its
target and infers the degree of freedom from the constraint's first non-locked
axis — a linear axis → linear actuator in cm, else an angular one (twist = X,
swing2 = Y, swing1 = Z) in radians; reads come back the same way. Drive
stiffness / damping / force limit are the base component's
`ChaosPositionDrive*` settings (defaults match `MebotController`). The first
command through the base disables the matching `MebotController` motor entry
so the two don't fight over the drive target — use one path or the other per
motor.

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
(Tab to switch, mouse to orbit/zoom — see *Cameras* below) and a
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
| R / F | front cranks + / − | front hips + / − |
| T / G | rear cranks + / − | rear hips + / − |
| Y / H | — | front cranks + / − |
| U / J | — | rear cranks + / − |

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
| **Tab** | next camera (Follow → Top → …); `CameraNames` lists the cycle in order and `[0]` is the start camera (without it: authored cameras first, runtime-added last) |
| **Right-drag** (or left-drag, `bAlsoOrbitWithLeftDrag`) | orbit: yaw / pitch the active camera's spring arm (`OrbitSensitivity` °/px, pitch clamped to `[MinPitch, MaxPitch]` = [−85°, 15°]) |
| **Mouse wheel** | zoom: arm length ± `ZoomStep` (40 cm) within `[MinArmLength, MaxArmLength]` = [60, 1500] cm |
| **Home** | reset the active arm to its authored rotation/length |

Everything is also a Blueprint/Python call on the component — `NextCamera()`,
`ActivateCamera(Name)`, `Orbit(DeltaYaw°, DeltaPitch°)`, `Zoom(DeltaCm)`,
`ResetOrbit()`, `GetActiveCamera()` — so a touch UI or a gamepad stick can drive
the same arm. Validated live (2026-09-13, `doc/media/base_component/camera_*.jpg`,
`camera_switch_orbit_zoom.gif`): Tab cycling, wheel zoom and Home through the
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

`Content/Maps/URL/Map_BaseTest_URL` now has a **GameMode Override** of
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

## Media

Captured 2026-09-12 over Pixel Streaming from Chrome (`doc/media/base_component/`):

- `lift_drive_linkage_drive_and_5bar.gif` — MuJoCo linkage base: drive forward,
  centre legs extend (front wheel lifts, body rises ~6 cm), then retract.
- `linkage_01_rest_threequarter.jpg`, `linkage_02_driving_forward.jpg`,
  `linkage_03_legs_extended_side.jpg`, `linkage_04_legs_retracted_side.jpg`,
  `linkage_05_zoom_5bar_leg.png`.
- `mebot_chaos_drive.gif` and `mebot_0*.jpg` — the Chaos chair driven through
  the base component (reverse away from the building, then spin in place).
- `linkage_pawn_keyboard_teleop.gif`, `pawn_0*.jpg` — the linkage **pawn** driven
  by keyboard through the Pixel Streaming page (W, A, Q, E, R, F).
- `holonomic_pawn_keyboard_teleop.gif`, `holo_pawn_0*.jpg` — the holonomic pawn:
  drive, turn, front hips (R), front cranks (Y).
- `testmap_0*.jpg` — `Map_BaseTest_URL` on a plain Play with
  `BP_LiftDriveTestGameMode`: no HUD/widget, holonomic pawn driven by keys.
