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
echo Working directory: %CD%
echo (this should be the OUTER folder -- the one that CONTAINS a
echo  chpc_sec_vuln_helper folder, not the one you're inside of)
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: "py" was not found on PATH. Install Python 3 from
    echo python.org first ^(check "Add python.exe to PATH" during setup^),
    echo then re-run this script.
    goto :end
)

if not exist "chpc_sec_vuln_helper\windows_launcher.py" (
    echo ERROR: chpc_sec_vuln_helper\windows_launcher.py not found under
    echo %CD%
    echo This script must be run from where it sits, one level below the
    echo folder that contains chpc_sec_vuln_helper -- if you extracted a
    echo zip, check whether there's a second chpc_sec_vuln_helper folder
    echo nested one level deeper than expected.
    goto :end
)

echo Installing build tools (pyinstaller) and the optional .docx report
echo library (python-docx) if not already present...
py -3 -m pip install --upgrade pyinstaller python-docx
if errorlevel 1 (
    echo.
    echo pip install failed -- see the error above. If this machine has no
    echo internet access, see the airgapped instructions in this file's
    echo header comment.
    goto :end
)

echo.
echo Building chpc-sec-vuln-helper.exe ...
py -3 -m PyInstaller --onefile --name chpc-sec-vuln-helper ^
    --add-data "chpc_sec_vuln_helper\collectors\windows_collector.ps1;chpc_sec_vuln_helper\collectors" ^
    chpc_sec_vuln_helper\windows_launcher.py

if errorlevel 1 (
    echo.
    echo Build failed -- see the error above.
    goto :end
)

echo.
echo Done. Your .exe is at: %CD%\dist\chpc-sec-vuln-helper.exe
echo Copy that one file anywhere and double-click it -- no PowerShell or
echo Python needed to RUN it from then on ^(only to build it, just now^).

:end
echo.
pause
endlocal
