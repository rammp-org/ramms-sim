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
- `make_pawns.py` — makes `BP_LiftDriveLinkage_Ramms` / `BP_LiftDriveHolonomic_Ramms`
  keyboard-driveable pawns (RobotBase, diff-drive, 5-bar, KeyboardTeleop, follow
  + top-down cameras with a RammsRobotCameraComponent, AutoPossessPlayer).
  Keys: W/S A/D drive, E/Q legs, Y/H T/B Z/X C/V motors; N camera, mouse
  drag orbit, wheel zoom, Home reset.
- `make_test_map.py` — `BP_LiftDriveTestGameMode` + rewrites `Map_BaseTest_URL`
  (PlayerStart, GameMode Override, placed articulations removed) so a plain Play
  spawns, possesses and simulates the chosen lift-drive pawn.
- `run_chaos.sh` — PIE on Map_Demo: the Chaos chair drives and turns through
  its **control surface** (`chaos_t1.py` / `chaos_turn.py` / `chaos_stop.py`
  call `SetControl("drive.forward" | "drive.turn")` on the pawn's
  `RammsRobotControlSurfaceComponent`), then its constraint-driven Position
  motors are commanded and read back through the base (`chaos_pos_*.py`),
  the surface's lift axes and source arbitration are checked
  (`control_surface_check.py`), and the MebotController API is exercised.
- `run_mj_full.sh` — PIE on Map_BaseTest_URL with `BP_LiftDriveLinkage_Ramms`:
  points `BP_LiftDriveTestGameMode.DefaultPawnClass` at the linkage pawn for the
  run (unsaved; `mj_restore.py` reloads the game mode from disk afterwards), lets
  the game mode spawn/possess/unpause it, then drives and turns through the
  surface (`mj_drive.py`, `mj_turn.py`), moves the 5-bar legs to the bottom
  and top of the height range the linkage reports (`mj_lift.py`, which fails
  if the surface refuses), and lists the surface — drive, linkage, camera and
  the unclaimed crank / wheel motors (`control_surface_check.py`).
- `cs_common.py` — the runners' helpers: find the pawn's surface, pause the
  per-tick local input writers, `set_control` that raises when refused.
- `control_surface_check.py` — ad-hoc surface ops via `unreal._ramms_cs_op`:
  `describe | drive | stop | set <id> <v> | release <id> | trigger <id> |
  read <id> | json | arbitration`.

The runners resolve the repo root from their own location, so they work from
any clone. Gotchas: each remote command runs synchronously on the game thread,
so tests are chains of short scripts with local sleeps, run from **bash**; never
`set_editor_property` on live PIE components (use the `Set*` UFUNCTIONs); the
keyboard teleop component re-issues the key state every tick, so a scripted
command needs its tick disabled first (`cs_common.quiet_local_input`).
