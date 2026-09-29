# CHPC_bash_helper

A tool that builds bash scripts for you, on a machine with **no internet
access at all** — no cloud AI, no model, nothing beyond the Python 3
standard library. You either:

- **pick a template and answer a short series of choices** (a node
  drain/resume script, a backup, a cron job, a retry wrapper, ...), or
- **describe what you want in plain English** and it matches your
  description against the template library's tags/description by simple
  keyword overlap, and points you at the closest one to start from.

Either way you get a real, reviewable `.sh` file — not something typed
blind into a chat window. Every generated script is checked with `bash -n`
(a syntax-only parse, nothing is ever executed) before it's written, and
every template ships with tests that exercise every choice it offers.

It runs anywhere Python 3 is installed — **Windows, RHEL, Rocky, and
Debian alike** — since nothing in the tool itself is platform-specific;
only the *scripts it generates* are bash, meant to run on your Linux
targets. Two of the templates (`package_baseline`, `firewall_baseline`)
explicitly support both the RHEL/Rocky (`dnf`/`yum`, `firewalld`) and
Debian (`apt`, `ufw`) command sets, since you may be generating scripts
for either family.

## Why not just ask an AI to write it?

Because the whole point is that this runs on a box with no network path
to any AI service. "Describe what you want" here is deliberately simple
keyword matching against a curated, reviewed library — deterministic,
auditable, and it never invents a command it doesn't actually have a
vetted template for. If it can't find a good match, it says so plainly
instead of guessing.

## Getting it onto the airgapped machine

Copy the whole `chpc_bash_helper/` folder over (however you move files
onto that box today — that part is unchanged). Nothing needs `pip
install`; everything imported is Python's standard library.

The folder is self-contained and carries its own docs, so once it's
copied over you don't need the rest of this repo:
[`chpc_bash_helper/README.md`](chpc_bash_helper/README.md) has
per-OS (RHEL/Rocky/Debian/Windows) install steps, and
[`chpc_bash_helper/man/chpc-bash-helper.1`](chpc_bash_helper/man/chpc-bash-helper.1)
is a real Unix man page (`man -l chpc_bash_helper/man/chpc-bash-helper.1`,
or install it system-wide — see the README).

## Running it

```bash
# from the repo root, or anywhere chpc_bash_helper/ was copied to:
python3 -m chpc_bash_helper list
python3 -m chpc_bash_helper show node_drain_resume
python3 -m chpc_bash_helper describe "drain a node and note why"
python3 -m chpc_bash_helper build node_drain_resume
```

or, if you'd rather not remember the `-m` form:

```bash
./chpc_bash_helper/bin/chpc-bash-helper list          # Linux/macOS
chpc_bash_helper\bin\chpc-bash-helper.bat list         # Windows
```

