@echo off
REM Double-clickable launcher for NGFL Drafter.
REM PowerShell's default execution policy blocks .ps1 files on this machine,
REM so this wrapper bypasses it for this one script rather than weakening the
REM machine-wide policy.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
echo.
pause
