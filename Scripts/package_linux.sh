#!/usr/bin/env bash
# Cooks and packages RAMMS for Linux into Packaged/Linux — the self-contained
# build that cluster nodes (and containers/ramms.def) run. Native Linux only.
#
# Usage:
#   Scripts/package_linux.sh [extra BuildCookRun args...]
#
# Environment:
#   UE_ROOT   Unreal Engine root (default: $HOME/UnrealEngine)
#   CONFIG    Client configuration: Development (default) or Shipping.
#             Development keeps logging + console-variable access — recommended
#             until the headless pipeline is fully proven; Shipping for scale.
#   MAPS      Optional '+'-separated map list to cook (default: all maps).
#             Example: MAPS="Map_GraspTest+Map_CurbTest+Map_CrowdTest"

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPROJECT="$REPO_ROOT/Ramms.uproject"
UE_ROOT="${UE_ROOT:-$HOME/UnrealEngine}"
CONFIG="${CONFIG:-Development}"

log() { echo "[package_linux] $*"; }

if [ "$(uname -s)" != Linux ]; then
	log "ERROR: this script must run on Linux."
	exit 1
fi

RUNUAT="$UE_ROOT/Engine/Build/BatchFiles/RunUAT.sh"
if [ ! -f "$RUNUAT" ]; then
	log "ERROR: engine not found at '$UE_ROOT' (set UE_ROOT to your UE 5.7 root)"
	exit 1
fi

ARGS=(
	BuildCookRun
	-project="$UPROJECT"
	-platform=Linux
	-clientconfig="$CONFIG"
	-build -cook -stage -pak
	-archive -archivedirectory="$REPO_ROOT/Packaged"
	-unattended -noP4 -utf8output
)
if [ -n "${MAPS:-}" ]; then
	ARGS+=(-map="$MAPS")
fi

log "packaging (config=$CONFIG)..."
"$RUNUAT" "${ARGS[@]}" "$@"
log "done — output in Packaged/Linux (launch via Ramms.sh or Scripts/run_headless.sh)"
