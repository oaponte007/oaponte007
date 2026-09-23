#!/usr/bin/env bash
# install_jacamar_ci.sh -- interactive installer/configurator for Jacamar CI
# (the HPC-focused GitLab custom-executor driver, gitlab.com/ecp-ci/jacamar-ci)
# on top of GitLab Runner, targeting RHEL/Rocky Linux 8, 9, and 10.
#
# Asks for every piece of site-specific information it needs (GitLab URL and
# runner token, which scheduler backend, downscoping mechanism, paths), then:
#   1. installs OS build/runtime dependencies (dnf)
#   2. installs GitLab Runner from the official package repo
#   3. builds jacamar-auth from source (or uses a binary you already built)
#   4. configures the chosen downscoping mechanism (setuid capabilities, or
#      sudo, or none for single-user/test deployments)
#   5. writes jacamar's own config file (jacamar.toml)
#   6. registers the GitLab Runner and wires it to Jacamar's custom-executor
#      commands in GitLab Runner's config.toml
#   7. verifies and (re)starts the gitlab-runner service
#
# Run with --dry-run first to see every command it would execute without
# changing anything. Run with --help for all options.
#
# Sources consulted while writing this (Jacamar CI's own docs site,
# ecp-ci.gitlab.io, was unreachable from the environment this was written in,
# so this leans on what's corroborated across multiple sources -- see
# JACAMAR_CI_SETUP.md for citations and the parts worth double-checking
# against your own Jacamar CI version before running this against production):
#   - gitlab.com/ecp-ci/jacamar-ci (build: `make build`, `make install PREFIX=...`)
#   - Jacamar CI admin tutorial/configuration docs (jacamar.toml [general]/[auth]
#     keys, the [runners.custom] wiring pattern, downscope = setuid|sudo|none)
#   - Jacamar CI non-root setuid deployment guide (capabilities via setcap
#     rather than a full setuid bit, restricted to the gitlab-runner account)

set -euo pipefail

# ---------------------------------------------------------------------------
# globals / defaults
# ---------------------------------------------------------------------------

SCRIPT_NAME="$(basename "$0")"
DRY_RUN=0
SKIP_OS_CHECK=0
ASSUME_YES=0
ANSWERS_FILE=""

JACAMAR_REPO_URL="https://gitlab.com/ecp-ci/jacamar-ci.git"
JACAMAR_SRC_DIR="/usr/local/src/jacamar-ci"

# Populated by prompts (or --answers file); defaults shown are what the
# prompt offers, not silent assumptions -- every value is confirmed before
# anything is installed.
GITLAB_URL=""
GITLAB_TOKEN=""
RUNNER_DESCRIPTION="jacamar-hpc-runner"
RUNNER_TAGS="hpc,jacamar"
RUNNER_CONFIG_PATH="/etc/gitlab-runner/config.toml"
EXECUTOR_BACKEND="slurm"          # slurm | flux | shell
JACAMAR_DATA_DIR='$HOME'
LIMIT_BUILD_DIR="true"
DOWNSCOPE_MODE="setuid"           # setuid | sudo | none
JACAMAR_TOML_PATH="/etc/gitlab-runner/jacamar.toml"
JACAMAR_PREFIX="/opt/jacamar"
JACAMAR_BIN=""                    # resolved after install: $JACAMAR_PREFIX/bin/jacamar-auth
JACAMAR_BINARY_SOURCE="build"     # build | existing
JACAMAR_EXISTING_BINARY=""
LOG_LOCATION="/var/log/gitlab-runner/jacamar.log"
LOG_LEVEL="info"
SUDO_ALLOWED_USERS="ALL"          # only used when DOWNSCOPE_MODE=sudo

OS_ID=""
OS_VERSION_ID=""

# ---------------------------------------------------------------------------
# logging + the dry-run command wrapper
# ---------------------------------------------------------------------------

