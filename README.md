# slurm-monitor

An autonomous monitoring/remediation agent for Slurm clusters.

It polls node health via `scontrol show node`, classifies the `Reason=`
Slurm gives for any DRAIN/DOWN state, tries a safe automated fix when one
exists, and — the core rule it was built around — **if the same node
reports the same problem again within a rolling 24-hour window, it stops
retrying and force-drains the node with a note explaining exactly why**,
so an admin doesn't get stuck babysitting an endless
`job → cleanup failure → drain → resume → job → drain` loop.

## How it decides what to do

For every node currently in a `DRAIN`/`DRAINED`/`DOWN`-like state:

1. **Classify** the `Reason=` text against the common-issue rule table in
   [`slurm_monitor/classifier.py`](slurm_monitor/classifier.py) (CPU
   topology mismatch, low `RealMemory`, not responding, kill-task-failed,
   prolog/epilog failure, unexpected reboot, GRES/GPU mismatch, GPU
   failure, filesystem problems, health-check drains, OOM, admin drains,
   or unknown). Add a line to that table to teach it a new failure mode —
   classification is just a prioritized regex list.
2. **Admin-initiated drains are left alone**, always.
3. If this exact `(node, category)` pair is already **quarantined** (the
   agent already force-drained it for this and nobody has resumed it
   since), it does nothing further and just reports `manual_review`.
4. Otherwise it checks history (SQLite, survives restarts): has this
   `(node, category)` pair fired within the trailing 24h?
   - **No (first sighting):** record it, run the read-only diagnostics for
     that category (`lscpu`, `slurmd -C`, `free -m`, `nvidia-smi`,
     `journalctl`, …), and if — and only if — the category is one of the
     small set considered safe to self-heal (currently: transient *not
     responding*, via `systemctl restart slurmd`; *kill task failed*, via
     `scontrol reconfigure`), attempt the fix and resume the node with a
     note describing what was done. Every hardware- or config-adjacent
     category (memory, CPU topology, GPU, filesystem, reboot, GRES, …) is
     deliberately **never** auto-resumed — the node is left exactly as
     Slurm left it, and a diagnostic report (probable cause + numbered
     recommended actions + confidence) is logged/notified for a human.
   - **Yes (recurrence):** force `State=DRAIN` with a
     `Reason=` note such as:

     ```
     AUTO-DRAIN by slurm-monitor: recurring 'Low RealMemory' detected 2x
     within 24h (first=2026-01-01T09:00:00Z latest=2026-01-01T14:00:00Z).
     Last raw reason: 'Low RealMemory'. Automated remediation suspended
     pending manual investigation; run `slurm-monitor diagnose node047`
     for details, then `scontrol update NodeName=node047 State=RESUME`
     once resolved.
     ```

     and quarantines the `(node, category)` pair so it won't be touched
     again until an admin resumes the node.
5. Once a node leaves the problem state (an admin resumed it), any
   quarantine on it is cleared — the next occurrence of that problem is
   treated as a fresh first sighting.

Nothing here is a black box: every decision is a plain
`Decision(node, category, action, note, occurrences_in_window)`, logged and
optionally pushed to a webhook.

## Safety model

- **`dry_run: true` by default.** State-changing `scontrol` commands are
  logged, not executed, until you flip it off in config.
- The only actions ever taken *without* a human are (a) resuming a node the
  agent just fixed itself for a known-transient issue, and (b)
  force-draining a node that has proven, by recurring, that whatever
  already happened to it did not actually fix it.
- Hardware-adjacent categories (GPU failure, unexpected reboot, CPU
  topology, `RealMemory` mismatch, filesystem, GRES mismatch) are never
  auto-fixed or auto-resumed — the agent only diagnoses and reports.
- Diagnostics are always read-only commands; the only mutating commands the
  agent ever issues are `systemctl restart slurmd`, `scontrol reconfigure`,
  `scontrol update ... State=RESUME`, and `scontrol update ... State=DRAIN`.

## Install

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for a full step-by-step guide
(prerequisites, permissions, dry-run rollout, systemd, operating it day to
day). Quick version:

```bash
pip install .
cp config/slurm_monitor.example.yaml /etc/slurm-monitor/slurm_monitor.yaml
# edit the copy: db_path, webhook_url, recurrence_threshold, etc.
```

Run once, safely, to see what it *would* do:

```bash
slurm-monitor --config /etc/slurm-monitor/slurm_monitor.yaml watch --once
```

Diagnose a single node on demand (read-only, works even with `dry_run`):

```bash
slurm-monitor diagnose node047
```

```
Node:        node047
State:       DRAINED
Reason:      Low RealMemory

Configured RealMemory exceeds the memory reported by slurmd. Configured=512000 MB vs detected=510842 MB.

Recommended Action
----------------------------------
1. Verify with: slurmd -C
2. Check physical memory: dmidecode --type memory
3. If hardware is healthy, lower RealMemory in slurm.conf (leave headroom, don't configure right up to the detected boundary).
4. scontrol reconfigure
5. Verify node health, then: scontrol update NodeName=<node> State=RESUME

Confidence: HIGH
Occurrences of this problem on this node in the last 24h: 1
```

List every node currently drained/down, with its classification and
24h occurrence count:

```bash
slurm-monitor status
```

Manually clear a quarantine (e.g. after fixing the underlying hardware
issue and resuming the node yourself):

```bash
slurm-monitor resolve node047 --category low_real_memory
```

Once you trust the dry-run decisions, install the systemd unit:

```bash
sudo cp systemd/slurm-monitor.service /etc/systemd/system/
sudo systemctl enable --now slurm-monitor
```

and set `dry_run: false` in config for it to actually act.

## Extending it

- New failure signature → add one `(regex, Category)` line to
  `classifier._RULES` and an entry in `classifier.CATEGORY_INFO`
  (title, whether it's `auto_fixable`, and which read-only commands to run).
- New diagnostic logic for a category → add a branch in
  `diagnostics._analyze`.
- New safe auto-fix → add a branch in `remediation.attempt_fix`, and flip
  `auto_fixable: True` for that category only once you're confident the fix
  is low-risk and reversible.

## Development

```bash
pip install -e . pytest
pytest
```