Windows can run the tool and generate the `.sh` file (it's just Python),
but you'd then copy that file to the actual Linux/airgapped box to run
it — bash scripts don't execute natively on Windows.

## The four commands

### `list`

Every template in the library, with its description and tags.

### `show <template-id>`

What a specific template asks (its variables, yes/no toggles, and
multiple-choice groups), so you know what you're getting into before
running the wizard. Add `--raw` to see the actual unrendered template
text.

### `describe "<what you want>"`

Ranks every template by keyword overlap with your description against
its tags and title/description text, best match first, and tells you the
`build` command to run for the top one. Purely deterministic string
matching — see `chpc_bash_helper/match.py` if you want to see exactly how
a match scored the way it did.

### `build <template-id>`

The wizard: asks every question the template declares, in order, shows
you a summary, and — once you confirm — writes the script, makes it
executable, and runs `bash -n` on it. Example:

```
$ python3 -m chpc_bash_helper build node_drain_resume

=== Node Drain / Resume Wrapper (Slurm or PBS/PBS Pro) ===
Drains or resumes one or more compute nodes with a required reason, ...
(press Enter to accept the [default] shown, where there is one)

Node name(s), space-separated (e.g. node001 node002) [node001]: node042
Reason to record (used for drain; ignored for resume) [Scheduled maintenance]: Low RealMemory investigation
Require typed YES confirmation before acting? [Y/n]:
  1. Slurm (default)
  2. PBS / PBS Pro
Scheduler in use on this cluster [slurm]:
  1. drain (take offline) (default)
  2. resume (bring back online)
Action to perform [drain]:

--- about to write node_drain_resume.sh ---
Write this script now? [Y/n]: y
Wrote node_drain_resume.sh (executable, passed `bash -n` syntax check).
Review it before running -- especially anything that drains a node,
deletes files, or changes accounts -- it's your script now.
```

**Non-interactive build**, for repeatable generation or scripting the
tool itself — answer everything with flags instead of prompts:

```bash
python3 -m chpc_bash_helper build node_drain_resume \
    --var "NODE_LIST=node042" \
    --var "REASON=Low RealMemory investigation" \
    --toggle "REQUIRE_CONFIRMATION=off" \
    --toggle-group "SCHEDULER=slurm" \
    --toggle-group "ACTION=drain" \
    --out node042_drain.sh
```

- `--var NAME=VALUE` answers one variable (repeatable)
- `--toggle NAME=on|off` answers one yes/no toggle (repeatable)
- `--toggle-group NAME=VALUE` answers one multiple-choice group (repeatable)
- `--yes` with none of the above just takes every default, non-interactively
- anything you don't answer falls back to that question's declared default

## The template library

16 templates ship today, in `chpc_bash_helper/library/`:

**General dev/admin building blocks** (not HPC-specific — the "workaround"
patterns that get hand-written over and over):

| id | what it builds |
|---|---|
| `bash_skeleton` | A clean new-script starting point: usage/help, logging, an error trap that names the failing line, optional `--dry-run` |
| `retry_wrapper` | Retries any command with fixed or exponential backoff and a max-attempts cap |
| `wait_for_condition` | Polls until a port/file/service/process is ready, with a timeout |
| `lockfile_singleton` | `flock`-guards a command so two overlapping runs (e.g. cron) never execute at once |

**HPC / sysadmin operations**:

| id | what it builds |
|---|---|
| `node_drain_resume` | Drains/resumes node(s) via Slurm (`scontrol`) or PBS/PBS Pro (`pbsnodes`), with a reason and typed confirmation |
| `mount_validation` | Checks mounts are present, writable, and above a free-space threshold; health-check-friendly exit code |
| `disk_cleanup` | Reports or deletes files older than N days matching a pattern, under given directories |
| `log_archive` | Tars/gzips logs older than N days into a timestamped archive, with optional deletion of originals |
| `user_provision` | Creates/updates a user account, optional group, optional SSH key install, optional password-login lock |
| `package_baseline` | Installs a package list via `dnf`/`yum` (RHEL/Rocky) or `apt` (Debian) from your already-configured repos |
| `service_watchdog` | Checks a systemd service, restarts with backoff on failure, optional syslog alert if it never recovers |
| `rsync_backup` | `rsync`s sources into a dated backup directory, prunes old dated backups by retention count |
| `cron_installer` | Installs a crontab entry or a systemd timer+service pair for an existing script |
| `host_key_sync` | Distributes `known_hosts` entries and/or an SSH public key across a list of hosts |
| `firewall_baseline` | Opens a services/ports baseline via `firewalld` (RHEL/Rocky) or `ufw` (Debian) |
| `diag_snapshot` | Bundles system info, `dmesg`, journal, disk/network/process state, and scheduler status into one tarball |

Every one of these is a starting point, not a finished product for your
exact environment — that's the point of the wizard: it adapts the
template to *your* choices, and the result is plain, readable bash you're
expected to read and adjust further by hand if you need to. Every
generated script says so in its own header comment.

## Safety notes

- Destructive templates (`node_drain_resume`, `disk_cleanup` in delete
  mode) default to asking for explicit confirmation or default to the
  safe/reporting mode — check what a template defaults to with `show`
  before assuming.
- `bash -n` only checks *syntax*. It never executes anything, and it
  can't tell you whether the *logic* is right for your cluster — read
  the generated script before running it, especially anything that
  changes node state, deletes files, or touches accounts.
- Nothing here reaches the network on its own. `package_baseline`
  installs from *your* already-configured repos; it never tries to
  reach the public internet.

## Adding your own template

A template is just two files sharing a name in `chpc_bash_helper/library/`:

- `<id>.json` — metadata: `id`, `title`, `description`, `tags`, and the
  questions to ask (`variables`, `toggles`, `toggle_groups`)
- `<id>.sh.tmpl` — the actual bash text, with placeholders:
  - `{{VAR_NAME}}` — substituted with the variable's answer
  - `{{#TOGGLE_NAME}} ... {{/TOGGLE_NAME}}` — kept if the toggle/toggle-group
    option is true, removed entirely (including the markers) if false;
    these can nest (e.g. a scheduler choice nested around an action choice)

A `toggle_group` is for a multiple-choice question where exactly one
option applies (scheduler, OS family, mode); each option maps to its own
plain toggle name that the template body checks with `{{#...}}`. A plain
`toggle` is a yes/no question standing on its own.

Drop the pair into `library/`, then run the test suite — the most
important test (`tests_chpc_bash_helper/test_library_syntax.py`) renders
your new template with every toggle and toggle-group choice exercised at
least once and runs `bash -n` on each result, so a typo in one branch of
a new template fails the test suite instead of surfacing on a real node.

## Development

```bash
python3 -m pytest tests_chpc_bash_helper/
```

73 tests: the templating engine (`test_engine.py`), the keyword matcher
(`test_match.py`), the CLI and interactive wizard
(`test_cli.py`), and — the one that matters most —
every template rendered under every choice and syntax-checked
(`test_library_syntax.py`).

## Planned follow-ups

The same engine (templating + wizard + keyword matching) is meant to be
reused for a Python-script generator and an Ansible-playbook generator,
once this one's been used for a while and proven out. Not started yet.
