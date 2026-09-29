@echo off
REM Convenience launcher for Windows: run bin\chpc-bash-helper.bat directly
REM instead of typing `python -m chpc_bash_helper`. Copy the whole
REM chpc_bash_helper\ folder anywhere and this works -- nothing to install
REM (no pip, no network); requires Python 3 from python.org.
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