log()      { printf '\033[1;34m[info]\033[0m %s\n' "$*"; }
warn()     { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
err()      { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
die()      { err "$*"; exit 1; }

# The single choke point for every command that changes system state.
# Under --dry-run it only prints; otherwise it actually runs the command.
# Never used for read-only checks (command -v, id, systemctl is-active) --
# those always run for real so prompts/validation reflect true state even
# during a dry run.
run() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '\033[1;36m[dry-run]\033[0m would run: %s\n' "$(printf '%q ' "$@")"
        return 0
    fi
    "$@"
}

# Same idea, for writing a file with specific content/owner/mode instead of
# running an external command.
write_file() {
    local path="$1" content="$2" mode="${3:-0644}" owner="${4:-root:root}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '\033[1;36m[dry-run]\033[0m would write %s (mode=%s owner=%s):\n' "$path" "$mode" "$owner"
        printf '%s\n' "$content" | sed 's/^/    /'
        return 0
    fi
    printf '%s\n' "$content" >"$path"
    chmod "$mode" "$path"
    chown "$owner" "$path" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# arg parsing
# ---------------------------------------------------------------------------

usage() {
    cat <<EOF
Usage: $SCRIPT_NAME [options]

Interactively gathers everything needed to install and configure Jacamar CI
on top of GitLab Runner, then does it.

Options:
  --dry-run           Print every command instead of running it. Nothing on
                       the system is changed. Use this first.
  --skip-os-check      Proceed even if /etc/os-release isn't recognized as
                       RHEL/Rocky 8, 9, or 10 (e.g. another RHEL derivative).
  --yes, -y            Don't ask for a final confirmation before installing.
  --answers FILE       Read answers from FILE (KEY=VALUE per line, same
                       variable names this script prints in its summary)
                       instead of prompting interactively. Useful for
                       reruns/automation once you know your site's values.
  -h, --help           Show this help and exit.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --skip-os-check) SKIP_OS_CHECK=1 ;;
        --yes|-y) ASSUME_YES=1 ;;
        --answers) ANSWERS_FILE="${2:?--answers requires a file path}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# root + OS checks
# ---------------------------------------------------------------------------

require_root() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        return 0   # previewing doesn't need privilege
    fi
    if [[ "$EUID" -ne 0 ]]; then
        die "this script installs system packages and system services; re-run as root (sudo $SCRIPT_NAME ...)"
    fi
}

detect_os() {
    if [[ ! -r /etc/os-release ]]; then
        warn "cannot read /etc/os-release; cannot verify this is a supported OS"
        return
    fi
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_VERSION_ID="${VERSION_ID:-unknown}"
}

check_supported_os() {
    if [[ "$SKIP_OS_CHECK" -eq 1 ]]; then
        warn "--skip-os-check set; proceeding on $OS_ID $OS_VERSION_ID without verifying support"
        return
    fi
    local major="${OS_VERSION_ID%%.*}"
    case "$OS_ID" in
        rhel|rocky|almalinux|centos)
            case "$major" in
                8|9|10) log "detected $OS_ID $OS_VERSION_ID -- supported" ;;
                *) die "detected $OS_ID $OS_VERSION_ID -- this script targets RHEL/Rocky 8, 9, or 10. Re-run with --skip-os-check to proceed anyway." ;;
            esac
            ;;
        *) die "detected $OS_ID $OS_VERSION_ID -- this script targets RHEL/Rocky 8, 9, or 10. Re-run with --skip-os-check to proceed anyway." ;;
    esac
}

# ---------------------------------------------------------------------------
# prompt helpers (skipped entirely if --answers was given; see load_answers)
# ---------------------------------------------------------------------------

INTERACTIVE=1

