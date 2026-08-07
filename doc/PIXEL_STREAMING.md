# Pixel Streaming — Setup & Usage

View and drive the RAMMS sim from any web browser (desktop, tablet, phone —
mouse/keyboard/touch/gamepad all forward into the sim). Built on Unreal's
**Pixel Streaming 2** engine plugin (WebRTC): the sim encodes its viewport
with the GPU's hardware encoder and streams it to browsers; browser input
streams back over the same connection.

This is the practical how-to. Strategy, cluster deployment plans, and the
debugging history live in [PIXEL_STREAMING_PLAN.md](PIXEL_STREAMING_PLAN.md).

Status by platform (2026-08-05):

| Platform | Status |
|----------|--------|
| Windows | **Validated end-to-end** (RTX / NVENC H264) |
| macOS | Working (VideoToolbox); previously blocked by the toast bug — see [Hardening](#how-ramms-hardens-the-video-path) |
| Linux | Expected working (Epic's daily-exercised container path); pending cluster bring-up (plan phase 2) |

## Architecture (30 seconds)

Two processes plus a browser:

```
┌──────────────┐   ws://host:8888    ┌───────────────────┐    http://host:8080
│  RAMMS sim   │ ──────────────────► │ Signalling server │ ◄──────────────────  Browser(s)
│  (streamer)  │                     │  (Node, + web UI) │
└──────┬───────┘                     └───────────────────┘
       │                WebRTC (video out / input back, UDP, peer-to-peer)
       └────────────────────────────────────────────────────────────────────►  Browser(s)
```

The signalling server only brokers the connection; video flows directly
sim → browser. Multiple browsers can watch the same streamer.

## One-time setup: signalling server

Requires **Node.js** (18+). Clone Epic's infrastructure at the branch
matching the engine (**UE5.7**) and build it:

```bash
git clone -b UE5.7 https://github.com/EpicGamesExt/PixelStreamingInfrastructure
cd PixelStreamingInfrastructure
npm install && npm run build
```

The PixelStreaming2 plugin is already enabled in `Ramms.uproject` — no
project setup is needed on the UE side.

## Running

### 1. Start the signalling server

```bash
cd PixelStreamingInfrastructure/SignallingWebServer
node ./dist/index.js --serve --http_root ./www --player_port 8080 --streamer_port 8888
```

Leave it running. Order doesn't matter — the sim reconnects automatically.

### 2. Launch the sim with streaming enabled

Add `-PixelStreamingConnectionURL=ws://127.0.0.1:8888` to any `-game` (or
packaged) launch. Any map works; `Map_Demo` shown here.

**Windows (PowerShell):**

```powershell
$UE = "C:\Program Files\Epic Games\UE_5.7"
& "$UE\Engine\Binaries\Win64\UnrealEditor.exe" "$PWD\Ramms.uproject" Map_Demo `
  -game -windowed -resx=1280 -resy=720 `
  -PixelStreamingConnectionURL=ws://127.0.0.1:8888 -log
```

**macOS:**

```bash
UE="/Users/Shared/Epic Games/UE_5.7"
"$UE/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" \
  "$PWD/Ramms.uproject" Map_Demo -game -windowed -resx=1280 -resy=720 \
  -PixelStreamingConnectionURL=ws://127.0.0.1:8888 -log
```

> macOS gotchas: launch the binary **inside**
> `UnrealEditor.app/Contents/MacOS/` (the bare `Engine/Binaries/Mac/
> UnrealEditor` stub fails with "Failed to find game directory"), and `-game`
> logs go to `~/Library/Logs/Ramms/Ramms.log`, not the project's Saved dir.
> The first `-game` boot compiles shaders for many minutes; later boots are
> ~a minute.

**Linux (packaged build, headless):**

```bash
./Ramms.sh Map_Demo -RenderOffscreen \
  -PixelStreamingConnectionURL=ws://<signalling-host>:8888 -log
```

`-RenderOffscreen` renders without a window — the cluster mode. (The
`run_headless.sh` `RAMMS_PS_URL` hook lands with plan phase 2.)

Successful connection shows in the sim log as
`LogEpicRtcWebsocket: Websocket connection made to: ws://...`, and in the
signalling log as a `DefaultStreamer` registration. RAMMS also logs
`Pixel Streaming: switched default streamer to the viewport MediaCapture
producer` — see [Hardening](#how-ramms-hardens-the-video-path).

### 3. View and drive

Open **http://127.0.0.1:8080** and click into the page. Video streams out;
mouse/keyboard/touch stream back in (WASD drives the chair). From other
devices on the LAN use this machine's IP instead of `127.0.0.1`. More
viewers = more tabs/devices pointed at the same URL (an SFU is only needed
at scale — see the plan doc).

The ⓘ button on the player page opens live session stats (codec, bitrate,
RTT, resolution) — the first place to look when something seems off.

## Useful flags

| Flag | Effect |
|------|--------|
| `-PixelStreamingConnectionURL=ws://host:8888` | Enable streaming and point at the signalling server (required — must be on the command line at boot) |
| `-RenderOffscreen` | Render with no local window (headless nodes) |
| `-resx=1920 -resy=1080` | Stream resolution follows the viewport size |
| `-PixelStreamingEncoderCodec=H264\|AV1\|VP9\|VP8` | Encoder codec; default H264 (hardware). Leave at default unless you have a reason |
| `-PixelStreamingHudStats` | On-screen per-peer streaming stats in the sim |
| `-PixelStreamingLogStats=true` | Per-second WebRTC stats to the log |

Security defaults for shared/pipeline-watching pages: leave
`-AllowPixelStreamingCommands` off and use the frontend's view-only /
spectator configuration (see plan doc, use case A).

## How RAMMS hardens the video path

Stock Pixel Streaming 2 (UE 5.7) captures **every Slate window's backbuffer,
unfiltered**. Any extra window — e.g. a persistent notification toast such
as the AssetGuideline "Missing Project Settings!" popup — alternates with
the game viewport in the capture pipeline, forcing it to rebuild every frame.
Result: signalling, input, and audio work but video stays **permanently
black with zero errors logged**, on every platform. This bit both Mac and
Windows dev runs of RAMMS before it was root-caused (full forensics in
[PIXEL_STREAMING_PLAN.md](PIXEL_STREAMING_PLAN.md)).

RAMMS therefore swaps the default streamer's video producer to the
**viewport MediaCapture producer**, which captures only the scene viewport
and is immune to extra windows. This happens automatically at startup
(`Source/Ramms/RammsPixelStreamingSetup.cpp`) whenever a connection URL is
given; it is a no-op in editor/PIE and on platforms without the plugin.
Packaged builds were never affected (the toast is editor-module-only).

## Troubleshooting

**"WebRTC connected, waiting for video" (input works, screen black):**

1. Confirm the RAMMS producer-swap log line appeared
   (`Pixel Streaming: switched default streamer to the viewport MediaCapture
   producer`). If it's missing, the hardening didn't run — check that the
   connection URL was on the command line (not added later) and the log for
   `LogRamms` warnings.
2. Open `chrome://webrtc-internals` in the viewing browser: if there is **no
   inbound-rtp video stat at all**, the encoder never produced a packet —
   sim-side capture problem. If frames are received but the page is black,
   it's a frontend/browser issue (click into the page; check autoplay).
3. Check the sim log for `LogAVCodecs` errors (encoder init failures) and
   repeated `PixelCaptureMediaCapture_N will be destroyed` warnings during
   the session (capture-pipeline churn — the extra-window symptom).
4. Verbose logging for the whole video path:
   `-LogCmds="LogPixelStreaming2RTC Verbose, LogPixelCapture Verbose,
   LogMediaIOCore Verbose, LogAVCodecs Verbose"`.

**Browser says "gave up waiting for DefaultStreamer":** the sim wasn't
connected yet (first boot compiles shaders for minutes). Click to retry once
the sim log shows the websocket connection.

**No connection from other devices:** open TCP 8080/8888 on the host
firewall; WebRTC media needs UDP reachability between browser and sim
machine (on typical LANs this is direct; across networks a TURN relay may
be needed — see plan doc, phase 2).

**NPCs T-posing in `-game` (historical):** unrelated to streaming — an anim
graph node lived in an Editor-type module and broke crowd anim blueprints in
uncooked `-game` runs. Fixed 2026-08-05 in the RammsCrowd plugin
(`RammsCrowdUncooked` UncookedOnly module + CoreRedirect). If it recurs,
check the log for `LoadErrors` naming `AnimGraphNode_RammsFootPlacement`.
