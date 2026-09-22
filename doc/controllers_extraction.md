# Extracting the controllers into `ramms-controllers`

Moving the 5-bar linkage and differential-drive controllers out of RammsCore
into their own plugin submodule, so controllers are a leaf that robots and
input sources consume rather than something baked into the core.

Status: **step 1 in progress** (decouple input from concrete controllers).

## Why a separate plugin

Convention here is that a new RAMMS system gets its own `rammp-org/ramms-<name>`
plugin submodule rather than accreting into RammsCore. The 5-bar satisfies the
harder half of that already: it depends only on `IRammsControlContributor` and
`URammsRobotBaseComponent`, and reaches the physics backend solely through the
base component, so nothing in it is MuJoCo- or Newton-specific.

The differential drive does not. It keeps a direct Chaos path for robots with
no base component — `SkeletalMeshComponent`, `FBodyInstance`, `GetWheelBody`,
`SetMaxAngularVelocityInRadians` — and falls back to driving wheel bones by
name (`doc/mujoco_sim_roadmap.md:229-242`). Moving it as-is carries an engine
physics dependency into the new plugin; moving it without the fallback breaks
the existing Chaos Blueprints.

**This has to be settled before the move, not during it.** Two options:

  - Retire the Chaos fallback first, once the Chaos-only Blueprints are
    confirmed dead or migrated to a base component. Then the boundary above is
    true for both controllers and the new plugin needs no physics dependency.
  - Keep it, and declare `PhysicsCore` / `Engine` physics as a dependency of
    `ramms-controllers`, accepting that the plugin is not backend-neutral.

The first is preferable and is the reason this doc lists the fallback as a
prerequisite rather than a detail.

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

### …but that diagram is not what the build says

`RammsControl` is a *module* of the **RammsUI plugin**, and plugin dependencies
are declared per plugin, not per module. So `RammsCore.uplugin` lists
`RammsUI`, and through it:

```
RammsCore  ->  RammsUI (plugin)  ->  RammsStreaming, ProceduralMeshComponent
```

Nothing in RammsCore uses a widget. It takes the whole UI plugin, its Slate
surface and its streaming dependency, to get three structs and two enums — and
a headless or dedicated-server configuration that wants only the robot core
pulls all of it in.

**Recommendation: promote `RammsControl` to its own plugin
(`rammp-org/ramms-control`) as part of this work, not after it.** It is the
same convention every other system here follows, it makes the diagram above
true instead of aspirational, and it is far cheaper now than once
`ramms-controllers` has been split out and also depends on it — at that point
three plugins have to move at once instead of one. The module is small and has
no dependencies of its own beyond `Core`/`CoreUObject`.

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

`drive.forward` and `drive.turn` are already the contract, not something this
work invents: `doc/base_component_controls.md` documents them as the
diff-drive axes and the PIE and remote examples set them by name. What was
missing was a single definition — they were file-local literals in the
controller `.cpp`, repeated in the consumers. Step 1 promotes them to a shared
header in `RammsControl` so there is one place to decouple *against*; the Ids
themselves do not change and are not renamable without breaking those callers.

Per-instance controls cannot be constants: the 5-bar advertises
`linkage.<component>.height`. Those are discovered by (`Group`, `Kind`) from
the surface instead — `Group == Linkage && Kind == Position`.

## Public API leaving RammsCore

Approved as a breaking change: the API landed recently and has no consumers
outside this repository.

Inside it there are several, and they are reflected-name lookups that a move
breaks silently rather than at compile time — Python asks for
`unreal.RammsDifferentialDriveController` and gets `None` if the class has
moved module. They need migrating with the move:

  - `Scripts/pie_tests/base_component/make_assets.py`, `make_pawns.py` — these
    *author* Blueprints with these component classes, so the assets they
    produce carry the old class references too;
  - `chaos_t1.py`, `chaos_sample.py`, `mj_turn.py`, `mj_t3.py`, `mj_state.py`,
    `mj_lift.py`, `fix_dup_base.py` — `get_component_by_class` lookups.

Existing `.uasset` Blueprints referencing the moved classes need redirectors
(`[CoreRedirects]` in `Config/DefaultEngine.ini`), and the move is not done
until those scripts run green against re-saved assets.

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
