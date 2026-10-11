@echo off
rem Double-click to open SortBuddy. The first run sets everything up (a few minutes).
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Setting up SortBuddy for the first time...
    py -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\pythonw.exe" (
        echo Could not create the Python environment. Is Python installed from python.org?
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install -e ".[ocr]"
    if errorlevel 1 (
        echo Install failed; see the messages above.
        pause
        exit /b 1
    )
)

start "" ".venv\Scripts\pythonw.exe" -m sortbuddy.gui
