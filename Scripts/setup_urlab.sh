#!/usr/bin/env bash
# Sets up the Plugins/unreal-robotics-lab submodule for building RAMMS on
# macOS/Linux: applies the one nested patch upstream does not carry, builds
# its third-party dependencies, and regenerates project files.
#
# Idempotent — safe to re-run any time.
#
# Usage:
#   Scripts/setup_urlab.sh [--no-thirdparty] [--no-projectfiles]
#
# Environment:
#   UE_ROOT   Unreal Engine install root
#             (default: /Users/Shared/Epic Games/UE_5.8)
#
# Our URLab fixes now live on our FORK, not in a patch:
#   git@github.com:rammp-org/UnrealRoboticsLab  branch ramms/v0.6.0-beta
# The submodule pins that branch's tip, so `git submodule update --init`
# already brings the fixes (the `nil` macro guard, the Mac Build.cs dylib
# linking + install-linux cross path, the MjBody world-body render fix, the
# quick-convert preview refresh, the CoACD/MuJoCo build-script dylib staging,
# the legacy-subscriber port overrides). The fork's `upstream` remote points
# at urlab-sim/UnrealRoboticsLab so each fix can be split onto a clean branch
# and PR'd back. See the ramms/v0.6.0-beta commit for the grouped changelog.
#
# The ONE thing still applied as a patch is the NESTED submodule
# third_party/CoACD/src (we don't own CoACD's repo, so its fix cannot be
# committed on our fork):
# Scripts/patches/coacd-src-local-fixes.patch:
#   - CMakeLists.txt / cmake/openvdb.cmake / public/coacd.h: build + template
#     compile fixes for modern clang/CMake.
#
# NOTE: third-party builds run with --no-submodule-sync — the default sync
# checks out the pinned SHA and would discard the CoACD source patch.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUBMODULE="$REPO_ROOT/Plugins/unreal-robotics-lab"
COACD_SRC="$SUBMODULE/third_party/CoACD/src"
COACD_PATCH="$REPO_ROOT/Scripts/patches/coacd-src-local-fixes.patch"
UPROJECT="$REPO_ROOT/Ramms.uproject"
UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.8}"

BUILD_THIRDPARTY=1
GEN_PROJECTFILES=1
for arg in "$@"; do
	case "$arg" in
		--no-thirdparty) BUILD_THIRDPARTY=0 ;;
		--no-projectfiles) GEN_PROJECTFILES=0 ;;
		*) echo "unknown argument: $arg"; exit 2 ;;
	esac
done

log() { echo "[setup_urlab] $*"; }

# --- 0. submodule present? ---
if [ ! -f "$SUBMODULE/URLab.uplugin" ] && [ ! -f "$SUBMODULE/UnrealRoboticsLab.uplugin" ]; then
	log "submodule looks uninitialized — running git submodule update --init"
	git -C "$REPO_ROOT" submodule update --init Plugins/unreal-robotics-lab
fi

# --- 1. our URLab fixes are committed on the fork branch, not patched ---
# The submodule pin already carries them. Warn (don't fail) if the checkout
# is unexpectedly a bare upstream tag with none of our commits — e.g. someone
# repointed the URL back to urlab-sim.
if ! git -C "$SUBMODULE" merge-base --is-ancestor \
		41fd7cceda538039581f5ed48e88956171c5d753 HEAD 2>/dev/null; then
	log "WARN: submodule does not contain our fix commit 41fd7cc — is the URL"
	log "      the rammp-org/UnrealRoboticsLab fork and the pin on ramms/v0.6.0-beta?"
	log "      (run: git submodule sync && git submodule update --init Plugins/unreal-robotics-lab)"
fi

# --- 2. apply nested CoACD source fixes (idempotent) ---
if [ ! -f "$COACD_SRC/CMakeLists.txt" ]; then
	log "CoACD src submodule uninitialized — running git submodule update --init --recursive"
	git -C "$SUBMODULE" submodule update --init --recursive third_party/CoACD/src
fi
if git -C "$COACD_SRC" apply --reverse --check "$COACD_PATCH" 2>/dev/null; then
	log "CoACD source fixes already applied — skipping patch"
elif git -C "$COACD_SRC" apply --check "$COACD_PATCH" 2>/dev/null; then
	git -C "$COACD_SRC" apply "$COACD_PATCH"
	log "CoACD source fixes applied"
else
	log "ERROR: CoACD source patch no longer applies cleanly (upstream drift)."
	log "Fix by hand and regenerate with:"
	log "  (cd Plugins/unreal-robotics-lab/third_party/CoACD/src && git diff > $COACD_PATCH)"
	exit 1
fi

# --- 3. build third-party dependencies (MuJoCo, CoACD, libzmq) ---
if [ "$BUILD_THIRDPARTY" = 1 ]; then
	log "building third-party dependencies (this can take a while on first run)..."
	# --no-submodule-sync: the default sync checks out each dep's pinned SHA,
	# which would DISCARD the CoACD source patch applied above.
	#
	# On Linux, --engine points the third-party builds at UE's bundled
	# clang/libc++ toolchain. Without it, system gcc/libstdc++ produces
	# ABI-incompatible .so files (undefined std::* symbols at editor startup).
	# macOS uses the system toolchain, matching what UBT does there.
	THIRDPARTY_ARGS=(--no-submodule-sync)
	if [ "$(uname -s)" = Linux ]; then
		THIRDPARTY_ARGS+=(--engine "$UE_ROOT")
	fi
	bash "$SUBMODULE/third_party/build_all.sh" "${THIRDPARTY_ARGS[@]}"
	log "third-party build finished"
fi

# --- 4. regenerate project files ---
if [ "$GEN_PROJECTFILES" = 1 ]; then
	case "$(uname -s)" in
		Darwin) GPF="$UE_ROOT/Engine/Build/BatchFiles/Mac/GenerateProjectFiles.sh" ;;
		Linux)  GPF="$UE_ROOT/Engine/Build/BatchFiles/Linux/GenerateProjectFiles.sh" ;;
		*) log "unsupported platform for project file generation — skip"; GPF="" ;;
	esac
	if [ -n "$GPF" ]; then
		if [ ! -f "$GPF" ]; then
			log "ERROR: engine not found at '$UE_ROOT' (set UE_ROOT to your UE install)"
			exit 1
		fi
		log "generating project files..."
		"$GPF" -project="$UPROJECT" -game
		log "project files generated"
	fi
fi

log "done. Build with:"
log "  \"$UE_ROOT/Engine/Build/BatchFiles/$( [ "$(uname -s)" = Darwin ] && echo Mac || echo Linux )/Build.sh\" RammsEditor $( [ "$(uname -s)" = Darwin ] && echo Mac || echo Linux ) Development -Project=\"$UPROJECT\""
