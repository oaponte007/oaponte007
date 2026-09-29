# CHPC_ansible_helper

Builds Ansible playbooks on a machine with **no network access and no
AI model involved at all** — pick a template and answer a short series
of choices, or describe what you want in plain English and get matched
to the closest template. The same tool as `chpc_bash_helper`/
`chpc_python_helper`, generating an Ansible playbook (YAML) instead.

Every template uses only `ansible.builtin` (ansible-core) modules —
**no extra collections needed**, since an airgapped controller can't
`ansible-galaxy install` anything it doesn't already have.

This file covers getting it installed and running. For the full command
reference, every template in the library, and how to add your own, see
[`../CHPC_HELPER_SUITE_MANUAL.md`](../CHPC_HELPER_SUITE_MANUAL.md). A
Unix man page also ships in
[`man/chpc-ansible-helper.1`](man/chpc-ansible-helper.1).

## Requirements

To **generate** playbooks: Python 3.9+ and the sibling `chpc_helper_core/`
folder — nothing else, no `pip install`, works on a box with no Ansible
installed at all.

To **run** the generated playbooks: `ansible-core` on whatever machine
acts as your controller (that's a separate, existing requirement of
using Ansible at all — this tool doesn't install Ansible for you).

## Install (the generator itself)

"Install" just means: get `chpc_ansible_helper/` **and** `chpc_helper_core/`
onto the machine, as sibling folders, however you normally move files
onto it.

### RHEL / Rocky Linux 8, 9, and 10

```bash
python3 --version
sudo dnf install -y python3   # if missing
```

```bash
cd /path/containing/both/folders
python3 -m chpc_ansible_helper list
# or:
chmod +x chpc_ansible_helper/bin/chpc-ansible-helper
./chpc_ansible_helper/bin/chpc-ansible-helper list
```

### Debian

```bash
python3 --version
sudo apt-get install -y python3   # if missing (use your local mirror if airgapped)
```

Same as RHEL/Rocky from there.

### Windows

Install Python 3 from [python.org](https://www.python.org/downloads/)
(check **"Add python.exe to PATH"**). Copy `chpc_ansible_helper` and
`chpc_helper_core` into the same folder, then:

```bat
python -m chpc_ansible_helper list
REM or:
chpc_ansible_helper\bin\chpc-ansible-helper.bat list
```

Windows can generate the `.yml` playbook fine (it's plain Python), but
you'd run it with `ansible-playbook` from wherever your actual Ansible
controller is — Ansible itself doesn't run on Windows. There's no
man-page support on Windows either; use this README or the full manual.

## Quick start

```bash
python3 -m chpc_ansible_helper list
python3 -m chpc_ansible_helper describe "install packages across my inventory"
python3 -m chpc_ansible_helper build package_baseline
```

Non-interactive:

```bash
python3 -m chpc_ansible_helper build node_drain_resume \
    --var "NODE_LIST=node042" \
    --toggle-group "SCHEDULER=slurm" \
    --toggle-group "ACTION=drain" \
    --out node042_drain.yml
```

Then, on your actual controller:

```bash
ansible-playbook node042_drain.yml
```

Every generated playbook is checked with `ansible-playbook --syntax-check`
if `ansible-core` is on the machine that built it, or falls back to a
plain YAML structural check (PyYAML, if installed) otherwise, or skips
gracefully with a note if neither is available — building a playbook
never requires Ansible to be installed on the machine doing the
generating. Always read the playbook before running it.

## Man page

```bash
man -l chpc_ansible_helper/man/chpc-ansible-helper.1
```

or install system-wide:

```bash
sudo mkdir -p /usr/local/share/man/man1
sudo cp chpc_ansible_helper/man/chpc-ansible-helper.1 /usr/local/share/man/man1/
sudo mandb   # Debian; usually automatic on RHEL/Rocky
man chpc-ansible-helper
```
