#!/usr/bin/env bash
# Launches one headless-but-rendering RAMMS instance from a packaged Linux
# build: no display server, but a real Vulkan RHI so cameras render and the
# ToF/sonar GPU ray-tracing path works (this is NOT -NullRHI — NullRHI kills
# cameras and silently degrades ToF/sonar to the CPU line-trace fallback,
# which has different semantics).
#
# Usage:
#   Scripts/run_headless.sh [MAP] [INSTANCE] [extra UE args...]
#
#   MAP       Map name (default: Map_GraspTest)
#   INSTANCE  Instance index on this host (default: 0). Drives per-instance
#             Saved-dir isolation (logs, config, URLab shared-memory session
#             dirs) and the URLab bridge port block.
#
# Environment:
#   RAMMS_PACKAGED  Packaged build root (default: <repo>/Packaged/Linux)
#   RAMMS_FPS       Fixed render framerate (default: 30). Paired with
#                   -UseFixedTimeStep so camera frames keep a fixed phase
#                   relationship to URLab Direct-mode physics steps.
#   RAMMS_PORT_BASE URLab port block base (default: 5559 = upstream PortBase).
#                   Instance i gets slot = base + i*20, laid out as
#                   step=slot+0, state=slot+1, cameras=slot+2..slot+9
#                   (CamBasePort + camera index), ctrl=slot+10, info=slot+11.
#
# Since URLab v0.6.0-beta the -URLabInstanceIndex/-URLabPortBase/
# -URLabPortStride/-URLabStepPort/-URLabStatePort/-URLabCamBasePort switches
# are native (Bridge/BridgeServerConfigUtils.cpp ApplyEnvAndCommandLineOverrides);
# only -URLabCtrlPort/-URLabInfoPort for the legacy subscriber remain as our
# own addition (committed on our URLab fork branch ramms/v0.6.0-beta). The
# bridge's own INI lives inside the plugin dir and is shared by every instance
# on a host, so the command line is the only per-instance channel. Clients
# learn actual camera ports from the handshake.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAP="${1:-Map_GraspTest}"
INSTANCE="${2:-0}"
shift $(( $# > 2 ? 2 : $# )) || true

PACKAGED="${RAMMS_PACKAGED:-$REPO_ROOT/Packaged/Linux}"
FPS="${RAMMS_FPS:-30}"
PORT_BASE="${RAMMS_PORT_BASE:-5559}"
PORT_STRIDE=20

log() { echo "[run_headless:$INSTANCE] $*"; }

LAUNCHER="$PACKAGED/Ramms.sh"
if [ ! -f "$LAUNCHER" ]; then
	log "ERROR: packaged build not found at '$PACKAGED' (run Scripts/package_linux.sh, or set RAMMS_PACKAGED)"
	exit 1
fi

# step/state/cam derive in-engine from index*stride (DerivePorts); ctrl/info
# are the legacy subscriber's slots at the top of the same block.
SLOT=$(( PORT_BASE + INSTANCE * PORT_STRIDE ))
CTRL_PORT=$(( SLOT + 10 ))
INFO_PORT=$(( SLOT + 11 ))

# Default the per-instance Saved dir to the CURRENT directory, not the
# packaged tree: inside a container the packaged build is read-only (and on
# SLURM, cwd is the submit dir on writable shared FS). Override with
# RAMMS_SAVED_DIR for scratch mounts.
SAVED_DIR="${RAMMS_SAVED_DIR:-$PWD/RammsSaved/inst$INSTANCE}"
mkdir -p "$SAVED_DIR"

log "map=$MAP fps=$FPS step_port=$SLOT state_port=$(( SLOT + 1 )) cam_base=$(( SLOT + 2 )) saved=$SAVED_DIR"
exec "$LAUNCHER" "$MAP" \
	-RenderOffscreen -Unattended -NoSound -stdout -UTF8Output \
	-UseFixedTimeStep -FPS="$FPS" -Deterministic \
	-saveddir="$SAVED_DIR" \
	-URLabInstanceIndex="$INSTANCE" -URLabPortBase="$PORT_BASE" -URLabPortStride="$PORT_STRIDE" \
	-URLabCtrlPort="$CTRL_PORT" -URLabInfoPort="$INFO_PORT" \
	"$@"
