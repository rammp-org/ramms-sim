@echo off
rem Double-click to: close the editor, build, relaunch with Scripts\worldgen\verify.py.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify.ps1"
