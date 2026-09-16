# UI panels + input refactor — plan

Status: **agreed** (2026-09-15; decisions below settled with William). Follows the robot base
architecture (`doc/base_component_controls.md`, `doc/mujoco_sim_roadmap.md`).

## Goals

1. **Reusable UI panels** built on the `ramms-ui` plugin (`rammp-org/ramms-ui`),
   which is where anything shared with the real-robot HMI should live.
2. **No hard-coded bindings in components.** Controllers stop carrying key
   maps and fixed component/motor names; a robot *describes* what it can do
   (from `RammsRobotBaseComponent`'s motor registry plus the controllers present
   on the actor) and panels, keyboards, gamepads and remote clients drive that
   description.
3. **Auto-wiring** of the differential drive, MeBot lift/linkage controller,
   5-bar linkage, arm/gripper and camera from the registry — no per-robot glue.
4. **Enhanced Input** (input mapping contexts / input actions) as the single
   keyboard / gamepad path, replacing the polled `IsInputKeyDown` components.

## Where we are (survey, 2026-09-15)

- **UI.** The project has one real UI: the Epic vehicle-template HUD
  (`URammsUI`, speed + gear, spawned by `ARammsPlayerController::BeginPlay`,
  duplicated verbatim in `ATimeTrialPlayerController`) and a bare mobile
  touch widget class slot. RammsCore / RammsAccess / RammsMujocoSupport /
  RammsStreaming contain **no** UMG or Slate. The only rich UI is URLab's
  MuJoCo dashboard (`UMjSimulateWidget`, hard-loaded by `AAMjManager`).
- **ramms-ui** exists (public, last push 2026-04-21) but is **not** a
  submodule; two places already assume it
  (`Plugins/RammsCore/Scripts/unreal_remote/__init__.py` expects
  `RammsRemoteBridge`; RammsStreaming's README names
  `URammsStreamCameraBridge` as living there). It brings: `URammsUISubsystem`
  (robot-controller registry, event bus, property store, themes), an
  `IRammsRobotController` actor interface with a **fixed vocabulary**
  (`SendMovementInput`, `RequestMebotMode`, `RequestArmAction`,
  `RequestSeatAdjust`, `SendCommand[WithPayload]`), a widget library
  (`URammsPanel`, `URammsJoystickWidget`, `URammsAxisControl`, buttons,
  sliders, notifications, `URammsMebotController`, `URammsArmController`,
  `URammsStatusPanel`), layouts/presets, a Remote Control bridge and the
  camera/PGM projection pipeline. It depends on RammsStreaming; the symbols
  it uses still exist in ours (both tips are from April 2026), so "up to
  date" is a submodule add + a UE 5.7 build check, not a port. It was
  designed for the real-robot HMI (commands leave UE over RMSS/ROS).
- **Input.** `Config/DefaultInput.ini` still carries legacy Action/Axis
  mappings (Handbrake, SwitchCamera=**Tab**, ResetVR=**R**, MoveForward…)
  that nothing binds (the project runs `EnhancedPlayerInput`). Enhanced
  Input is used only by the vehicle pawn (7 `UInputAction`s), the two player
  controllers' IMC lists, and URLab's twist controller (`IMC_TwistControl`).
  Everything robot-related **polls keys**: `URammsKeyboardTeleopComponent`
  (W/S/A/D, E/Q, per-motor groups), `URammsRobotCameraComponent` (N, Home,
  mouse), `URammsEndEffectorTeleopComponent` and `URammsMjArmTeleopComponent`
  (near-duplicate I/K/J/L/U/O/M/./arrows/[/]/G/R maps), and URLab's
  `UMjInputHandler` (1–7, P, R, O, F). Collisions: Tab (INI vs URLab
  widget), R (INI vs URLab reset vs both arm teleops), O (URLab vs arm
  teleop). The polling was chosen because Pixel Streaming key events reach
  `PlayerInput` directly; Enhanced Input reads the same `PlayerInput`, so it
  is not a real constraint (to be confirmed by a spike, phase 4).
