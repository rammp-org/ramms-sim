#!/usr/bin/env bash
# Sets up the Plugins/unreal-robotics-lab submodule for building RAMMS on
# macOS/Linux: applies the local fixes the upstream plugin does not (yet)
# carry, builds its third-party dependencies, and regenerates project files.
#
# Idempotent — safe to re-run any time (e.g. after `git submodule update`,
# which discards the local fixes).
#
# Usage:
#   Scripts/setup_urlab.sh [--no-thirdparty] [--no-projectfiles]
#
# Environment:
#   UE_ROOT   Unreal Engine install root
#             (default: /Users/Shared/Epic Games/UE_5.7)
#
# What the patches contain:
# Scripts/patches/unreal-robotics-lab-local-fixes.patch (plugin repo):
#   - MsgpackHelpers.cpp: push/undef/pop the `nil` macro around rpclib includes
#     (Apple's MacTypes.h defines `nil`, breaking msgpack's `typedef nil_t nil`).
#   - URLab.Build.cs: Mac branch in AddThirdPartyLibrary — links the third-party
#     dylibs (MuJoCo/CoACD/libzmq); without it the plugin fails to link on Mac.
#   - URLab.Build.cs: ThirdPartyPath resolves to third_party/install-linux/
#     when cross-compiling Windows→Linux (artifacts from
#     Scripts/build_all_linux_cross.ps1 — see doc/PARALLEL_SIM_PLAN.md).
#   - third_party/CoACD/build.sh: CMAKE_POLICY_VERSION_MINIMUM=3.5 (CMake 4.x
#     compatibility) + executable bit.
#   - third_party/build_all.sh: executable bit.
# Scripts/patches/coacd-src-local-fixes.patch (NESTED submodule third_party/CoACD/src):
#   - CMakeLists.txt / cmake/openvdb.cmake / public/coacd.h: build + template
#     compile fixes for modern clang/CMake.
#
# NOTE: third-party builds run with --no-submodule-sync — the default sync
# checks out the pinned SHA and would discard the CoACD source patch.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUBMODULE="$REPO_ROOT/Plugins/unreal-robotics-lab"
PATCH="$REPO_ROOT/Scripts/patches/unreal-robotics-lab-local-fixes.patch"
COACD_SRC="$SUBMODULE/third_party/CoACD/src"
COACD_PATCH="$REPO_ROOT/Scripts/patches/coacd-src-local-fixes.patch"
UPROJECT="$REPO_ROOT/Ramms.uproject"
UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.7}"

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

# --- 1. apply local fixes (idempotent) ---
if git -C "$SUBMODULE" apply --reverse --check "$PATCH" 2>/dev/null; then
	log "local fixes already applied — skipping patch"
elif git -C "$SUBMODULE" apply --check "$PATCH" 2>/dev/null; then
	git -C "$SUBMODULE" apply "$PATCH"
	log "local fixes applied"
else
	log "ERROR: patch no longer applies cleanly — upstream has drifted."
	log "Apply the equivalent changes by hand (see the patch header comments in"
	log "$PATCH) and regenerate the patch with:"
	log "  (cd Plugins/unreal-robotics-lab && git diff > $PATCH)"
	exit 1
fi

# --- 1b. apply port-override patch (idempotent) ---
# Adds -URLabStepPort= / -URLabStatePort= / -URLabCtrlPort= / -URLabInfoPort= /
# -URLabCamPort= command-line switches so multiple sim instances can share a
# host (cluster / parallel training — see doc/PARALLEL_SIM_PLAN.md). Kept as
# a separate patch so it can be dropped once upstreamed.
PORTS_PATCH="$REPO_ROOT/Scripts/patches/urlab-port-overrides.patch"
if git -C "$SUBMODULE" apply --reverse --check "$PORTS_PATCH" 2>/dev/null; then
	log "port-override patch already applied — skipping"
elif git -C "$SUBMODULE" apply --check "$PORTS_PATCH" 2>/dev/null; then
	git -C "$SUBMODULE" apply "$PORTS_PATCH"
	log "port-override patch applied"
else
	log "ERROR: port-override patch no longer applies cleanly — upstream has drifted."
	log "Fix by hand and regenerate (see the header of $PORTS_PATCH)."
	exit 1
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
