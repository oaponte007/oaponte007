# Jacamar CI setup

[`jacamar/install_jacamar_ci.sh`](jacamar/install_jacamar_ci.sh) installs and
configures [Jacamar CI](https://gitlab.com/ecp-ci/jacamar-ci) — the
HPC-focused GitLab custom-executor driver — on top of GitLab Runner,
targeting RHEL/Rocky Linux 8, 9, and 10. It asks for everything site-specific
(GitLab URL and runner token, which scheduler backend, downscoping
mechanism, paths), then does the install for you.

## Read this first: what's verified vs. what to double-check

Jacamar CI's own documentation site, `ecp-ci.gitlab.io`, was unreachable
from the environment this script was written in (blocked by network egress
policy), so it was written from what's corroborated across multiple
independent sources (search results referencing the official docs, the
project's Go package listing, and third-party institutional setup guides)
rather than a direct read of the current docs page. Before running this
against a production cluster:

1. **Read the actual current docs** at the Jacamar CI documentation site (or
   your local mirror/cache of it) and diff them against what this script
   does, especially:
   - The exact `jacamar.toml` keys for your Jacamar CI *version* — this
     script writes only the keys confirmed across sources
     (`[general] executor`, `data_dir`, `limit_build_dir`;
     `[auth] downscope`; `[auth.logging] location`/`level`). Anything
     site-specific beyond that (per-partition Slurm settings, named
     "environments," project-level overrides) is **not** guessed at here —
     add those yourself once you've confirmed the current key names.
   - Whether the binary your build produces is named `jacamar-auth` (what
     every source referenced here shows) or something else — the script
     checks for both `jacamar-auth` and a fallback `jacamar` and tells you
     which it found.
2. **The `sudo` and `setuid` downscoping mechanisms are what's clearly
   documented**; `none` is for single-user/test use only. If your site has
   its own hardened variant of either, adapt `configure_downscope()`
   accordingly rather than assuming this script's defaults match.
3. **Slurm/Flux client setup is out of scope.** This script only checks
   that `sbatch`/`srun` (or `flux`) are on `PATH` and warns if not — it does
   not install or configure the scheduler client itself. That's the same
   cluster access your other job-submitting users already have.

Running with `--dry-run` first (see below) costs nothing and lets you
review every command and every file it would write before it touches a
real system.

## What it does, in order

1. Installs OS packages: `git`, `golang`, `gcc`, `make`, `libcap`, `curl`,
   `tar`, `policycoreutils-python-utils`.
2. Installs GitLab Runner from the official package repository
   (`packages.gitlab.com/runner/gitlab-runner`) if not already present.
3. Builds `jacamar-auth` from source
   (`git clone gitlab.com/ecp-ci/jacamar-ci`, `make build`,
   `make install PREFIX=...`) — or uses a binary you've already built, if
   you tell it to.
4. Configures the downscoping mechanism you chose:
   - **setuid** — grants `cap_setuid,cap_setgid` to the binary via `setcap`
     (deliberately *not* a full setuid-root bit), restricted to execution by
     the `gitlab-runner` account (`chown root:gitlab-runner`, `chmod 550`).
     Note: `/etc/security/limits.conf` (PAM-enforced limits) do **not**
     apply under this mode — set limits via the `gitlab-runner` systemd
     unit instead if you need them.
   - **sudo** — writes `/etc/sudoers.d/jacamar` granting `gitlab-runner` a
     passwordless `sudo` rule to run the binary as the target user(s) you
     specify, validated with `visudo -c` before being left in place.
   - **none** — no privilege changes; every job runs as the `gitlab-runner`
     service account. Single-user/test deployments only.
5. Writes `jacamar.toml` (default `/etc/gitlab-runner/jacamar.toml`).
6. Registers the GitLab Runner (`gitlab-runner register --non-interactive`)
   and appends a `[runners.custom]` block wiring all four custom-executor
   stages (`config`/`prepare`/`run`/`cleanup`) to `jacamar-auth`.
7. Runs `gitlab-runner verify` and restarts/enables the `gitlab-runner`
   systemd service.
8. Warns (doesn't fail) if the scheduler client binaries for your chosen
   backend aren't on `PATH` yet.

## Usage

```bash
# Preview everything first -- no changes, no root required.
./install_jacamar_ci.sh --dry-run

# Real run, interactive prompts for every value:
sudo ./install_jacamar_ci.sh

# Non-interactive, from a saved answers file (KEY=VALUE per line, using the
# exact variable names the script prints in its summary -- see below):
sudo ./install_jacamar_ci.sh --answers site-answers.env --yes
```

`--skip-os-check` lets it proceed on a RHEL derivative the script doesn't
explicitly recognize (anything other than `rhel`/`rocky`/`almalinux`/`centos`
in `/etc/os-release`, or a major version outside 8/9/10).

### Answers file format

```bash
GITLAB_URL="https://gitlab.example.com"
GITLAB_TOKEN="glrt-..."
RUNNER_DESCRIPTION="jacamar-hpc-runner"
RUNNER_TAGS="hpc,jacamar"
RUNNER_CONFIG_PATH="/etc/gitlab-runner/config.toml"
EXECUTOR_BACKEND="slurm"           # slurm | flux | shell
JACAMAR_DATA_DIR='$HOME'
LIMIT_BUILD_DIR="true"
DOWNSCOPE_MODE="setuid"            # setuid | sudo | none
SUDO_ALLOWED_USERS="ALL"           # only read when DOWNSCOPE_MODE=sudo
JACAMAR_BINARY_SOURCE="build"      # build | existing
JACAMAR_PREFIX="/opt/jacamar"      # only read when JACAMAR_BINARY_SOURCE=build
JACAMAR_EXISTING_BINARY=""         # only read when JACAMAR_BINARY_SOURCE=existing
JACAMAR_TOML_PATH="/etc/gitlab-runner/jacamar.toml"
LOG_LOCATION="/var/log/gitlab-runner/jacamar.log"
LOG_LEVEL="info"                   # debug | info | warn | error
```

Treat `GITLAB_TOKEN` in that file like any other secret (restrictive file
permissions, not committed to a repo).

## Idempotency / re-running

- OS package installs and the `git clone`/`make build` step are safe to
  re-run (the script pulls the latest instead of re-cloning if the source
  directory already exists).
- Runner registration is skipped if a runner with the same `--description`
  already appears in the target `config.toml` — remove that block manually
  first if you actually want to re-register (e.g. after rotating the
  token).
- Re-running after changing an answer (e.g. switching `DOWNSCOPE_MODE`) does
  **not** undo the previous mode's changes (an old sudoers file, capability
  bits already set) — clean those up yourself if you're switching modes on
  a host that's already been configured once.

## Uninstalling / rolling back

```bash
sudo systemctl disable --now gitlab-runner
sudo gitlab-runner unregister --config /etc/gitlab-runner/config.toml --name <description>
sudo rm -f /etc/sudoers.d/jacamar          # only if you used downscope=sudo
sudo dnf remove -y gitlab-runner
```

The `jacamar-auth` binary and `jacamar.toml` are just files under
`$JACAMAR_PREFIX` / `/etc/gitlab-runner` — remove them if you're fully
decommissioning the host.
