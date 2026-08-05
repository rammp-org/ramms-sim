# Pixel Streaming Plan — Cluster Access, rammp-ui Remote HMI, Demos

Plan of record for adopting Unreal Pixel Streaming across RAMMS and rammp-ui.
Drafted 2026-08-01. Facts below verified against the installed UE 5.7 engine
plugin (`Engine/Plugins/Media/PixelStreaming2`), not just docs.

## What Pixel Streaming 2 gives us (UE 5.7)

- Engine plugin streams the rendered viewport over WebRTC to any browser and
  feeds browser input (mouse/keyboard/touch/gamepad) back to the engine.
  Touch works from stock mobile browsers — no client app to install.
- Companion infra (github.com/EpicGamesExt/PixelStreamingInfrastructure,
  branch matched to engine version): Node signalling server, TypeScript web
  frontend, optional SFU for one-to-many fan-out (simulcast supported with
  H264/VP8 per the plugin settings).
- Codecs: H264 / AV1 / VP9 / VP8; hardware encode via NVENC on NVIDIA GPUs
  (our RTX 6000 Pro cluster nodes qualify), software VPx fallback.
- Launch wiring: `-PixelStreamingConnectionURL=ws://<signalling>:<port>`
  (legacy `-PixelStreamingURL` also present in 5.7). Compatible with
  `-RenderOffscreen` — the headless-but-rendering mode our cluster plan
  already uses.
- **Platform limit (verified in the .uplugin module allowlists): Win64,
  Linux (x64), Mac only — NO LinuxArm64.** Stock Pixel Streaming cannot
  ship in an Orin build regardless of encoder hardware. Note the encoder
  side is NOT the blocker on our hardware: Orin NX / AGX Orin have NVENC
  units (only the Orin Nano lacks them), and JetPack 6 exposes both the
  V4L2/Multimedia API path and the desktop-style NVENCODE API on Jetson.
  The barrier is narrower than it first looks, though: in the 5.7 SOURCE
  tree, EpicRtc.Build.cs already resolves LinuxArm64 binaries
  (Lib/Linux/aarch64/libepicrtc.a) — only the .uplugin module allowlists
  exclude the platform. Since rammp-ui already requires a LinuxArm64
  engine source build, "PS from the Orin" is a small engine patch (add
  LinuxArm64 to the module allowlists) plus two validations: the aarch64
  libepicrtc.a actually ships in the GitDeps package, and the encoder path
  works on-device (JetPack 6 exposes the NVENCODE API on NX/AGX; software
  VPx is the fallback). If the binary is missing, a UDN ticket to Epic —
  the Build.cs plumbing suggests the platform is nearly enabled upstream.

## Use case A — cluster instances (dev access + training-pipeline eyeballs)

**Feasibility: high; effort: low; do this first.** Composes directly with
the parallel-sim infrastructure (doc/PARALLEL_SIM_PLAN.md): the packaged
Linux build already runs offscreen Vulkan on RT/NVENC-capable nodes.

- Enable PixelStreaming2 in the project (runtime cost is zero until a
  streaming session connects; encode cost while connected is NVENC —
  negligible next to the sensor pipeline).
- `run_headless.sh` gains optional `RAMMS_PS_URL` env → appends
  `-PixelStreamingConnectionURL=...`. Per-instance port block already
  exists; signalling gets one port per instance (or one signalling process
  multiplexing streamer IDs — decide at spike).
- Deployment shape: one signalling container per node (added to
  `containers/`), or a central signalling host per cluster; WebRTC media
  flows directly node→browser over UDP, so cluster⇄workstation UDP
  reachability decides whether a TURN relay (coturn) is needed — verify
  during the spike, VPN/LAN only, no public exposure.
- A tiny "portal" page (ramms-tools cluster module) lists live instances
  (from the launcher/SLURM state) with click-to-view frontend links. Epic's
  matchmaker exists if this outgrows a static page.
- Training-pipeline validation payoff: any collection/eval instance becomes
  watchable live in a browser tab — spot-check rollouts without touching
  the job. Keep instances launched *without* a connection URL for
  max-throughput runs; attach streaming only on debug launches.
- Security defaults: leave `-AllowPixelStreamingCommands` off; input
  injection restricted to view-only frontends for pipeline-watching pages.

## Use case B — rammp-ui remote HMI (touchscreens, tablets, phones, XR)

**Feasibility: split.** Browsers-as-clients is exactly what PS is for
(touch input included) — but the stream must originate from an x64 machine.

- **From the Orin: needs the source-build allowlist patch** (see above) —
  not viable with a stock/launcher engine, but a 1-2 day spike on the
  LinuxArm64 source build rammp-ui already uses. The NX/AGX NVENC hardware
  is fine.
