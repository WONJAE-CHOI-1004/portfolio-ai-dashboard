@echo off
REM Price-target watch check for Windows Task Scheduler (daily/frequent).
REM ASCII only. No LLM; fast.
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
echo ==== price check %DATE% %TIME% ==== >> logs\price_check.log
py run_price_check.py >> logs\price_check.log 2>&1
endlocal
