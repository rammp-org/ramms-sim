# Windows counterpart of Scripts/setup_urlab.sh (patch handling only). Unlike
# the .sh it does NOT build third-party deps or generate project files - on
# Windows those are separate scripts (third_party\build_all.ps1 for the native
# editor, Scripts\build_all_linux_cross.ps1 for the Linux cross route).
#
# Our URLab fixes now live on our FORK, not in a patch:
#   git@github.com:rammp-org/UnrealRoboticsLab  branch ramms/v0.6.0-beta
# The submodule pins that branch's tip, so `git submodule update --init` brings
# the fixes (install-linux/ ThirdPartyPath cross hunk, the -URLabCtrlPort/
# -URLabInfoPort legacy-subscriber overrides, and the macOS-only hunks) with
# no patch to apply. This script now only handles the one NESTED patch:
#   coacd-src-local-fixes.patch (nested submodule third_party/CoACD/src) -
#     required to compile CoACD with clang 20 (the UE Linux cross toolchain);
#     not needed for MSVC native builds but harmless. It cannot live on the
#     fork because we do not own CoACD's repo.
#
# Idempotent - safe to re-run any time.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File Scripts\setup_urlab.ps1 [-CheckOnly]
#
#   -CheckOnly   Verify the patches are applied; exit non-zero if any is
#                missing instead of applying it.

param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Submodule = Join-Path $RepoRoot "Plugins\unreal-robotics-lab"
$CoacdSrc = Join-Path $Submodule "third_party\CoACD\src"
$PatchDir = Join-Path $RepoRoot "Scripts\patches"

function Log($msg) { Write-Host "[setup_urlab] $msg" }

# Runs git capturing stderr without tripping $ErrorActionPreference=Stop
# (git writes benign warnings to stderr - e.g. exec-bit mode warnings on
# Windows - and PS 5.1 turns redirected native stderr into a terminating
# error under Stop).
function Invoke-Git([string[]]$GitArgs) {
    $Prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $Output = & git @GitArgs 2>&1 } finally { $ErrorActionPreference = $Prev }
    return [pscustomobject]@{ Code = $LASTEXITCODE; Output = $Output }
}

function Test-GitApply($RepoDir, $Patch, $Reverse) {
    $GitArgs = @("-C", $RepoDir, "apply", "--check")
    if ($Reverse) { $GitArgs += "--reverse" }
    $GitArgs += $Patch
    return ((Invoke-Git $GitArgs).Code -eq 0)
}

function Ensure-Patch($RepoDir, $PatchName) {
    $Patch = Join-Path $PatchDir $PatchName
    if (-not (Test-Path $Patch)) { throw "patch not found: $Patch" }

    if (Test-GitApply $RepoDir $Patch $true) {
        Log "$PatchName - already applied"
        return
    }
    if (Test-GitApply $RepoDir $Patch $false) {
        if ($CheckOnly) {
            throw "$PatchName is NOT applied in $RepoDir - run Scripts\setup_urlab.ps1 (without -CheckOnly) to apply it."
        }
        $R = Invoke-Git @("-C", $RepoDir, "apply", $Patch)
        if ($R.Code -ne 0) { $R.Output | Write-Host; throw "git apply failed for $PatchName" }
        Log "$PatchName - applied"
        return
    }
    throw ("$PatchName no longer applies cleanly to $RepoDir - upstream has drifted. " +
        "Apply the equivalent changes by hand (see the patch header comments) and regenerate with: " +
        "git -C `"$RepoDir`" diff > `"$Patch`"")
}

# --- 0. submodules present? ---
if (-not (Test-Path (Join-Path $Submodule "UnrealRoboticsLab.uplugin")) -and
    -not (Test-Path (Join-Path $Submodule "URLab.uplugin"))) {
    if ($CheckOnly) { throw "unreal-robotics-lab submodule looks uninitialized - run git submodule update --init" }
    Log "unreal-robotics-lab submodule uninitialized - running git submodule update --init"
    $R = Invoke-Git @("-C", $RepoRoot, "submodule", "update", "--init", "Plugins/unreal-robotics-lab")
    if ($R.Code -ne 0) { $R.Output | Write-Host; throw "git submodule update failed" }
}
if (-not (Test-Path (Join-Path $CoacdSrc "CMakeLists.txt"))) {
    if ($CheckOnly) { throw "CoACD src submodule looks uninitialized - run git submodule update --init --recursive" }
    Log "CoACD src submodule uninitialized - running git submodule update --init --recursive"
    $R = Invoke-Git @("-C", $Submodule, "submodule", "update", "--init", "--recursive", "third_party/CoACD/src")
    if ($R.Code -ne 0) { $R.Output | Write-Host; throw "git submodule update failed for CoACD src" }
}

# --- 1. plugin-repo fixes are committed on the fork branch, not patched ---
$R = Invoke-Git @("-C", $Submodule, "merge-base", "--is-ancestor", "41fd7cceda538039581f5ed48e88956171c5d753", "HEAD")
if ($R.Code -ne 0) {
    Log "WARN: submodule does not contain our fix commit 41fd7cc - is the URL the"
    Log "      rammp-org/UnrealRoboticsLab fork and the pin on ramms/v0.6.0-beta?"
    if ($CheckOnly) { throw "URLab submodule missing our fix commit" }
}

# --- 2. nested CoACD source patch (we do not own CoACD's repo) ---
Ensure-Patch $CoacdSrc "coacd-src-local-fixes.patch"

Log "done - CoACD nested patch present; URLab fixes come from the fork branch."
