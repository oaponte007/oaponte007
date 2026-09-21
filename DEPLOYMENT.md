# Deploying slurm-monitor on a real cluster

This walks through taking the agent from "code in a repo" to "running
safely against your Slurm cluster," end to end.

## 0. Prerequisites

- Python 3.9+ on whichever host will run the agent (the Slurm controller,
  or any host with `scontrol`/`sinfo` talking to it — e.g. a management
  node). It does **not** need to run on every compute node.
- Slurm client commands (`sinfo`, `scontrol`, `slurmd`) reachable from that
  host, and the host configured so those commands can talk to `slurmctld`
  (normal `slurm.conf`/`munge` setup — the same thing an admin's shell
  session needs).
- Permission to run `scontrol update NodeName=... State=DRAIN|RESUME`.
  Slurm gates this by `SlurmUser`/operator/admin level in `slurm.conf`'s
  `AllowedAuthenticator`/`SlurmUser` and the calling user's association
  privileges — in practice, run the agent as the `SlurmUser` (usually
  `slurm`) or a user granted `Operator`/`Administrator` level via
  `sacctmgr`. Running it as an unprivileged user will make every drain/
  resume attempt fail (harmlessly — it'll just log the error).
- If you want the agent to run the per-category diagnostic commands
  (`lscpu`, `slurmd -C`, `nvidia-smi`, `journalctl -u slurmd`, …) *on the
  affected compute node* rather than on the host the agent itself runs on,
  set up passwordless SSH (a dedicated key, restricted to running specific
  read-only commands via `authorized_keys` `command=` / a small allowlist
  wrapper) from the agent host to every compute node, and point
  `remote_exec` at it (see step 3). If you skip this, diagnostics still run
  — just from the agent's own host, which is enough for anything that only
  needs `scontrol`/`sinfo` (e.g. GRES/CfgTRES comparisons) but not for
  node-local checks like `nvidia-smi`.

## 1. Install the package

```bash
git clone <this-repo>
cd oaponte007
python3 -m venv /opt/slurm-monitor/venv
/opt/slurm-monitor/venv/bin/pip install .
```

This installs the `slurm-monitor` console script into the venv along with
its one dependency (PyYAML).

## 2. Create the state directory and config

```bash
sudo mkdir -p /etc/slurm-monitor /var/lib/slurm-monitor
sudo cp config/slurm_monitor.example.yaml /etc/slurm-monitor/slurm_monitor.yaml
sudo chown -R slurm:slurm /var/lib/slurm-monitor
```

Edit `/etc/slurm-monitor/slurm_monitor.yaml`:

- Leave `dry_run: true` for now — this is the whole point of the next step.
- Set `db_path: /var/lib/slurm-monitor/history.db`.
- Set `recurrence_window_hours`/`recurrence_threshold` if 24h/2 isn't right
  for your site (e.g. a noisier cluster might want threshold 3).
- Set `remote_exec` only if you did the SSH setup in step 0, e.g.:
  `remote_exec: "ssh -o BatchMode=yes -o ConnectTimeout=5 {node} -- {command}"`.
- Set `webhook_url` if you want Slack/Mattermost-style notifications on
  every force-drain and every "needs manual review" event. Leave it `null`
  otherwise — everything is logged either way.

## 3. Dry-run it against your real cluster

This is the important step: run the agent in read-only mode against
production for a while *before* letting it touch anything.

```bash
sudo -u slurm /opt/slurm-monitor/venv/bin/slurm-monitor \
    --config /etc/slurm-monitor/slurm_monitor.yaml watch --once
```

Run that by hand (or on a cron every few minutes) for a day or two. It
will print one line per node it would have acted on:

```
node047    low_real_memory    manual_review
node012    not_responding     resume
```

with the state-changing `scontrol update ...` commands it *would* have run
logged at `[dry-run] would run: ...` in its log output instead of executed.
Confirm:

- The classifications look right for the Reason= strings your cluster
  actually produces (`slurm-monitor status` shows the currently drained
  nodes with their classification).
- The recommended actions in `slurm-monitor diagnose <node>` for a real
  drained node make sense for your hardware/config.
- Nothing you'd consider "wrong" would have been auto-resumed — check the
  `resume` decisions particularly closely, since that's the one action
  that puts a node back into service unattended.

If a Reason= string on your cluster doesn't match any rule (shows up as
`unknown`), add a line to `classifier._RULES`/`CATEGORY_INFO` for it (see
"Extending it" in the README) and re-run.

## 4. Go live

Once you're comfortable with what it decided during the dry run:

```yaml
# /etc/slurm-monitor/slurm_monitor.yaml
dry_run: false
```

Install and start the systemd service:

```bash
sudo cp systemd/slurm-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now slurm-monitor
sudo systemctl status slurm-monitor
journalctl -u slurm-monitor -f
```

The unit runs `slurm-monitor watch` (the continuous poll loop, default
every 60s per `poll_interval`), as the `slurm` user, restarting on failure.

## 5. Operating it

- **Watch the logs** (`journalctl -u slurm-monitor`) or the webhook channel
  for `force_drain` and `manual_review` events — those are the ones that
  need a human. `resume` events are the agent successfully self-healing
  and need no action.
- **Review the audit trail periodically**, not just the live log stream.
  Every decision is persisted to `db_path` and queryable with
  `slurm-monitor log`/`slurm-monitor report` (see the README) even after
  the agent has restarted. A good habit is a weekly
  `slurm-monitor report --since 7d`, either run by hand or piped somewhere
  admins actually look:

  ```bash
  # weekly digest via cron, e.g. /etc/cron.d/slurm-monitor-report:
  0 8 * * 1 slurm /opt/slurm-monitor/venv/bin/slurm-monitor \
      --config /etc/slurm-monitor/slurm_monitor.yaml report --since 7d \
      | mail -s "slurm-monitor weekly report" hpc-admins@example.com
  ```

  The report's "flagged for manual review, by node/category" breakdown is
  the most useful part for finding the *harder* problems: a node/category
  pair that keeps showing up there — even if it never quite crosses the
  24h recurrence threshold into a force-drain — is exactly the kind of
  recurring-but-not-yet-automatic-drain pattern worth a human digging into
  before it does.
- **When a node gets auto-drained**, its `Reason=` field is the
  explanation (`scontrol show node <name>` or `sinfo -R` shows it
  directly) — no need to dig through logs to find out why. Investigate
  per the recommended actions in `slurm-monitor diagnose <node>`, fix the
  underlying issue, then `scontrol update NodeName=<node> State=RESUME`.
  That resume automatically clears the agent's quarantine on the node the
  next time it polls (no separate command needed) — though
  `slurm-monitor resolve <node>` exists if you ever need to clear a
  quarantine without resuming (e.g. you want the agent to try again before
  you've physically confirmed the fix).
- **Tune `recurrence_threshold`** per site: 2 (the default) means "stop
  retrying the second time this exact problem recurs within 24h." Raise it
  if your cluster has categories that legitimately need a couple of
  automated resume cycles before settling.
- **Back up `/var/lib/slurm-monitor/history.db`** if you care about
  historical occurrence data surviving a host rebuild — it's a plain
  SQLite file, `sqlite3 history.db ".dump"` works fine.

## 6. Rolling back

Stop the service and nothing further happens — no cleanup needed, since
the agent never modifies `slurm.conf` or holds any persistent lock on
nodes beyond the `Reason=` text and `State=` it already set via normal
`scontrol` commands, which any admin can override with their own
`scontrol update ... State=RESUME` at any time.

```bash
sudo systemctl disable --now slurm-monitor
```
