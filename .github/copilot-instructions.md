# Copilot Instructions for RAMMS-Sim

## Project Overview

RAMMS-Sim (Robotic Assistive Mobility and Manipulation Simulation) is an Unreal Engine 5.7 project that provides a high-fidelity simulation environment for robotic assistive technologies. The project simulates:

- **MeBot** - Mobile robotic wheelchair base with differential drive, articulated caster arms, and elevation systems
- **Kinova Jaco Gen 3** - Robotic manipulator arm with skeletal mesh and joint constraints
- **Accessible Van** - Van with controllable doors and articulated ramp system
- **Camera Capture System** - Multi-camera RGB + depth + motion vector data capture

## Architecture

### Plugin-Based Structure

The project uses a modular plugin architecture with several plugins managed as git submodules; the main ones are:

- **RammsCore** (`Plugins/RammsCore/`) - Core simulation components
  - `RammsDifferentialDriveController` - Differential drive physics controller
  - `MebotControllerComponent` - Linear/angular actuator control for wheelchair
  - `KinovaGen3ControllerComponent` - Robotic arm controller
  - `GripperControllerComponent` - End effector control
  - `VanRampComponent` / `VanDoorComponent` - Vehicle accessibility components
  - Blueprint function libraries for differential drive and IK calculations

- **CameraCapture** (`Plugins/CameraCapture/`) - Camera data acquisition
  - `UIntrinsicSceneCaptureComponent2D` - Custom camera intrinsics support
  - `CaptureComponent` - Automated multi-camera RGB/depth/motion capture
  - Outputs `.raw` files with transformations and camera config CSVs

### Module Organization

```
Source/Ramms/           - Main game module (vehicle templates, game mode, player controller)
Plugins/RammsCore/Source/
  ├── RammsCore/        - Runtime components (C++ controllers, libraries)
  └── RammsCoreEditor/  - Editor-only utilities
Plugins/CameraCapture/Source/
  └── CameraCapture/    - Runtime capture components
Content/                - Blueprint assets, materials, meshes, levels
  ├── mebot/           - MeBot wheelchair assets
  ├── kinova/          - Kinova arm assets
  ├── luci/            - Luci wheelchair assets
  └── VehicleTemplate/ - Base vehicle templates
py/                     - Python integration scripts
```

## Key Conventions

### Component Attachment Pattern

Actor components find and configure child components by name or type:
- `CaptureComponent` auto-detects all `UIntrinsicSceneCaptureComponent2D` children
- `MebotControllerComponent` locates constraints by `ConstraintName` property
- `RammsDifferentialDriveController` finds skeletal mesh via `SkeletalMeshComponentName` or auto-finds first

### Physics Control Modes

Controllers support multiple modes:
- **TorqueControl** - Direct torque application to wheel bones
- **VelocityControl** - Velocity-based control with PID feedback
- **ForceControl** - Force-based movement (for non-skeletal components)

Check `EDriveControlMode` enum in `RammsDifferentialDriveTypes.h` when modifying drive systems.

### Camera Intrinsics System

Two projection modes for cameras:
1. **Custom Intrinsics** (`bUseCustomIntrinsics = true`) - Pixel-based camera parameters (fx, fy, cx, cy)
2. **Maintain Y-Axis** (`bMaintainYAxis = true`) - Adjusts horizontal FOV to maintain vertical FOV

Camera parameters can be:
- Defined inline on component
- Shared via `CameraIntrinsicsAsset` data assets (e.g., "DA_RealSense_D435")

### Motor Configuration Pattern

Components like `MebotControllerComponent` use configuration structs:
```cpp
USTRUCT(BlueprintType)
struct FAngularMotorConfig {
    FName ConstraintName;
    EMotorAxis ControlAxis;
    bool bEnabled;
    bool bInvertDirection;
    float TargetAngle;
    // ... motor parameters
};
```

Always check for `bEnabled` and `bInvertDirection` flags when adding motor types.

### Coordinate Systems

- UE uses left-handed Z-up coordinate system
- CameraCapture outputs transformations as position (tx, ty, tz) + quaternion (qw, qx, qy, qz)
- Python integration scripts (`py/external_connect.py`) use `upyrc` library for remote execution

## Build & Development

### Building the Project

Open `Ramms.uproject` in Unreal Engine 5.7 or build via Visual Studio:

```powershell
# Generate project files
& "C:\Program Files\Epic Games\UE_5.7\Engine\Build\BatchFiles\Build.bat" Ramms Win64 Development

# Build in Visual Studio
& "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" Ramms.sln /t:Build /p:Configuration=Development
```

### Plugin Development

Plugins are git submodules. To update:
```bash
git submodule update --remote Plugins/RammsCore
git submodule update --remote Plugins/CameraCapture
git submodule update --remote Plugins/RammsStreaming
git submodule update --remote Plugins/RammsAssets
git submodule update --remote Plugins/RammsCrowd
git submodule update --remote Plugins/RammsHumanPhysics
git submodule update --remote Plugins/RammsNewtonPhysics
git submodule update --remote Plugins/RammsMujocoPhysics
```

When adding new C++ classes to plugins:
1. Add to appropriate `Public/` or `Private/` directory
2. Update module's `.Build.cs` if adding new dependencies
3. Regenerate project files via UE Editor or `GenerateProjectFiles.bat`

### Python Integration

Python scripts use `upyrc` library for remote execution:
```bash
cd py
pip install -r requirements.txt
python external_connect.py
```

Ensure Python plugin is enabled in `.uproject` and UE Editor has remote execution enabled.

## Engine Plugins Used

Key UE plugins this project depends on:
- `ChaosModularVehicle` - Vehicle physics system
- `PhysicsControl` - Advanced physics constraint control
- `GeometryScripting` - Procedural geometry manipulation
- `PCGPythonInterop` - Python integration
- `DatasmithCADImporter` - CAD file import (Win64/Linux only)

## Working with Assets

### Asset Naming

- Blueprints: `BP_<Name>` (e.g., `BP_MebotGameMode`)
- Materials: `M_<Name>` (e.g., `M_DmvCapture` for depth+motion capture)
- Data Assets: `DA_<Name>` (e.g., `DA_RealSense_D435`)

### Large File Management

Project uses Git LFS for large assets. After cloning:
```bash
git lfs install
git lfs pull
```

Additional environments downloaded via Fab plugin (within UE Editor), not committed to repo.

## Common Patterns

### Adding a New Controller Component

1. Inherit from `UActorComponent`
2. Add `UCLASS(ClassGroup=(Ramms), meta=(BlueprintSpawnableComponent))`
3. Place in `Plugins/RammsCore/Source/RammsCore/Public/`
4. Implement `BeginPlay()` to find/configure child components
5. Use `TickComponent()` for physics updates
6. Expose parameters as `UPROPERTY(EditAnywhere, BlueprintReadWrite)`

### Skeletal Mesh Control

When controlling skeletal meshes:
```cpp
USkeletalMeshComponent* SkelMesh = ...; // Find the mesh
FName BoneName = FName("bone_name");
FTransform BoneTransform = SkelMesh->GetBoneTransform(...);
// Apply forces/torques via physics constraints
```

### Blueprint Function Libraries

For reusable calculations, create static blueprint libraries:
- `RammsDifferentialDriveLibrary` - Drive kinematics/odometry
- `RammsIKLibrary` - Inverse kinematics utilities

Mark functions as `UFUNCTION(BlueprintCallable, Category = "...")`.
