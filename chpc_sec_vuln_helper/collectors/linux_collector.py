#!/usr/bin/env python3
"""Collects the real, current security-relevant state of a RHEL/Rocky
8/9/10 host into one JSON file -- pure Python 3 standard library, no
pip installs, meant to run directly on the (possibly airgapped) target
with `sudo` for full coverage (some checks, like accounts with no
password, need root to read /etc/shadow; anything that can't be
checked without more privilege is skipped and noted, never guessed).

Run directly: sudo python3 linux_collector.py [-o output.json]
or via the CLI: chpc-sec-vuln-helper collect -o output.json

Collected-data field reference (consumed by rules/linux_rules.py and
feeds/matcher.match_linux):

  os: {family, name, major_version, version_id, kernel}
  packages: [{name, epoch, version, release, arch}, ...]
  services_running / services_enabled: [unit name, ...]
  listening_ports: [{port, proto, address}, ...]
  selinux_status: "enforcing" | "permissive" | "disabled" | null
  firewall_active: bool | null
  sshd_config: {Directive: "value", ...} | null
  users: [{name, uid, has_password}, ...] | null
  auto_updates_enabled: bool | null
  auditd_active: bool | null
  time_sync_active: bool | null
  password_policy: {minlen, max_days} | null
  world_writable_files: [path, ...] | null
  faillock_configured: bool | null
  sudoers_nopasswd_entries: [line, ...] | null
  collector_warnings: [message, ...]
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _run(cmd: list[str], timeout: float = 15.0) -> str | None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def collect(warnings: list[str]) -> dict:
    data: dict = {}
    data["os"] = _collect_os()
    if data["os"]["family"] not in ("rhel", "rocky"):
        warnings.append(
            f"This looks like {data['os']['name'] or data['os']['family']}, not RHEL or Rocky Linux -- "
            "this tool's baseline rules and CVE feed are built for RHEL/Rocky 8/9/10, so no "
            "findings will be reported for this host."
        )
    data["packages"] = _collect_packages(warnings)
    services = _collect_services(warnings)
    data["services_running"] = services[0]
    data["services_enabled"] = services[1]
    data["listening_ports"] = _collect_listening_ports(warnings)
    data["selinux_status"] = _collect_selinux()
    data["firewall_active"] = _collect_unit_active("firewalld")
    data["sshd_config"] = _collect_sshd_config(warnings)
    data["users"] = _collect_users(warnings)
    data["auto_updates_enabled"] = _collect_unit_active("dnf-automatic.timer")
    data["auditd_active"] = _collect_unit_active("auditd")
    data["time_sync_active"] = _collect_unit_active("chronyd")
    data["password_policy"] = _collect_password_policy(warnings)
    data["world_writable_files"] = _collect_world_writable(warnings)
    data["faillock_configured"] = _collect_faillock_configured()
    data["sudoers_nopasswd_entries"] = _collect_sudoers_nopasswd(warnings)
    return data


def _collect_os() -> dict:
    info: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                info[key] = value.strip().strip('"')
    except OSError:
        pass

    os_id = info.get("ID", "").lower()
    if os_id == "rocky":
        family = "rocky"
    elif os_id in ("rhel", "redhat"):
        family = "rhel"
    else:
        # Not what this tool's rule set and CVE feed are built for --
        # report the real ID rather than silently mislabeling it as
        # "rhel", which would apply the wrong rules and compare this
        # system's packages against the wrong distro's advisories.
        family = os_id or "unknown"
    version_id = info.get("VERSION_ID", "")
    major_version = None
    m = re.match(r"(\d+)", version_id)
    if m:
        major_version = int(m.group(1))

    kernel = _run(["uname", "-r"])
    return {
        "family": family,
        "name": info.get("NAME", "Linux"),
        "major_version": major_version,
        "version_id": version_id,
        "kernel": (kernel or "").strip() or None,
    }


def _collect_packages(warnings: list[str]) -> list[dict] | None:
    output = _run(["rpm", "-qa", "--queryformat", "%{NAME}|%{EPOCH}|%{VERSION}|%{RELEASE}|%{ARCH}\n"], timeout=60)
    if output is None:
        warnings.append("Could not run 'rpm -qa' -- package list (and CVE matching) skipped.")
        return None
    packages = []
    for line in output.splitlines():
        parts = line.split("|")
        if len(parts) != 5:
            continue
        name, epoch, version, release, arch = parts
        packages.append({
            "name": name,
            "epoch": None if epoch in ("(none)", "") else epoch,
            "version": version,
            "release": release,
            "arch": arch,
        })
    return packages


def _collect_services(warnings: list[str]) -> tuple[list[str] | None, list[str] | None]:
    running_out = _run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"])
    enabled_out = _run(["systemctl", "list-unit-files", "--type=service", "--state=enabled", "--no-legend", "--plain"])
    if running_out is None or enabled_out is None:
        warnings.append("Could not query systemctl -- service list skipped.")
        return None, None
    running = [line.split()[0].removesuffix(".service") for line in running_out.splitlines() if line.strip()]
    enabled = [line.split()[0].removesuffix(".service") for line in enabled_out.splitlines() if line.strip()]
    return running, enabled


def _collect_listening_ports(warnings: list[str]) -> list[dict] | None:
    output = _run(["ss", "-tulnH"])
    if output is None:
        warnings.append("Could not run 'ss' -- listening port list skipped.")
        return None
    ports = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        proto = fields[0]
        local_addr = fields[4]
        if ":" not in local_addr:
            continue
        address, _, port_str = local_addr.rpartition(":")
        try:
            port = int(port_str)
        except ValueError:
            continue
        ports.append({"port": port, "proto": proto, "address": address})
    return ports


def _collect_selinux() -> str | None:
    output = _run(["getenforce"])
    if output is None:
        return None
    return output.strip().lower() or None


def _collect_unit_active(unit: str) -> bool | None:
    output = _run(["systemctl", "is-active", unit])
    if output is None:
        return None
    return output.strip() == "active"


_SSHD_CONFIG_LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]*)\s+(.+?)\s*$")


def _parse_sshd_config_text(text: str, config: dict) -> None:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _SSHD_CONFIG_LINE_RE.match(stripped)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        # sshd honors the FIRST value it encounters for most directives;
        # RHEL/Rocky's default config Includes sshd_config.d/*.conf near
        # the top, so those drop-ins are parsed first here to match that.
        if key not in config:
            config[key] = value


def _collect_sshd_config(warnings: list[str]) -> dict | None:
    config: dict[str, str] = {}
    found_anything = False

    dropin_dir = Path("/etc/ssh/sshd_config.d")
    if dropin_dir.is_dir():
        for path in sorted(dropin_dir.glob("*.conf")):
            try:
                _parse_sshd_config_text(path.read_text(), config)
                found_anything = True
            except OSError:
                continue

    main_path = Path("/etc/ssh/sshd_config")
    try:
        _parse_sshd_config_text(main_path.read_text(), config)
        found_anything = True
    except OSError:
        pass

    if not found_anything:
        warnings.append("Could not read /etc/ssh/sshd_config -- SSH hardening checks skipped.")
        return None
    return config


def _collect_users(warnings: list[str]) -> list[dict] | None:
    try:
        passwd_lines = Path("/etc/passwd").read_text().splitlines()
    except OSError:
        warnings.append("Could not read /etc/passwd -- account checks skipped.")
        return None

    shadow_by_name: dict[str, str] = {}
    try:
        for line in Path("/etc/shadow").read_text().splitlines():
            fields = line.split(":")
            if len(fields) >= 2:
                shadow_by_name[fields[0]] = fields[1]
    except (OSError, PermissionError):
        warnings.append("Could not read /etc/shadow (needs root/sudo) -- 'accounts with no password' check skipped.")

    users = []
    for line in passwd_lines:
        fields = line.split(":")
        if len(fields) < 3:
            continue
        name, _, uid_str = fields[0], fields[1], fields[2]
        try:
            uid = int(uid_str)
        except ValueError:
            continue
        has_password = None
        if name in shadow_by_name:
            # an EMPTY field means "no password required"; "!"/"*" mean
            # locked (can't log in via password) but is NOT the same
            # thing as "no password" -- only a literal empty string is.
            has_password = shadow_by_name[name] != ""
        users.append({"name": name, "uid": uid, "has_password": has_password})
    return users


def _collect_password_policy(warnings: list[str]) -> dict | None:
    policy: dict[str, int] = {}
    try:
        text = Path("/etc/security/pwquality.conf").read_text()
        m = re.search(r"^\s*minlen\s*=\s*(\d+)", text, re.MULTILINE)
        if m:
            policy["minlen"] = int(m.group(1))
    except OSError:
        pass

    try:
        text = Path("/etc/login.defs").read_text()
        m = re.search(r"^\s*PASS_MAX_DAYS\s+(\d+)", text, re.MULTILINE)
        if m:
            policy["max_days"] = int(m.group(1))
    except OSError:
        pass

    if not policy:
        warnings.append("Could not read password policy files -- password policy checks skipped.")
        return None
    return policy


_WORLD_WRITABLE_SEARCH_DIRS = ["/etc", "/usr/local/bin", "/opt", "/srv"]
_WORLD_WRITABLE_LIMIT = 50


def _collect_world_writable(warnings: list[str]) -> list[str] | None:
    existing_dirs = [d for d in _WORLD_WRITABLE_SEARCH_DIRS if Path(d).is_dir()]
    if not existing_dirs:
        return []
    output = _run(
        ["find", *existing_dirs, "-xdev", "-type", "f", "-perm", "-0002"],
        timeout=30,
    )
    if output is None:
        warnings.append("Could not scan for world-writable files -- that check was skipped.")
        return None
    files = [line for line in output.splitlines() if line.strip()]
    return files[:_WORLD_WRITABLE_LIMIT]


def _collect_faillock_configured() -> bool | None:
    for path in ("/etc/pam.d/system-auth", "/etc/pam.d/password-auth"):
        try:
            if "pam_faillock.so" in Path(path).read_text():
                return True
        except OSError:
            continue
    if Path("/etc/pam.d/system-auth").exists() or Path("/etc/pam.d/password-auth").exists():
        return False
    return None


def _collect_sudoers_nopasswd(warnings: list[str]) -> list[str] | None:
    paths = [Path("/etc/sudoers")]
    sudoers_d = Path("/etc/sudoers.d")
    if sudoers_d.is_dir():
        try:
            paths.extend(sorted(sudoers_d.iterdir()))
        except PermissionError:
            pass

    found: list[str] = []
    readable_any = False
    for path in paths:
        try:
            text = path.read_text()
        except (OSError, PermissionError):
            continue
        readable_any = True
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if "NOPASSWD" in stripped:
                found.append(stripped)

    if not readable_any:
        warnings.append("Could not read /etc/sudoers (needs root/sudo) -- passwordless-sudo check skipped.")
        return None
    return found


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Collect security-relevant state from this RHEL/Rocky host.")
    parser.add_argument("-o", "--output", help="Write JSON here instead of stdout.")
    args = parser.parse_args(argv)

    warnings: list[str] = []
    data = collect(warnings)
    data["hostname"] = socket.gethostname()
    data["collected_at"] = datetime.now(timezone.utc).isoformat()
    data["schema_version"] = 1
    data["collector_warnings"] = warnings

    output_text = json.dumps(data, indent=2)
    if args.output:
        Path(args.output).write_text(output_text)
        print(f"Wrote {args.output} ({len(warnings)} warning(s)).", file=sys.stderr)
    else:
        print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
