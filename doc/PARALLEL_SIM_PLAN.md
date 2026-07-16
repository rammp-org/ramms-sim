# Parallel Headless Simulation for Policy Training & Data Collection

Plan of record for running RAMMS at scale — headless (but rendering, for
visual/ToF/sonar data) on SLURM GPU clusters — for robotics policy training,
evaluation, and dataset collection. Drafted 2026-Q2 from a full inventory of the
RAMMS repos; updated as phases land.

## Decisions of record

- **GPU nodes**: RT-core GPUs (e.g. RTX 6000 Pro). The ToF/sonar GPU
  inline-ray-tracing path and Lumen HWRT are the plan of record; the CPU
  line-trace fallback is a degraded mode (different trace semantics), not a
  target.
- **No Epic container-registry dependency.** Engine comes from a self-managed
  UE 5.7 source/installed build on a Linux build machine (Epic GitHub source
  access exists today but is not assumed in general). The cluster image
  (`containers/ramms.def`) bundles our own packaged build — no external
  registries.
- **Dataset format: deferred, pluggable.** The collector writes through a
  writer interface; LeRobot / RLDS / zarr are candidates pending what the
  research team uses. Not a blocker for Phases 0–2.
- **Both modes supported**: online RL with the sim in the loop (saves
  storage), and offline episode collection (repeatability). Same launch and
  isolation infrastructure serves both.

## What exists (inventory summary, 2026-07)

| Piece | State |
|---|---|
| **URLab bridge** (`Plugins/unreal-robotics-lab`) | msgpack/ZMQ RPC :5559, state PUB :5555, ctrl/info :5556/:5557, per-camera PUB :5558+, same-host shared-memory transport. **Deterministic lockstep**: `Direct` (client sends ctrl, sim steps N, returns obs — built for RL) and `Puppet` (client owns integrator, UE renders qpos) step modes. Single-client, fixed ports, no multi-instance scheme (roadmap). |
| **urlab_bridge** (separate repo, github.com/URLab-Sim/urlab_bridge) | Typed Python client, `gymnasium.Env` (single-env), policy runner, ROS2 broadcaster. |
| **Sensors** (RammsCore) | ToF (`RammsToFSensorComponent`, up to 64×64 zones) + sonar via `FRammsSensorRayTracer` — GPU inline RT compute vs the TLAS (needs real RHI + HWRT + `r.RayTracing.AsyncBuild=0`), CPU LineTrace fallback (no channel/owner filtering — different semantics). IMU. |
| **Cameras** (CameraCapture + URLab MjCamera) | SceneCapture2D with real intrinsics (OpenCV model, RealSense presets), async GPU readback, fisheye/Brown-Conrady lens shader; URLab cameras publish RGB/depth-f32/segmentation over ZMQ/SHM, deliverable inline in `step_ok` (sync). |
| **ramms-tools** (atdev-inc/ramms-tools) | Python dev/control clients: Remote Control HTTP :30010, RMSS streaming TCP :30030, CLIs, TUI. Editor-oriented — **not** the training path. New orchestration CLIs land here. |
| **Project** | Game + Editor targets (no server target — not wanted; we need rendering). Linux/Vulkan SM6 targeted. Map-per-scenario (`Map_GraspTest`, `Map_CurbTest`, …) with per-map game-mode overrides; standard UE map URL selects scenario — no custom CLI needed. No packaging/CI/cluster scripts before this plan. |
| **Physics plugins** | URLab embeds MuJoCo (physics thread in-process). RammsNewtonPhysics vendors newton (Warp/GPU, FixedStepHz=60). RammsMujocoPhysics / RammsHumanPhysics are empty placeholders. |

Training path = **URLab bridge** (lockstep + sensors). Remote Control/RMSS
stay for interactive dev. The URLab docs' recommended split holds: mass
parallel *training* in MJX/mjlab where possible; RAMMS provides sensor-rich
rollouts, vision-policy data, and evaluation.

## Architecture

N independent UE processes, one env each (URLab is single-env by design),
orchestrated from Python:

```
SLURM job array
└── task[i] on a GPU node
    ├── Apptainer (containers/ramms.def): packaged Linux build
    │     Ramms <Map> -RenderOffscreen -Unattended -NoSound
    │     -UseFixedTimeStep -FPS=30 -Deterministic -saveddir=<inst_i>
    │     URLab bridge on port block base+i*10 (or SHM, same host)
    └── Python worker (urlab_bridge client)
          reset(seed_i, randomization_i) → Direct-mode step loop
          → obs + camera/ToF/sonar frames
          → episode shards (pluggable writer) on shared FS   [offline]
          → or feeds VectorEnv for the trainer               [online]
```

Determinism recipe: URLab `Direct` stepping (client-owned clock) + UE
`-UseFixedTimeStep -FPS=N` so rendered frames keep a fixed phase relationship
to physics steps; `include_cameras=sync` for blocking fresh-frame observations.

## Workstreams

### 1. Linux build & packaging — **Phase 0 (scripts landed, unverified on Linux)**

Two supported build routes:

**A. Native Linux** (build machine or container):
- `Scripts/build_linux.sh` — URLab third-party (now passes `--engine` on
  Linux: UE clang/libc++, avoids the ABI wall) + RammsEditor/Ramms builds.
- `Scripts/package_linux.sh` — `BuildCookRun` → `Packaged/Linux` (optional
  `MAPS=` cook list; `CONFIG=Shipping` once proven).

