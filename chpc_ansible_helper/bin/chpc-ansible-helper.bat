@echo off
REM Convenience launcher for Windows: run bin\chpc-ansible-helper.bat
REM directly instead of typing `python -m chpc_ansible_helper`. Copy the
REM whole chpc_ansible_helper\ folder (and its sibling chpc_helper_core\)
REM anywhere and this works -- nothing to install; requires Python 3
REM from python.org. You'd still run the generated .yml with
REM ansible-playbook from wherever your Ansible controller actually is,
REM since Ansible itself doesn't run on Windows.
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%..\..;%PYTHONPATH%"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m chpc_ansible_helper %*
) else (
    python -m chpc_ansible_helper %*
)
endlocal
