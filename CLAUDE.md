# RAMMS-Sim - Claude Code guide

Unreal Engine 5.7 C++ simulation for robotic assistive mobility/manipulation: MeBot differential-drive wheelchair base, 7-DOF Kinova Gen3 arm (DLS/FABRIK/CCD IK), GPU-raytraced ToF/Sonar/IMU sensors, multi-camera EXR capture, and RMSS TCP streaming. Requires exactly UE 5.7.

## Key rules
- **Plugins are git submodules** (`Plugins/RammsCore`, `CameraCapture`, `RammsStreaming`, `RammsAssets`, `RammsHumanPhysics`, `RammsNewtonPhysics`, `RammsMujocoPhysics`). Edit and commit plugin code in the plugin's own repo, then bump the submodule pointer in this superproject; committing plugin changes only here loses them. Run `git submodule update --init --recursive` before any build.
- **pre-commit clang-format skips `Plugins/`** (`.pre-commit-config.yaml` has `exclude: ^Plugins/`), so only `Source/` is auto-formatted. When you touch plugin C++, run clang-format manually with the repo `.clang-format`.
- **Reflected changes need a full recompile.** Adding/altering any `UPROPERTY/UFUNCTION/UCLASS/USTRUCT/UENUM` regenerates `.generated.h`; rebuild via `Build.bat` rather than trusting Live Coding for header/reflection edits.
- **RMSS wire protocol is a cross-process contract.** `FRammsStreamHeader` in `Plugins/RammsStreaming/Source/RammsStreaming/Public/RammsStreamProtocol.h` is a fixed 32-byte little-endian header (magic `RMSS`, `VERSION=1`, `HEADER_SIZE=32`) with `ERammsStreamMessageType` opcodes, consumed by external TCP/Python clients on port 30030. Changing field layout, opcodes, size, or version means bumping `VERSION` and updating source, sink, and external clients together.
- **GPU sensor shaders have a fixed path.** `.usf` compute shaders live in `Plugins/RammsCore/Shaders/Private/` (e.g. `RammsSensorTrace.usf`) and are mapped to virtual path `/RammsCore` in `FRammsCoreModule::StartupModule()`; include them as `/RammsCore/...`. RammsCore pulls engine `Renderer/Private` + `Internal` headers for the RDG TLAS SRV, so the GPU trace path is coupled to UE 5.7 internals and needs Lumen HW RT to populate the TLAS.
- **Never set `r.RayTracing.ForceAllRayTracingEffects=1`** - it breaks the `DrawDebugMesh` used for sensor/camera frustum visualization. Keep `r.RayTracing` and `r.Lumen.HardwareRayTracing` enabled in `Config/DefaultEngine.ini` so the sensor TLAS stays populated.
- **All sensors trace along their local +X axis.** Orient ToF/Sonar/IMU components accordingly.

## Stack & layout
- C++ (UE 5.7) + Blueprints; HLSL compute shaders; Python for URDF/remote control. IK uses **Eigen** (see `RammsCore.Build.cs`).
- `Source/Ramms/` - main runtime module (game mode, pawn, Chaos vehicle); `Source/*.Target.cs` define the `Ramms` and `RammsEditor` targets.
- `Plugins/RammsCore/Source/RammsCore/` - controllers, sensors, IK (`Public/`+`Private/`); `Shaders/Private/`; `Content/Python/urdf/` conversion scripts.
- `Config/` - `.ini` project/renderer settings; `Content/` - maps, robot/vehicle blueprints.

## Build, run, test
- Set `$UE = "C:\Program Files\Epic Games\UE_5.7"` (adjust to your install).
- **Build URLab's native third-party deps once after cloning, and again whenever the `unreal-robotics-lab` submodule pointer moves:** `cd Plugins/unreal-robotics-lab/third_party; ./build_all.ps1` compiles MuJoCo/CoACD/libzmq into `third_party/install/`. Skip it and `RammsEditor` fails at the rules stage with `MuJoCo install is missing '...INSTALLED_SHA.txt'` - the `URLab` module (pulled in via `RammsMujocoSupport`) enforces a SHA drift check against those installs.
- Compile after C++ edits: `& "$UE\Engine\Build\BatchFiles\Build.bat" RammsEditor Win64 Development -Project="$PWD\Ramms.uproject" -WaitMutex`. Standalone target is `Ramms`.
- Package: `RunUAT.bat BuildCookRun -Project=... -Build -Cook -Stage -Pak -Archive`.
- Run: open `Ramms.uproject` in UE 5.7, or launch the built editor/`-game`.
- **No C++ automation-test suite** - a clean UBT compile of `RammsEditor` is the primary gate. URDF Python has `Plugins/RammsCore/Content/Python/urdf/test_urdf.py`; remote-control Python uses UE Remote Execution (port 6776).

## Conventions
- Format C++ with the repo `.clang-format` (Epic C++ Coding Standard: tabs `UseTab: Always`, `ColumnLimit: 0`, `PointerAlignment: Left`, reflection macros treated as statement macros). Run `pre-commit install` once.
- New plugin C++ classes go in the plugin's `Public/` (exported via `*_API`) or `Private/`; add deps to the module `.Build.cs`, then regenerate project files.
- Prefer UE types/logging (`UE_LOG`, `TArray`, `FString`); do not introduce STL where an engine equivalent exists.

## When to ask
- Changing the RMSS protocol, URDF naming/mapping, or any cross-process/wire format.
- Renderer, ray-tracing, or `Config/*.ini` changes that affect sensors or Lumen.
- Bumping the UE engine version or moving a submodule to an incompatible revision.
- Public plugin API changes (`RAMMSCORE_API`/`RAMMSSTREAMING_API` headers) that other modules depend on.