- Practical paths, in order:
  1. **Orin PS2 spike**: engine patch adding LinuxArm64 to the
     PixelStreaming2 module allowlists (runtime modules), GitDeps sync to
     confirm the aarch64 libepicrtc.a exists, on-device encoder check.
     Success → full interactive PS from the Orin, same stack as everywhere
     else, and paths 2/3 below become fallbacks only.
  2. **Jetson-native WebRTC sidecar** (view-first): GStreamer `webrtcbin`
     with the Orin NX/AGX hardware encoder (`nvv4l2h264enc`, or NVENCODE-
     backed FFmpeg on JetPack 6), capturing the UI (screen/DRM capture, or
     a shared texture handoff later). Hardware encode makes this cheap on
     the Orin — mirroring to nearby touchscreens/tablets with the native
     app untouched. Input back-channel (touch on the remote → HMI) is
     custom plumbing — a small bridge from browser touch events to the app
     (Remote Control API or a rammp-ui input socket) — start view-only,
     add input second.
  3. **x64-hosted HMI streams**: for settings with infrastructure nearby
     (clinic, lab, booth), run additional rammp-ui instances on an x64 box
     with real PS2 — full interactive touch on any browser device. The
     onboard Orin touchscreen stays native; remote devices get their own
     sessions rather than mirroring the driver's screen (usually what you
     actually want for a caregiver/clinician view).
  4. **XR**: the PS frontend's WebXR path is experimental; treat as a
     research spike off paths 1/3, not a commitment. Native XR (e.g.
     CloudXR) is out of scope for now.
- rammp-ui repo impact: enable the plugin for x64 targets only (it's
  engine-side, no code); the shared frontend/signalling config lives in the
  new infra repo (below) so RAMMS and rammp-ui use the same stack.

## Use case C — booth/demo dual-streaming

**Feasibility: trivial once A exists.** Extra browser peers on the same
streamer give mirrored views (frontend supports spectator/view-only
configuration); the SFU handles multi-viewer fan-out beyond a handful of
peers, including simulcast quality tiers for weak conference Wi-Fi. A
laptop running the sim + one signalling container + any number of
displays/phones pointed at a URL is the whole booth setup.

## Repo organization

New small OSS repo **`rammp-org/rammp-stream`** (serves both RAMMS and
rammp-ui, so it should not live inside either):
- pinned fork/config of Epic's PixelStreamingInfrastructure (signalling +
  frontend, branch-matched to our engine version),
- RAMMP-branded frontend shell (touch-first layout for HMI use, view-only
  spectator page for pipeline-watching/demos),
- container definitions (docker for dev/Jetson-adjacent boxes, apptainer
  for SLURM nodes) and compose files,
- the GStreamer Jetson sidecar (path B.1) when it lands.
Cluster-side wiring (launch flags, portal) stays with the existing
parallel-sim files in this repo (`Scripts/`, `containers/`, ramms-tools).

## Local runbook (spike A — validated 2026-08-03 on Mac)

Two processes; order doesn't matter (the streamer reconnects).

**1. Signalling server + web frontend** (one-time setup: clone
`github.com/EpicGamesExt/PixelStreamingInfrastructure` at the branch
matching the engine — `UE5.7` — then `npm install && npm run build` at the
repo root. Current local checkout: `~/atdev/PixelStreamingInfrastructure`.)

```bash
cd ~/atdev/PixelStreamingInfrastructure/SignallingWebServer
node ./dist/index.js --serve --http_root ./www --player_port 8080 --streamer_port 8888
```

**2. The sim, streaming** (any map; PixelStreaming2 must be enabled in the
.uproject — it is):

```bash
"/Users/Shared/Epic Games/UE_5.7/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" \
  ~/atdev/Ramms/Ramms.uproject VehicleBasic -game -windowed -resx=1280 -resy=720 \
  -PixelStreamingConnectionURL=ws://127.0.0.1:8888 -PixelStreamingEncoderCodec=VP8 -log
```

**ROOT CAUSE FOUND (2026-08-05, Windows, proven bidirectionally): the
"Missing Project Settings!" AssetGuideline toast breaks PS2 video.**
The Fab CitySampleCrowd pack ships an AssetGuideline
(`/Game/Fab/CitySampleCrowd/AssetGuidelines/CitySampleCrowdAssetGuideline_VT_StaticLighting`)
demanding `r.VirtualTextures=True`; this project deliberately sets it
False, so every `-game` launch (editor binaries; `UnrealEd` owns
AssetGuideline, so packaged builds are immune) spawns a persistent
notification toast — a second Slate window. UE 5.7's
`FVideoProducerBackBuffer` pushes **every** Slate window's backbuffer
unfiltered, so the 1146x161 toast alternates with the 1280x720 viewport
each frame; `FVideoCapturer` treats each alternation as an input resolution
change and recreates the whole capture pipeline every frame (observed: ~5
`PixelCaptureMediaCapture` objects destroyed per frame, 300+ per session).
The capturer never survives initialization, and the encoder's "no data yet"
paths return success **silently** — hence signalling/input/Opus all fine,
video permanently black, zero diagnostic output, identical on every
platform. Minimizing the toast window makes video appear within a second;
restoring it kills video again.

