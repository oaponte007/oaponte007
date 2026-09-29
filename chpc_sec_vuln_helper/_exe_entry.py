"""Entry point used only when freezing this package into a standalone
.exe with PyInstaller (see build_windows_exe.bat).

PyInstaller runs its target script as a bare top-level module
(__name__ == "__main__", no __package__), so pointing it directly at
windows_launcher.py would break its relative imports (`from . import
cli`) with "attempted relative import with no known parent package".
This tiny wrapper uses a plain absolute import instead, which works
both frozen and unfrozen, and is the only thing PyInstaller should be
told to build from.
"""
from chpc_sec_vuln_helper.windows_launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
