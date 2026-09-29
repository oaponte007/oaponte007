@echo off
REM Convenience launcher for Windows: run bin\chpc-bash-helper.bat directly
REM instead of typing `python -m chpc_bash_helper`. Copy chpc_bash_helper\
REM and its sibling chpc_helper_core\ folder into the same parent folder
REM and this works -- nothing to install (no pip, no network); requires
REM Python 3 from python.org.
REM
REM This still generates plain .sh (bash) files -- Windows can build them,
REM but you copy the resulting script to the actual Linux/airgapped box to
REM run it, since bash scripts don't execute natively on Windows.
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%..\..;%PYTHONPATH%"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m chpc_bash_helper %*
) else (
    python -m chpc_bash_helper %*
)
endlocal
