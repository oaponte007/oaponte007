@echo off
REM Convenience launcher for Windows: run bin\chpc-python-helper.bat
REM directly instead of typing `python -m chpc_python_helper`. Copy the
REM whole chpc_python_helper\ folder (and its sibling chpc_helper_core\)
REM anywhere and this works -- nothing to install; requires Python 3
REM from python.org.
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%..\..;%PYTHONPATH%"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m chpc_python_helper %*
) else (
    python -m chpc_python_helper %*
)
endlocal
