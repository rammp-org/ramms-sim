# Camera capture benchmark

Measures what capture costs per frame as the camera count grows.

```sh
# The throttle override on the command line is REQUIRED -- see Pitfalls.
"$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" Ramms.uproject \
  "-ini:EditorSettings:[/Script/UnrealEd.EditorPerformanceSettings]:bThrottleCPUWhenNotForeground=False"

Scripts/pie_tests/camera_capture/run_bench.sh 1 2 4 8
```

Each step restarts PIE, places exactly N cameras (Manual registration, so the
demo map's own five robot cameras are not counted), and walks four phases in one
session: `warmup` (discarded), `baseline` (cameras present, capture stopped),
`capture` (capture on, serialization off) and `serialize` (both on). Results land
in `bench_results.json`.

## Results, 2026-10-06

Editor build, `Map_Demo`, Mac/arm64 Metal, 640x480 colour + 320x240 depth,
90 frames per phase. **Indicative only** -- an editor build on a heavy map, not
a packaged build.

| cameras | baseline | capture | over baseline | per camera | serialization alone |
|---|---|---|---|---|---|
| 1 | 43.18 ms | 76.98 ms | +33.80 | 33.80 | +0.61 |
| 2 | 45.16 ms | 115.65 ms | +70.50 | 35.25 | +2.29 |
| 4 | 48.50 ms | 150.74 ms | +102.24 | 25.56 | +10.54 |
| 8 | 44.24 ms | 241.56 ms | +197.31 | 24.66 | +2.81 |

Capture p95 / max: 127/188, 129/275, 166/232, 324/840 ms.

### Single capture vs two renders, 2026-10-06

Both at 640x480 colour **and** 640x480 depth, so the comparison is like for
like (the table above gave the two-render mode a quarter-resolution depth pass,
which flattered it).

| cameras | 2 renders | 1 render | saved | reduction |
|---|---|---|---|---|
| 1 | +32.09 ms | +17.13 ms | 14.96 ms | 46.6% |
| 2 | +82.70 ms | +43.07 ms | 39.63 ms | 47.9% |
| 4 | +118.34 ms | +71.07 ms | 47.27 ms | 39.9% |
| 8 | +218.70 ms | +120.55 ms | 98.15 ms | 44.9% |

Per camera: 32.1 -> 17.1, 41.4 -> 21.5, 29.6 -> 17.8, 27.3 -> 15.1 ms.

Serialization gets cheaper too, because there is no motion EXR to write: at
eight cameras it drops from +39.10 ms to +11.46 ms.

> **These numbers are a no-motion comparison, and they predate the depth/motion
> split.** They were taken when motion could only exist in the two-render mode,
> so the harness disabled it for single capture only -- the "2 renders" column
> includes a motion pass and the "1 render" column does not. Part of what reads
> as the mode's saving is simply the motion render missing from one side, and
> the serialization figure above is entirely that. Motion is its own pass now,
> available in either mode and costing its own render in either, and
> `bench_setup.py` sets it identically for both. **Re-run before quoting these.**

`SetCaptureMode(SingleCaptureColorDepth)` uses the engine's
`SCS_SceneColorSceneDepth`, which writes scene colour to RGB and scene depth to
alpha in one pass. Verified on a real capture: alpha came back 288.75..501.50
with 6592 distinct values -- **centimetres**.

Both modes produce centimetres now, from the same engine path: the depth that
used to come out of the DMV pass was never a distance at all. Measured against
`SCS_SceneColorSceneDepth` on one scene with the same cameras, it correlated
-0.11 with true range and +0.73 with scene LUMINANCE -- it was largely the
photograph. That is why depth moved to the depth buffer in both modes.

What single capture still costs: colour is linear scene colour rather than
tone-mapped, and both planes share one render target and therefore one
resolution -- separate depth intrinsics are ignored, with a warning. Motion is
no longer among the costs; it is available in either mode.

### Two things the camera-count tables say:

- **Cost is roughly linear in camera count**, 25-35 ms each. That is rendering,
  not the capture plumbing.

  The renders per camera are no longer two. Depth and motion are separate passes
  now, so a camera costs one render for colour+depth in `SingleCaptureColorDepth`
  or two in `TonemappedColorPlusDepth`, plus one more if motion is on. With the
  benchmark's defaults that is **3N** renders for the two-render mode and **2N**
  for single capture -- the tables above were taken when it was 2N and N, with
  motion folded into the depth pass rather than costing a render of its own.
- **Serialization is close to free**: 0.6-10.5 ms on top of capture, for all
  cameras combined. EXR encoding and disk I/O are on background threads via
  ImageWriteQueue, and the measurements agree.

So the lever for multi-camera headroom is the render side: capture rate
(`CaptureEveryNFrames`), resolution, the capture mode, and whether motion
vectors are wanted at all -- not the CPU-side readback path. Motion being its
own pass makes that last one a whole render per camera rather than a channel
that came along for free, which is the single biggest knob here.

There is no before/after here. The subsystem's async readback path asserted on
its first harvested frame before the fixes in `CameraCapture` 93cbdae, so there
is no "before" to measure against.

## Pitfalls

Both of these produced confidently wrong numbers before being caught.

**The editor throttles when not in the foreground.** It shows up as an identical
p95 across every phase, baseline included -- 125.00 ms, 8 FPS. The means then
only record how often a phase hit the cap, and scaling looks sublinear because
everything saturates against the ceiling. `UEditorPerformanceSettings` is not
exposed to Python, so the override has to be on the command line as above.
`bench_capture.py` sets `t.MaxFPS 0` and `r.VSync 0` itself and emits a
`throttle_suspected` flag when the p95s coincide.

**The engine clamps the delta time it reports.** A frame slower than the clamp
comes back *as* the clamp, so `p95` and `max` both read exactly 125.00 ms while
the baseline varied normally -- the slow frames, which are the interesting ones,
were invisible. The sampler uses `time.perf_counter()` instead.
