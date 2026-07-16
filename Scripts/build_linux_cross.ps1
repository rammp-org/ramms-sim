# Builds and (optionally) packages RAMMS for LINUX from a WINDOWS machine
# using UE's Windows->Linux cross-compilation toolchain.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File Scripts\build_linux_cross.ps1 [-Package] [-Config Development|Shipping] [-Maps "Map_A+Map_B"]
#
# Environment:
#   UE_ROOT               UE 5.7 root (default: C:\Program Files\Epic Games\UE_5.7)
#   LINUX_MULTIARCH_ROOT  set by the UE Linux cross-toolchain installer
#
# Order of operations for a fresh checkout on Windows:
#   1. Apply URLab patches once:  (see Scripts/setup_urlab.sh header — on
#      Windows apply the three Scripts\patches\*.patch files with git apply
#      in the submodule roots, or run setup_urlab.sh from Git Bash/WSL with
#      --no-thirdparty --no-projectfiles)
#   2. Scripts\build_all_linux_cross.ps1   (Linux third-party -> install-linux/)
#   3. This script.
#
# The packaged output (Packaged\Linux) is what containers/ramms.def bundles —
# copy it to a Linux box / the cluster and run Scripts/run_headless.sh.

param(
    [switch]$Package,
    [string]$Config = "Development",
    [string]$Maps = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$UProject = Join-Path $RepoRoot "Ramms.uproject"
$UERoot = if ($env:UE_ROOT) { $env:UE_ROOT } else { "C:\Program Files\Epic Games\UE_5.7" }

function Log($msg) { Write-Host "[build_linux_cross] $msg" -ForegroundColor Cyan }

if (-not $env:LINUX_MULTIARCH_ROOT) {
    throw "LINUX_MULTIARCH_ROOT is not set — install the UE Linux cross-toolchain first."
}
$BuildBat = Join-Path $UERoot "Engine\Build\BatchFiles\Build.bat"
if (-not (Test-Path $BuildBat)) {
    throw "Engine not found at '$UERoot' (set UE_ROOT)."
}

$InstallLinux = Join-Path $RepoRoot "Plugins\unreal-robotics-lab\third_party\install-linux"
if (-not (Test-Path (Join-Path $InstallLinux "MuJoCo\INSTALLED_SHA.txt"))) {
    throw "Linux third-party artifacts missing ($InstallLinux) — run Scripts\build_all_linux_cross.ps1 first."
}

Log "building Ramms Linux $Config..."
& $BuildBat Ramms Linux $Config -Project="$UProject" -WaitMutex
if ($LASTEXITCODE -ne 0) { throw "Linux game build failed" }

if ($Package) {
    # Cooking runs the WINDOWS editor to cook content for the Linux target,
    # so the Windows editor must be buildable too (native third_party install/).
    $RunUAT = Join-Path $UERoot "Engine\Build\BatchFiles\RunUAT.bat"
    $UatArgs = @(
        "BuildCookRun",
        "-project=$UProject",
        "-platform=Linux",
        "-clientconfig=$Config",
        "-build", "-cook", "-stage", "-pak",
        "-archive", "-archivedirectory=$(Join-Path $RepoRoot 'Packaged')",
        "-unattended", "-noP4", "-utf8output"
    )
    if ($Maps) { $UatArgs += "-map=$Maps" }
    Log "packaging for Linux (config=$Config)..."
    & $RunUAT @UatArgs
    if ($LASTEXITCODE -ne 0) { throw "BuildCookRun failed" }
    Log "done — output in Packaged\Linux (deploy to cluster + containers/ramms.def)"
} else {
    Log "done (build only — pass -Package to cook/stage/pak)"
}