prompt_text() {
    local __var="$1" __prompt="$2" __default="${3:-}" __input
    if [[ "$INTERACTIVE" -eq 0 ]]; then return 0; fi
    if [[ -n "$__default" ]]; then
        read -r -p "$__prompt [$__default]: " __input
    else
        read -r -p "$__prompt: " __input
    fi
    printf -v "$__var" '%s' "${__input:-$__default}"
}

prompt_required() {
    local __var="$1" __prompt="$2"
    while true; do
        prompt_text "$__var" "$__prompt" ""
        [[ -n "${!__var}" ]] && return 0
        warn "this value is required"
    done
}

prompt_secret() {
    local __var="$1" __prompt="$2" __input
    if [[ "$INTERACTIVE" -eq 0 ]]; then return 0; fi
    while true; do
        read -r -s -p "$__prompt: " __input
        echo
        if [[ -n "$__input" ]]; then
            printf -v "$__var" '%s' "$__input"
            return 0
        fi
        warn "this value is required"
    done
}

prompt_choice() {
    # prompt_choice VAR "prompt text" default opt1 opt2 opt3 ...
    local __var="$1" __prompt="$2" __default="$3"; shift 3
    local __opts=("$@") __input
    if [[ "$INTERACTIVE" -eq 0 ]]; then return 0; fi
    while true; do
        read -r -p "$__prompt (${__opts[*]}) [$__default]: " __input
        __input="${__input:-$__default}"
        for opt in "${__opts[@]}"; do
            if [[ "$opt" == "$__input" ]]; then
                printf -v "$__var" '%s' "$__input"
                return 0
            fi
        done
        warn "please enter one of: ${__opts[*]}"
    done
}

prompt_yesno() {
    local __var="$1" __prompt="$2" __default="$3" __input
    if [[ "$INTERACTIVE" -eq 0 ]]; then return 0; fi
    while true; do
        read -r -p "$__prompt [y/n, default $__default]: " __input
        __input="${__input:-$__default}"
        case "$__input" in
            y|Y|yes) printf -v "$__var" '%s' "yes"; return 0 ;;
            n|N|no) printf -v "$__var" '%s' "no"; return 0 ;;
            *) warn "please answer y or n" ;;
        esac
    done
}

load_answers() {
    [[ -z "$ANSWERS_FILE" ]] && return 0
    [[ -r "$ANSWERS_FILE" ]] || die "cannot read answers file: $ANSWERS_FILE"
    log "loading answers from $ANSWERS_FILE (interactive prompts disabled)"
    INTERACTIVE=0
    # shellcheck disable=SC1090
    . "$ANSWERS_FILE"
}

# ---------------------------------------------------------------------------
# gather all the information this install needs
# ---------------------------------------------------------------------------