Consequences and fixes:
- The 2026-08-04 "Mac limitation" conclusion is almost certainly this same
  bug (the toast appears on Mac too) — **retest Mac after removing the
  guideline** before writing Mac off. The VP8-on-Mac advice is moot.
- Immediate fix: in an editor session (or on the toast itself), click
  **"Remove Guideline"** to strip the AssetGuideline from the CitySample
  assets and commit the change; "Dismiss" works per-session. Do NOT flip
  `r.VirtualTextures=True` casually — it is False on purpose (sensor/perf);
  evaluate separately if the crowd textures actually need it.
- Durable hardening — **IMPLEMENTED (2026-08-05)**: `Source/Ramms/
  RammsPixelStreamingSetup.cpp` (installed from the primary game module)
  swaps the default streamer's producer to
  `FVideoProducerMediaCapture::CreateActiveViewportCapture()` once
  Pixel Streaming reports ready (with a short ticker retry — OnReady fires
  a few ms before the default streamer exists). The viewport producer
  captures only the scene viewport, so ANY toast (AssetGuideline,
  shader-compile notifications, plugin messages) is harmless. Validated on
  Windows with the AssetGuideline toast visible: video streams normally.
  No-op in editor/PIE, when no `-PixelStreamingConnectionURL` is given, and
  on platforms without PS2 (`RAMMS_WITH_PIXEL_STREAMING=0`). Removing the
  guideline (above) is still worth doing for editor hygiene, but streaming
  no longer depends on it. Packaged cluster builds (use case A) were
  unaffected either way.
- Upstream: worth an Epic report — `FVideoProducerBackBuffer` needs a
  game-viewport window filter; a second differently-sized window yields
  permanently-black video with no log output (silent `Ok` returns in
  `TEpicRtcVideoEncoder::Encode`, capturer churn in `FVideoCapturer`).

**3. View + drive**: open http://127.0.0.1:8080 and click into the page —
video streams out, mouse/keyboard/touch stream back in (WASD drives the
chair). Other devices on the LAN: same URL with this machine's IP. More
simultaneous viewers: just open more tabs/devices (SFU only needed at
scale).

Gotchas learned:
- On Mac, launch the binary inside `UnrealEditor.app/Contents/MacOS/` — the
  bare `Engine/Binaries/Mac/UnrealEditor` stub fails to resolve the project
  ("Failed to find game directory").
- `-game` runs log to `~/Library/Logs/Ramms/Ramms.log`, not the project's
  Saved dir and not the editor log location.
- First `-game` boot compiles shaders for many minutes at full CPU with no
  visible progress; subsequent boots are ~a minute. The streamer shows in
  the signalling log as `DefaultStreamer` once EpicRtc joins.
- Linux/cluster variant: identical flags on the packaged build, plus
  `-RenderOffscreen` (no window) — see `Scripts/run_headless.sh` once the
  `RAMMS_PS_URL` hook lands (phase 2).

## Phases

1. **Spike A (half a day, x64 desktop):** enable plugin, local signalling,
   browser drive of the sim incl. keyboard teleop through PS; confirm
   runtime connect/disconnect behavior and view-only mode.
2. **Cluster bring-up:** signalling container + `run_headless.sh` flag +
   UDP reachability/TURN decision on the real cluster; portal page listing
   instances. Gate: watch a live collection rollout from a workstation
   browser.
3. **Booth kit:** view-only frontend config + SFU; one-command compose.
4. **Spike B.1 (Jetson sidecar):** GStreamer webrtcbin + V4L2 encoder
   mirroring the Orin screen to a tablet browser, view-only. Gate decides
   how far to invest vs leaning on x64-hosted sessions (B.2).
5. **Interactive remote HMI:** input path for whichever of B.1/B.2 won;
   multi-session UX (who controls what — reuse the ramms-access arbitration
   pattern: explicit priority with timeout).
6. **XR spike** (optional, after 2+5): WebXR frontend against an x64 HMI
   instance.

## Open questions

- Cluster network topology: is workstation⇄node UDP direct, or do we need
  coturn on a head node? (Decides half of phase 2's effort.)
- rammp-ui session model for remote devices: mirror the driver's screen vs
  independent caregiver/clinician sessions (B.2 naturally gives the
  latter; the sidecar gives the former).
- Whether demo booths get sim streams (A), HMI streams (B.2), or both on
  one signalling stack (rammp-stream should assume both).