**B. Windows→Linux cross-compile** (standard UE workflow, needs the UE Linux
cross-toolchain / `LINUX_MULTIARCH_ROOT`):
- `Scripts/build_all_linux_cross.ps1` — cross-compiles MuJoCo/CoACD/libzmq
  with the cross-toolchain's clang/libc++ (same flags as `build_all.sh
  --engine`) into `third_party/install-linux/` — separate from the
  Windows-native `install/` so the local editor's libs survive (each dep
  build wipes its install dir). `URLab.Build.cs` picks `install-linux/`
  automatically when targeting Linux from a Windows host (in the local-fixes
  patch).
- `Scripts/build_linux_cross.ps1 [-Package]` — UBT Linux build + optional
  `BuildCookRun -platform=Linux` (cooking runs the Windows editor).

Both routes produce the same `Packaged/Linux` output.

- `containers/ramms.def` bundles it — self-contained Apptainer image (ubuntu
  base + Vulkan loader + NVIDIA ICD manifest; run with `--nv`).
- Risk: RammsCore's sensor tracer includes engine **Renderer private
  headers** — build machine needs the exact UE 5.7 tree; engine upgrades will
  bite here first.
- Cross-route caveat: the three CMake cross builds are authored from the
  native recipes but not yet exercised — first run on the Windows box will
  shake out toolchain/sysroot details (CoACD's TBB/OpenVDB tree is the likely
  friction point).

### 2. Single-instance headless bring-up — **Phase 1**
- `Scripts/run_headless.sh` (landed): offscreen-Vulkan launch with fixed
  timestep, per-instance `-saveddir`, port-block derivation.
- Verify on a Linux RT-core node: boot `Map_GraspTest`, `hello` handshake,
  100 Direct steps, camera bytes arrive, ToF/sonar return GPU-path hits,
  state stream flows. Automate as the smoke test → CI canary + SLURM health
  probe.
- URLab port-override patch: **landed** as
  `Scripts/patches/urlab-port-overrides.patch` (applied by `setup_urlab.sh`,
  compiles on Mac). Adds `-URLabStepPort/StatePort/CtrlPort/InfoPort/CamPort=`
  switches — required because the bridge INI lives inside the plugin dir
  (shared by all instances) and the cooked path hardcoded :5559. Cooked-build
  bridge autostart confirmed in source (`AAMjManager` owns the bridge when no
  editor subsystem resolves). Remaining Phase-1 verification: SHM session
  isolation under per-instance `-saveddir`, and the whole thing on Linux.
- Validate Vulkan inline ray query (`RHISupportsInlineRayTracing`) on the
  target driver; confirm `r.VirtualTextures=False` behaves on Vulkan.

### 3. Multi-instance per node — **Phase 2**
- `ramms-launch` (new `ramms_tools.cluster` module): spawn N instances,
  derived port blocks, isolated saveddirs/logs, hello-probe readiness, crash
  detect/restart, teardown.
- GPU sharing via NVIDIA MPS; benchmark envs/GPU vs camera resolution
  (readback + VRAM bound). Prefer SHM transport for same-host workers.

### 4. SLURM deployment — **Phase 3**
- `slurm/collect_array.sbatch`, `slurm/eval.sbatch`: job arrays, ports from
  `SLURM_PROCID`, `CUDA_VISIBLE_DEVICES` binding, logs/shards on shared FS,
  requeue-safe (shard-level idempotency).
- `ramms-cluster` CLI: submit/monitor/cancel sweeps from a YAML manifest
  (seeds, domain-randomization configs, scenario suites).

### 5. Data collection & datasets — **Phase 3**
- `ramms-collect`: drives episodes (scripted policy, URLab recording replays,
  or trained policy via `urlab_policy`) → shards via the **pluggable writer**
  (format TBD with researchers; include camera intrinsics/extrinsics + sensor
  calibration in episode metadata).
- Replay-multiplication: re-render URLab qpos/qvel recordings under
  randomized appearance/lighting/crowds to multiply visual data from few
  demonstrations.

### 6. Training-loop integration — **Phase 4**
- Online: `URLabVectorEnv` — gymnasium `VectorEnv` fanning out over N remote
  instances (async step).
- Offline: collect → train externally (mjlab/MJX/your stack) → `ramms-eval`
  runs checkpoints against scenario suites and reports metrics.

## Phase status

- [x] Phase 0: plan doc, `build_linux.sh`, `package_linux.sh`,
      `run_headless.sh`, `containers/ramms.def`, setup_urlab `--engine` fix,
      URLab port-override patch (compiles on Mac), Windows→Linux cross route
      (`build_all_linux_cross.ps1` + `build_linux_cross.ps1` + Build.cs
      `install-linux/` resolution)
      *(authored on Mac — first Linux/Windows run will shake out details)*
- [ ] Phase 1: Linux build + packaged headless instance verified end-to-end
      (incl. GPU ToF/sonar) on an RT-core node; smoke test scripted
- [ ] Phase 2: N instances/node via `ramms-launch`; envs/GPU benchmark
- [ ] Phase 3: SLURM templates + `ramms-collect` at scale
- [ ] Phase 4: `URLabVectorEnv` online RL; `ramms-eval` suites

## Open items

- Dataset format decision (researchers) — writer interface keeps it cheap.
- Where the Linux UE build lives (dedicated build node vs. workstation).
- Chaos-based scenarios (RammsCrowd pedestrians, vehicle dynamics) in
  collection: fine headless, but not deterministic like the MuJoCo path —
  use for data diversity, not reproducible eval.
- URLab upstream coordination: port-override + packaged-game-autostart
  patches should go upstream (single-client bridge multi-instance support is
  on their roadmap).
