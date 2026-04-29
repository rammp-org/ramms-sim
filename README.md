# RAMMS-Sim

Robotic Assistive Mobility and Manipulation Simulation (RAMMS) — An Unreal
Engine 5.7 simulation environment for robotic assistive technologies.

<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

- [RAMMS-Sim](#ramms-sim)
  - [Overview](#overview)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Project Structure](#project-structure)
    - [Plugin Submodules](#plugin-submodules)
    - [Directory Layout](#directory-layout)
  - [Simulation Features](#simulation-features)
    - [Mobile Robotic Base (MeBot)](#mobile-robotic-base-mebot)
    - [Kinova Gen 3 Manipulator](#kinova-gen-3-manipulator)
    - [Accessible Van with Ramp](#accessible-van-with-ramp)
    - [Sensor Simulation](#sensor-simulation)
    - [Camera Capture System](#camera-capture-system)
    - [Real-Time Streaming](#real-time-streaming)
  - [Configuration](#configuration)
    - [Renderer & Ray Tracing](#renderer--ray-tracing)
    - [Game Settings](#game-settings)
  - [Python Integration](#python-integration)
  - [URDF Interoperability](#urdf-interoperability)
  - [Example Environments](#example-environments)
  - [Developing](#developing)
    - [Code Style](#code-style)
    - [Updating Plugin Submodules](#updating-plugin-submodules)
    - [Adding C++ Classes to Plugins](#adding-c-classes-to-plugins)
  - [License](#license)
  - [Contributing](#contributing)
  - [Contact](#contact)

<!-- markdown-toc end -->

https://github.com/user-attachments/assets/fdc96795-279f-4ccf-a092-382f6755a65d

## Overview

RAMMS-Sim provides a high-fidelity simulation environment for developing and
testing robotic assistive mobility and manipulation systems. Built on Unreal
Engine 5.7, it offers:

- **Physics-based robotics** — Differential drive wheelchair, 7-DOF robotic
  arm with three IK solvers, two-finger gripper
- **GPU-accelerated sensors** — Time-of-Flight, Sonar, and IMU with optional
  inline ray tracing on the GPU (RT cores or software fallback)
- **Multi-camera capture** — RGB + depth + motion vectors with custom
  intrinsics and EXR output
- **Real-time streaming** — Binary protocol (RMSS) over TCP for external
  control and data consumption
- **Accessible environment simulation** — Van with controllable door and
  articulated ramp
- **Python scripting** — Remote execution for external control and data
  collection

## Prerequisites

- **Unreal Engine 5.7**
- **Windows** with DirectX 12 (recommended) or **Linux** with Vulkan SM6
- **GPU with ray tracing support** — Required for GPU-accelerated sensors;
  RT cores used when available, software ray tracing otherwise
- **Python 3.10+** (optional) — For remote execution scripts

## Installation

This repository uses git submodules for plugins. Clone recursively:

```bash
git clone --recursive https://github.com/rammp-org/ramms-sim.git
cd ramms-sim
```

If you've already cloned without `--recursive`, initialize the submodules:

```bash
git submodule update --init --recursive
```

Then open `Ramms.uproject` in Unreal Engine 5.7. The plugins are automatically
detected and compiled.

## Project Structure

### Plugin Submodules

The project uses a modular plugin architecture. Four plugins are managed as
git submodules:

| Plugin | Path | Description |
|--------|------|-------------|
| **RammsCore** | `Plugins/RammsCore/` | Core simulation components — differential drive, MeBot controller, Kinova Gen3 arm with IK solvers, gripper, sensor simulation (ToF, Sonar, IMU), GPU ray tracing, URDF import/export |
| **CameraCapture** | `Plugins/CameraCapture/` | Multi-camera capture system — RGB + depth + motion vectors with custom camera intrinsics, EXR output, and frustum visualization |
| **RammsStreaming** | `Plugins/RammsStreaming/` | Real-time binary streaming over TCP (RMSS protocol, port 30030) — image data, depth frames, motion vectors, point clouds |
| **RammsAssets** | `Plugins/RammsAssets/` | 3D models and materials — Kinova Gen3 arm, gripper, MeBot base, operator seat, ORBBEC and LUCI camera models |

An additional local plugin (**VolingaRenderer**) provides custom rendering
capabilities.

### Directory Layout

```
Ramms/
├── Config/                  Project configuration (.ini files)
├── Content/                 Blueprint assets, materials, meshes, levels
│   ├── Blueprints/            Game logic (BP_MebotGameMode, etc.)
│   ├── Maps/                  Game levels
│   ├── Robots/                Robot actor blueprints (BP_Kinova_Gen3, BP_Mebot_Ramms)
│   ├── Vehicles/              Vehicle variants (AdaptedVanRamp, IDBuzz, etc.)
│   ├── ada_door/              Accessible door system
│   ├── Fab/                   Downloaded Fab marketplace assets
│   └── ...
├── Plugins/
│   ├── RammsCore/             Core simulation (submodule)
│   │   ├── Source/RammsCore/    C++ controllers, sensors, IK, GPU ray tracing
│   │   ├── Source/RammsCoreEditor/  Editor utilities
│   │   ├── Shaders/Private/     HLSL compute shaders (RammsSensorTrace.usf)
│   │   └── Content/Python/urdf/  URDF import/export scripts
│   ├── CameraCapture/         Camera data acquisition (submodule)
│   ├── RammsStreaming/        TCP binary streaming (submodule)
│   ├── RammsAssets/           Robot & sensor 3D models (submodule)
│   └── VolingaRenderer/       Custom rendering (local)
├── Source/Ramms/              Main game module (game mode, pawn, vehicles)
├── py/                        Python remote execution scripts
├── urdf/                      Robot URDF model files
├── doc/                       Documentation images
├── Ramms.uproject             Project file
└── Ramms.sln                  Visual Studio solution
```

## Simulation Features

### Mobile Robotic Base (MeBot)

Complete simulation of the MeBot powered wheelchair base:
- Differential drive with torque and velocity control modes
- PID feedback, slip modeling, and odometry tracking
- Front and rear caster arm articulation
- Main drive wheel elevation system for multiple drive modes (front/mid/rear
  wheel drive)
- Configurable motor parameters (max RPM, torque curves, braking)

**Components:** `URammsDifferentialDriveController`, `UMebotControllerComponent`,
`URammsDifferentialDriveLibrary`

### Kinova Gen 3 Manipulator

Physics-based 7-DOF robotic arm with:
- Skeletal mesh with per-joint physics constraints
- Three IK solver algorithms: **DLS** (Damped Least Squares), **FABRIK**
  (per-joint scalar DLS), and **CCD** (Cyclic Coordinate Descent)
- Joint, end-effector, position, velocity, and torque control modes
- Two-finger adaptive gripper with open/close/toggle state machine
- Null-space optimization for preferred poses

**Components:** `UKinovaGen3ControllerComponent`,
`UGripperControllerComponent`, `URammsIKLibrary`

See the [RammsCore README](Plugins/RammsCore/README.md) for detailed IK solver
documentation and tuning guides.

### Accessible Van with Ramp

Articulated accessible van system:
- Controllable van door with keyframe animation
- Articulated van ramp with realistic physics and easing curves

**Components:** `UVanDoorComponent`, `UVanRampComponent`

**Credits:** Custom modification of CC-licensed base model: "Volkswagen ID.
BUZZ" (https://skfb.ly/oTs6B) by Sloftm_Carz, licensed under
[CC-BY 4.0](http://creativecommons.org/licenses/by/4.0/).

### Sensor Simulation

Three sensor types with configurable noise, bias, update rate, and debug
visualization:

| Sensor | Component | Description |
|--------|-----------|-------------|
| **Time-of-Flight** | `URammsToFSensorComponent` | Single-point or NxM grid distance sensor (modeled after VL53L0X / VL53L5CX). GPU or CPU ray tracing. |
| **Sonar / RADAR** | `URammsSonarSensorComponent` | Cone-beam distance sensor with golden-angle spiral ray distribution. GPU or CPU ray tracing. |
| **IMU** | `URammsIMUSensorComponent` | Accelerometer + gyroscope + orientation. Supports gravity, EMA filtering, dead-bands, bias, and noise. |

The ToF and Sonar sensors support **GPU-accelerated ray tracing** via a
compute shader with DXR inline ray tracing (`TraceRayInline`). The GPU path:
- Uses hardware RT cores when available, software ray tracing otherwise
- Falls back automatically to CPU `LineTrace` when GPU is unavailable
- Is controlled per-component via `bUseGPURayTracing` (default: on)
- Shows as `RammsSensorTraceDispatch` in `stat gpu` for profiling

All sensors fire along their local **+X axis** and provide shape
visualization in the editor viewport (frustum for ToF grid, line for ToF
single-point, cone for sonar) with configurable colors and filled planes.

See the [RammsCore README](Plugins/RammsCore/README.md) for detailed sensor
configuration and GPU ray tracing setup.

### Camera Capture System

Production-grade multi-camera capture for simulation and research:

- **Custom camera intrinsics** — Pixel-based parameters (fx, fy, cx, cy)
  for precise real-world camera matching
- **Reusable presets** — Data Assets for sensor profiles (e.g.,
  `DA_RealSense_D435`)
- **Multi-modal output** — RGB, depth (in alpha channel), and motion vectors
  as 32-bit float EXR files with per-frame JSON metadata
- **Frustum visualization** — Editor viewport shape with filled translucent
  planes

**Components:** `UIntrinsicSceneCaptureComponent2D`, `UCaptureComponent`,
`ACameraCaptureManager`

### Real-Time Streaming

Binary streaming over TCP for external tools and controllers:

- **RMSS protocol** with 32-byte header + JSON metadata + binary payload
- **Message types:** Image data, depth frames, motion vectors, point clouds,
  subscribe/unsubscribe, ping/ack
- **Compression:** None, LZ4, JPEG, or PNG
- **Default port:** 30030

**Components:** `URammsStreamSourceComponent`, `URammsStreamSinkComponent`,
`URammsStreamingSubsystem`

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

- **Default map:** `VehicleTemplate/Maps/VehicleBasic`
- **Default game mode:** `BP_VehicleAdvGameMode`
- **Splitscreen:** Enabled (2-player horizontal, 3-player top-favored)

## Python Integration

Python scripts in the `py/` directory enable external control and data
collection via UE's Remote Execution interface (port 6776):

| Script | Purpose |
|--------|---------|
| `mebot_control_example.py` | Control MeBot wheelchair (velocity, drive mode, caster arms) |
| `camera_capture_example.py` | Discover cameras, read parameters, access render targets |
| `move_actor_circle_remote.py` | Non-blocking actor animation (circle, figure-8, vertical) |
| `upyrc_*.py` | Integration examples and utilities |

**Setup:**

```bash
cd py
python -m venv env
env\Scripts\activate      # Windows
pip install -r requirements.txt
```

Enable **Remote Execution** in the UE Editor: **Edit > Project Settings >
Plugins > Python > Remote Execution > Enable Remote Execution**.

## URDF Interoperability

The project includes URDF (Unified Robot Description Format) files and
bidirectional conversion tools for interoperability with ROS, MoveIt,
PyBullet, MuJoCo, and other robotics tools:

- `urdf/gen3_6dof.urdf` — Kinova Gen3 6-DOF arm
- `urdf/mebot.urdf` — MeBot mobile base

Export and import scripts run inside the UE Editor Python console. See the
[RammsCore README](Plugins/RammsCore/README.md#urdf-export--import) for
detailed usage.

## Example Environments

This repository does not include all example environments to keep the
repository size manageable. Additional environments and assets can be
downloaded for free using the **Fab plugin** within Unreal Engine.

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

```bash
git submodule update --remote Plugins/RammsCore
git submodule update --remote Plugins/CameraCapture
git submodule update --remote Plugins/RammsStreaming
git submodule update --remote Plugins/RammsAssets
```

### Adding C++ Classes to Plugins

1. Add the class to the appropriate `Public/` or `Private/` directory in the
   plugin's Source folder
2. Update the module's `.Build.cs` if adding new dependencies
3. Regenerate project files via UE Editor or `GenerateProjectFiles.bat`

## License

See LICENSE file for details.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull
request with your changes.

## Contact

For questions or support, please open an issue on GitHub or contact the
maintainers directly.