- **Controller wiring.** Every controller resolves its dependencies the same
  way — optional `FName` override, else `GetComponents<T>()` first match —
  and carries defaults for a specific robot: diff-drive `left_motor` /
  `right_motor` + bone names; MeBot's six constraint names in its
  constructor; Kinova `ArmSkMesh` / `end_effector`; gripper `GripperSkMesh`,
  `link_0_r/l`; the MuJoCo EE controller's `pinch` / `fingers_actuator` /
  `base_target`; RammsAccess's controller-name overrides.
- **Discovery gap.** `URammsRobotBaseComponent` has no way to enumerate its
  motors: every accessor takes an `FName`, the registry `TMap` is private and
  `GetMotorSpec` isn't a UFUNCTION. A panel or remote client cannot ask
  "what motors does this robot have" — the single biggest blocker.
- **Remote.** Remote Control HTTP is exposed only generically
  (`URammsCoreBridge` actor/component path lookups; typed calls exist only
  for `URammsSkeletalPoseComponent`); no `RemoteControlPreset` assets. RMSS
  carries sensor frames only, no commands. The only non-HTTP command ingress
  is RammsAccess's UDP intent stream (port 30040) → `SetExternalDriveInput`
  / `ApplyEndEffectorTeleopInput`.

## Design

### 1. A robot describes its controls (shared model, lives in ramms-ui)

Replace the fixed-vocabulary interface with a **described control surface**
that a panel can render and any input source can drive:

```
FRammsControlAxis    { Id (FName, e.g. "drive.forward"), Group, DisplayName,
                       Kind {Continuous | Position | Velocity | Action},
                       Range (min,max), Units (rad / cm / normalized), Default,
                       Flags (bSpringToZero, bReadback) }
FRammsControlSurface { RobotName, TArray<FRammsControlAxis>, TArray<FName> Groups }

IRammsControlSurfaceProvider   GetControlSurface(), OnControlSurfaceChanged
IRammsControlSink              SetAxis(Id, Value, Source), TriggerAction(Id, Source),
                               Release(Id, Source), GetAxisValue(Id)
```

`Source` (Keyboard / Gamepad / Touch / Remote / Autonomy) carries the
priority/arbitration that `SetDriveInput` vs `SetExternalDriveInput` does
today, generalized to every axis (external sources hold for a timeout, exactly
as the diff-drive does now).

The existing `IRammsRobotController` calls become **named actions and axes**
in this model (`RequestMebotMode(CurbAscent)` → `TriggerAction("mebot.mode.curb_ascent")`,
`SendMovementInput(v)` → `SetAxis("drive.forward"/"drive.turn")`,
`RequestSeatAdjust(axis, d)` → `SetAxis("seat.<axis>", …)`). The real-robot
HMI implements the provider/sink over RMSS/ROS; the sim implements them over
`RobotBase` + controllers. `IRammsRobotController` **stays** as a
compatibility shim (an adapter maps it onto the sink); the HMI is not
migrated in this series — nothing is gained by doing so now.

**Module placement (decided).** The description/sink types live in a
second, dependency-light module inside the ramms-ui plugin — `RammsControl`
(Core/CoreUObject/Engine only, no UMG) — that both `RammsUI` and `RammsCore`
depend on. ramms-ui becomes a required submodule of ramms-sim (the remote
scripts already assume it). Not RammsCore: a UE plugin builds all of its
modules when enabled, so the HMI project would have to compile the whole
RammsCore plugin (Eigen, sensor shaders against renderer internals) just for
two headers. Not a new repo: overkill.

### 2. The sim side: contributions + adapter (RammsCore / RammsMujocoSupport)

- **`RobotBase` enumeration API** (RammsCore): `GetMotorIds()`,
  `GetMotorSpecs()`, `GetMotorSpec` as a UFUNCTION, `GetMotorCount()`, and an
  `OnRegistryLoaded` delegate. Blueprint- and Remote-Control-reachable.
