# Base-component PIE tests

Drives the running editor over Python remote execution
(`Scripts/editor_remote_exec.py`) to validate the shared robot base component
on both physics backends. Requires the editor open with Remote Execution on.
The lift-drive assets live in the optional `RammsPrivateAssets` plugin
(`git submodule update --init --checkout Plugins/RammsPrivateAssets`, then
restart the editor); the MuJoCo builders/tests need it, the Chaos chair test
doesn't. `move_private_assets.py` is the one-shot migration that put them there.

- `make_assets.py` — creates the motor / 5-bar DataTables under
  `/Game/Robots/Data`, adds `RobotBase` to `BP_Mebot_Ramms`, and builds
  `BP_LiftDriveLinkage_Ramms` (child of the imported articulation) with the
  base, diff-drive and both centre 5-bar controllers. Idempotent.
- `make_input_assets.py` — authors the Enhanced Input assets under
  `/Game/Input/Ramms`: the `IA_Ramms_*` actions, the single `IMC_RammsRobot`
  mapping context (every key, once) and one `URammsControlInputMap` per robot
  family (`DA_RammsInput_LiftDriveLinkage` / `LiftDriveHolonomic` / `Mebot`)
  binding actions to control Ids (wildcards such as `motor.*_front_crank`).
  Re-run it to change a key; it overwrites mappings and bindings.
- `make_pawns.py` — makes `BP_LiftDriveLinkage_Ramms` / `BP_LiftDriveHolonomic_Ramms`
  driveable pawns (RobotBase, diff-drive, 5-bar, follow + top-down cameras
  with a RammsRobotCameraComponent, ControlSurface, SimControl, ControlInput
  with the family's input map, AutoPossessPlayer). The legacy polled
  KeyboardTeleop is removed.
  Keys (IMC_RammsRobot): W/S A/D drive, E/Q legs, Y/H T/B Z/X C/V motor
  groups, N camera / Home reset, I/K J/L U/O + arrows + M/. arm, R resync,
  [ ] G gripper, P pause, Backspace reset, / step, 1-7 debug toggles; mouse
  drag orbit and wheel zoom stay on the camera component.
- `make_test_map.py` — `BP_LiftDriveTestGameMode` + rewrites `Map_BaseTest_URL`
  (PlayerStart, GameMode Override, placed articulations removed) so a plain Play
  spawns, possesses and simulates the chosen lift-drive pawn.
- `run_chaos.sh` — PIE on Map_Demo: the Chaos chair drives and turns through
  its **control surface** (`chaos_t1.py` / `chaos_turn.py` / `chaos_stop.py`
  call `SetControl("drive.forward" | "drive.turn")` on the pawn's
  `RammsRobotControlSurfaceComponent`), then its constraint-driven Position
  motors are commanded and read back through the base (`chaos_pos_*.py`),
  the surface's lift axes and source arbitration are checked
  (`control_surface_check.py`), the Kinova arm and gripper are driven through
  `arm.forward` / `gripper.closed` / `arm.resync` (`chaos_arm.py`), the
  RammsUISubsystem registry is checked, Enhanced Input actions are injected
  through `ControlInput` (lift motor group, gripper open / close, arm up —
  `control_input_check.py`), and the MebotController API is exercised.
- `run_mj_full.sh` — PIE on Map_BaseTest_URL with `BP_LiftDriveLinkage_Ramms`:
  points `BP_LiftDriveTestGameMode.DefaultPawnClass` at the linkage pawn for the
  run (unsaved; `mj_restore.py` reloads the game mode from disk afterwards), lets
  the game mode spawn/possess/unpause it, then drives and turns through the
  surface (`mj_drive.py`, `mj_turn.py`), moves the 5-bar legs to the bottom
  and top of the height range the linkage reports (`mj_lift.py`, which fails
  if the surface refuses), lists the surface — drive, linkage, camera, sim and
  the unclaimed crank / wheel motors — and pauses, resumes and resets the
  MuJoCo scene through `sim.pause` / `sim.running` / `sim.reset`
  (`control_surface_check.py`), then repeats drive / linkage height / camera
  next / pause / reset by injecting the Enhanced Input actions (W, Q, N, P,
  Backspace) into `ControlInput` and checks URLab's hotkey handler is off
  (`control_input_check.py`).
- `cs_common.py` — the runners' helpers: find the pawn's surface, pause the
  per-tick local input writers, `set_control` that raises when refused.
- `strip_bp_input.py` — removes a robot Blueprint's direct input wiring (key
  events, input-action reads, the per-tick `SetDriveInput` write) via
  `RammsBlueprintCleanupLibrary` (RammsCoreEditor); run once on
  `BP_Mebot_Ramms` on 2026-09-15.
- `access_send.py` — host-side sender of ramms-access v1 intent packets (UDP
  JSON: `--drive X Y`, `--ee-lin`, `--ee-ang`, `--event`); `access_check.py`
  asserts the surface's owner (`expect_owner drive.forward Autonomy`).
- `hud_check.py` — the auto-spawned control HUD (ramms-ui) via
  `unreal._ramms_hud_op`: `status | shot | joystick <x> <y> | joystick_release |
  row <id> <value> | action <id> | hold <id> <+|-> | release <id>` — drives
  the panel's rows and the drive joystick the way a touch would.
- `control_input_check.py` — Enhanced Input ops via `unreal._ramms_ci_op`:
  `status | inject <IA name> <x> <y> <z> [hold_s] | expect <id> <min> <max> |
  camera | camera_changed | urlab`. `inject` feeds an action as if its key
  were held (`URammsControlInputComponent::InjectActionByName`).
- `control_surface_check.py` — ad-hoc surface ops via `unreal._ramms_cs_op`:
  `describe | drive | stop | set <id> <v> | release <id> | trigger <id> |
  read <id> | json | arbitration | registry`.

The runners resolve the repo root from their own location, so they work from
any clone. Gotchas: each remote command runs synchronously on the game thread,
so tests are chains of short scripts with local sleeps, run from **bash**; never
`set_editor_property` on live PIE components (use the `Set*` UFUNCTIONs); the
chair's legacy tick re-issues its joystick every frame, so a scripted
command on the chair needs its actor tick disabled first
(`cs_common.quiet_local_input`).
