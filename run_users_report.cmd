@echo off
REM Per-user personalized reports for Windows Task Scheduler (weekly).
REM ASCII only.
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== users report %DATE% %TIME% ==== >> logs\users_report.log
py run_users_report.py >> logs\users_report.log 2>&1
echo ==== end %DATE% %TIME% (exit %ERRORLEVEL%) ==== >> logs\users_report.log
endlocal