- **`IRammsControlContributor`** (C++ interface on components):
  `DescribeControls(TArray<FRammsControlAxis>&)`, `ApplyAxis(Id, Value)`,
  `TriggerAction(Id)`, `ReleaseAxis(Id)`, `ReadAxis(Id)`, and
  `GetClaimedMotorIds()`. Implemented by:
  - `URammsDifferentialDriveController` → `drive.forward`, `drive.turn`
    (continuous, normalized; a 2-D group the panel renders as a joystick);
    claims its two motor ids.
  - `UMebotControllerComponent` → one Position axis per configured motor
    (range from the registry `ControlRange`, else the constraint limits;
    units rad/cm), grouped "Lift" / "Casters"; claims them.
  - `URamms5BarLinkageController` → `linkage.<name>.height` (cm) and,
    optionally, the two hip angles; claims its hips.
  - Arm/gripper (`UKinovaGen3ControllerComponent` +
    `UGripperControllerComponent`; MuJoCo `URammsMjEndEffectorController`)
    → EE twist axes (6) + gripper open/close/toggle actions + resync action;
    the two arm teleop components' duplicated key maps disappear.
  - `URammsRobotCameraComponent` → `camera.next`, `camera.reset` actions,
    `camera.orbit_yaw/pitch`, `camera.zoom` axes.
- **`URammsRobotControlSurfaceComponent`** (RammsCore, one per robot actor):
  on BeginPlay gathers every contributor via `GetComponents<>` + interface
  check, merges their descriptions, then appends a **"Motors" group** with a
  raw axis per registry motor **not claimed** by any contributor (type/range
  from `FRammsMotorSpec`) — so a freshly imported robot with only a
  `RobotBase` is already controllable, and nothing needs hand-wiring. It
  implements `IRammsControlSurfaceProvider` + `IRammsControlSink`, routes
  `SetAxis` to the owning contributor (or `RobotBase::SetMotorCommand` for
  raw motors), arbitrates sources, and registers the actor with
  `URammsUISubsystem`. This is the auto-wiring.
- Controllers keep their **tuning** properties (torque curves, PID, rates,
  drive stiffness) and their optional name overrides for exotic setups; the
  per-robot *defaults* (bone/constraint names) move out of constructors into
  the motor table (`ChaosName`) and the Blueprint, which is where
  `make_assets.py` already puts them.

### 3. Panels (ramms-ui)

- **`URammsControlSurfacePanel`** — a generic renderer: one `URammsPanel`
  per group; `URammsAxisControl` for Position/Velocity axes (label, value
  readback, ± / reset), `URammsJoystickWidget` for a 2-D continuous pair
  (drive), `URammsButton` for actions; groups collapsible; readback via
  `GetAxisValue` on tick or `OnAxisChanged`. Rendered entirely from the
  description — no robot-specific code.
- The existing themed panels (`URammsMebotController` modes,
  `URammsArmController` home/retract, `URammsStatusPanel`) become optional
  **decorations** that target named actions/axes when present (they hide
  otherwise), so the same layout works on the sim and the real robot.
- A sim **layout preset** (`URammsLayoutBase` subclass in ramms-sim content):
  control-surface panel, joystick, status panel (speed/battery replace the
  vehicle HUD's speed/gear), camera widget optional. The touch path is the
  joystick widget → sink (replacing the engine virtual joystick +
  `MobileControlsWidget` slot).
- Spawned by the player controller through ramms-ui's layout host, once,
  shared by `ARammsPlayerController` / `ATimeTrialPlayerController` (dedupe
  the copied block) and `ARammsMujocoTestGameMode`'s plain controller.

### 4. Input: Enhanced Input only

- **`URammsControlInputMap`** (data asset, in `RammsControl`): a list of
  `{UInputAction, ControlId, Scale / Mode (Axis | Action | Increment at rate)}`
  entries plus the IMC to add and its priority.
- **`URammsControlInputComponent`** (player controller or pawn): on possess,
  adds the IMC via `UEnhancedInputLocalPlayerSubsystem`, binds each
  `UInputAction` (Triggered/Completed) and forwards to the sink with
  `Source = Keyboard/Gamepad`; "increment at rate" reproduces the current
  held-key behaviour for position motors; Completed → `Release` for
  spring-to-zero axes (fixes the latched-command class of bugs for good).
- Assets: `IMC_RammsRobot` + `IA_Drive` (2-D), `IA_LinkageHeight`,
  `IA_MotorGroup_*`, `IA_CameraNext/Reset/Orbit/Zoom`, `IA_EE_*`,
  `IA_Gripper_*` — one place to see and change every key; gamepad bindings
  come for free.
- Retire the polling: `URammsKeyboardTeleopComponent`,
  `URammsEndEffectorTeleopComponent`'s and `URammsMjArmTeleopComponent`'s key
  sets, `URammsRobotCameraComponent`'s key/mouse reading (its orbit/zoom math
  stays as the contributor). Delete the dead legacy mappings from
  `DefaultInput.ini`. Resolve the Tab/R/O collisions by owning them in the
  IMC.
