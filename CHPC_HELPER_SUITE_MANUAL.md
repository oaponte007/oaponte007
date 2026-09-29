# CHPC_*_helper suite

Three tools that build scripts for you, on a machine with **no internet
access at all** — no cloud AI, no model, nothing beyond the Python 3
standard library:

| App | Generates | Syntax-checked with |
|---|---|---|
| `chpc_bash_helper` | bash scripts (`.sh`) | `bash -n` |
| `chpc_python_helper` | Python 3 scripts (`.py`) | `python3 -m py_compile` |
| `chpc_ansible_helper` | Ansible playbooks (`.yml`) | `ansible-playbook --syntax-check` (falls back to a plain YAML check, or skips, if Ansible isn't installed on the machine generating it) |

All three share the exact same mechanics (`chpc_helper_core/`) and the
exact same interface. You either:

- **pick a template and answer a short series of choices** (a node
  drain/resume script, a backup, a cron job, a retry wrapper, ...), or
- **describe what you want in plain English** and it matches your
  description against that app's template library by simple keyword
  overlap, and points you at the closest one to start from.

Either way you get a real, reviewable file — not something typed blind
into a chat window. Every template ships with tests that render it
under every choice it offers and syntax-check the result.

All three run anywhere Python 3 is installed — **Windows, RHEL, Rocky,
and Debian alike** — since nothing in any of the tools themselves is
platform-specific; only what they *generate* targets your Linux/Ansible
targets. The `chpc_bash_helper`/`chpc_python_helper` package_baseline
and firewall_baseline templates explicitly support both the RHEL/Rocky
(`dnf`/`yum`, `firewalld`) and Debian (`apt`, `ufw`) command sets;
`chpc_ansible_helper`'s versions auto-detect per target host from
Ansible facts, or shell out directly to the same commands — either way,
without needing any collection beyond bare `ansible-core`.

## Why not just ask an AI to write it?

Because the whole point is that this runs on a box with no network path
to any AI service. "Describe what you want" here is deliberately simple
keyword matching against a curated, reviewed library — deterministic,
auditable, and it never invents a command it doesn't actually have a
vetted template for. If it can't find a good match, it says so plainly
instead of guessing.

## Getting one onto the airgapped machine

Each app is **two folders**: its own (`chpc_bash_helper/`,
`chpc_python_helper/`, or `chpc_ansible_helper/`) plus the shared
`chpc_helper_core/` engine they all depend on. Copy the app you need
*and* `chpc_helper_core/` over as sibling directories (same parent
folder) — however you move files onto that box today. Nothing needs
`pip install`; everything imported is Python's standard library.

Each app's own folder carries its own docs, so once copied over you
don't need the rest of this repo:

- [`chpc_bash_helper/README.md`](chpc_bash_helper/README.md) /
  [`man/chpc-bash-helper.1`](chpc_bash_helper/man/chpc-bash-helper.1)
- [`chpc_python_helper/README.md`](chpc_python_helper/README.md) /
  [`man/chpc-python-helper.1`](chpc_python_helper/man/chpc-python-helper.1)
- [`chpc_ansible_helper/README.md`](chpc_ansible_helper/README.md) /
  [`man/chpc-ansible-helper.1`](chpc_ansible_helper/man/chpc-ansible-helper.1)

each with per-OS (RHEL/Rocky/Debian/Windows) install steps and a real
Unix man page (`man -l <path-to-the-.1-file>`, or install it
system-wide — see that app's README).

## Running one

The three apps only differ by package name and, for `build`, the file
extension. Substitute `chpc_bash_helper` / `chpc_python_helper` /
`chpc_ansible_helper` below for whichever you're using:

```bash
# from the folder containing both chpc_bash_helper/ and chpc_helper_core/:
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

Windows can run any of the three tools and generate the file (it's just
Python), but you'd then copy that file to the actual Linux/Ansible
target to run it — bash/Ansible don't execute natively on Windows, and
some `chpc_python_helper` templates use POSIX-only modules
(`fcntl`/`pwd`/`grp`) for the specific operations (locking, account
lookups) that inherently need them.

## The four commands (identical across all three apps)

### `list`

Every template in that app's library, with its description and tags.

### `show <template-id>`

What a specific template asks (its variables, yes/no toggles, and
multiple-choice groups), so you know what you're getting into before
running the wizard. Add `--raw` to see the actual unrendered template
text.

### `describe "<what you want>"`

Ranks every template by keyword overlap with your description against
its tags and title/description text, best match first, and tells you the
`build` command to run for the top one. Purely deterministic string
matching — see `chpc_helper_core/match.py`.

### `build <template-id>`

The wizard: asks every question the template declares, in order, shows
you a summary, and — once you confirm — writes the file and
syntax-checks it. Example (bash; python/ansible are the same shape):

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

## The template library (16 in each app)

The same 16 ideas, each expressed in the idiom of its own tool — a
retry loop is a hand-written `while` loop in bash/Python but
`until`/`retries`/`delay` in Ansible; a package install branches on
`dnf` vs `apt` in bash/Python but auto-detects per host from
`ansible_facts['os_family']` (or is one call to the generic `package`
module) in Ansible. "Same specs, different apps" means the same
*coverage*, adapted to what each tool actually does well — not a
line-for-line port.

**General dev/admin building blocks** (not HPC-specific — the "workaround"
patterns that get hand-written over and over):

| id | bash / python | ansible |
|---|---|---|
| `bash_skeleton` / `python_skeleton` / `ansible_skeleton` | new-script scaffold: usage/help, logging, error trap, optional `--dry-run` | play scaffold: hosts/become/tasks, optional handler example (Ansible's own `--check` flag is the built-in dry-run) |
| `retry_wrapper` | hand-written retry loop, fixed or exponential backoff | native `until`/`retries`/`delay` (fixed delay only — no native exponential backoff) |
| `wait_for_condition` | poll loop for a port/file/service/process, with timeout | native `wait_for` module for port/file; `until`/`retries` for service/process |
| `lockfile_singleton` | `flock`-guards a command so overlapping runs never execute at once | same, via an `flock`-wrapped task per target host |

**HPC / sysadmin operations**:

| id | what it builds |
|---|---|
| `node_drain_resume` | Drains/resumes node(s) via Slurm (`scontrol`) or PBS/PBS Pro (`pbsnodes`), with a reason and typed confirmation |
| `mount_validation` | Checks mounts are present, writable, and above a free-space threshold |
| `disk_cleanup` | Reports or deletes files older than N days matching a pattern |
| `log_archive` | Archives logs older than N days into a timestamped `.tar.gz`, optional deletion of originals |
| `user_provision` | Creates/updates a user account, optional group, optional SSH key install, optional password-login lock |
| `package_baseline` | Installs a package list from your already-configured repos (RHEL/Rocky and Debian) |
| `service_watchdog` | Checks a systemd service, restarts with backoff on failure, optional syslog alert |
| `rsync_backup` | `rsync`s sources into a dated backup directory, prunes by retention count |
| `cron_installer` | Installs a cron entry or a systemd timer+service pair |
| `host_key_sync` | Distributes `known_hosts` entries and/or an SSH public key across a node list/inventory |
| `firewall_baseline` | Opens a services/ports baseline (`firewalld`/`ufw`, RHEL/Rocky and Debian) |
| `diag_snapshot` | Bundles system info, `dmesg`, journal, disk/network/process state, and scheduler status into one tarball |

The Ansible versions fan out across your inventory (a `TARGET_HOSTS`
variable picks the host pattern/group) rather than looping over a
hosts file from one machine — that's Ansible's actual advantage over
the bash/Python versions, which run once from wherever the relevant
tool (scontrol, ssh, ...) is available.

Every one of these is a starting point, not a finished product for your
exact environment — the wizard adapts the template to *your* choices,
and the result is plain, readable code you're expected to read and
adjust further by hand if you need to. Every generated file says so in
its own header.

## Safety notes

- Destructive templates default to asking for explicit confirmation or
  default to the safe/reporting mode — check what a template defaults
  to with `show` before assuming.
- The syntax check only checks *syntax* (or, for Ansible with
  `ansible-playbook` available, module/argument shape too). It never
  executes anything, and it can't tell you whether the *logic* is right
  for your cluster — read the generated file before running it,
  especially anything that changes node state, deletes files, or
  touches accounts.
- Nothing here reaches the network on its own. `package_baseline`
  installs from *your* already-configured repos; it never tries to
  reach the public internet.

## Adding your own template

A template is two files sharing a name in that app's `library/`
directory:

- `<id>.json` — metadata: `id`, `title`, `description`, `tags`, and the
  questions to ask (`variables`, `toggles`, `toggle_groups`)
- `<id><ext>` (`.sh.tmpl` / `.py.tmpl` / `.yml.tmpl`) — the actual
  template text, with placeholders:
  - `{{VAR_NAME}}` — substituted with the variable's answer (no space
    inside the braces — this matters for Ansible, see below)
  - `{{#TOGGLE_NAME}} ... {{/TOGGLE_NAME}}` — kept if the toggle/toggle-group
    option is true, removed entirely (including the markers) if false;
    these can nest (e.g. a scheduler choice nested around an action choice)

A `toggle_group` is for a multiple-choice question where exactly one
option applies (scheduler, OS family, mode); each option maps to its own
plain toggle name that the template body checks with `{{#...}}`. A plain
`toggle` is a yes/no question standing on its own.

**The one rule every template must follow**: a `{{VAR_NAME}}`
placeholder must be the *entire* value of its key — never concatenated
with other literal text on the same line (`key: foo{{VAR}}` or
`key: {{VAR}} bar` are both wrong). Each app's `_prepare_variables`
turns a variable's raw text into a value that's only safe to use
*standalone* (Python's `repr()`, or JSON/YAML's `json.dumps()`) — it
can't protect a value some other text was glued onto. If you need to
combine a variable with other text, assign it once in a `vars:` block
(Python: a top-level `NAME = {{VAR}}`) and reference the *bare name*
everywhere else (Ansible: real Jinja2 `{{ bare_name }}`, always **with**
a space — that's what keeps it from colliding with this tool's own
no-space `{{VAR_NAME}}` syntax; Python: an f-string's single-brace
`{bare_name}`).

Drop the pair into `library/`, then run that app's test suite. Its
`test_library_syntax.py` renders the new template under every toggle
and toggle-group choice, using both the template's declared defaults
*and* an adversarial value (containing a colon, quotes, etc.) for every
string/path/choice variable, and syntax-checks every result — this is
what actually caught several placeholder-concatenation bugs (the exact
mistake described above) during development, across all three apps,
before they ever shipped. Don't skip the adversarial pass when adding a
template: it exercises a class of bug the default-values-only render
can miss entirely.

## Development

```bash
python3 -m pytest tests_chpc_bash_helper/
python3 -m pytest tests_chpc_python_helper/
python3 -m pytest tests_chpc_ansible_helper/
```

229 tests across the three apps: the shared templating engine, the
keyword matcher, the CLI and interactive wizard, and — the ones that
matter most — every template rendered under every choice (defaults and
adversarial values) and syntax-checked.
