@echo off
REM Builds chpc-sec-vuln-helper.exe -- a double-click menu (collect / update
REM feed / scan / list feeds) that needs no PowerShell or Python typing to
REM use afterwards. Run this ONCE, on a real Windows machine, from the
REM OUTER folder that contains the chpc_sec_vuln_helper folder (i.e. run
REM it as "chpc_sec_vuln_helper\build_windows_exe.bat" from one level up,
REM or just double-click it from inside this folder -- either works, it
REM finds its own location below).
REM
REM A working .exe can only be built on Windows itself -- there is no way
REM to cross-compile one from Linux or Mac, so this script has to be run
REM on the machine (or a machine like it) where the .exe will be used.
REM
REM Requirements (one-time): Python 3.9+ already installed, with internet
REM access to fetch two small packages. If this build machine is airgapped
REM too, run "pip download pyinstaller python-docx -d wheels\" on a
REM connected machine first, copy the wheels\ folder here, and change the
REM two "pip install" lines below to
REM "pip install --no-index --find-links wheels pyinstaller python-docx".

setlocal
cd /d "%~dp0.."

echo Installing build tools (pyinstaller) and the optional .docx report
echo library (python-docx) if not already present...
py -3 -m pip install --upgrade pyinstaller python-docx
if errorlevel 1 (
    echo.
    echo pip install failed -- see the error above. If this machine has no
    echo internet access, see the airgapped instructions in this file's
    echo header comment.
    exit /b 1
)

echo.
echo Building chpc-sec-vuln-helper.exe ...
py -3 -m PyInstaller --onefile --name chpc-sec-vuln-helper ^
    --add-data "chpc_sec_vuln_helper\collectors\windows_collector.ps1;chpc_sec_vuln_helper\collectors" ^
    chpc_sec_vuln_helper\windows_launcher.py

if errorlevel 1 (
    echo.
    echo Build failed -- see the error above.
    exit /b 1
)

echo.
echo Done. Your .exe is at: dist\chpc-sec-vuln-helper.exe
echo Copy that one file anywhere and double-click it -- no PowerShell or
echo Python needed to RUN it from then on (only to build it, just now).
endlocal