- **URLab hotkeys (decided):** RAMMS game modes **disable `UMjInputHandler`**
  (and the simulate widget's Tab toggle) rather than patching the fork. The
  functions those keys perform that we still want — sim reset, pause/resume,
  step, the debug-visualizer toggles — come back as **named actions** from a
  MuJoCo sim contributor in RammsMujocoSupport (`sim.reset`, `sim.pause`,
  `sim.debug.contacts`, …), so they are reachable from the panel, the input
  map and Remote Control like everything else.
- **Spike (done first, see below):** confirm Enhanced Input receives Pixel
  Streaming keyboard input in PIE, since the polling was introduced for that;
  the mouse-orbit Slate fallback from the camera component carries over into
  the input component if needed.

### 5. Remote and external clients

- The control surface is the natural **Remote Control** payload:
  `GetControlSurfaceJson()`, `SetAxis`, `TriggerAction` on the adapter,
  replacing path-based `SetDriveInput`/`SetMotorCommand` calls in
  `unreal_remote`; a `RemoteControlPreset` can expose them.
- **RammsAccess** (UDP intents) becomes a client of the sink with
  `Source = Autonomy`, dropping its controller-name overrides.
- RMSS stays sensor-only unless a command opcode is wanted later (that would
  be a protocol version bump — ask first).

## Phases

| # | Scope | Deliverable / validation |
|---|---|---|
| 0 | **ramms-ui in tree.** Add `Plugins/RammsUI` as a submodule (`rammp-org/ramms-ui`), UE 5.7 build, fix anything stale, `unreal_remote`'s bridge lookup works. The vehicle HUD class `URammsUI` is **not** renamed: the whole vehicle-template layer (HUD, `ARammsPawn`, `Content/VehicleTemplate`, the touch UI assets) is legacy slated for removal once phase 3 replaces it, so nothing new builds on it. | Editor builds with the plugin; `find_ramms_widgets()` returns. |
| 1 | **Shared model.** `RammsControl` module in ramms-ui (structs + interfaces + input-map asset), `IRammsRobotController` shim. `RobotBase` enumeration API. | ramms-ui PR; ramms-core PR; both compile standalone. |
| 2 | **Contributions + adapter.** Contributor interface on diff-drive, MeBot, 5-bar, arm/gripper, camera; `URammsRobotControlSurfaceComponent` with claims + raw-motor fallback + source arbitration + subsystem registration; Remote Control JSON. | PIE runners drive the chair and both lift-drive pawns **through the sink** (`SetAxis`), not the controllers; a robot with only a `RobotBase` exposes its motors. |
| 3 | **Panels.** `URammsControlSurfacePanel`, decorations, sim layout preset, joystick, status panel replacing the vehicle HUD; single spawn path in the player controllers. | Pixel Streaming page drives the chair and the lift-drive pawns from touch/mouse; screenshots of the panel per robot. |
| 4 | **Enhanced Input.** Spike (4.0), then input map + component + IMC/IA assets; retire polled components; INI cleanup; collision fixes incl. URLab hotkeys. | Keyboard + gamepad drive every robot with the same map; no `IsInputKeyDown` left in RammsCore/RammsMujocoSupport. |
| 5 | **Cleanup.** RammsAccess → sink; docs (`base_component_controls.md` becomes the control-surface guide); delete the retired components after one release. | Docs + runners updated. |

Phases 1–2 are the load-bearing ones and can be validated headlessly with the
existing PIE runner scripts; 3 and 4 can proceed in parallel once 2 lands.

Status (2026-09-16): ramms-ui #34, ramms-core #23, ramms-mujoco-support #5,
ramms-access #1 and ramms-private-assets #1 are merged; this superproject
branch pins their mains, except RammsCore, which is pinned at the head of the
still-open ramms-core #24 (`ReadTarget`, so panels show a target set directly
on a controller). #24 merges first, then the gitlink moves to the resulting
main commit. Phases 0–1 done (ramms-ui #34, ramms-core #23, ramms-sim #43). Phase 2: adapter + diff-drive / MeBot / 5-bar / camera contributors
done and validated — `run_chaos.sh` and `run_mj_full.sh` now drive, turn and
lift through `SetControl` on the pawns' `ControlSurface`, and the lift-drive
pawn lists its unclaimed cranks / wheels as `motor.<id>` axes. The 5-bar's
height range is derived from the mechanism (`GetReachableHeightRange`), which
also exposed that the runner's old "lift to 16 cm" had been refused since the
motor-range check landed. Arm / gripper contributors (Chaos Kinova via
`RammsEndEffectorTeleopComponent`, MuJoCo via `RammsMjArmTeleopComponent`,
same `arm.*` / `gripper.*` ids), the MuJoCo sim contributor
(`RammsMjSimControlComponent`: `sim.reset` / `sim.pause` / `sim.step` /
`sim.running` + the URLab debug toggles) and the `RammsUISubsystem`
control-surface registry are in too, all exercised by the runners. Phase 2 is
complete; the "per-robot defaults out of constructors" cleanup moves to phase 5.

Phase 4 (2026-09-15): `URammsControlInputComponent` (RammsCore) + the assets
from `make_input_assets.py` (`IA_Ramms_*`, `IMC_RammsRobot`, `DA_RammsInput_*`;
`FRammsControlInputBinding` gained `ControlIdZ` and wildcard Ids). The lift-drive
pawns and the chair carry `ControlInput`; the polled `KeyboardTeleop` is off the
pawns (class kept one release), the camera's N / Home polling is gone, and both
arm teleops' key polling is off by default. `RammsMujocoTestGameMode` disables
URLab's `UMjInputHandler` and simulate widget. Validated by injecting the
actions through the same Enhanced Input path (`control_input_check.py` in both
runners): drive, linkage height, motor groups, camera next, gripper, arm, sim
pause / reset. Left for later: mouse orbit / wheel zoom stay polled on the
camera component; the chair's drive still also runs through the legacy vehicle
template (`IA_Throttle` -> Chaos vehicle, joystick tick) until phase 3 replaces
that layer; the dead `DefaultInput.ini` action / axis mappings were not deleted
(the vehicle-template layer goes as a whole).

Phase 3 (2026-09-15): in ramms-ui, `URammsControlSurfacePanel` (+
`URammsControlRow`, `URammsSurfaceJoystick`), `URammsSimLayout` and the
single spawn path `URammsControlHUDSubsystem` / `URammsControlHUDSettings`.
`ARammsPlayerController` no longer spawns the vehicle HUD / mobile controls.
The paired-axis convention (lower Order = vertical) is documented on
`FRammsControlAxis::PairedAxis` and the arm / camera contributors follow it.
Validated in PIE on the chair (13 rows: slider row moves a lift motor, action
row closes the gripper, hold row raises the arm, joystick drives) and the
lift-drive pawn (24 rows: joystick drives, linkage row lowers the leg,
`sim.pause` row pauses, `camera.next` row switches), with screenshots. Left
for later: the `URammsStatusPanel` (speed / battery) and the themed
decorations (MeBot modes, arm home / retract) on the sim layout; per-robot
Pixel Streaming screenshots (the page path is unchanged: keys and touch reach
the same Enhanced Input / sink paths); the time-trial variant keeps its own HUD.

Phase 5 (2026-09-15): RammsAccess drives the surface with `Source = Autonomy`
(ramms-access PR; legacy direct path kept as fallback); the diff-drive
contributor goes through the external hold so a surface command outranks the
chair's legacy per-tick joystick writer; `unreal_remote.control_surface`
wraps the surface for Remote Control clients (and the client's component
discovery parameter name was fixed). `base_component_controls.md` is the
control-surface guide. Deferred: deleting the retired components
(`RammsKeyboardTeleopComponent`, the arm teleops' key polling, the vehicle
HUD spawn members) after one release; the `IRammsRobotController` shim stays
(decision 2); the `DefaultInput.ini` legacy mappings go with the vehicle
layer.

Follow-up (2026-09-15, after the first PIE try-out): the HUD was visible but
not clickable — the vehicle template's `DefaultTouchInterface` virtual
joystick (shown whenever `bUseMouseForTouch` fakes touch in PIE) sat above
every widget, and the viewport captured the mouse. `URammsControlHUDSubsystem`
now deactivates the engine touch interface and switches the player to
Game-and-UI input mode with a visible cursor (`bReplaceEngineTouchInterface`,
`bGameAndUIInputMode` in the settings). `BP_Mebot_Ramms` still carried direct
input wiring the export revealed — keys 1–8 / + / − to MeBot motor presets,
`IA_Throttle` / `IA_Steering` reads feeding a per-tick `SetDriveInput` — all
stripped with `URammsBlueprintCleanupLibrary::RemoveLegacyInputNodes`
(RammsCoreEditor; `Scripts/pie_tests/base_component/strip_bp_input.py`), so
the chair is driven only through the surface. The vehicle mapping context
(`IMC_Vehicle_Default`) is still added by `BP_VehicleAdvPlayerController` and
goes with the vehicle layer.

Second try-out: the wheel over the panel didn't scroll it (the collapsible
groups forced `ConsumeMouseWheel = Always`; the panel now handles the wheel
itself), and a touch drag on the panel or joystick also orbited the camera
(the camera now asks Slate for the widget path under the cursor and leaves
drags and the wheel that land on UI alone). `bUseMouseForTouch` is now off
in `DefaultInput.ini`: with it on, a desktop PIE session fakes touch, so
hover, widget paths and wheel routing only update while a button is held.
Real touch (Pixel Streaming) is unaffected.

