# Scripting and remote control

<sub>[README](../README.md) · [Getting started](getting_started.md) · [Features](features.md) · [Scripting and remote control](remote_and_scripting.md) · [World generation](world_generation.md)</sub>

Driving RAMMS-Sim from outside: Python in the editor, the ramms-tools CLIs over Remote Control, a browser over Pixel Streaming, and AI assistants over MCP.

- [Python integration](#python-integration)
- [ramms-tools (Remote Control API)](#ramms-tools-remote-control-api)
- [Pixel Streaming (remote browser access)](#pixel-streaming-remote-browser-access)
- [MCP server (AI assistants in the editor)](#mcp-server-ai-assistants-in-the-editor)

## Python Integration

`Scripts/editor_remote_exec.py` is a dependency-free client for UE's Python
Remote Execution. It runs a snippet or a script file inside a running editor
and prints the editor-side output:

```bash
python Scripts/editor_remote_exec.py --code "unreal.log('hi')"
python Scripts/editor_remote_exec.py --file path/to/script.py
python Scripts/editor_remote_exec.py --eval "unreal.SystemLibrary.get_project_directory()"
```

Remote Execution is enabled in this project's settings (multicast
239.0.0.1:6766, loopback). For another project, enable it under **Edit >
Project Settings > Plugins > Python > Remote Execution > Enable Remote
Execution**.

The PIE test runners under `Scripts/pie_tests/` drive the editor through it.

### Recording a run for video

The physics backend does not run in real time under the Movie Render Queue, so
to film a simulated behaviour, record it first and play the recording back in a
Level Sequence afterwards. `Scripts/record_transforms.py` records every visible
mesh on an actor each editor tick, keyed on the physics clock
(`RammsRobotBaseComponent.GetSimulationTime`, `mjData.time` on the MuJoCo
backend), plus the rest of the level's static meshes once, as one JSON file.
Run it through `editor_remote_exec.py` while PIE is running, `begin <out.json>
[<actor label>]` before the behaviour and `end` after it (the default actor is
the first Pawn with a `RammsRobotBaseComponent`). The file's header documents
the format. The playback side (clustering the meshes into their rigid bodies,
keying a Level Sequence, rendering) is a consumer's concern; the first one is
the curb negotiation video.

### ramms-tools (Remote Control API)

The sister repository [ramms-tools](https://github.com/rammp-org/ramms-tools)
(`pip install -e ../ramms-tools`) is the supported way for programs and users
to drive RAMMS from outside the editor. It talks to the engine's **Remote
Control API** (HTTP port 30010, in the editor and in `-game` / packaged
builds with the plugin) and ships a library plus CLIs: `ramms-control`,
`ramms-curb`, `ramms-sensors`, `ramms-kinova`, `ramms-rammp-gen1`,
`ramms-gripper`, `ramms-pose`, `ramms-imu`, `ramms-stream`, `ramms-notify`,
`ramms-status`, `ramms-tui`, and `ramms-worldgen` for
[world generation](features.md#world-generation-procedural-randomized-environments).

For any robot with a control surface (the RAMMP Gen1 and Gen2 curb pawns, the
chair, the lift-drive bases; the Gen2 pawn and the lift-drive bases come with
the private assets):

- `ramms-control` lists robots and their controls, sets, triggers and releases
  them, drives (`drive --forward 0.3 --seconds 2`, strafing in holonomic modes)
  and switches drive modes (`mode holonomic`).
- `ramms-curb` reads a crossing's phase and status, toggles curb assist and the
  Gen1 crossing style, shows what Gen2 senses ahead (`detect`: step height,
  edge distance, approach angle, far side) and runs a crossing
  (`go --wait` starts it, holds the stick forward as a rider would while it
  runs and prints the phase log and stats). It also reads and sets the Gen2 seat.
- `ramms-sensors` lists, adds and reads ToF, sonar and IMU sensors and capture
  cameras, and streams a camera's colour, depth, motion vectors and segmentation
  mask over RMSS (`streams start`, `camera front_camera --save shots`).
- The TUI's Robot tab shows the same live.

A Remote or Autonomy command on a Continuous or Velocity control (the drive
axes, the jog, arm and camera rates, a raw `motor.<id>` speed in a robot's
low-level mode) lasts only while its source is heard from. Once nothing has
come from that source on the robot's control surface for the deadman's window
(`DeadmanSeconds`, 0.3 s) plus a grace of the last two frames, the control
springs back to its default: a Continuous one as if released, a Velocity one by
being commanded its default (0, stop). Heard is per source, not per control:
any command the surface applies from that source -- a set, a trigger, a
release, of any control -- keeps all of its held controls, so a client sending
its controls one request at a time is not taken for gone between them, and a
control it set once stays while it keeps sending others. The grace means a long
frame (an editor throttled to 3 frames a second in the background, a hitch) is
not taken for silence.

Remote Control carries no client identity, and `Source` is whatever the caller
passes: any client may send as `Autonomy` (which outranks `Remote` and local
input) or as `Script` (whose commands never lapse). Two clients sending as the
same source keep each other's commands alive.

ramms-tools re-sends held commands at 10 Hz, one batched request per round,
and releases them at the end, so a client that drops off stops the robot within
about 0.3 s plus two frames. Position, Enum and Action controls, keyboard,
gamepad, touch and Script commands, and the robot's own commands (a drive
mode's stance, a curb crossing holding the arm still) stay until they are
changed or released. A drive-mode switch carries held drive commands into the
new mode as of when they were sent, so it gives a client that already went
quiet no fresh lease. Details: the RammsCore README, "The drive deadman".

Robot sensing goes through `URammsSensorRigComponent` (RammsCore). The Gen1
curb pawn ships with one (`SensorRig`: `imu`, `front_tof`, `front_sonar` and an
RGB-D `front_camera` at the front of the chassis), as does the Gen2 curb pawn in
the private assets, and `URammsSensingBridge` adds the same sensors to any robot
at runtime (`ramms-sensors --robot <chair> rig apply chair`; without `--robot` a
preset goes on the first robot found). Sensing changes need a play world (PIE or
a game).

A rig camera streams on RMSS channels C, C+100, C+200 and C+300 as
`camera/<name>/color`, `camera/<name>/depth`, `motion/<name>` and
`mask/<name>`. These use the stream ids and the `group`, `role` and `fmt`
metadata that ramms-tools' `StreamSender` uses, with one difference: colour goes
out as `FrameRGB`, not `StreamSender`'s `ImageData`. Robots carry cameras with
the same name (`front_camera`), so a client picks a robot's camera by the frame
metadata's `actor` (and its channel), never by name alone. RMSS needs no header
or version change for this.

The sim sends frames only to a client that has subscribed (an empty Subscribe
means every channel), so a send-only client such as `StreamSender` is never
queued frames, and a camera role is built only while a subscriber wants it.
Over the bridge, `save_to_disk` is refused, and `StopCameraStreams` stops only
what the bridge started.

IMU data comes from the physics engine that simulates the body, and needs no
IMU component:

- `URammsPhysicsImuSubsystem` samples MuJoCo bodies (the RammsMujocoSupport
  provider, at each MuJoCo step) and Chaos bodies or bones (at each physics
  step) at the sensor's point.
- The acceleration is what an accelerometer reads (+g up at rest).
- `URammsIMUSensorComponent`'s `Source` (Auto by default) uses the same
  samples, averaged over its update interval. It differences its own transform
  (`Kinematic`) for a body no engine simulates, or when `bUsePhysicsVelocity`
  is off.
- Remote callers read the latest sample (`URammsSensingBridge::ReadBodyImuJson`,
  `ramms-sensors imu --body chassis`) or every physics-step sample: in batches
  over Remote Control (`ReadImuSamplesJson`), or as a continuous RMSS stream
  (`StartImuStreamJson`).
- Remote callers share 32 of a world's 64 IMU points (a read point expires
  after 10 s unread) and at most 8 IMU streams; a stream nobody has subscribed
  to for 30 s stops.

UE 5.6+ refuses remote **function calls** unless they are allow-listed.
`Config/DefaultRemoteControl.ini` lists:

- the RAMMS bridges (`RammsCoreBridge`, `RammsRemoteBridge`,
  `RammsWorldGenBridge`, `RammsSensingBridge`), whole: function libraries
  meant for remote use, with their own limits;
- function by function, what ramms-tools calls on the robot control surface,
  the drive-mode selector, the Gen1 and Gen2 curb controllers, the Gen2 seat,
  the Kinova arm, the gripper, the Gen1 lift controller, the skeletal pose
  component, the world generator, and the traffic spawner and signal clock;
- the few engine getters the tools use.

The list is checked against every function call: `/remote/object/call`, each
call inside `/remote/batch`, and the WebSocket server's calls. A call matches an
entry when the object's own class is the entry's class (or a subclass of it,
with `bAllowChildClasses`) and the function's UFUNCTION name equals
`FunctionName` (case ignored), wherever that function is declared -- an
inherited function is listed under the class it is called on. A class listed
whole exposes every Blueprint-callable function it has and inherits (a
component's `K2_DestroyComponent`, an actor's `K2_DestroyActor`), so add a new
call by `FunctionName` unless the class is a bridge meant for remote use.

`FunctionName` is optional in UE, so its value goes in parentheses:
`FunctionName=("SetControl")`. A bare `FunctionName="SetControl"` does not
parse; the entry is then left without a function and allows every function of
the class (and, with `bAllowChildClasses`, of every subclass).

The list does **not** cover property access. `/remote/object/property` reads
and writes any public property that is instance-editable in the editor, or
Blueprint-visible (and not read-only) in a game -- on any object a client can
name. Safety settings therefore are not instance-editable Blueprint-writable
properties: the control surface's deadman window (`DeadmanSeconds`) is a class
default, and the hold window that is writable (`ExternalHoldSeconds`) is used
within 0.1 to 2 s whatever it is set to.

Remote Control is reachable from the network: the HTTP server (:30010) binds
localhost by default, but the WebSocket server (:30020) listens on every
interface and carries the same calls and property access.

## Pixel Streaming (Remote Browser Access)

View and drive the sim from any web browser — desktop, tablet, or phone —
with no client install. Built on Unreal's Pixel Streaming 2 plugin (WebRTC):
the sim hardware-encodes its viewport and streams it out; browser
mouse/keyboard/touch input streams back in. Works for local dev sessions,
watching headless cluster instances live, and multi-viewer demo setups.

Quick start (two processes + a browser):

```bash
# 1. Signalling server (one-time setup: clone Epic's PixelStreamingInfrastructure
#    at the UE5.8 branch, `npm install && npm run build`)
cd PixelStreamingInfrastructure/SignallingWebServer
node ./dist/index.js --serve --http_root ./www --player_port 8080 --streamer_port 8888
```

```powershell
# 2. Any -game or packaged launch, plus the connection URL flag
& "$UE\Engine\Binaries\Win64\UnrealEditor.exe" "$PWD\Ramms.uproject" Map_Demo `
  -game -windowed -resx=1280 -resy=720 `
  -PixelStreamingConnectionURL=ws://127.0.0.1:8888 -log
```

Then open **http://127.0.0.1:8080** and click into the page — WASD drives
the chair. Other devices on the LAN use the host's IP; extra viewers are
just extra tabs.

RAMMS automatically hardens the video path at startup (it swaps the default
streamer to a viewport-only capture producer — stock UE 5.8 captures every
window and goes silently black if e.g. a notification toast is open).

See **[PIXEL_STREAMING.md](PIXEL_STREAMING.md)** for macOS/Linux
launch commands, flags, architecture, and troubleshooting, and
[PIXEL_STREAMING_PLAN.md](PIXEL_STREAMING_PLAN.md) for the cluster /
remote-HMI / demo roadmap.

## MCP Server (AI assistants in the editor)

UE 5.8 ships Epic's **Model Context Protocol** plugin, an MCP server that runs
inside the editor so an AI assistant can query and drive it. The plugin is
enabled in `Ramms.uproject`; it does not exist in 5.7.

The project ships the server settings in
`Config/DefaultEditorPerProjectUserSettings.ini`, so a fresh clone starts the
server automatically on `http://127.0.0.1:8000/mcp`:

```ini
[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]
ServerUrlPath=/mcp
ServerPortNumber=8000
bAutoStartServer=True
bEnableToolSearch=True
```

Those are defaults, not locks. **Edit > Editor Preferences > General > Model
Context Protocol** overrides them per user, and your choice is written to
`Saved/Config/<Platform>/EditorPerProjectUserSettings.ini`, which is not
tracked. To start the server for one session without changing any setting,
launch the editor with `-ModelContextProtocolStartServer` (add
`-ModelContextProtocolPort=N` to move the port).

**Connecting a client.** `.mcp.json` at the repo root is committed and points
at the endpoint above, so Claude Code picks it up on startup and asks once
whether to trust it. Other clients can generate their own config from the
editor console:

```
ModelContextProtocol.GenerateClientConfig <ClaudeCode|Cursor|VSCode|Gemini|Codex|All>
```

Check it is up with `lsof -nP -iTCP:8000 -sTCP:LISTEN`, or look for
`LogModelContextProtocol: Starting MCP server on port 8000` in the editor log.
The server only runs while the editor is open.

**If you override the port or path**, the committed `.mcp.json` still points at
the old endpoint, and the client fails to connect even though the server is
running. Regenerate it from the editor console after changing either setting:

```
ModelContextProtocol.GenerateClientConfig ClaudeCode
```

That rewrites `.mcp.json` from the values actually in effect. Keep the change
local unless the new endpoint is meant for everyone — the committed file is the
default the rest of the team gets.

**What it exposes.** Tool search is on, so `tools/list` returns three
meta-tools — `list_toolsets`, `describe_toolset`, `call_tool` — that front the
registered toolsets rather than registering every tool natively. Stock 5.8
contributes two (agent skills, editor context), and this project adds a third.

### The RAMMS toolset

`Content/Python/ramms_toolset/` registers `RammsToolset`, which exposes the
same surface the PIE runners in `Scripts/pie_tests/base_component/` drive, so an
assistant can inspect and command a running sim directly:

| Tool | Purpose |
|------|---------|
| `sim_status` | Is PIE running, which map, which robots are present |
| `begin_pie` / `end_pie` | Start play (optionally loading a map first) and stop it |
| `describe_controls` | A robot's control axes: ids, kinds, units, ranges |
| `read_control` | Live value, commanded target and arbitration owner, per axis |
| `set_control` / `release_control` | Command and release an axis as the Script source |
| `physics_status` | Active backend plus every motor's type, value and velocity |
| `newton_settings` | The Newton interpreter and worker paths, resolved and existence-checked |

`Content/Python/init_unreal.py` registers it at startup, wired up through
`StartupScripts` in `Config/DefaultEngine.ini` — the engine only auto-runs
`init_unreal.py` from *plugin* content directories, not from the project's own,
so the entry is what makes it load.

Two things to know when calling the tools:

- **Every parameter is required**, even ones with Python defaults; the
  generated schema marks them all required. Pass `""` for `robot` to mean
  "the only robot present".
- **Iterate without restarting the editor.** After editing the module:

  ```python
  import toolset_registry, ramms_toolset
  toolset_registry.reload_module(ramms_toolset)
  ```

  which unregisters, reloads every submodule, and registers again.

For heavier scripting the Python Remote Execution route above is still there,
and the two agree by construction: the toolset wraps the same calls.

> **Note:** Epic's plugin warns that data sent through it to an LLM service is
> Licensed Technology under the UE EULA, and that you are responsible for
> ensuring your provider does not train on it. See EULA section 6(e).
