@echo off
title Optio - AI Entertainment Decision System
cd /d "%~dp0"

REM  Double-click this file. That is the whole instruction.
REM
REM  A .bat is used rather than the .ps1 directly because Windows opens
REM  .ps1 files in Notepad when you double-click them - it will not run
REM  them. This one hands off to PowerShell with the execution policy
REM  bypassed for this single call, which changes nothing system-wide.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Optio\run.ps1" -Open

echo.
echo  ============================================================
echo   Optio has stopped.
echo.
echo   If something went wrong, the message is above this line.
echo   Close this window when you have read it.
echo  ============================================================
echo.
pause
