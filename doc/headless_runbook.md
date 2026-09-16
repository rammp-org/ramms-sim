# Headless URLab/MuJoCo runbook — hard-won operational truths

Practical rules for scripting URLab work headlessly (import, convert, sim,
acceptance), distilled from the `feat/newton-improvements` effort. These are
UE 5.7 / URLab facts that cost real debugging time; they are engine-stable and
apply to all the MuJoCo simulation work (see `doc/mujoco_sim_roadmap.md`).

## Running / driving the editor headlessly

- **Rig/scene edits and imports need a live editor**, not `-game`/cooked. Use
  `UnrealEditor` (the app-bundle binary on macOS — the bare stub fails with
  "Failed to find game directory") with `-ExecutePythonScript`, or the URLab
  bridge's editor ops, or Remote Control.
- **Python `unreal.log` is NOT reliably surfaced by headless runs.** A script's
  result must be written to a **file** (e.g. `Saved/<something>.txt`) and read
  back; don't parse it out of the log.
- **`-ExecCmds` console commands apply *after* the first world tick** — i.e.
  after `BeginPlay`/backend init. A whole bisect campaign on the newton branch
  tested nothing because cvars set via `-ExecCmds` landed too late. For anything
  that must be in effect at init, parse it from the **command line**
  (`FParse::Value/Param`) instead.
- **Don't kill `UnrealEditor-Cmd` when the log looks done** — Python
  `save_asset` runs *after* the last C++ log line; a premature kill silently
  discards the save.
- **Remote Control gotchas** (validated this project): the property-write API
  silently fails on array-valued `TOptional` fields (clears them to unset) —
  use the generated `Set*` UFUNCTIONs for arrays; scalar writes are fine. Python
  remote execution must be enabled in the RC project settings. Never write
  properties on *live* (PIE) URLab components — it re-initializes them mid-sim.

## Headless acceptance / determinism

- **Spectator-only game mode** for `-game` acceptance: the default game mode
  spawns a colliding pawn that contaminates the robot. Launch with
  `?game=/Script/Engine.GameMode?SpectatorOnly=1`.
- **Determinism recipe:** URLab `Direct` step mode + `-UseFixedTimeStep -FPS=N`
  makes the MuJoCo stepping reproducible. Seeding is *client-side* today — the
  `reset` RPC carries no seed (a candidate wire-contract change, see the
  roadmap), so resolve all randomization before `begin_pie`.
- **Keep the MuJoCo twin far from any other physics instance** — overlapping
  robots read garbage transforms and depenetrate explosively (looks like
  "vibration in place" with upZ≈1.0).

## URLab import landmines (asset pipeline)

- **Source-control provider blocks scripted imports** (can't `CheckOut`) — set
  the SC provider to None, or a scripted reimport silently fails and the asset
  gets deleted on disk.
- **AssetRegistry boot crash** ("index out of bounds") recurs after file-level
  `.uasset` deletion while `CachedAssetRegistry*.bin` still indexes them — purge
  `Intermediate/CachedAssetRegistry*.bin`.
- **Physical materials must be saved on creation** — an in-memory package is
  invisible to `LoadObject` next session and gets silently recreated at default
  friction.
- **Delete-then-reimport the same asset name in one editor session fails
  silently** (the deleted object lingers) — reimport in a fresh session.
- **AssetTools refuses imports while in Play mode** — and URLab's bridge
  auto-start can enter play on boot; ensure PIE is stopped before importing.
- **Mesh assets are shared mutable state** — a generator that writes into a
  mesh's `BuildScale`/collision means "restore the committed asset" is only
  valid if the mesh-asset folder is restored too.

## MJCF hygiene

- **`.gitignore`'s `*.obj` eats exporter mesh OBJs** — a fresh clone can't
  compile an MJCF that references `.obj` visuals. Keep `.glb` sidecars committed
  and regenerate the OBJs with `mujoco/bake_inertials.py` (trimesh GLB→OBJ, with
  the +180°X round-trip convention).
- **Bake explicit inertials** into any MJCF shared across engines
  (`mujoco/bake_inertials.py <model.xml>`) — identity for MuJoCo, but gives
  Newton and any other consumer the exact mass distribution.
