@echo off
REM Weekly headless portfolio analysis for Windows Task Scheduler.
REM ASCII only (cmd.exe cannot parse UTF-8 Korean comments reliably).
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== run start %DATE% %TIME% ==== >> logs\weekly.log
py run_weekly.py >> logs\weekly.log 2>&1
echo ==== run end   %DATE% %TIME% (exit %ERRORLEVEL%) ==== >> logs\weekly.log
endlocal
