# Semantic class channel for CameraCapture — plan, not yet built

Recorded 2026-10-07. Nothing here is implemented. Depth and motion are already
decoupled (CameraCapture `feat/decouple-depth-and-motion`); this is the third
plane.

## Shape

The motion pass writes velocity to its render target and has a spare channel.
A semantic class id read from the custom depth stencil goes in B, so the pass
produces motion and labels for one render. Instance ids are explicitly out of
scope — see "Why not instance ids".

## Blockers, in dependency order

### 1. `r.CustomDepth=3`, a renderer setting

`Config/DefaultEngine.ini` has no `CustomDepth` entry, so the engine default
applies: custom depth **without** stencil. `PPI_CustomStencil` reads zero until
this is "Enabled with Stencil".

Two consequences beyond enabling the feature:

- It costs an extra depth pass over every primitive that opts in.
- **It activates an existing code path.** `RammsCameraProjectorComponent` already
  calls `SetRenderCustomDepth` / `SetCustomDepthStencilValue`, with
  `PGMCustomStencilValue` defaulting to 1. That code is inert today because the
  setting is off. Turning it on changes the behaviour of a shipped feature, so
  that is a change to test, not a side effect to accept quietly.

CLAUDE.md gates renderer and `Config/*.ini` changes behind asking, and the ToF /
Sonar TLAS and Lumen want a before/after check.

### 2. Nothing assigns stencil values

This is the bulk of the work and none of it is in CameraCapture.

- A class → id convention. What is 1? What is 7? Where does that table live so
  that a consumer of the files can read it back?
- A mechanism that applies it: every primitive to be labelled needs
  `SetRenderCustomDepth(true)` and a stencil value, at BeginPlay and on spawn.
- Coverage decisions for skeletal meshes, instanced static meshes, foliage and
  landscape.
- A defined value for "unlabelled". Stencil 0 is what anything opted out
  returns, so 0 cannot also mean a real class.
- **Range coordination.** There are 255 slots and the projector is already using
  them. Mostly a RammpUI concern rather than this project's, but a shared
  reserved range avoids the two features silently overwriting each other where
  they do meet.

### 3. The capture material, by hand

`M_DmvCapture` needs `PPI_CustomStencil` into B. It must be edited in the
material editor, not from a script: three scripted attempts to move the velocity
between channels produced structurally identical graphs that returned scene
colour where velocity belongs. `SceneTexture:Velocity` is only valid at one
point in the post-process stack and a duplicate does not inherit whatever makes
it valid there.

**Acceptance test for any change to that material:** a STATIC camera must read
`|velocity| ~0`. The current material gives 0.00031 static and 0.01264 while
rotating at 60 deg/s, uncorrelated with scene luminance. Every broken variant
gave 0.48 static, correlating +0.9 with luminance — it was showing the picture.

## The rest, once labels exist

- **Capture**: a segmentation plane on `FCaptureData`. It shares the motion
  pass, so it inherits the motion grid and needs no geometry of its own — but
  that grid is already distinct from both colour and depth.
- **Resampling**: nearest neighbour, always. Interpolating a label is worse than
  interpolating depth: it invents classes that were never in the scene.
- **Serialisation**: EXR is float and a class id is an integer. Either write
  float and require readers to round, or emit an 8-bit PNG where the value is
  exact. The second is less convenient and harder to get wrong.
- **Metadata**: `segmentation_width`/`height`, the unlabelled value, and the
  class → name table. Without the table a consumer cannot tell what 7 means.
- **Wire**: an RMSS channel, `VERSION` bump, source and sink together. External
  Python clients on 30030 live outside this repo and have to land alongside.
- **UI**: a fourth step in the panel's channel cycle. `M_MaskColormap` already
  exists in RammsUI with `DataTexture`, `MaskScale` and class/index parameters,
  and a discrete palette is what labels want — a continuous ramp would imply an
  ordering between classes that does not exist.
- **Tests**: assign known stencil values to known actors, assert the captured
  ids land on the right pixels, and assert no id appears that was never
  assigned. That last one is the nearest-neighbour check.

## Why not instance ids

A post-process material runs as a full-screen pass with no primitive being
shaded, so `PerInstanceCustomData` and `CustomPrimitiveData` have no meaning in
it. It can read scene textures and nothing per-object. More than 255 distinct
ids therefore needs either a shared material function in every mesh's material
or a dedicated pass that overrides materials scene-wide. Both are a larger
decision than this plane.