gather_answers() {
    [[ "$INTERACTIVE" -eq 0 ]] && return 0

    echo
    log "== GitLab connection =="
    prompt_required GITLAB_URL "GitLab instance URL (e.g. https://gitlab.example.com)"
    prompt_secret   GITLAB_TOKEN "Runner registration/authentication token (from GitLab: Settings > CI/CD > Runners)"

    echo
    log "== Runner identity =="
    prompt_text RUNNER_DESCRIPTION "Runner description/name" "$RUNNER_DESCRIPTION"
    prompt_text RUNNER_TAGS "Runner tags (comma-separated, jobs select this runner with these)" "$RUNNER_TAGS"
    prompt_text RUNNER_CONFIG_PATH "GitLab Runner config.toml path" "$RUNNER_CONFIG_PATH"

    echo
    log "== Execution backend =="
    echo "  slurm : submit each CI job through Slurm (sbatch/srun must already work on this host)"
    echo "  flux  : submit each CI job through Flux"
    echo "  shell : run CI jobs directly on this host, no scheduler (local/dev use)"
    prompt_choice EXECUTOR_BACKEND "Which backend should Jacamar submit jobs to?" "$EXECUTOR_BACKEND" slurm flux shell

    echo
    log "== Jacamar data directory =="
    echo "  Where Jacamar stages each job's working files. A per-user path like"
    echo "  \$HOME (expanded per job's user) is typical for setuid/sudo downscoping;"
    echo "  a fixed shared path (e.g. /ecp) is typical for downscope=none."
    prompt_text JACAMAR_DATA_DIR "data_dir" "$JACAMAR_DATA_DIR"
    prompt_yesno LIMIT_BUILD_DIR_YN "Limit each job's build directory to its own subdirectory (limit_build_dir)?" "yes"
    [[ "$LIMIT_BUILD_DIR_YN" == "yes" ]] && LIMIT_BUILD_DIR="true" || LIMIT_BUILD_DIR="false"

    echo
    log "== Privilege downscoping =="
    echo "  setuid : jacamar-auth gets cap_setuid/cap_setgid (via setcap, not a full"
    echo "           setuid bit), restricted to the gitlab-runner account, and runs"
    echo "           each job as its actual submitting user. Recommended for"
    echo "           multi-user production clusters."
    echo "  sudo   : jacamar-auth runs job steps via a sudoers NOPASSWD rule instead"
    echo "           of file capabilities. Use if your site policy prefers sudo"
    echo "           over capabilities."
    echo "  none   : every job runs as the gitlab-runner service account itself."
    echo "           Only appropriate for a single-user or test deployment."
    prompt_choice DOWNSCOPE_MODE "Downscoping mode" "$DOWNSCOPE_MODE" setuid sudo none
    if [[ "$DOWNSCOPE_MODE" == "sudo" ]]; then
        prompt_text SUDO_ALLOWED_USERS "sudoers target user pattern (ALL for any submitting user, or a specific user/group)" "$SUDO_ALLOWED_USERS"
    fi

    echo
    log "== Jacamar binary =="
    prompt_choice JACAMAR_BINARY_SOURCE "Build jacamar-auth from source now, or use a binary you already have?" "$JACAMAR_BINARY_SOURCE" build existing
    if [[ "$JACAMAR_BINARY_SOURCE" == "build" ]]; then
        prompt_text JACAMAR_PREFIX "Install prefix (binary lands at PREFIX/bin/jacamar-auth)" "$JACAMAR_PREFIX"
    else
        prompt_required JACAMAR_EXISTING_BINARY "Path to your existing jacamar-auth binary"
    fi

    echo
    log "== Paths and logging =="
    prompt_text JACAMAR_TOML_PATH "Where to write jacamar's own config file" "$JACAMAR_TOML_PATH"
    prompt_text LOG_LOCATION "Jacamar auth log file path" "$LOG_LOCATION"
    prompt_choice LOG_LEVEL "Jacamar log level" "$LOG_LEVEL" debug info warn error
}

print_summary() {
    local downscope_extra="" binary_extra=""
    if [[ "$DOWNSCOPE_MODE" == "sudo" ]]; then
        downscope_extra=$'\n'"  sudoers target users     : $SUDO_ALLOWED_USERS"
    fi
    if [[ "$JACAMAR_BINARY_SOURCE" == "build" ]]; then
        binary_extra=$'\n'"  install prefix           : $JACAMAR_PREFIX"
    else
        binary_extra=$'\n'"  existing binary path     : $JACAMAR_EXISTING_BINARY"
    fi

    cat <<EOF

================= Jacamar CI install plan =================
GitLab URL           : $GITLAB_URL
Runner description   : $RUNNER_DESCRIPTION
Runner tags           : $RUNNER_TAGS
Runner config.toml    : $RUNNER_CONFIG_PATH
Executor backend      : $EXECUTOR_BACKEND
Jacamar data_dir      : $JACAMAR_DATA_DIR
limit_build_dir       : $LIMIT_BUILD_DIR
Downscope mode        : $DOWNSCOPE_MODE${downscope_extra}
Jacamar binary source : $JACAMAR_BINARY_SOURCE${binary_extra}
jacamar.toml path     : $JACAMAR_TOML_PATH
Log location          : $LOG_LOCATION (level: $LOG_LEVEL)
Dry run               : $([[ "$DRY_RUN" -eq 1 ]] && echo yes || echo no)
==============================================================

EOF
    if [[ "$ASSUME_YES" -eq 0 && "$INTERACTIVE" -eq 1 ]]; then
        local confirm
        read -r -p "Proceed with these settings? [y/N]: " confirm
        [[ "$confirm" == "y" || "$confirm" == "Y" ]] || die "aborted by user"
    fi
}

