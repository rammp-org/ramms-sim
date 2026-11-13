# Getting started

<sub>[README](../README.md) · [Getting started](getting_started.md) · [Features](features.md) · [Scripting and remote control](remote_and_scripting.md) · [World generation](world_generation.md)</sub>

Installing, building and configuring RAMMS-Sim, and working on it.

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Building from the command line](#building-from-the-command-line)
- [Repository layout](#repository-layout)
- [Configuration](#configuration)
- [Developing](#developing)

## Prerequisites

- **Unreal Engine 5.8**
- **Windows** with DirectX 12 (recommended) or **Linux** with Vulkan SM6
- **Visual Studio 2022** (Windows) — with the *Game development with C++*
  workload (MSVC toolchain), required both by UE 5.8 and to compile the
  native third-party dependencies
- **CMake** — On your `PATH`, for building the unreal-robotics-lab
  third-party dependencies
- **GPU with ray tracing support** — Required for GPU-accelerated sensors;
  RT cores used when available, software ray tracing otherwise
- **Python 3.10+** (optional) — For remote execution scripts

## Installation

First-time setup is four steps: clone with submodules, build the
`unreal-robotics-lab` native third-party dependencies, download the Fab
content packs, and open the project. Steps 2 and 3 are required **before**
the first build/launch — skipping step 2 makes the build fail outright, and
skipping step 3 leaves example maps and the crowd system without their assets.

### 1. Clone with submodules

This repository uses git submodules for plugins. Clone recursively:

```bash
git clone --recursive https://github.com/rammp-org/ramms-sim.git
cd ramms-sim
```

If you've already cloned without `--recursive`, initialize the submodules:

```bash
git submodule update --init --recursive
```

### 2. Build the unreal-robotics-lab third-party dependencies

The `URLab` module (pulled in via `unreal-robotics-lab` and
`RammsMujocoSupport`) links against native libraries — **MuJoCo**, **CoACD**,
and **libzmq** — that are compiled from source into
`Plugins/unreal-robotics-lab/third_party/install/`. This must be done once
before the first project build, and again whenever the `unreal-robotics-lab`
submodule pointer moves (each dependency's build script records the installed
SHA, and the build system enforces a drift check against it).

Requires **CMake** and a C++ toolchain (Visual Studio 2022 / MSVC on
Windows, Xcode command-line tools on macOS) on your `PATH` — see
[Prerequisites](#prerequisites).

**Windows (PowerShell):**
```powershell
cd Plugins/unreal-robotics-lab/third_party
./build_all.ps1
```

You then have to build the protospec for the URL module:

**Windows (PowerShell):**
```powershell
cd ../protospec
./build.ps1
```

The script syncs each dependency's source submodule to the expected revision,
builds it in Release, and installs into `third_party/install/`.

**macOS / Linux:** do **not** run `build_all.sh` directly. Run the setup
script from the repository root instead; it verifies the submodule, applies the
one nested patch that can't live on our fork, builds the third-party
dependencies, and regenerates project files:

```bash
UE_ROOT="/Users/Shared/Epic Games/UE_5.8" Scripts/setup_urlab.sh   # macOS
UE_ROOT="$HOME/UnrealEngine" Scripts/setup_urlab.sh                # Linux: your UE 5.8 root
```

On Linux `UE_ROOT` has to be set: the script builds the dependencies and
ProtoSpec with the engine's bundled clang, found under `UE_ROOT`.

Our fixes to unreal-robotics-lab (the `nil` macro clash between Apple's
`MacTypes.h` and rpclib/msgpack, the Mac dylib link branch in `URLab.Build.cs`,
the `MjBody` world-body render fix, the quick-convert preview refresh, and the
build-script dylib staging) now live on **our fork**, not in a patch file —
see [The unreal-robotics-lab fork](#the-unreal-robotics-lab-fork) below. The
submodule pins the fork branch, so `git submodule update --init` already brings
them. The only thing `setup_urlab` still patches is the **nested** CoACD source
submodule (`Scripts/patches/coacd-src-local-fixes.patch`), which can't live on
our fork because we don't own CoACD's repo — so re-run `setup_urlab` after a
`git submodule update --recursive`, which reverts that nested patch.

The script is idempotent — re-run it any time. Flags: `--no-thirdparty` skips
the dependency build, `--no-projectfiles` skips project file generation;
`UE_ROOT` defaults to `/Users/Shared/Epic Games/UE_5.8`.

#### The unreal-robotics-lab fork

The `unreal-robotics-lab` submodule points at **our fork**,
`git@github.com:rammp-org/UnrealRoboticsLab`, pinned to branch
**`ramms/v0.6.0-beta`** — the upstream `v0.6.0-beta` tag plus our committed
fixes (grouped by category in that branch's commit for easy upstreaming). The
fork keeps an `upstream` remote (`urlab-sim/UnrealRoboticsLab`) so each fix can
be split onto a clean branch and PR'd back.

If you cloned **before** the submodule moved to the fork, point your local
checkout at the new URL:

```bash
git submodule sync Plugins/unreal-robotics-lab
git submodule update --init --recursive Plugins/unreal-robotics-lab
```

New recursive clones pick up the fork automatically from `.gitmodules`.

> If you skip this step, compiling `RammsEditor` fails at the build-rules
> stage with an error like `MuJoCo install is missing '...INSTALLED_SHA.txt'`.
> The same error after a `git pull` means the submodule moved — re-run
> `build_all.ps1` (Windows) or `Scripts/setup_urlab.sh` (macOS/Linux) to
> refresh the installs.

### 3. Download content packs from Fab

Marketplace content under `Content/Fab/` is **not committed** to the
repository (multi-GB size, and the Fab license requires each user to claim
the free packs themselves). Without it the project still builds and runs, but
example environments show missing assets and the crowd system falls back to
proxy meshes.

- **City Sample Crowds** (required for the crowd system) — claim and install
  via **Epic Games Launcher → Fab Library → City Sample Crowds → Add to
  Project**, then restart the editor. The `RammsCrowd` plugin detects the
  pack on editor startup and automatically migrates it to
  `/Game/Fab/CitySampleCrowd` (one-time, a few minutes, with toast
  notifications). If it is missing, an editor toast links to the Fab listing
  and crowd agents simulate with proxy meshes. See
  [RammsCrowd's SETUP.md](https://github.com/rammp-org/ramms-crowd/blob/main/doc/SETUP.md) §0 for details.
- **Example environment & prop packs** (optional) — the example maps use a
  number of free packs (furniture, grocery/supermarket props, street/urban
  environments, etc.). Claim them on [Fab](https://www.fab.com) and add them
  to the project via the **Fab plugin** inside the Unreal Editor so they land
  under `Content/Fab/`. A map that references a pack you haven't installed
  simply shows missing-asset placeholders for those actors.

### 4. Open the project

Open `Ramms.uproject` in Unreal Engine 5.8. The plugins are automatically
detected and compiled (or build from the command line — see the next
section).

## Building from the command line

You can compile the C++ (project module + all plugin modules, including
`RammsCore`) entirely from a terminal without opening the editor. This is the
fastest way to validate C++ changes in CI or after editing controllers/plugins.

These commands invoke **UnrealBuildTool (UBT)** through the engine's batch
scripts. They build directly from `Ramms.uproject` and the `.Target.cs` files —
generating IDE project files is optional (see the last subsection).

> Prerequisites: submodules initialized and the unreal-robotics-lab
> third-party dependencies built (see [Installation](#installation)), plus a
> full UE 5.8 installation. The required .NET toolchain ships with the engine.

The project defines two targets:

| Target | Use |
|--------|-----|
| `RammsEditor` | Editor modules — build this to load the project (and your C++) in the editor or to run editor/commandlet/headless-editor sessions. |
| `Ramms` | Standalone game/runtime — build this for packaged or `-game` runs. |

Valid build configurations: `Debug`, `DebugGame`, `Development` (default),
`Test`, `Shipping`. Platform tokens: `Win64`, `Mac`, `Linux`.

### Locate your engine installation

Set a variable pointing at your UE 5.8 root, then reuse it below. Adjust the
path to match your install.

**Windows (PowerShell):**
```powershell
$UE = "C:\Program Files\Epic Games\UE_5.8"
```

**Windows (cmd):**
```bat
set "UE=C:\Program Files\Epic Games\UE_5.8"
```

**macOS (zsh/bash):**
```bash
UE="/Users/Shared/Epic Games/UE_5.8"
```

**Linux (bash):**
```bash
UE="$HOME/UnrealEngine"   # your UE 5.8 install/build root (no Epic launcher on Linux)
```

Run the commands below from the repository root (the folder containing
`Ramms.uproject`).

### Compile the editor target

This is the usual command after changing C++ — it rebuilds the project and every
plugin module, so you can launch the editor without triggering a Live Coding /
hot-reload pass.

**Windows (PowerShell):**
```powershell
& "$UE\Engine\Build\BatchFiles\Build.bat" RammsEditor Win64 Development -Project="$PWD\Ramms.uproject" -WaitMutex
```

**macOS:**
```bash
"$UE/Engine/Build/BatchFiles/Mac/Build.sh" RammsEditor Mac Development -Project="$PWD/Ramms.uproject" -WaitMutex
```

**Linux:**
```bash
"$UE/Engine/Build/BatchFiles/Linux/Build.sh" RammsEditor Linux Development -Project="$PWD/Ramms.uproject" -WaitMutex
```

### Compile a standalone game target

Swap the target to `Ramms` (and pick a configuration, e.g. `Shipping`) to build
the runtime game module:

**Windows (PowerShell):**
```powershell
& "$UE\Engine\Build\BatchFiles\Build.bat" Ramms Win64 Development -Project="$PWD\Ramms.uproject" -WaitMutex
```

**macOS / Linux:** use the platform's `Build.sh` (as above) with target `Ramms`
and platform `Mac` / `Linux`.

### Package the project

To cook content and produce a runnable build (not just compile), use the
Unreal Automation Tool (`RunUAT`):

**Windows (PowerShell):**
```powershell
& "$UE\Engine\Build\BatchFiles\RunUAT.bat" BuildCookRun `
  -Project="$PWD\Ramms.uproject" -NoP4 `
  -Platform=Win64 -ClientConfig=Development `
  -Build -Cook -Stage -Pak -Archive -ArchiveDirectory="$PWD\Packaged"
```

**macOS / Linux:**
```bash
"$UE/Engine/Build/BatchFiles/RunUAT.sh" BuildCookRun \
  -Project="$PWD/Ramms.uproject" -NoP4 \
  -Platform=Mac -ClientConfig=Development \
  -Build -Cook -Stage -Pak -Archive -ArchiveDirectory="$PWD/Packaged"
```
(Use `-Platform=Linux` on Linux.) The packaged output lands in `Packaged/`.

### Cross-compile for Linux from Windows

Linux builds (e.g. for headless simulation on clusters — see
[PARALLEL_SIM_PLAN.md](PARALLEL_SIM_PLAN.md)) can be produced entirely on a Windows machine
using Epic's standard Windows→Linux cross-compilation workflow. This needs a
**one-time toolchain install**:

1. Download the **native toolchain** installer for your engine version from
   Epic's [Linux Development Requirements](https://dev.epicgames.com/documentation/en-us/unreal-engine/linux-development-requirements-for-unreal-engine)
   page — for **UE 5.8** that is **v26 clang-20.1.8 rockylinux8**
   (`v26_clang-20.1.8-rockylinux8.exe`).
2. Run the installer. It is fully automated: it unpacks the clang/lld
   cross-toolchain and sysroot (default: `C:\UnrealToolchains\<version>\`)
   and sets the `LINUX_MULTIARCH_ROOT` environment variable machine-wide.
3. **Open a new terminal** (existing shells don't see the new environment
   variable), and verify:

   ```powershell
   echo $env:LINUX_MULTIARCH_ROOT
   # -> C:\UnrealToolchains\v26_clang-20.1.8-rockylinux8\
   ```

With the toolchain in place, build and package with the repo scripts (they
apply the required URLab patches automatically and cross-compile the
MuJoCo/CoACD/libzmq third-party libraries, plus URLab's own MjShim and
ProtoSpec libraries, into `third_party/install-linux/` before the UBT build):

```powershell
# 1. Cross-compile URLab's native libraries (once, and after any
#    unreal-robotics-lab submodule bump)
powershell -ExecutionPolicy Bypass -File Scripts\build_all_linux_cross.ps1

# 2. Build the Linux game target; add -Package to cook/stage/pak
powershell -ExecutionPolicy Bypass -File Scripts\build_linux_cross.ps1 -Package
```

The packaged output lands in `Packaged\Linux` — copy it to a Linux machine
(or bundle it with `containers/ramms.def`) and launch via
`Scripts/run_headless.sh`. Both scripts check for the toolchain and fail
with install instructions if `LINUX_MULTIARCH_ROOT` is missing.

**ARM64 Linux (`LinuxArm64`, e.g. a Jetson):** pass `-Platform LinuxArm64` to
both scripts. The same toolchain covers it (its installer puts the aarch64
target next to x86_64). The libraries go to `third_party/install-linuxarm64/`
and the package to `Packaged\LinuxArm64`. Pixel Streaming doesn't ship for
LinuxArm64, so that build leaves it out.

```powershell
powershell -ExecutionPolicy Bypass -File Scripts\build_all_linux_cross.ps1 -Platform LinuxArm64
powershell -ExecutionPolicy Bypass -File Scripts\build_linux_cross.ps1 -Platform LinuxArm64 -Package
```

### Regenerate IDE project files (optional)

Only needed for IDE/IntelliSense (Visual Studio, Rider, VS Code, Xcode) or after
adding modules / editing a `.Build.cs`. It is **not** required for the
command-line builds above.

**Windows (PowerShell):**
```powershell
& "$UE\Engine\Build\BatchFiles\Build.bat" -ProjectFiles -Project="$PWD\Ramms.uproject" -Game -Engine -Progress
```

**macOS:**
```bash
"$UE/Engine/Build/BatchFiles/Mac/GenerateProjectFiles.sh" -Project="$PWD/Ramms.uproject" -Game -Engine
```

**Linux:**
```bash
"$UE/Engine/Build/BatchFiles/Linux/GenerateProjectFiles.sh" -Project="$PWD/Ramms.uproject" -Game -Engine
```

## Repository layout

The plugins are listed, with links to their own READMEs, in the [README](../README.md#plugins).

```
ramms-sim/
├── Config/                    Project configuration (.ini files)
├── Content/                   Blueprints, materials, meshes, levels
│   ├── Blueprints/              Game logic (BP_RammpGen1GameMode, etc.)
│   ├── Maps/                    Test and demo levels (Map_Demo, Map_ArmTest, Map_RampTest, ...)
│   │   └── Gen/                 Generated example worlds (Map_Gen_Downtown, _Park, _Office, ...)
│   ├── Robots/                  Robot blueprints (BP_RammpGen1_Ramms, BP_RammpGen1_Mujoco, BP_Kinova_Gen3, ...; pawns: robot_pawn.md)
│   ├── Vehicles/                Accessible van with ramp
│   ├── ada_door/                Accessible door system
│   ├── Python/                  init_unreal.py and the RAMMS MCP toolset
│   └── Fab/                     Fab marketplace packs (not committed; see Installation)
├── Plugins/                   Plugin submodules (see the README's plugin table)
│   ├── RammsCore/               Robot base, controllers, IK, sensors, GPU ray tracing, URDF
│   ├── RammsControl/            Control-surface model
│   ├── RammsUI/                 Panels, joysticks, camera widgets
│   ├── RammsWorldGen/           Procedural worlds
│   ├── RammsCrowd/              Pedestrian crowds
│   ├── CameraCapture/           Calibrated cameras and EXR capture
│   ├── RammsStreaming/          RMSS TCP streaming
│   ├── RammsAccess/             Alternative-access input
│   ├── unreal-robotics-lab/     URLab (MuJoCo), our fork
│   ├── RammsMujoco*/            MuJoCo integration and support
│   ├── RammsNewtonPhysics/      Newton worker bridge
│   └── ...
├── Source/Ramms/              Main game module (robot pawns, player controller, game mode)
├── Scripts/                   Build, packaging, editor remote execution, worldgen and PIE test scripts
├── containers/                Apptainer definition for headless cluster runs
├── doc/                       These guides, design notes, plans and images (README media in doc/images/readme/)
└── Ramms.uproject             Project file
```

## Configuration

### Renderer & Ray Tracing

The project is configured for DX12 with hardware ray tracing and Lumen
global illumination. Key settings in `Config/DefaultEngine.ini`:

| Setting | Value | Purpose |
|---------|-------|---------|
| `DefaultGraphicsRHI` | `DefaultGraphicsRHI_DX12` | DirectX 12 rendering |
| `r.RayTracing` | `True` | Enable ray tracing support |
| `r.Lumen.HardwareRayTracing` | `True` | Lumen HW RT (populates TLAS for sensors) |
| `r.DynamicGlobalIlluminationMethod` | `1` | Lumen dynamic GI |
| `r.ReflectionMethod` | `1` | Lumen reflections |
| `r.Shadow.Virtual.Enable` | `1` | Virtual shadow maps |
| `r.Substrate` | `True` | Substrate material system |
| `r.AllowStaticLighting` | `False` | Fully dynamic lighting |

> **⚠ Important:** Avoid `r.RayTracing.ForceAllRayTracingEffects=1` — it
> breaks `DrawDebugMesh` rendering used by sensor and camera frustum
> visualization. Lumen HW RT naturally populates the TLAS for sensor traces.

### Game Settings

- **Default map:** `Maps/Map_Demo`
- **Default game mode:** `BP_RammpGen1GameMode` (pawn `BP_RammpGen1_Ramms`, controller `ARammsPlayerController`)
- **Splitscreen:** Enabled (2-player horizontal, 3-player top-favored)

## Developing

### Code Style

Follow the [Epic C++ Coding Standard](https://dev.epicgames.com/documentation/en-us/unreal-engine/epic-cplusplus-coding-standard-for-unreal-engine).

1. Ensure `clang-format` is installed
2. Ensure [pre-commit](https://pre-commit.com) is installed
3. Set up `pre-commit` for this repository:

```console
pre-commit install
```

### Updating Plugin Submodules

Check every plugin out at the commit this repository pins (after a pull):

```bash
git submodule update --init --recursive
```

Move one plugin to the tip of its tracked branch, then commit the new pointer
here (one plugin bump per PR keeps the history readable):

```bash
git submodule update --remote Plugins/RammsCore
git add Plugins/RammsCore
```

### Adding C++ Classes to Plugins

1. Add the class to the appropriate `Public/` or `Private/` directory in the
   plugin's Source folder
2. Update the module's `.Build.cs` if adding new dependencies
3. Regenerate project files via UE Editor or `GenerateProjectFiles.bat`
