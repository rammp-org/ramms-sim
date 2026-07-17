# Cross-compiles URLab's third-party dependencies (MuJoCo, CoACD, libzmq)
# for LINUX from a WINDOWS machine, using the same UE Linux cross-toolchain
# that UBT uses for Windows->Linux game builds.
#
# Output goes to Plugins/unreal-robotics-lab/third_party/install-linux/ -
# deliberately separate from install/ (the Windows-native libs your local
# editor uses), because every dep build wipes its own install dir and the
# two platforms would otherwise clobber each other. URLab.Build.cs picks
# install-linux/ automatically when targeting Linux from a Windows host
# (part of Scripts/patches/unreal-robotics-lab-local-fixes.patch).
#
# Prerequisites:
#   - UE Linux cross-toolchain installed (the same one you already use for
#     Windows->Linux packaging); LINUX_MULTIARCH_ROOT must be set (the
#     toolchain installer sets it machine-wide).
#   - CMake 3.24+ and Ninja on PATH.
#   - Scripts/setup_urlab.sh's patches applied (run the setup once on this
#     checkout, or apply the two patch files with git apply) - the CoACD
#     source fixes are required to compile with clang 20.
#   - Submodules initialised (third_party/*/src checked out).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File Scripts\build_all_linux_cross.ps1
#
# NOTE: mirrors third_party/build_all.sh's `--engine` flags (libc++,
# -fuse-ld=lld, warning suppressions for TBB/OpenVDB under clang 20). This
# script never syncs submodules (equivalent of --no-submodule-sync) so it
# cannot discard the CoACD source patch.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$ThirdParty = Join-Path $RepoRoot "Plugins\unreal-robotics-lab\third_party"
$InstallRoot = Join-Path $ThirdParty "install-linux"
$BuildType = "Release"

function Log($msg) { Write-Host "[cross-thirdparty] $msg" -ForegroundColor Cyan }

# --- UE Linux cross-toolchain ---
$MultiArch = $env:LINUX_MULTIARCH_ROOT
if (-not $MultiArch) {
    throw "LINUX_MULTIARCH_ROOT is not set. Install the UE Linux cross-toolchain (same prerequisite as Windows->Linux packaging)."
}
$TC = Join-Path $MultiArch "x86_64-unknown-linux-gnu"
$Clang = Join-Path $TC "bin\clang.exe"
$ClangXX = Join-Path $TC "bin\clang++.exe"
if (-not (Test-Path $ClangXX)) {
    throw "Cross clang++ not found at $ClangXX - is the toolchain installed for x86_64?"
}
Log "toolchain: $TC"

if (-not (Get-Command ninja -ErrorAction SilentlyContinue)) {
    # Fall back to the ninja bundled with Visual Studio's CMake tools.
    $VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $VsNinja = $null
    if (Test-Path $VsWhere) {
        $VsRoot = & $VsWhere -latest -property installationPath 2>$null
        if ($VsRoot) {
            $Candidate = Join-Path $VsRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"
            if (Test-Path $Candidate) { $VsNinja = Split-Path -Parent $Candidate }
        }
    }
    if ($VsNinja) {
        Log "ninja not on PATH - using VS-bundled ninja from $VsNinja"
        $env:PATH = "$VsNinja;$env:PATH"
    } else {
        throw "ninja not found on PATH (required as the CMake generator for cross builds). Install ninja, or install VS's 'C++ CMake tools' component."
    }
}