# ---------------------------------------------------------------------------
# step 1: OS package dependencies
# ---------------------------------------------------------------------------

install_os_packages() {
    log "installing OS packages (git, go, gcc, make, libcap, curl)"
    run dnf install -y git golang gcc make libcap curl tar policycoreutils-python-utils
}

# ---------------------------------------------------------------------------
# step 2: GitLab Runner
# ---------------------------------------------------------------------------

install_gitlab_runner() {
    if command -v gitlab-runner >/dev/null 2>&1; then
        log "gitlab-runner already installed ($(gitlab-runner --version 2>&1 | head -1))"
        return
    fi
    log "installing GitLab Runner from the official package repository"
    run bash -c 'curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.rpm.sh" | bash'
    run dnf install -y gitlab-runner
    if ! id gitlab-runner >/dev/null 2>&1 && [[ "$DRY_RUN" -eq 0 ]]; then
        warn "gitlab-runner package installed but the gitlab-runner system user wasn't found -- check the package post-install log"
    fi
}

# ---------------------------------------------------------------------------
# step 3: jacamar-auth binary
# ---------------------------------------------------------------------------

build_jacamar() {
    if [[ "$JACAMAR_BINARY_SOURCE" == "existing" ]]; then
        [[ -x "$JACAMAR_EXISTING_BINARY" ]] || [[ "$DRY_RUN" -eq 1 ]] || \
            die "provided binary is not executable or does not exist: $JACAMAR_EXISTING_BINARY"
        JACAMAR_BIN="$JACAMAR_EXISTING_BINARY"
        log "using existing jacamar-auth binary at $JACAMAR_BIN"
        return
    fi

    log "checking Go toolchain (Jacamar CI needs Go >= 1.14; CGO is required for os/user)"
    if command -v go >/dev/null 2>&1; then
        log "found: $(go version)"
    else
        warn "go not found on PATH yet (expected before install_os_packages runs, or if dry-run skipped it)"
    fi

    if [[ -d "$JACAMAR_SRC_DIR/.git" ]]; then
        log "jacamar-ci source already cloned at $JACAMAR_SRC_DIR; pulling latest"
        run git -C "$JACAMAR_SRC_DIR" pull --ff-only
    else
        log "cloning $JACAMAR_REPO_URL -> $JACAMAR_SRC_DIR"
        run git clone "$JACAMAR_REPO_URL" "$JACAMAR_SRC_DIR"
    fi

    log "building jacamar-auth (make build && make install PREFIX=$JACAMAR_PREFIX)"
    run bash -c "cd '$JACAMAR_SRC_DIR' && make build"
    run bash -c "cd '$JACAMAR_SRC_DIR' && make install PREFIX='$JACAMAR_PREFIX'"

    if [[ "$DRY_RUN" -eq 1 ]]; then
        JACAMAR_BIN="$JACAMAR_PREFIX/bin/jacamar-auth"
        log "[dry-run] would resolve jacamar binary to $JACAMAR_BIN"
        return
    fi

    if [[ -x "$JACAMAR_PREFIX/bin/jacamar-auth" ]]; then
        JACAMAR_BIN="$JACAMAR_PREFIX/bin/jacamar-auth"
    elif [[ -x "$JACAMAR_PREFIX/bin/jacamar" ]]; then
        warn "found $JACAMAR_PREFIX/bin/jacamar instead of jacamar-auth -- using it, but double check this matches your Jacamar CI version's binary name"
        JACAMAR_BIN="$JACAMAR_PREFIX/bin/jacamar"
    else
        die "build finished but no jacamar-auth/jacamar binary found under $JACAMAR_PREFIX/bin -- check the make output above"
    fi
    log "jacamar binary: $JACAMAR_BIN"
}

