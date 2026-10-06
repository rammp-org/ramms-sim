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

Two things these say:

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
