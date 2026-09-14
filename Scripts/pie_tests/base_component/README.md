# Base-component PIE tests

Drives the running editor over Python remote execution
(`Scripts/editor_remote_exec.py`) to validate the shared robot base component
on both physics backends. Requires the editor open with Remote Execution on.

- `make_assets.py` — creates the motor / 5-bar DataTables under
  `/Game/Robots/Data`, adds `RobotBase` to `BP_Mebot_Ramms`, and builds
  `BP_LiftDriveLinkage_Ramms` (child of the imported articulation) with the
  base, diff-drive and both centre 5-bar controllers. Idempotent.
- `make_pawns.py` — makes `BP_LiftDriveLinkage_Ramms` / `BP_LiftDriveHolonomic_Ramms`
  keyboard-driveable pawns (RobotBase, diff-drive, 5-bar, KeyboardTeleop, follow
  + top-down cameras with a RammsRobotCameraComponent, AutoPossessPlayer).
  Keys: W/S A/D drive, E/Q legs, R/F T/G Y/H U/J motors; Tab camera, mouse
  drag orbit, wheel zoom, Home reset.
- `make_test_map.py` — `BP_LiftDriveTestGameMode` + rewrites `Map_BaseTest_URL`
  (PlayerStart, GameMode Override, placed articulations removed) so a plain Play
  spawns, possesses and simulates the chosen lift-drive pawn.
- `run_chaos.sh` — PIE on Map_Demo: the Chaos chair drives through the base
  component (`chaos_*.py`).
- `run_mj_full.sh` — PIE on Map_BaseTest_URL with the placed linkage swapped
  for the child BP (editor world only; the map is reloaded unsaved after):
  unpause the MuJoCo scene, drive, retract (expected refused), extend
  (`mj_*.py`).

Gotchas: each remote command runs synchronously on the game thread, so tests are
chains of short scripts with local sleeps, run from **bash**; the MuJoCo scene in
Map_BaseTest_URL starts paused; never `set_editor_property` on live PIE
components (use the `Set*` UFUNCTIONs).