# ---------------------------------------------------------------------------
# step 4: downscoping
# ---------------------------------------------------------------------------

configure_downscope() {
    case "$DOWNSCOPE_MODE" in
        setuid)
            log "granting cap_setuid,cap_setgid to $JACAMAR_BIN (capabilities, not a full setuid bit) and restricting execution to gitlab-runner"
            run setcap cap_setuid,cap_setgid+ep "$JACAMAR_BIN"
            run chown root:gitlab-runner "$JACAMAR_BIN"
            run chmod 550 "$JACAMAR_BIN"
            warn "resource limits from /etc/security/limits.conf are NOT enforced under setuid downscoping (PAM isn't in the path)." \
                 " Set limits via the gitlab-runner systemd unit instead (e.g. LimitNOFILE=) if you need them."
            ;;
        sudo)
            local sudoers_file=/etc/sudoers.d/jacamar
            local sudoers_line="gitlab-runner ALL=($SUDO_ALLOWED_USERS) NOPASSWD: $JACAMAR_BIN"
            log "writing $sudoers_file"
            write_file "$sudoers_file" "$sudoers_line" 0440 "root:root"
            if [[ "$DRY_RUN" -eq 0 ]]; then
                visudo -c -f "$sudoers_file" || die "generated sudoers file failed validation: $sudoers_file"
            fi
            ;;
        none)
            log "downscope=none: jobs will run as the gitlab-runner service account itself. No privilege changes to apply."
            ;;
    esac
}

# ---------------------------------------------------------------------------
# step 5: jacamar.toml
# ---------------------------------------------------------------------------

write_jacamar_toml() {
    local toml
    toml=$(cat <<EOF
# Written by install_jacamar_ci.sh. See CHPC_MANUAL.md's sibling,
# JACAMAR_CI_SETUP.md, for what each of these keys does and where to look
# for site-specific options (per-partition Slurm settings, environments,
# etc.) this installer intentionally does not guess at.

[general]
executor = "$EXECUTOR_BACKEND"
data_dir = "$JACAMAR_DATA_DIR"
limit_build_dir = $LIMIT_BUILD_DIR

[auth]
downscope = "$DOWNSCOPE_MODE"

[auth.logging]
location = "$LOG_LOCATION"
level = "$LOG_LEVEL"
EOF
)
    log "writing jacamar config -> $JACAMAR_TOML_PATH"
    write_file "$JACAMAR_TOML_PATH" "$toml" 0640 "root:gitlab-runner"

    if [[ "$DRY_RUN" -eq 0 ]]; then
        mkdir -p "$(dirname "$LOG_LOCATION")"
        chown gitlab-runner:gitlab-runner "$(dirname "$LOG_LOCATION")" 2>/dev/null || true
    else
        log "[dry-run] would ensure $(dirname "$LOG_LOCATION") exists and is writable by gitlab-runner"
    fi
}

# ---------------------------------------------------------------------------
# step 6: register the runner + wire up the custom executor
# ---------------------------------------------------------------------------

