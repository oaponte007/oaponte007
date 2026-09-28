@echo off
REM Builds a standalone Windows .exe (no Python install needed to run it)
REM from billing_app.py. Run this ON WINDOWS, with Python already
REM installed (python.org's installer includes Tkinter by default).

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

pyinstaller --onefile --noconsole --name "Coastal HPC Billing Statement Builder" ^
    --add-data "Jo-Wayne_Billing_Statement_Template.docx;." ^
    billing_app.py

echo.
echo Done. Find the .exe in the "dist" folder.
pause
