# Close the editor, build RammsEditor, relaunch the editor running Scripts/worldgen/verify.py.
# Progress: Saved\WorldGen\build.log, verify_progress.log, verify_report.json
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$UE = "C:\Program Files\Epic Games\UE_5.8"
$Out = Join-Path $Root "Saved\WorldGen"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
Start-Transcript -Path (Join-Path $Out "verify.ps1.log") -Force | Out-Null
"root=$Root"

# 1. close the editor (graceful first, then force)
$procs = Get-Process -Name "UnrealEditor*" -ErrorAction SilentlyContinue
if ($procs) {
    "closing editor: $($procs.Id -join ', ')"
    $procs | ForEach-Object { $_.CloseMainWindow() | Out-Null }
    Start-Sleep -Seconds 15
    $procs = Get-Process -Name "UnrealEditor*" -ErrorAction SilentlyContinue
    if ($procs) { "forcing"; $procs | Stop-Process -Force; Start-Sleep -Seconds 5 }
} else { "editor not running" }

# 1b. a force-closed editor leaves auto-save restore data behind, and the next launch blocks on a
#     modal "Restore Packages" dialog before running anything; the generated maps are rebuilt anyway.
$restore = Join-Path $Root "Saved\Autosaves\PackageRestoreData.json"
if (Test-Path $restore) { "dropping auto-save restore prompt"; Remove-Item -Force $restore }

# 2. build
"building..."
$buildLog = Join-Path $Out "build.log"
& "$UE\Engine\Build\BatchFiles\Build.bat" RammsEditor Win64 Development -Project="$Root\Ramms.uproject" -WaitMutex 2>&1 | Tee-Object -FilePath $buildLog
$code = $LASTEXITCODE
"build exit code: $code"
Set-Content -Path (Join-Path $Out "build.exitcode") -Value $code
if ($code -ne 0) { "BUILD FAILED - not launching the editor"; Stop-Transcript | Out-Null; exit $code }

# 3. relaunch with the verification script
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Out "verify_report.json"), (Join-Path $Out "verify_progress.log")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Root "Content\Maps\Gen\Map_Gen_*.umap")
$script = Join-Path $Root "Scripts\worldgen\verify.py"
"launching editor with $script"
# Keep rendering at full rate when the editor is not the foreground window, so screenshots taken by the
# verification scripts are not starved (command-line ini override; applies to this session only).
$noThrottle = "-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.EditorPerformanceSettings]:bThrottleCPUWhenNotForeground=False"
Start-Process -FilePath "$UE\Engine\Binaries\Win64\UnrealEditor.exe" -ArgumentList @("`"$Root\Ramms.uproject`"", "-ExecCmds=`"py $script`"", $noThrottle)
"launched"
# The editor restores its last window placement, which can be off-screen (a monitor that is no longer
# attached). An off-screen window never renders, so screenshots and scene captures come back black.
# Wait for the main window, then put it on the primary display.
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class Win32 {
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
"@
$deadline = (Get-Date).AddMinutes(4)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $p = Get-Process -Name "UnrealEditor" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like "*Ramms*" } | Select-Object -First 1
    if ($p -and $p.MainWindowHandle -ne 0) {
        [Win32]::ShowWindow($p.MainWindowHandle, 9) | Out-Null            # SW_RESTORE
        [Win32]::SetWindowPos($p.MainWindowHandle, [IntPtr]::Zero, 40, 40, 1800, 1000, 0x0040) | Out-Null  # SWP_SHOWWINDOW
        [Win32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
        "moved editor window '$($p.MainWindowTitle)' on-screen"
        break
    }
}
Stop-Transcript | Out-Null
