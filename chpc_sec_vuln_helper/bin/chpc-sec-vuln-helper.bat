@echo off
REM Convenience launcher for Windows. Copy the whole chpc_sec_vuln_helper\
REM folder anywhere -- this app is fully standalone (no chpc_helper_core
REM dependency, unlike the chpc-*-helper script generators).
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%..\..;%PYTHONPATH%"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m chpc_sec_vuln_helper %*
) else (
    python -m chpc_sec_vuln_helper %*
)
endlocal