Deferred by decision (2026-09-15): the holonomic base's four omni wheels are
`<motor>` (torque) actuators in the MJCF and appear on the surface as raw
continuous `motor.*_omni_wheel` axes. That is fine for now; a holonomic drive
contributor (`drive.forward` / `drive.strafe` / `drive.turn`, claiming the
omni wheels and closing its own velocity loop over the torque actuators, as
the differential drive does) replaces those raw rows when it lands.

## Decisions (2026-09-15)

1. Shared types: `RammsControl` module inside the ramms-ui plugin.
2. `IRammsRobotController` stays as a shim; the HMI is not migrated now.
3. Enhanced Input for Pixel Streaming: spike first, no polling fallback
   unless the spike fails (result recorded below).
4. URLab hotkeys: disable `UMjInputHandler` in RAMMS game modes; expose sim
   reset / pause / debug toggles as named actions through our interfaces.
5. No rename of `URammsUI`: the vehicle-template layer is legacy and will be
   removed in favour of our own systems.

## Spike: Enhanced Input over Pixel Streaming

**Result (2026-09-15): works.** PIE on `Map_Demo` with the chair
(`BP_Mebot_Ramms`, whose throttle is an Enhanced Input action `IA_Throttle` in
`IMC_Vehicle_Default`, bound in `ARammsPawn::SetupPlayerInputComponent`).
From the Pixel Streaming player page in Chrome, holding **W** (a keyboard
event on the video element) drove `RammsDifferentialDriveController::DriveInput`
to (0, 1) within a frame and the chair from x = −349 to x = −18 (it stopped
against the building), and releasing W returned the input to (0, 0). So
Pixel Streaming keyboard events reach `EnhancedPlayerInput` exactly as they
reach the polled path — Enhanced Input is the only keyboard/gamepad path;
no polling fallback. (Mouse buttons/axes over the stream remain the known
editor-PIE limitation, independent of the input system.)
