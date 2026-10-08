"""Measure what camera capture costs per frame, at a given camera count.

Reads bench_config.json beside this file (remote exec takes no arguments) and
writes bench_result.json when it finishes. Self-driving: one invocation arms a
slate post-tick callback that walks the phases and tears itself down, so the
shell just waits for the result file.

Phases, all in one PIE session so the scene and GPU state are identical:

  warmup     discarded -- the first frames include render target creation and
             shader compilation, which are not what is being measured
  baseline   cameras present, capture stopped
  capture    capture running, serialization OFF
  serialize  capture running, serialization ON

Keeping the last two apart matters: serialization is EXR encoding and disk I/O
on background threads, a different cost from the capture path itself, and
conflating them makes capture look worse than it is.

Frame time comes from the post-tick delta -- real wall clock, the user-visible
number. The subsystem's own AverageCaptureTimeMs is recorded alongside, but it
covers only the kick phase (enqueueing the GPU copies), not the harvest, so it
is a component and not the total.

    python3 Scripts/editor_remote_exec.py \
        --file Scripts/pie_tests/camera_capture/bench_capture.py
"""

import json
import os
import statistics
import time

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "bench_config.json")))

CAMERA_COUNT = int(CFG.get("camera_count", 1))
FRAMES = int(CFG.get("frames_per_phase", 180))
WARMUP = int(CFG.get("warmup_frames", 60))
RESULT_PATH = os.path.join(HERE, "bench_result.json")

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = ues.get_game_world()
if world is None:
    raise RuntimeError("PIE is not running")

mgr = None
for a in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.CameraCaptureManager):
    mgr = a
    break
if mgr is None:
    raise RuntimeError("no CameraCaptureManager in the PIE world")


def summarize(samples):
    s = sorted(samples)
    if not s:
        return {}
    return {
        "frames": len(s),
        "mean_ms": round(statistics.fmean(s), 3),
        "median_ms": round(statistics.median(s), 3),
        "p95_ms": round(s[max(0, int(len(s) * 0.95) - 1)], 3),
        "max_ms": round(s[-1], 3),
    }


PHASES = ["warmup", "baseline", "capture", "serialize"]

state = {
    "phase_index": 0,
    "count": 0,
    "samples": {p: [] for p in PHASES},
    "handle": None,
    "done": False,
    "last_time": None,
}


def enter_phase(name):
    """Capture/serialization settings for each phase.

    Warmup CAPTURES. The cold costs this phase exists to discard -- render
    target creation, shader compilation, the first trip through the readback
    path -- only happen if capture is actually running, so stopping capture here
    warmed nothing and pushed every one of them into the measured `capture`
    phase instead. That inflates the first result and nothing else, which is the
    hardest kind of benchmark error to notice.
    """
    if name == "warmup":
        mgr.set_serialization_enabled(False)
        mgr.start_capture()
    elif name == "baseline":
        mgr.stop_capture()
    elif name == "capture":
        mgr.set_serialization_enabled(False)
        mgr.start_capture()
    elif name == "serialize":
        mgr.set_serialization_enabled(True)
    print("[bench] phase -> %s" % name)


def finish():
    _stop()
    mgr.stop_capture()

    sub = None
    out = {
        "camera_count": CAMERA_COUNT,
        "color": CFG.get("color", ""),
        "depth": CFG.get("depth", ""),
        "frames_per_phase": FRAMES,
        # warmup is recorded but not reported as a result
        "baseline": summarize(state["samples"]["baseline"]),
        "capture": summarize(state["samples"]["capture"]),
        "serialize": summarize(state["samples"]["serialize"]),
    }

    # A p95 identical across every phase means the frame rate was clamped and
    # the numbers describe the clamp rather than the workload. Say so in the
    # result rather than leaving a reader to spot it.
    p95s = {k: out[k].get("p95_ms") for k in ("baseline", "capture", "serialize") if out[k]}
    out["throttle_suspected"] = len(set(p95s.values())) == 1 and len(p95s) > 1

    b = out["baseline"].get("mean_ms")
    for phase in ("capture", "serialize"):
        m = out[phase].get("mean_ms")
        if b and m:
            out[phase]["over_baseline_ms"] = round(m - b, 3)
            out[phase]["per_camera_ms"] = round((m - b) / max(1, CAMERA_COUNT), 3)

    with open(RESULT_PATH, "w") as fh:
        json.dump(out, fh, indent=2)
    state["done"] = True
    print("[bench] done -> %s" % RESULT_PATH)


def _stop():
    if state["handle"] is not None:
        unreal.unregister_slate_post_tick_callback(state["handle"])
        state["handle"] = None


def tick(delta_seconds):
    """Sample wall clock, not the engine's delta.

    UEngine clamps the delta it reports, so a frame slower than the clamp comes
    back AS the clamp -- which showed up as a p95 and max of exactly 125.00 ms
    (8 FPS) for every capture phase while the baseline varied normally. That
    hides how slow the slow frames actually are, and it is the slow frames that
    matter. time.perf_counter() is not clamped.
    """
    # A slate post-tick callback outlives PIE. Left registered it fires against
    # a destroyed world and throws every frame, which both floods the log and
    # adds a per-frame exception to anything measured afterwards -- so any
    # failure unregisters rather than repeating.
    if state["done"] or state["handle"] is None:
        return
    if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is None:
        _stop()
        return
    now = time.perf_counter()
    last = state.get("last_time")
    state["last_time"] = now
    if last is None:
        return  # no interval yet

    name = PHASES[state["phase_index"]]
    state["samples"][name].append((now - last) * 1000.0)
    state["count"] += 1

    limit = WARMUP if name == "warmup" else FRAMES
    if state["count"] >= limit:
        state["count"] = 0
        state["last_time"] = None  # do not charge the next phase this interval
        state["phase_index"] += 1
        try:
            if state["phase_index"] >= len(PHASES):
                finish()
            else:
                enter_phase(PHASES[state["phase_index"]])
        except Exception as e:
            print("[bench] aborting after error: %s" % e)
            _stop()


# Without this the measurement is of the editor's throttle, not of capture.
# The editor caps the frame rate hard when its window is not in the foreground
# (and smooths it in general), which showed up as a p95 pinned to exactly
# 125.00 ms -- 8 FPS -- in every configuration, baseline included. The means
# then only recorded how often each phase hit the cap.
unreal.SystemLibrary.execute_console_command(world, "t.MaxFPS 0")
unreal.SystemLibrary.execute_console_command(world, "r.VSync 0")
# The remaining cap, bThrottleCPUWhenNotForeground, lives on
# UEditorPerformanceSettings, which is NOT exposed to Python. It is
# config=EditorSettings, so it has to come from the editor's command line:
#   -ini:EditorSettings:[/Script/UnrealEd.EditorPerformanceSettings]:bThrottleCPUWhenNotForeground=False
# The throttle_suspected flag below is the check that it actually took effect.

# Remove any previous result so the shell can wait on the file appearing.
if os.path.exists(RESULT_PATH):
    os.remove(RESULT_PATH)

enter_phase("warmup")
state["handle"] = unreal.register_slate_post_tick_callback(tick)
# Held on the module so the callback is not garbage collected mid-run.
unreal.CameraCaptureBenchState = state
print("[bench] armed: %d cameras, %d frames per phase" % (CAMERA_COUNT, FRAMES))
