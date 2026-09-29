@echo off
REM Builds a standalone Windows .exe (no Python install needed to run it)
REM from billing_app.py. Run this ON WINDOWS, with Python already
REM installed (python.org's installer includes Tkinter by default).

REM pywin32/pefile are only needed by pyinstaller's --version-file support
REM below, not by the app itself, so they're not in requirements.txt.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller pywin32 pefile

REM Decodes the docx template and the logo from their committed *.b64
REM form, then builds app_icon.ico from the logo (make_icon.py calls
REM decode_assets.py itself too, so this first call is really just for
REM the template -- harmless to call it explicitly either way).
python decode_assets.py
python make_icon.py

REM The logo (and therefore app_icon.ico) is optional cosmetic branding --
REM only pass --icon / bundle it if make_icon.py actually produced one.
set ICON_ARGS=
set LOGO_DATA_ARGS=
if exist app_icon.ico set ICON_ARGS=--icon app_icon.ico
if exist coastal_hpc_logo.png set LOGO_DATA_ARGS=--add-data "coastal_hpc_logo.png;."

pyinstaller --onefile --noconsole --name "Coastal HPC Billing Statement Builder" ^
    --version-file version_info.txt ^
    %ICON_ARGS% ^
    --add-data "Jo-Wayne_Billing_Statement_Template.docx;." ^
    %LOGO_DATA_ARGS% ^
    billing_app.py

echo.
echo Done. Find the .exe in the "dist" folder.
pause
