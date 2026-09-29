# CHPC_python_helper

Builds Python 3 scripts on a machine with **no network access and no AI
model involved at all** — pick a template and answer a short series of
choices, or describe what you want in plain English and get matched to
the closest template. The same tool as `chpc_bash_helper`, generating
Python instead of bash.

This file covers getting it installed and running. For the full command
reference, every template in the library, and how to add your own, see
[`../CHPC_HELPER_SUITE_MANUAL.md`](../CHPC_HELPER_SUITE_MANUAL.md). A
Unix man page also ships in
[`man/chpc-python-helper.1`](man/chpc-python-helper.1).

## Requirements

Python 3.9 or newer, and its sibling folder `chpc_helper_core/` (the
shared engine both this and `chpc_bash_helper` build on) copied
alongside it. Nothing else — no `pip install`, no dependencies, and no
network access needed to run it.

## Install

"Install" here just means: get the `chpc_python_helper/` folder **and**
the `chpc_helper_core/` folder onto the machine, however you normally
move files onto it — there's no package to build or register.

### RHEL / Rocky Linux 8, 9, and 10

Python 3 ships by default. Confirm it, install if missing:

```bash
python3 --version
sudo dnf install -y python3   # if missing
```

Copy both `chpc_python_helper/` and `chpc_helper_core/` onto the
machine as siblings (same parent directory), then:

```bash
cd /path/containing/both/folders
python3 -m chpc_python_helper list
# or:
chmod +x chpc_python_helper/bin/chpc-python-helper
./chpc_python_helper/bin/chpc-python-helper list
```

### Debian

```bash
python3 --version
sudo apt-get install -y python3   # if missing (use your local mirror if airgapped)
```

Same as RHEL/Rocky from there — copy both folders as siblings, then
`python3 -m chpc_python_helper list` or the `bin/` launcher.

### Windows

Install Python 3 from [python.org](https://www.python.org/downloads/)
(check **"Add python.exe to PATH"**) if not already installed. Copy
`chpc_python_helper` and `chpc_helper_core` into the same folder, then:

```bat
python -m chpc_python_helper list
REM or:
chpc_python_helper\bin\chpc-python-helper.bat list
```

Windows can build the `.py` scripts fine (it's plain Python), but if
they're meant to run on RHEL/Rocky/Debian, copy the generated file over
to that target — some templates use POSIX-only modules (`fcntl`, `pwd`,
`grp`) that only work on Linux, matching what those specific operations
(file locking, user account lookups) need. There's no man-page support
on Windows; use this README or the full manual instead.

## Quick start

```bash
python3 -m chpc_python_helper list
python3 -m chpc_python_helper describe "drain a node and note why"
python3 -m chpc_python_helper build node_drain_resume
```

Non-interactive:

```bash
python3 -m chpc_python_helper build node_drain_resume \
    --var "NODE_LIST=node042" \
    --toggle-group "SCHEDULER=slurm" \
    --toggle-group "ACTION=drain" \
    --out node042_drain.py
```

Every generated script is checked with `python3 -m py_compile` before
being written — a syntax check only, nothing is ever executed. Always
read the script before running it.

## Man page

```bash
man -l chpc_python_helper/man/chpc-python-helper.1
```

or install system-wide:

```bash
sudo mkdir -p /usr/local/share/man/man1
sudo cp chpc_python_helper/man/chpc-python-helper.1 /usr/local/share/man/man1/
sudo mandb   # Debian; usually automatic on RHEL/Rocky
man chpc-python-helper
```
