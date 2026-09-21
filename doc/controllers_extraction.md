# Extracting the controllers into `ramms-controllers`

Moving the 5-bar linkage and differential-drive controllers out of RammsCore
into their own plugin submodule, so controllers are a leaf that robots and
input sources consume rather than something baked into the core.

Status: **step 1 in progress** (decouple input from concrete controllers).

## Why a separate plugin

Convention here is that a new RAMMS system gets its own `rammp-org/ramms-<name>`
plugin submodule rather than accreting into RammsCore. The controllers already
satisfy the harder half of that: they depend only on `IRammsControlContributor`
and `URammsRobotBaseComponent`, and reach the physics backend *only* through the
base component — so nothing in them is MuJoCo- or Newton-specific.

## What moves — 10 files, ~2,760 lines

| area | files | lines |
| --- | --- | --- |
| 5-bar | `Ramms5BarLinkageController.{h,cpp}`, `Ramms5BarLinkageSpec.h`, `Ramms5BarKinematics.{h,cpp}` | 809 |
| differential drive | `RammsDifferentialDriveController.{h,cpp}`, `RammsDifferentialDriveLibrary.{h,cpp}`, `RammsDifferentialDriveTypes.h` | 1,949 |

## Where the control vocabulary actually lives

Not in RammsCore. `FRammsControlAxis`, `FRammsControlSurface`,
`ERammsControlKind/Units/Source` are in **`RammsUI/Source/RammsControl`**, and
`RammsCore` includes `RammsControlTypes.h` from there. So the dependency order is

```
RammsControl (types)  <-  RammsCore (contributor iface, robot base)  <-  ramms-controllers
                                                                     <-  RammsAccess
```

which makes `RammsControl` the right home for a shared **control-Id vocabulary** —
it is already a dependency of everyone who needs to speak it.

## The two dependency inversions

Both sit in modules that would otherwise have to depend on the new plugin:

| consumer | coupling |
| --- | --- |
| `RammsKeyboardTeleopComponent` (RammsCore) | `TObjectPtr<URammsDifferentialDriveController>`, `TArray<TObjectPtr<URamms5BarLinkageController>>`, found by `FindComponentByClass` / `GetComponents` |
| `RammsAccessInputComponent` (RammsAccess) | `TObjectPtr<URammsDifferentialDriveController>`, calls `SetExternalDriveInput` |

**Decision: decouple, don't relocate.** Both are already doing "find the thing
that drives and feed it an axis", which is what the control surface is for.
Driving `SetControl(Id, Value, Source)` instead means a new controller — the
holonomic one — is picked up by keyboard teleop and the access input with no
change in either, the same property that makes the UI populate itself.

The Ids are currently file-local literals in the controller `.cpp`
(`drive.forward`, `drive.turn`), so there is nothing to decouple *against*
yet. Step 1 promotes them to a shared header in `RammsControl`.

Per-instance controls cannot be constants: the 5-bar advertises
`linkage.<component>.height`. Those are discovered by (`Group`, `Kind`) from
the surface instead — `Group == Linkage && Kind == Position`.

## Public API leaving RammsCore

Approved as a breaking change: the API landed recently and has no outside
consumers.

`URamms5BarLinkageController`, `URammsDifferentialDriveController`,
`URammsDifferentialDriveLibrary`, `URamms5BarKinematics` (both
`UBlueprintFunctionLibrary`), `FRamms5BarLinkageSpec`, `FMotorParameters`,
`FWheelState`, `FOdometryData`, `FDifferentialDriveCommand`,
`EDriveControlMode`.

## Assets needing redirects

| asset | repo |
| --- | --- |
| `BP_Mebot_Ramms`, `BP_Mebot_Mujoco`, `Showcase.umap` | ramms-sim |
| `BP_LiftDriveLinkage_Ramms`, `BP_LiftDriveHolonomic_Ramms` | private |
| **`DT_LiftDriveLinkage_5Bar`** | private |

`Config/DefaultEngine.ini` already uses `+ActiveClassRedirects` (lines 120-123),
so there is precedent for the class ones.

The data table is the risk: `FRamms5BarLinkageSpec` is its **row struct**, and a
struct redirect that fails to resolve drops the rows rather than erroring —
the same silent-success shape that has cost this project time before. Verify by
loading the table and checking row count, not by the absence of a log line.

## Order

1. **Decouple teleop + access input** from the concrete types, controllers still
   in RammsCore. Provable by compile; no asset risk.
2. **Create `ramms-controllers`, move the files, add redirects, bump the
   pointer.** A pure move, no API rewiring.
3. **Verify all six assets and the data table load**, in PIE.
4. **Build the holonomic controller** in the new plugin, against a seam step 1
   already proved.

Splitting 1 from 2 keeps "rewire the API" and "move between modules"
independently verifiable, rather than one commit where a broken Blueprint could
be either cause.