register_runner() {
    if [[ "$DRY_RUN" -eq 0 && -f "$RUNNER_CONFIG_PATH" ]] && grep -q "\"$RUNNER_DESCRIPTION\"" "$RUNNER_CONFIG_PATH" 2>/dev/null; then
        warn "a runner named '$RUNNER_DESCRIPTION' already appears in $RUNNER_CONFIG_PATH; skipping registration (edit/remove it manually first if you want to re-register)"
        return
    fi

    log "registering GitLab Runner against $GITLAB_URL"
    run gitlab-runner register \
        --non-interactive \
        --config "$RUNNER_CONFIG_PATH" \
        --url "$GITLAB_URL" \
        --registration-token "$GITLAB_TOKEN" \
        --name "$RUNNER_DESCRIPTION" \
        --tag-list "$RUNNER_TAGS" \
        --executor "custom"

    local custom_block
    custom_block=$(cat <<EOF

  [runners.custom]
    config_exec = "$JACAMAR_BIN"
    config_args = ["config", "--configuration", "$JACAMAR_TOML_PATH"]
    prepare_exec = "$JACAMAR_BIN"
    prepare_args = ["prepare", "--configuration", "$JACAMAR_TOML_PATH"]
    run_exec = "$JACAMAR_BIN"
    run_args = ["run", "--configuration", "$JACAMAR_TOML_PATH"]
    cleanup_exec = "$JACAMAR_BIN"
    cleanup_args = ["cleanup", "--configuration", "$JACAMAR_TOML_PATH"]
EOF
)
    log "appending [runners.custom] wiring to $RUNNER_CONFIG_PATH"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '\033[1;36m[dry-run]\033[0m would append to %s:\n%s\n' "$RUNNER_CONFIG_PATH" "$custom_block"
    else
        printf '%s\n' "$custom_block" >>"$RUNNER_CONFIG_PATH"
    fi
}

verify_and_start() {
    log "verifying runner configuration"
    run gitlab-runner verify --config "$RUNNER_CONFIG_PATH" || warn "gitlab-runner verify reported a problem -- check the output above before relying on this runner"

    log "enabling and (re)starting the gitlab-runner service"
    run systemctl enable gitlab-runner
    run systemctl restart gitlab-runner
}

# ---------------------------------------------------------------------------
# step 7: scheduler sanity checks
# ---------------------------------------------------------------------------

check_scheduler_backend() {
    case "$EXECUTOR_BACKEND" in
        slurm)
            if command -v sbatch >/dev/null 2>&1 && command -v srun >/dev/null 2>&1; then
                log "found sbatch/srun on PATH"
            else
                warn "executor=slurm but sbatch/srun were not found on PATH." \
                     " Jacamar does not install Slurm itself -- install/configure the cluster's Slurm client on this host first," \
                     " then re-run (or just fix PATH/module load and restart gitlab-runner)."
            fi
            ;;
        flux)
            if command -v flux >/dev/null 2>&1; then
                log "found flux on PATH"
            else
                warn "executor=flux but the flux binary was not found on PATH -- install/configure Flux on this host first."
            fi
            ;;
        shell)
            log "executor=shell: no scheduler client required."
            ;;
    esac
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

main() {
    require_root
    detect_os
    check_supported_os

    load_answers
    gather_answers
    print_summary

    install_os_packages
    install_gitlab_runner
    build_jacamar
    configure_downscope
    write_jacamar_toml
    register_runner
    verify_and_start
    check_scheduler_backend

    cat <<EOF

================= Done =================
GitLab Runner config : $RUNNER_CONFIG_PATH
Jacamar config          : $JACAMAR_TOML_PATH
Jacamar binary            : ${JACAMAR_BIN:-"(not resolved -- dry run)"}
Log file                    : $LOG_LOCATION

Next steps:
  1. tail -f $LOG_LOCATION and $RUNNER_CONFIG_PATH's sibling gitlab-runner
     log (journalctl -u gitlab-runner -f) while running a trivial test
     pipeline tagged with: $RUNNER_TAGS
  2. If executor=slurm/flux and check_scheduler_backend warned above, fix
     that before trusting real jobs to this runner.
  3. Re-running this script is safe: package installs and the git
     clone/build are idempotent, and registration is skipped if a runner
     with this description is already present in the config file.
==========================================
EOF
}

main "$@"
