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

`SetCaptureMode(SingleCaptureColorDepth)` uses the engine's
`SCS_SceneColorSceneDepth`, which writes scene colour to RGB and scene depth to
alpha in one pass. Verified on a real capture: alpha came back 288.75..501.50
with 6592 distinct values -- **centimetres**, which is what `FCaptureData` and
the RMSS metadata have always claimed. The DMV material emits a normalised
0..1 instead, so this mode is the one whose units match the documentation.

What it costs: no motion vectors at all (they come from the DMV pass), colour is
linear scene colour rather than tone-mapped `SCS_FinalColorHDR`, and both planes
share one render target and therefore one resolution -- separate depth
intrinsics are ignored, with a warning.

### Two things the camera-count tables say:

- **Cost is roughly linear in camera count**, 25-35 ms each. Each camera is
  *two* scene captures -- colour and depth/motion -- so N cameras means 2N extra
  scene renders. That is rendering, not the capture plumbing.
- **Serialization is close to free**: 0.6-10.5 ms on top of capture, for all
  cameras combined. EXR encoding and disk I/O are on background threads via
  ImageWriteQueue, and the measurements agree.

So the lever for multi-camera headroom is the render side: capture rate
(`CaptureEveryNFrames`), resolution, and whether motion vectors are wanted at
all -- not the CPU-side readback path.

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
