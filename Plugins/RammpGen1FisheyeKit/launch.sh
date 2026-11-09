#!/usr/bin/env bash
# RAMMP Gen1 (formerly the MeBot) with six fisheyes, streaming to ROS 2: starts ramms-sim as a standalone game on a map with the
# kit's game mode (?game= overrides the map's own, without editing the map), then the RMSS -> ROS 2 bridge.
#
#   Plugins/RammpGen1FisheyeKit/launch.sh [map] [--foxglove] [--no-sim] [bridge --ros-args ...]
#     map          a ramms-sim map name (default Map_Demo), e.g. Map_Dojo, Map_CurbTest
#     --foxglove   also start foxglove_bridge on ws://localhost:8765
#     --no-sim     only the bridge (the sim already runs: in the editor, Play with World Settings ->
#                  GameMode Override = BP_RammpGen1FisheyeGameMode)
# Environment: UE_EDITOR (default: UnrealEditor on PATH, else $UE_ROOT/Engine/Binaries/Linux/UnrealEditor),
# ROS 2 Humble in /opt/ros/humble. Ctrl+C stops the bridge(s) and the sim.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
project="$(cd "$here/../.." && pwd)/Ramms.uproject"
[ -f "$project" ] || { echo "expected the kit in <ramms-sim>/Plugins/RammpGen1FisheyeKit (no $project)" >&2; exit 1; }
map=Map_Demo foxglove=0 sim=1 bridge_args=()
while [ $# -gt 0 ]; do
	case "$1" in
	--foxglove) foxglove=1 ;;
	--no-sim) sim=0 ;;
	--ros-args) bridge_args=("$@"); break ;;
	-*) echo "unknown option $1" >&2; exit 2 ;;
	*) map="$1" ;;
	esac
	shift
done
ue="${UE_EDITOR:-$(command -v UnrealEditor || echo "${UE_ROOT:-/opt/UnrealEngine}/Engine/Binaries/Linux/UnrealEditor")}"
gm=/RammpGen1FisheyeKit/BP_RammpGen1FisheyeGameMode.BP_RammpGen1FisheyeGameMode_C
pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

if [ "$sim" = 1 ]; then
	[ -x "$ue" ] || { echo "UnrealEditor not found: set UE_EDITOR=<path to Engine/Binaries/Linux/UnrealEditor>" >&2; exit 1; }
	echo "== sim: /Game/Maps/$map with $gm"
	# -game: standalone game from the editor binary (uncooked content); ulimit -c 0: no multi-GB core dumps
	(ulimit -c 0; exec "$ue" "$project" "/Game/Maps/$map?game=$gm" -game -windowed -ResX=1280 -ResY=720 -vulkan) &
	pids+=($!)
fi
set +u
source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
set -u
if [ "$foxglove" = 1 ]; then
	echo "== foxglove_bridge on ws://localhost:8765"
	ros2 run foxglove_bridge foxglove_bridge --ros-args -p port:=8765 >/dev/null 2>&1 &
	pids+=($!)
fi
echo "== RMSS -> ROS 2 bridge (retries until the sim is in play): /rammp_gen1/cam/TN_*/..."
"$here/ros/run_bridge.sh" --ros-args -p compressed:=true -p publish_raw:=false "${bridge_args[@]:1}" &
pids+=($!)
wait "${pids[-1]}"
