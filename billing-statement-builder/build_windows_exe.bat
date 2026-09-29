@echo off
REM Builds a standalone Windows .exe (no Python install needed to run it)
REM from billing_app.py. Run this ON WINDOWS, with Python already
REM installed (python.org's installer includes Tkinter by default).

REM pywin32/pefile are only needed by pyinstaller's --version-file support
REM below, not by the app itself, so they're not in requirements.txt.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller pywin32 pefile

pyinstaller --onefile --noconsole --name "Coastal HPC Billing Statement Builder" ^
    --version-file version_info.txt ^
    --add-data "Jo-Wayne_Billing_Statement_Template.docx;." ^
    billing_app.py

echo.
echo Done. Find the .exe in the "dist" folder.
pause
