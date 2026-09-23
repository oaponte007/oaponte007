# chpc Manual

**chpc** (Coastal HPC Node Health Checker) is a lightweight daemon that runs
on each compute node, checks it against a baseline captured at install time
plus whatever else you tell it to check, and drains the node through Slurm
or PBS/PBS Pro — with a reason and concrete recovery steps — when something
fails repeatedly. It is an improved, open replacement for LBNL's classic
Node Health Check (NHC): same idea (a checks file, a hostmask, an escape
hatch to run any shell command), plus an install-time baseline, a
consecutive-failure debounce, multi-scheduler support, and drain messages
that tell you what to do next instead of just what broke.

Target platforms: **RHEL / Rocky Linux 8, 9, and 10.** Compatibility notes
for each are called out throughout this manual, not just in one section,
since they affect installation, the systemd unit, and CPU pinning.

---

## Table of contents

1. [How it works](#1-how-it-works)
2. [OS compatibility: RHEL/Rocky 8, 9, 10](#2-os-compatibility-rhelrocky-8-9-10)
3. [Installation](#3-installation)
4. [The baseline](#4-the-baseline)
5. [The checks file (DSL reference)](#5-the-checks-file-dsl-reference)
6. [Builtin checks, one by one](#6-builtin-checks-one-by-one)
7. [Configuration reference (chpc.yaml)](#7-configuration-reference-chpcyaml)
8. [CLI reference](#8-cli-reference)
9. [How draining works (debounce, reasons, recovery)](#9-how-draining-works-debounce-reasons-recovery)
10. [Slurm and PBS/PBS Pro backends](#10-slurm-and-pbspbs-pro-backends)
11. [CPU pinning explained](#11-cpu-pinning-explained)
12. [systemd service](#12-systemd-service)
13. [Day-to-day operation](#13-day-to-day-operation)
14. [Extending chpc](#14-extending-chpc)
15. [Troubleshooting](#15-troubleshooting)
16. [Uninstalling](#16-uninstalling)

---

## 1. How it works

Each compute node runs its own `chpc` daemon, pinned to a single CPU core so
it never competes with job workloads. Every `check_interval` seconds it:

1. Asks the resource manager whether it currently considers this node
   drained/offline. If the RM says the node is healthy and chpc still has
   drains marked active locally, that means **an admin already fixed and
   resumed it manually** — chpc clears its own bookkeeping and starts
   fresh, rather than fighting the admin's decision.
2. Loads `checks.conf` and evaluates every line whose hostmask matches this
   node's hostname.
3. For each check: if it fails, bump a **consecutive-failure counter** for
   that exact check. Below the configured threshold, nothing else happens
   (this rides out a single transient blip). At or above the threshold, and
   only if this check isn't already marked as an active drain, chpc:
   - builds a short reason string and a longer set of recovery steps,
   - calls the resource-manager backend to drain the node with that reason,
   - writes the full recovery steps to the local log file,
   - marks that check "active" so it won't try to drain again every cycle.
4. If a check that was actively drained now passes again, chpc **does not
   resume the node on its own** unless you explicitly opted that exact
   check into `auto_resume_categories` in `chpc.yaml`. By default, a human
   always closes the loop — read the reason, run `chpc explain`, fix it,
   then `chpc resume`.

This mirrors real NHC's job (local, continuous, resource-manager-integrated
health checking) but adds: a captured baseline instead of hand-maintained
magic numbers, a debounce so one blip doesn't drain a node, PBS/PBS Pro
support alongside Slurm, and a reason message that always tells you what to
run next.

---

## 2. OS compatibility: RHEL/Rocky 8, 9, 10

chpc is pure Python + stdlib (plus PyYAML) and reads only stable, decades-old
Linux interfaces (`/proc/meminfo`, `/proc/mounts`, `/proc/<pid>/stat`,
`/sys/class/net`), so the checks themselves behave identically across all
three releases. The differences that *do* matter:

| Concern | RHEL/Rocky 8 | RHEL/Rocky 9 | RHEL/Rocky 10 |
|---|---|---|---|
| Default `/usr/bin/python3` | **3.6** — too old, dataclasses etc. need 3.7+ | 3.9 — sufficient | 3.12 (expected) — sufficient |
| What to install | `dnf install python3.9` (or `python3.11`) from AppStream, then use that interpreter explicitly | nothing extra | nothing extra |
| systemd version | 239 | 252 | newer |
| Default cgroup hierarchy | **v1** (legacy) unless you've set `systemd.unified_cgroup_hierarchy=1` | **v2** (unified) | v2 |
| `CPUAffinity=` (systemd unit) | supported (predates RHEL7) | supported | supported |
| `AllowedCPUs=` (systemd unit) | **not effective** — needs systemd ≥244 + cgroup v2 | works | works |
| SELinux | Enforcing by default | Enforcing by default | Enforcing by default |

Because of the cgroup v1/v2 split, **chpc does not rely on `AllowedCPUs=`**
for its "one CPU core" requirement. It pins itself in-process with
`os.sched_setaffinity()` — a kernel syscall, not a cgroup feature — which
behaves identically on all three releases regardless of systemd version or
cgroup hierarchy. `systemd/chpc.service` sets `CPUAffinity=` as a second,
independent, universally-supported layer. See [§11](#11-cpu-pinning-explained).

**SELinux:** chpc runs under the default `unconfined_service_t` context for
a hand-installed systemd unit, which can read `/proc`, `/sys/class/net`, and
execute `scontrol`/`pbsnodes`/`nvidia-smi` without any custom policy. If your
site runs a hardened/targeted policy that confines custom services, you may
need an `sepolicy generate`/`audit2allow` pass — this hasn't been tested
against such a policy.

**firewalld:** not applicable. chpc makes no inbound or outbound network
connections; it only runs local commands and reads local files.

**Slurm/PBS packages:** whatever version of Slurm or PBS Pro you've already
installed for the cluster. chpc's backends only depend on `scontrol`'s and
`pbsnodes`' command syntax, which is a property of the resource-manager
version, not the OS.

---

## 3. Installation

```bash
# RHEL/Rocky 8 only: get a modern Python first.
sudo dnf install python3.9
# RHEL/Rocky 9 and 10: system python3 is already sufficient, skip this.

git clone <this-repo>
cd oaponte007
python3.9 -m venv /opt/chpc/venv        # use python3 on RHEL9/10
/opt/chpc/venv/bin/pip install .

sudo mkdir -p /etc/chpc /var/lib/chpc /var/log/chpc
sudo cp config/chpc.example.yaml /etc/chpc/chpc.yaml
```

Edit `/etc/chpc/chpc.yaml` — at minimum decide `cpu_affinity` (which core)
and leave `dry_run: true` for the first pass. Then run install, which probes
this node and writes both the baseline and a starter checks file:

```bash
sudo /opt/chpc/venv/bin/chpc --config /etc/chpc/chpc.yaml install --core 0
```

```
captured baseline -> /etc/chpc/baseline.yaml
  cpu_count=64 real_memory_kb=263872000 gpu_count=4 mounts=3 interfaces=2
wrote starter checks file -> /etc/chpc/checks.conf

Detected resource manager: slurm
CPU pin: core(s) [0]

Next steps:
  1. Review/edit /etc/chpc/checks.conf
  2. Install the systemd unit: cp systemd/chpc.service /etc/systemd/system/
  3. sudo systemctl daemon-reload && sudo systemctl enable --now chpc
  4. Dry-run first: `chpc check` shows current results with no side effects.
```

Review `/etc/chpc/checks.conf` — `install` pre-fills GPU/mount checks if it
detected GPUs or non-pseudo mounts, but you should still edit the thresholds
to match your site. Then link `chpc` onto PATH and install the service:

```bash
sudo ln -s /opt/chpc/venv/bin/chpc /usr/local/bin/chpc
sudo cp systemd/chpc.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chpc
sudo systemctl status chpc
journalctl -u chpc -f
```

With `dry_run: true` (the default), chpc will log what it *would* run
without ever calling `scontrol`/`pbsnodes`. Watch it for a while, then flip
`dry_run: false` in `/etc/chpc/chpc.yaml` and `systemctl restart chpc` once
you trust its decisions.

**Provisioning at scale:** run the same steps via Ansible/Warewulf/whatever
you already use to configure compute nodes. `chpc install` is safe to run
identically on every node — it captures each node's *own* baseline, so a
shared playbook still produces a per-node-correct baseline file. Push the
same `checks.conf` everywhere; the hostmask column is exactly what lets one
shared file apply different lines to different node classes.

---

## 4. The baseline

`chpc install` (and `chpc baseline recapture`) probes the local node and
writes `baseline.yaml` (default `/etc/chpc/baseline.yaml`):

```yaml
cpu_count: 64
real_memory_kb: 263872000
gpu_count: 4
gpus:
  - "GPU 0: NVIDIA A100-SXM4-80GB (UUID: ...)"
  - "GPU 1: NVIDIA A100-SXM4-80GB (UUID: ...)"
  - ...
mounts:
  - {path: /scratch, fstype: nfs4}
  - {path: /home, fstype: nfs4}
interfaces: [eth0, ib0]
```

This is the "requirements set at the beginning of the install" — the
baseline-referencing checks (`check_real_memory`, `check_cpu_count`,
`check_gpu_count`) compare *live* state against these captured numbers, not
against a number someone typed into a config file by hand. If a check's
baseline field is missing (e.g. you delete `gpu_count` from the file, or
never ran `install`), that check reports **ok with a note**, never a
failure — a missing baseline is a setup gap, not evidence the node is sick,
and must never itself cause a drain.

**Recapture after a deliberate change** (RAM added, a GPU swapped, CPUs
reconfigured in the hypervisor):

```bash
chpc baseline recapture
chpc baseline show
```

`mounts` and `interfaces` are informational (used by `chpc install` to
pre-populate `checks.conf`) — `check_mount_present`/`check_network_interface`
take their expected path/interface as explicit `--path`/`--iface` flags in
checks.conf, not from the baseline, since which mounts/interfaces *should*
exist is a site policy decision, not something to silently freeze at
install time.

---

## 5. The checks file (DSL reference)

Default location: `/etc/chpc/checks.conf` (see
`config/chpc_checks.example.conf` for a full annotated starting point).

```
# comment
<hostmask> || <builtin_check_name> [--flag value ...]
<hostmask> || command || <any shell command line>
```

- **`hostmask`** is matched against the local hostname with shell-glob
  semantics (`fnmatch`), case-insensitively. `*` matches every host. This is
  what lets one `checks.conf`, pushed identically to every node, apply
  different lines to different node classes:

  ```
  *      || check_load_average --max-per-core 1.5
  gpu*   || check_gpu_count
  login* || check_mount_present --path /home --fstype nfs4
  ```

- **Builtin check lines** are `<name> --flag value --flag2 value2 ...`,
  parsed with `shlex` (so quoting works: `--path "/my mount"`).

- **The `command` form** is special: everything after the *second* `||` is
  taken verbatim as a shell command line and is never re-split — so the
  command itself may freely contain `||`, `&&`, or pipes:

  ```
  *  || command || test -f /scratch/.mounted && df -h /scratch
  *  || command || /usr/local/sbin/site_healthcheck.sh || echo "custom check failed"
  ```

  Exit code 0 is a pass; anything else is a fail, with stdout+stderr
  (truncated) captured as the failure detail.

- Lines starting with `#`, and blank lines, are ignored.

- A malformed line raises with the exact file and line number
  (`/etc/chpc/checks.conf:7: ...`) — `chpc check`/`chpc run` will report
  this as a single error action rather than silently skipping the rest of
  the file, so a typo doesn't quietly disable every check below it.

Every check line has a **stable identity** (`name:args`) used for debounce
counting and drain bookkeeping — editing a line's flags creates what chpc
treats as a *different* check (fresh debounce count), while re-ordering
lines or reloading the file does not reset an existing check's history.

---

## 6. Builtin checks, one by one

| Check | Flags | Compares against | Notes |
|---|---|---|---|
| `check_real_memory` | `--tolerance-percent N` (default 2) | baseline `real_memory_kb` | Reads `/proc/meminfo` `MemTotal`. Skips (ok) if no baseline. |
| `check_cpu_count` | `--tolerance N` (default 0) | baseline `cpu_count` | `os.cpu_count()`. Skips (ok) if no baseline. |
| `check_load_average` | `--max-per-core F` (default 1.5) | fixed ceiling | `os.getloadavg()[0] / cpu_count`. |
| `check_disk_usage` | `--path P` (default `/`), `--max-percent F` (default 90), `--max-inode-percent F` (optional) | fixed ceiling | `shutil.disk_usage`/`statvfs`. Reports the whole filesystem containing `path` — works identically for a dedicated mount or a plain directory. Repeat the line per mount/path you care about. The inode flag catches a full inode table (millions of small job files) even while byte usage looks fine. |
| `check_dir_size` | `--path P` (required); at least one of `--max-gb F`, `--max-percent F` (of the containing filesystem's total), `--max-files N`; `--max-scan N` (default 2,000,000), `--follow-symlinks` (flag) | fixed ceiling(s) | Walks the tree and sums real file sizes/counts — this is *the directory's own footprint*, not the filesystem's, so it isolates one directory growing on a shared filesystem. If the scan hits `--max-scan` before reaching a verdict it reports an inconclusive **pass** (never a false failure) — raise `--max-scan` or narrow `--path` for very large trees. |
| `check_swap_usage` | `--max-percent F` (default 50) | fixed ceiling | Passes automatically if no swap is configured. |
| `check_mount_present` | `--path P` (required), `--fstype T` (optional) | fixed requirement | Reads `/proc/mounts`. Existence only — pair with `check_disk_usage` on the same `--path` for capacity. |
| `check_zombie_processes` | `--max N` (default 5) | fixed ceiling | Scans `/proc/<pid>/stat` for state `Z`. |
| `check_gpu_count` | *(none)* | baseline `gpu_count` | Runs `nvidia-smi -L`. If `nvidia-smi` itself is missing and baseline expects 0 GPUs, that's a pass. Skips (ok) if no baseline. |
| `check_network_interface` | `--iface NAME` (required), `--allow-down` (flag) | fixed requirement | Reads `/sys/class/net/<iface>/operstate`; `--allow-down` checks only presence, not link state. |
| `command` | *(the raw shell command line)* | exit code | The escape hatch — anything you can script. |

All flags accept either `--flag value` or `--flag=value`.

**Draining on mount-point capacity, and on any directory:**

```
# A dedicated mount, existence + capacity + inodes:
*  || check_mount_present --path /scratch --fstype nfs
*  || check_disk_usage --path /scratch --max-percent 90 --max-inode-percent 85

# A plain directory that shares the root filesystem -- check_disk_usage
# works here too (it reports whatever filesystem the path lives on):
*  || check_disk_usage --path /var/spool/slurmd --max-percent 90

# One directory's OWN footprint, independent of the filesystem's overall
# fullness -- e.g. a single job/user scratch subdirectory that shouldn't
# be allowed to grow past a budget even if the shared filesystem it's on
# still has plenty of room overall:
*  || check_dir_size --path /scratch/jobtmp --max-gb 500
*  || check_dir_size --path /var/log --max-percent 20
```

Use `check_disk_usage` (cheap, `statvfs`-based) whenever "how full is this
filesystem" is the real question — that covers every dedicated mount case.
Reach for `check_dir_size` (a real tree walk, more I/O) only when you
specifically need "how big is *this one directory*," independent of
its filesystem's overall usage.

---

## 7. Configuration reference (chpc.yaml)

See `config/chpc.example.yaml` for the canonical, commented copy. Fields:

| Key | Default | Meaning |
|---|---|---|
| `dry_run` | `true` | Log, don't execute, every `scontrol`/`pbsnodes` mutating command. |
| `check_interval` | `60` | Seconds between evaluation cycles. |
| `failure_threshold` | `3` | Consecutive failed cycles before a drain fires. |
| `cpu_affinity` | `[0]` | Core(s) chpc pins itself to. Keep this to exactly one core on a compute node. |
| `resource_manager` | `auto` | `auto` \| `slurm` \| `pbs` \| `none`. Auto-detects via `scontrol`/`pbsnodes` on PATH. |
| `checks_file` | `/etc/chpc/checks.conf` | |
| `baseline_file` | `/etc/chpc/baseline.yaml` | |
| `state_db` | `/var/lib/chpc/state.db` | SQLite: debounce counters + active-drain bookkeeping. |
| `log_file` | `/var/log/chpc/chpc.log` | Full recovery instructions get appended here on every drain. |
| `log_level` | `INFO` | Standard Python logging level name. |
| `auto_resume_categories` | `[]` | Check names chpc may resume **without a human** once they pass again. Leave empty unless you're certain a flap on that specific check is safe to clear unattended. |
| `slurm_binary` | `scontrol` | |
| `pbs_binary` | `pbsnodes` | |
| `pbs_offline_flag` | `-o` | |
| `pbs_note_flag` | `-N` | |
| `pbs_clear_flag` | `-c` | |
| `command_timeout` | `20` | Seconds before a check's subprocess (nvidia-smi, a `command` check) is killed. |

Unknown keys in the YAML file are ignored (forward-compatible with future
versions), so a stray typo won't crash the daemon — but it also won't do
what you think, so double-check `chpc status`/`chpc check` after editing.

---

## 8. CLI reference

Every subcommand accepts `--config /path/to/chpc.yaml` before the
subcommand name: `chpc --config /etc/chpc/chpc.yaml <subcommand> ...`.
Omitting `--config` runs against hardcoded defaults (`/etc/chpc/...`,
`/var/lib/chpc/...`) — fine on the real node, but pass an explicit path
anywhere else (tests, a scratch directory) to avoid touching those paths.

### `chpc install`

Captures the baseline and writes a starter `checks.conf` if they don't
already exist.

```
chpc install [--core N] [--force] [--write-config PATH]
```

- `--core N` — pin to a specific core (default 0).
- `--force` — recapture the baseline / overwrite checks.conf even if they
  already exist. Without it, install is safe to re-run (a no-op on an
  already-installed node).

### `chpc check`

Pure preview: evaluates every check that matches this hostname, prints
pass/fail with detail, and **touches no state and drains nothing**. Exit
code 0 if everything passed, 1 otherwise — usable in a pre-flight script or
a cron sanity check independent of the daemon.

```
chpc check
```

### `chpc run`

The daemon loop — what the systemd unit executes. With no flags, pins the
configured core(s) and loops forever at `check_interval`. `--once` runs
exactly one real cycle (state updates and draining included) and exits —
useful for testing the real decision logic, or for running chpc from cron
instead of as a persistent service if you'd rather not have a long-running
daemon at all.

```
chpc run [--once] [--dry-run | --live]
```

`--dry-run`/`--live` override `dry_run` from the config file for this
invocation only.

### `chpc status`

Prints every check's last result, consecutive-failure streak, and whether
chpc currently considers it an active drain, plus a list of active drains
with their full reason string.

```
chpc status
```

### `chpc explain [check_name]`

Prints the full recovery instructions (the same text written to the log
file at drain time) for a named check, or — if you omit the name — for
every currently-active-drain or currently-failing check.

```
chpc explain check_real_memory
chpc explain          # everything currently failing/drained
```

### `chpc resume [check_name] [--node NAME] [--all]`

The human-in-the-loop action after you've fixed the underlying problem:
calls the resource-manager backend's resume/clear command, then clears
chpc's local bookkeeping for that check (or every check, with `--all`) so
its debounce counter starts fresh.

```
chpc resume check_real_memory
chpc resume --all
chpc resume check_gpu_count --node node047   # if node name != hostname
```

### `chpc baseline show|recapture`

```
chpc baseline show
chpc baseline recapture
```

---

## 9. How draining works (debounce, reasons, recovery)

**Debounce.** A single failed cycle never drains a node — `failure_threshold`
(default 3) consecutive failures are required. At the default 60s interval
that's ~3 minutes of confirmed failure, long enough to ride out one blip
(a momentary disk spike, an NFS server restart) without masking a real fault.

**The reason string** sent to the resource manager looks like:

```
[chpc] check_real_memory: Memory reported by the kernel no longer matches
the install-time baseline (3x consecutive). MemTotal=250000000kB
baseline=263872000kB diff=5.26% (tolerance 2.0%) Run `chpc explain
check_real_memory` on node047 for recovery steps.
```

— short enough for `sinfo -R`/`pbsnodes` to display usefully, but specific
enough (check name, measured vs. expected, occurrence count, and the exact
next command to run) that nobody has to guess what happened.

**Full recovery instructions** — a numbered list of concrete commands, per
check (see [§6](#6-builtin-checks-one-by-one) for which check maps to which
steps) — are written to `log_file` on every drain and available any time via
`chpc explain <check_name>`.

**No silent recovery.** Once you fix the issue, you close the loop yourself:

```bash
chpc explain check_real_memory     # re-read the steps if needed
# ... fix the actual problem ...
chpc resume check_real_memory      # calls scontrol/pbsnodes resume, clears chpc's counter
```

If you'd rather chpc auto-clear a *specific* check once it passes again —
appropriate only for something you're confident is safe to flap
unattended, like a mount that occasionally blips during a scheduled NFS
server restart — opt it in explicitly:

```yaml
auto_resume_categories: [check_mount_present]
```

Never add a hardware-adjacent check (`check_real_memory`, `check_cpu_count`,
`check_gpu_count`) to this list: a flapping value there is exactly the
signal a human should see before the node goes back into service.

**Reconciliation.** Every cycle, chpc also asks the backend whether the
node is *currently* drained. If the resource manager says no but chpc still
has active drains recorded, that means an admin already resumed the node
out-of-band — chpc clears its bookkeeping (all checks, debounce counts
included) rather than re-draining on the next failure using stale state.

---

## 10. Slurm and PBS/PBS Pro backends

Auto-detected via `resource_manager: auto` (checks for `scontrol` then
`pbsnodes` on PATH), or forced with `resource_manager: slurm|pbs|none`.

**Slurm** (`chpc/backends/slurm.py`) — standard, version-stable syntax:

```
scontrol update NodeName=<node> State=DRAIN Reason=<reason>
scontrol update NodeName=<node> State=RESUME
scontrol show node -o <node>              # used to check current state
```

**PBS / PBS Pro** (`chpc/backends/pbs.py`):

```
pbsnodes -o -N <reason> <node>            # drain (offline + note)
pbsnodes -c <node>                        # resume (clear offline)
pbsnodes <node>                           # used to check current state
```

> **Verify before production.** The `-o`/`-N`/`-c` flags are the common
> convention across OpenPBS, classic TORQUE/PBS, and PBS Pro, but this was
> written from documented behavior, not tested against a live PBS Pro
> install. Check `pbsnodes --help` / `man pbsnodes` on your actual PBS
> version before relying on this against production nodes. If your site
> differs, override the flags in `chpc.yaml` — they're passed as separate
> argv elements, never interpolated into a shell string, so there's no
> quoting hazard in overriding them:
>
> ```yaml
> pbs_binary: pbsnodes
> pbs_offline_flag: "-o"
> pbs_note_flag: "-N"
> pbs_clear_flag: "-c"
> ```

Both backends report `is_drained() -> None` (rather than guessing) when the
underlying command fails or its output doesn't parse — chpc treats "don't
know" as "don't reconcile," never as "assume healthy."

---

## 11. CPU pinning explained

The requirement was: chpc must never compete with job workloads for CPU.
Two layers enforce this, and only one of them is version-sensitive:

1. **`os.sched_setaffinity(0, cores)`**, called at daemon startup
   (`chpc/cpuaffinity.py`). This is a plain Linux syscall — it works
   identically on RHEL/Rocky 8, 9, and 10, independent of systemd version or
   cgroup hierarchy. Child processes chpc spawns (`nvidia-smi`, `scontrol`,
   `pbsnodes`, a `command` check's shell) inherit the same mask across
   fork/exec, so the *entire* daemon, checks included, stays on the
   configured core(s). If the requested core doesn't exist on this host,
   chpc falls back to the intersection with what's actually available and
   logs a warning rather than crashing.

2. **`CPUAffinity=0`** in `systemd/chpc.service` — a second, independent
   layer using the same syscall systemd-side. Supported since long before
   RHEL7, so it's safe to leave on for all three targets.

We deliberately do **not** rely on cgroup-based `AllowedCPUs=` as the
primary mechanism: it requires the unified (v2) cgroup hierarchy and
systemd ≥244, and RHEL/Rocky 8 ships systemd 239 on cgroup v1 by default —
`AllowedCPUs=` is simply ineffective there. If you're on RHEL/Rocky 9 or 10
*and* already running the unified hierarchy (`stat -fc %T /sys/fs/cgroup`
prints `cgroup2fs`), you can uncomment the `AllowedCPUs=0` line in the unit
file for a third, belt-and-suspenders layer — it changes nothing
functionally, since layers 1 and 2 already cover it.

---

## 12. systemd service

`systemd/chpc.service`:

```ini
[Service]
Type=simple
ExecStart=/usr/local/bin/chpc --config /etc/chpc/chpc.yaml run
Restart=on-failure
RestartSec=10
CPUAffinity=0
Nice=10
StateDirectory=chpc
LogsDirectory=chpc
NoNewPrivileges=true
```

- `CPUAffinity=0` — see [§11](#11-cpu-pinning-explained). Match this to
  whatever core `cpu_affinity` in `chpc.yaml` names.
- `Nice=10` — lets anything else on that core preempt chpc; it's a health
  checker, not a latency-sensitive service.
- `StateDirectory=chpc` / `LogsDirectory=chpc` — systemd creates and manages
  `/var/lib/chpc` and `/var/log/chpc` with correct ownership; no manual
  `mkdir`/`chown` needed for those two paths.
- `NoNewPrivileges=true` — chpc never needs privilege escalation.

Install and manage it the normal way:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chpc
sudo systemctl status chpc
journalctl -u chpc -f
```

`checks.conf` is reloaded from disk every cycle, so editing it takes effect
on the next `check_interval` tick with no restart. `chpc.yaml` is only read
at process start, so changing it does need `systemctl restart chpc`.

---

## 13. Day-to-day operation

- **New drain notification:** however you already watch Slurm/PBS state
  (sinfo/pbsnodes dashboards, alerting on state changes) will show it —
  chpc doesn't add a separate notification channel by design; the
  resource manager's own reason field *is* the notification, and it's
  self-explanatory (see [§9](#9-how-draining-works-debounce-reasons-recovery)).
- **On any node reported drained by chpc:** `ssh <node> chpc explain
  <check_name>` for the full recovery steps (or read `/var/log/chpc/chpc.log`
  on that node directly).
- **After fixing it:** `ssh <node> chpc resume <check_name>` (or `--all`).
- **Weekly/periodic review:** `chpc status` on any node shows its recent
  streaks even for checks that never crossed the drain threshold — a check
  that's failed 2 out of every 3 cycles for a week (never quite hitting
  `failure_threshold`) is worth investigating before it does.
- **Hardware change (RAM/GPU/CPU):** `chpc baseline recapture` on that node
  after the change, not before — you want the *old* baseline to catch the
  problem if the change goes wrong mid-maintenance.
- **Rolling out a new check across the fleet:** edit one line in the shared
  `checks.conf`, push it (Ansible/Puppet/whatever), done — no restart needed.

---

## 14. Extending chpc

**Easiest: use the `command` escape hatch.** Any script that exits 0/non-0
is a check — no code changes:

```
*  || command || /usr/local/sbin/my_custom_check.sh
```

**Adding a real builtin check** (when you want it to compare against the
baseline, or you want it to show up with a friendly name in `chpc status`):

1. Write a function in `chpc/checks/builtin.py`:
   `def check_my_thing(args, ctx) -> CheckResult`.
2. Register it in `BUILTIN_CHECKS` at the bottom of that file.
3. Add an entry to `RECOVERY_INFO` in `chpc/recovery.py` (title + ordered
   recovery steps) — this is what makes its drain reason self-explanatory
   instead of falling back to the generic "unrecognized check" text.
4. If it should reference the install-time baseline, add the field to
   `chpc/baseline.py`'s `capture()` and read it back via `ctx.baseline.get(...)`.

Every builtin check takes a `CheckContext` with injectable paths/runners
specifically so it's unit-testable without touching the real `/proc`,
`/sys`, or spawning real subprocesses — follow that pattern (see
`tests_chpc/test_builtin_checks.py` for examples) rather than calling
`subprocess`/reading `/proc` directly inside the function body.

---

## 15. Troubleshooting

**`chpc check` says every baseline-referenced check is "skipped, not
captured"** — you haven't run `chpc install`/`chpc baseline recapture` yet,
or `baseline_file` in `chpc.yaml` points somewhere that doesn't exist.

**A check keeps failing right at the threshold, then clearing, over and
over** — that's real flapping, not a debounce bug. Either fix the
underlying instability, or raise `failure_threshold` if the check itself
is just too sensitive (e.g. `check_load_average`'s ceiling is too tight for
real job load).

**`chpc resume` says the backend command failed** — check that the daemon's
user can run `scontrol`/`pbsnodes` at all (munge auth, PBS client config),
independent of chpc: `sudo -u <chpc's user> scontrol show node $(hostname)`
should work first.

**Drains aren't happening even though `chpc check` shows failures** — check
`dry_run` in `chpc.yaml`; while true, every mutating command is logged, not
executed (`journalctl -u chpc` will show `[dry-run] would run: ...` lines).

**On RHEL8 specifically:** if `chpc` itself won't start via systemd, check
which Python the shebang in `/opt/chpc/venv/bin/chpc` points at — it must be
the 3.9+ interpreter you installed from AppStream, not the system 3.6
`/usr/bin/python3`.

---

## 16. Uninstalling

```bash
sudo systemctl disable --now chpc
sudo rm /etc/systemd/system/chpc.service
sudo systemctl daemon-reload
```

chpc never modifies `slurm.conf`/PBS server config and holds no lock beyond
the ordinary `State=`/`Reason=` it already set via normal `scontrol`/
`pbsnodes` commands — any admin can override that with their own resume
command at any time, with or without chpc still installed. Removing
`/etc/chpc`, `/var/lib/chpc`, and `/var/log/chpc` is optional cleanup, not
required for a safe uninstall.
