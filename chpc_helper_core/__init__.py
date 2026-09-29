"""Shared engine for every chpc-*-helper app: templating (engine.py),
template-library loading (library.py), plain-English matching
(match.py), the interactive wizard (wizard.py), pluggable syntax
checkers (checks.py), and the generic CLI (cli.py). An app (bash,
python, ansible, ...) is just its own template library plus a couple of
lines of AppConfig wiring these together -- see any of
chpc_bash_helper/, chpc_python_helper/, chpc_ansible_helper/ for the
pattern.
"""

__version__ = "0.1.0"
