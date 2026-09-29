from chpc_sec_vuln_helper.rules.engine import evaluate
from chpc_sec_vuln_helper.rules.linux_rules import LINUX_RULES
from chpc_sec_vuln_helper.rules.windows_rules import WINDOWS_RULES


def test_every_linux_rule_has_kid_friendly_fields():
    for rule in LINUX_RULES:
        assert rule.title.strip()
        assert rule.description.strip()
        assert rule.danger.strip()
        assert rule.fix_steps, f"{rule.id} has no fix_steps"
        assert rule.severity in ("critical", "high", "medium", "low")
        assert rule.applicable_os


def test_every_windows_rule_has_kid_friendly_fields():
    for rule in WINDOWS_RULES:
        assert rule.title.strip()
        assert rule.description.strip()
        assert rule.danger.strip()
        assert rule.fix_steps
        assert rule.severity in ("critical", "high", "medium", "low")
        assert rule.applicable_os


def test_rule_ids_are_unique():
    linux_ids = [r.id for r in LINUX_RULES]
    windows_ids = [r.id for r in WINDOWS_RULES]
    assert len(linux_ids) == len(set(linux_ids))
    assert len(windows_ids) == len(set(windows_ids))


def test_linux_bad_config_flags_expected_rules():
    bad = {
        "os": {"family": "rhel", "major_version": 9},
        "selinux_status": "disabled",
        "firewall_active": False,
        "sshd_config": {"PermitRootLogin": "yes", "PasswordAuthentication": "yes",
                         "PermitEmptyPasswords": "no", "X11Forwarding": "no"},
        "users": [
            {"name": "root", "uid": 0, "has_password": True},
            {"name": "backup", "uid": 0, "has_password": True},
            {"name": "svc", "uid": 1000, "has_password": False},
        ],
        "auto_updates_enabled": False,
        "auditd_active": False,
        "time_sync_active": False,
        "password_policy": {"minlen": 6, "max_days": 99999},
        "world_writable_files": ["/etc/foo.conf"],
        "services_running": ["sshd", "telnet"],
        "faillock_configured": False,
        "sudoers_nopasswd_entries": ["deploy ALL=(ALL) NOPASSWD: ALL"],
    }
    findings = evaluate(LINUX_RULES, bad)
    flagged_ids = {f.rule.id for f in findings}
    expected = {
        "selinux_not_enforcing", "firewall_inactive", "ssh_root_login_permitted",
        "ssh_password_auth_enabled", "empty_password_users", "duplicate_uid0_accounts",
        "auto_updates_disabled", "auditd_inactive", "weak_password_minlen",
        "world_writable_files", "insecure_legacy_service_running", "time_sync_inactive",
        "password_never_expires", "no_account_lockout_policy", "passwordless_sudo",
    }
    assert expected <= flagged_ids


def test_linux_good_config_flags_nothing():
    good = {
        "os": {"family": "rhel", "major_version": 9},
        "selinux_status": "enforcing",
        "firewall_active": True,
        "sshd_config": {"PermitRootLogin": "no", "PasswordAuthentication": "no",
                         "PermitEmptyPasswords": "no", "X11Forwarding": "no"},
        "users": [{"name": "root", "uid": 0, "has_password": True}],
        "auto_updates_enabled": True,
        "auditd_active": True,
        "time_sync_active": True,
        "password_policy": {"minlen": 14, "max_days": 90},
        "world_writable_files": [],
        "services_running": ["sshd"],
        "faillock_configured": True,
        "sudoers_nopasswd_entries": [],
    }
    assert evaluate(LINUX_RULES, good) == []


def test_unknown_fields_are_skipped_not_failed():
    """A rule whose relevant field is missing entirely (collector
    couldn't check it) must never appear as a finding -- missing data
    is a skip, not a false positive.
    """
    sparse = {"os": {"family": "rhel", "major_version": 9}}
    assert evaluate(LINUX_RULES, sparse) == []


def test_non_rhel_rocky_host_gets_zero_linux_findings():
    ubuntu_like = {
        "os": {"family": "ubuntu", "major_version": 24},
        "selinux_status": "disabled",  # would fail if the gate didn't work
        "firewall_active": False,
    }
    assert evaluate(LINUX_RULES, ubuntu_like) == []


def test_windows_bad_config_flags_expected_rules():
    bad = {
        "os": {"family": "windows", "major_version": 11},
        "defender": {"enabled": False, "real_time_protection": False},
        "firewall_active": False,
        "smb1_enabled": True,
        "rdp": {"enabled": True, "network_level_authentication": False},
        "auto_updates_enabled": False,
        "local_password_policy": {"min_length": 4, "lockout_threshold": 0},
        "guest_account_enabled": True,
        "uac_enabled": False,
        "bitlocker_system_drive_status": "fullydecrypted",
        "smartscreen_enabled": False,
        "powershell_execution_policy": "Unrestricted",
        "remote_registry_running": True,
        "autoplay_enabled": True,
    }
    findings = evaluate(WINDOWS_RULES, bad)
    flagged_ids = {f.rule.id for f in findings}
    expected = {
        "defender_disabled", "firewall_disabled", "smb1_enabled", "rdp_without_nla",
        "auto_updates_disabled", "weak_min_password_length", "no_lockout_threshold",
        "guest_account_enabled", "uac_disabled", "bitlocker_disabled",
        "smartscreen_disabled", "powershell_unrestricted", "remote_registry_running",
        "autoplay_enabled",
    }
    assert flagged_ids == expected


def test_windows_good_config_flags_nothing():
    good = {
        "os": {"family": "windows", "major_version": 11},
        "defender": {"enabled": True, "real_time_protection": True},
        "firewall_active": True,
        "smb1_enabled": False,
        "rdp": {"enabled": False, "network_level_authentication": True},
        "auto_updates_enabled": True,
        "local_password_policy": {"min_length": 14, "lockout_threshold": 5},
        "guest_account_enabled": False,
        "uac_enabled": True,
        "bitlocker_system_drive_status": "fullyencrypted",
        "smartscreen_enabled": True,
        "powershell_execution_policy": "RemoteSigned",
        "remote_registry_running": False,
        "autoplay_enabled": False,
    }
    assert evaluate(WINDOWS_RULES, good) == []


def test_crashing_check_is_skipped_not_fatal():
    """A malformed collected-data shape (e.g. a string where a dict
    was expected) must not crash the whole evaluation.
    """
    weird = {"os": {"family": "rhel", "major_version": 9}, "sshd_config": "not-a-dict"}
    findings = evaluate(LINUX_RULES, weird)  # should not raise
    assert isinstance(findings, list)
