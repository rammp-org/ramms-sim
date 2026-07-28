#!/usr/bin/env bash
# Builds RAMMS for Linux (native — run this ON a Linux machine with a UE 5.7
# source/installed build; Mac→Linux cross-compilation is not supported by UE).
#
# Builds both targets:
#   RammsEditor — needed for cooking (package_linux.sh) and headless-editor runs
#   Ramms       — the game target that ships to cluster nodes
#
# Usage:
#   Scripts/build_linux.sh [--game-only|--editor-only] [--skip-urlab]
#
# Environment:
#   UE_ROOT   Unreal Engine root (source or installed build)
#             (default: $HOME/UnrealEngine)
#   CONFIG    Build configuration: Development (default), Shipping, DebugGame

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPROJECT="$REPO_ROOT/Ramms.uproject"
UE_ROOT="${UE_ROOT:-$HOME/UnrealEngine}"
CONFIG="${CONFIG:-Development}"

BUILD_GAME=1
BUILD_EDITOR=1
RUN_URLAB_SETUP=1
for arg in "$@"; do
	case "$arg" in
		--game-only) BUILD_EDITOR=0 ;;
		--editor-only) BUILD_GAME=0 ;;
		--skip-urlab) RUN_URLAB_SETUP=0 ;;
		*) echo "unknown argument: $arg"; exit 2 ;;
	esac
done

log() { echo "[build_linux] $*"; }

if [ "$(uname -s)" != Linux ]; then
	log "ERROR: this script must run on Linux (UE cannot cross-compile Mac→Linux)."
	exit 1
fi

BUILD_SH="$UE_ROOT/Engine/Build/BatchFiles/Linux/Build.sh"
if [ ! -f "$BUILD_SH" ]; then
	log "ERROR: engine not found at '$UE_ROOT' (set UE_ROOT to your UE 5.7 root)"
	exit 1
fi

# URLab third-party deps (MuJoCo/CoACD/libzmq) + local patches + project files.
# Uses UE's bundled clang/libc++ on Linux (see setup_urlab.sh).
if [ "$RUN_URLAB_SETUP" = 1 ]; then
	UE_ROOT="$UE_ROOT" bash "$REPO_ROOT/Scripts/setup_urlab.sh"
fi

if [ "$BUILD_EDITOR" = 1 ]; then
	log "building RammsEditor Linux $CONFIG..."
	"$BUILD_SH" RammsEditor Linux "$CONFIG" -Project="$UPROJECT" -WaitMutex
fi

if [ "$BUILD_GAME" = 1 ]; then
	log "building Ramms Linux $CONFIG..."
	"$BUILD_SH" Ramms Linux "$CONFIG" -Project="$UPROJECT" -WaitMutex
fi

log "done."
