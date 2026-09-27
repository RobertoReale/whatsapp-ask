@echo off
rem Double-click to start WhatsApp Ask: it opens in your browser. Close this window to stop it.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo The .venv folder is missing. Open a terminal in this folder and run once:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run app.py
pause