# Mirror build_all.sh --engine flag choices (see its comments for rationale).
$Target = "x86_64-unknown-linux-gnu"
$CFlags = "--target=$Target --sysroot=$TC -fPIC -Qunused-arguments -Wno-unknown-warning-option"
$CxxFlags = "--target=$Target --sysroot=$TC -stdlib=libc++ -nostdinc++ -isystem `"$TC/include/c++/v1`" -fPIC -Qunused-arguments -Wno-unknown-warning-option -Wno-missing-template-arg-list-after-template-kw"
$LdFlags = "--target=$Target --sysroot=$TC -stdlib=libc++ -fuse-ld=lld -L`"$TC/lib64`" -Wl,-rpath,`"`$ORIGIN`""

$CommonCMake = @(
    "-G", "Ninja",
    "-DCMAKE_SYSTEM_NAME=Linux",
    "-DCMAKE_SYSTEM_PROCESSOR=x86_64",
    "-DCMAKE_C_COMPILER=$Clang",
    "-DCMAKE_CXX_COMPILER=$ClangXX",
    "-DCMAKE_AR=$(Join-Path $TC 'bin\llvm-ar.exe')",
    "-DCMAKE_RANLIB=$(Join-Path $TC 'bin\llvm-ranlib.exe')",
    "-DCMAKE_C_FLAGS=$CFlags",
    "-DCMAKE_CXX_FLAGS=$CxxFlags",
    "-DCMAKE_EXE_LINKER_FLAGS=$LdFlags",
    "-DCMAKE_SHARED_LINKER_FLAGS=$LdFlags",
    "-DCMAKE_BUILD_TYPE=$BuildType",
    # CMAKE_SYSROOT/FIND_ROOT_PATH make find_library() re-root /usr/lib64
    # etc. under the toolchain (ccd's find_library(m) fails without them --
    # the --sysroot compiler flag alone is invisible to CMake's search).
    "-DCMAKE_SYSROOT=$TC",
    "-DCMAKE_FIND_ROOT_PATH=$TC",
    "-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER",
    "-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY",
    "-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY"
)

function Build-Dep {
    param($Name, $SrcDir, $ExtraCMake, $BuildTargetArgs)

    $Src = Join-Path $ThirdParty "$SrcDir\src"
    if (-not (Test-Path (Join-Path $Src "CMakeLists.txt"))) {
        throw "$Name source not found at $Src - initialise submodules first (git submodule update --init --recursive)."
    }
    $Install = Join-Path $InstallRoot $Name
    if (Test-Path $Install) {
        Log "$Name - wiping previous install-linux artifacts"
        Remove-Item -Recurse -Force $Install
    }
    # Separate build dir from the native Windows build (src\build) so the
    # two configurations never share a CMake cache.
    $BuildDir = Join-Path $Src "build-linux-cross"
    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

    Log "$Name - configuring"
    & cmake -S $Src -B $BuildDir "-DCMAKE_INSTALL_PREFIX=$Install" @CommonCMake @ExtraCMake
    if ($LASTEXITCODE -ne 0) { throw "$Name configure failed" }

    Log "$Name - building"
    & cmake --build $BuildDir --config $BuildType @BuildTargetArgs
    if ($LASTEXITCODE -ne 0) { throw "$Name build failed" }

    Log "$Name - installing"
    & cmake --install $BuildDir --config $BuildType
    if ($LASTEXITCODE -ne 0) { throw "$Name install failed" }

    # Stamp the source SHA so URLab.Build.cs drift checks accept the install.
    $Sha = (& git -C $Src rev-parse HEAD).Trim()
    Set-Content -Path (Join-Path $Install "INSTALLED_SHA.txt") -Value $Sha
    Log "$Name - INSTALLED_SHA=$Sha"
}

# --- CoACD custom overlay (mirrors third_party/CoACD/build.sh) ---
$CoacdSrc = Join-Path $ThirdParty "CoACD\src"
$CoacdCustom = Join-Path $ThirdParty "CoACD_custom"
if (Test-Path $CoacdCustom) {
    Log "CoACD - applying custom configuration overlay"
    Copy-Item -Force (Join-Path $CoacdCustom "CMakeLists.txt") $CoacdSrc
    foreach ($sub in "cmake", "public") {
        $from = Join-Path $CoacdCustom $sub
        if (Test-Path $from) {
            $to = Join-Path $CoacdSrc $sub
            New-Item -ItemType Directory -Force -Path $to | Out-Null
            Copy-Item -Recurse -Force "$from\*" $to
        }
    }
}

Build-Dep -Name "CoACD" -SrcDir "CoACD" `
    -ExtraCMake @("-DWITH_3RD_PARTY_LIBS=ON", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5") `
    -BuildTargetArgs @("--target", "_coacd")

Build-Dep -Name "MuJoCo" -SrcDir "MuJoCo" `
    -ExtraCMake @("-DMUJOCO_BUILD_EXAMPLES=OFF", "-DMUJOCO_BUILD_TESTS=OFF", "-DMUJOCO_BUILD_SIMULATE=OFF") `
    -BuildTargetArgs @()

Build-Dep -Name "libzmq" -SrcDir "libzmq" `
    -ExtraCMake @("-DBUILD_STATIC=OFF", "-DBUILD_TESTS=OFF", "-DWITH_PERF_TOOL=OFF", "-DENABLE_DRAFTS=OFF") `
    -BuildTargetArgs @()

Log "done - Linux third-party artifacts in $InstallRoot"
