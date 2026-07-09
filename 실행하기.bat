@echo off
REM Launch the portfolio dashboard in the browser (Streamlit, port 8502).
cd /d "%~dp0"
echo Starting dashboard... a browser tab will open at http://localhost:8502
py -m streamlit run dashboard.py --server.port 8502
pause
