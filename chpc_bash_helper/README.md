# CHPC_bash_helper

Builds bash scripts on a machine with **no network access and no AI model
involved at all** — pick a template and answer a short series of choices,
or describe what you want in plain English and get matched to the
closest template. Everything here is Python 3 standard library, so
nothing needs installing to *run* this tool, on any of the platforms
below.

This file covers getting it installed and running. For the full command
reference, every template in the library, and how to add your own, see
[`../CHPC_BASH_HELPER_MANUAL.md`](../CHPC_BASH_HELPER_MANUAL.md). A Unix
man page also ships in [`man/chpc-bash-helper.1`](man/chpc-bash-helper.1)
(see **Man page**, below).

## Requirements

Just Python 3.9 or newer. Nothing else — no `pip install`, no
dependencies, and (once the folder is on the machine) no network access
needed to run it.

## Install

"Install" here just means: get the `chpc_bash_helper/` folder onto the
machine, however you normally move files onto it (copy, `scp`, USB
drive, internal file transfer for an airgapped box, etc.) — there's no
package to build or register.

### RHEL / Rocky Linux 8, 9, and 10

Python 3 ships by default on all three. Confirm it's there:

```bash
python3 --version
```

If it's somehow missing (a minimal/stripped install), pull it from your
existing repos:

```bash
sudo dnf install -y python3       # RHEL/Rocky 8 and 9
sudo dnf install -y python3       # RHEL/Rocky 10 (dnf5, same command)
```

Copy `chpc_bash_helper/` onto the machine, then either:

```bash
cd /path/containing/chpc_bash_helper
python3 -m chpc_bash_helper list
```

or make the launcher executable once and use it directly:

```bash
chmod +x chpc_bash_helper/bin/chpc-bash-helper
./chpc_bash_helper/bin/chpc-bash-helper list
```

Optionally install the man page system-wide (see **Man page** below).

### Debian

Most Debian installs already have Python 3. Confirm, and install it if
not:

```bash
python3 --version
# if missing:
sudo apt-get update && sudo apt-get install -y python3
```

(On a fully airgapped Debian box with no reachable mirror, install
`python3` from your local package mirror instead of `apt-get update`
against the internet — the tool itself needs no further packages either
way.)

Same as RHEL/Rocky from there:

```bash
cd /path/containing/chpc_bash_helper
python3 -m chpc_bash_helper list
# or:
chmod +x chpc_bash_helper/bin/chpc-bash-helper
./chpc_bash_helper/bin/chpc-bash-helper list
```

### Windows

Install Python 3 from [python.org](https://www.python.org/downloads/)
(check **"Add python.exe to PATH"** during setup) if it isn't already
installed. The Microsoft Store version of Python 3 also works.

Copy the `chpc_bash_helper` folder anywhere, then from a Command Prompt
or PowerShell in the folder that *contains* `chpc_bash_helper`:

```bat
python -m chpc_bash_helper list
```

or use the batch launcher directly:

```bat
chpc_bash_helper\bin\chpc-bash-helper.bat list
```

Windows can run this tool and generate `.sh` files just fine — it's
plain Python — but bash scripts don't execute natively on Windows, so
you'd copy the generated script over to the actual Linux/airgapped
target to run it. There's no man-page support on Windows; use this
README or the full manual instead.

## Quick start

```bash
python3 -m chpc_bash_helper list                              # see every template
python3 -m chpc_bash_helper describe "drain a node and note why"  # find the right one
python3 -m chpc_bash_helper build node_drain_resume            # build it, interactively
```

Non-interactive (every answer supplied on the command line, e.g. for a
repeatable/scripted run):

```bash
python3 -m chpc_bash_helper build node_drain_resume \
    --var "NODE_LIST=node042" \
    --toggle-group "SCHEDULER=slurm" \
    --toggle-group "ACTION=drain" \
    --out node042_drain.sh
```

Always read the generated script before running it — it's syntax-checked
(`bash -n`), not judgment-checked.

## Man page

A real Unix man page ships at `man/chpc-bash-helper.1` (RHEL, Rocky, and
Debian all have `man` available). View it without installing anything:

```bash
man -l chpc_bash_helper/man/chpc-bash-helper.1
```

or install it system-wide so plain `man chpc-bash-helper` finds it from
anywhere:

```bash
sudo mkdir -p /usr/local/share/man/man1
sudo cp chpc_bash_helper/man/chpc-bash-helper.1 /usr/local/share/man/man1/
sudo mandb        # Debian (man-db); on RHEL/Rocky this is usually automatic,
                   # or run: sudo /usr/bin/mandb
man chpc-bash-helper
```

(Not applicable on Windows — `man` doesn't exist there; use this README
or the full manual.)
