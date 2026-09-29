"""Baseline/hardening rules for RHEL and Rocky Linux 8/9/10. Every
check reads the collected-data dict produced by
collectors/linux_collector.py -- see that module's docstring for the
exact field names.
"""
from __future__ import annotations

from .engine import Rule, fail, ok

_LINUX_OS = ["rhel", "rocky"]


def _check_selinux(data):
    status = data.get("selinux_status")
    if status is None:
        return None
    if status != "enforcing":
        return fail(f"SELinux is currently set to '{status}', not 'enforcing'.")
    return ok()


def _check_firewall(data):
    active = data.get("firewall_active")
    if active is None:
        return None
    if not active:
        return fail("firewalld is not active.")
    return ok()


def _check_ssh_root_login(data):
    sshd = data.get("sshd_config")
    if sshd is None:
        return None
    value = sshd.get("PermitRootLogin", "prohibit-password")
    if value.lower() in ("yes",):
        return fail(f"sshd_config has PermitRootLogin {value}")
    return ok()


def _check_ssh_password_auth(data):
    sshd = data.get("sshd_config")
    if sshd is None:
        return None
    value = sshd.get("PasswordAuthentication", "yes")
    if value.lower() == "yes":
        return fail("sshd_config has PasswordAuthentication yes")
    return ok()


def _check_ssh_empty_passwords(data):
    sshd = data.get("sshd_config")
    if sshd is None:
        return None
    value = sshd.get("PermitEmptyPasswords", "no")
    if value.lower() == "yes":
        return fail("sshd_config has PermitEmptyPasswords yes")
    return ok()


def _check_ssh_x11_forwarding(data):
    sshd = data.get("sshd_config")
    if sshd is None:
        return None
    value = sshd.get("X11Forwarding", "no")
    if value.lower() == "yes":
        return fail("sshd_config has X11Forwarding yes")
    return ok()


def _check_empty_password_users(data):
    users = data.get("users")
    if users is None:
        return None
    offenders = [u["name"] for u in users if u.get("has_password") is False]
    if offenders:
        return fail(f"Account(s) with no password set: {', '.join(offenders)}")
    return ok()


def _check_duplicate_uid0(data):
    users = data.get("users")
    if users is None:
        return None
    uid0_names = [u["name"] for u in users if u.get("uid") == 0]
    extra = [n for n in uid0_names if n != "root"]
    if extra:
        return fail(f"Account(s) other than root with UID 0 (full admin power): {', '.join(extra)}")
    return ok()


def _check_auto_updates(data):
    enabled = data.get("auto_updates_enabled")
    if enabled is None:
        return None
    if not enabled:
        return fail("dnf-automatic.timer is not enabled/active.")
    return ok()


def _check_auditd(data):
    active = data.get("auditd_active")
    if active is None:
        return None
    if not active:
        return fail("auditd is not active.")
    return ok()


def _check_password_minlen(data):
    policy = data.get("password_policy")
    if policy is None or policy.get("minlen") is None:
        return None
    minlen = policy["minlen"]
    if minlen < 14:
        return fail(f"pwquality minlen is {minlen} (should be 14 or more).")
    return ok()


def _check_world_writable(data):
    files = data.get("world_writable_files")
    if files is None:
        return None
    if files:
        shown = ", ".join(files[:5])
        more = f" (+{len(files) - 5} more)" if len(files) > 5 else ""
        return fail(f"World-writable file(s) found outside normal locations: {shown}{more}")
    return ok()


def _check_legacy_services(data):
    running = data.get("services_running")
    if running is None:
        return None
    legacy = {"telnet", "telnet.socket", "rsh", "rlogin", "vsftpd", "tftp", "tftp.socket"}
    found = sorted(set(running) & legacy)
    if found:
        return fail(f"Old, unencrypted service(s) running: {', '.join(found)}")
    return ok()


def _check_time_sync(data):
    active = data.get("time_sync_active")
    if active is None:
        return None
    if not active:
        return fail("No time-sync service (chronyd) is active.")
    return ok()


def _check_password_expiry(data):
    policy = data.get("password_policy")
    if policy is None or policy.get("max_days") is None:
        return None
    max_days = policy["max_days"]
    if max_days <= 0 or max_days >= 99999:
        return fail(f"PASS_MAX_DAYS is {max_days} -- passwords never expire.")
    return ok()


def _check_account_lockout(data):
    configured = data.get("faillock_configured")
    if configured is None:
        return None
    if not configured:
        return fail("No account-lockout (faillock) policy is configured.")
    return ok()


def _check_passwordless_sudo(data):
    entries = data.get("sudoers_nopasswd_entries")
    if entries is None:
        return None
    if entries:
        return fail(f"NOPASSWD sudo entries found: {', '.join(entries[:5])}")
    return ok()


LINUX_RULES: list[Rule] = [
    Rule(
        id="selinux_not_enforcing",
        title="SELinux is not fully turned on",
        severity="high",
        description=(
            "SELinux is a security guard built into Red Hat and Rocky Linux that "
            "watches what every program is allowed to do, even ones that are "
            "already running."
        ),
        danger=(
            "If SELinux is off (or only 'permissive', meaning it watches but "
            "doesn't stop anything), a program that gets hacked can much more "
            "easily spread to other parts of the computer instead of being "
            "boxed in."
        ),
        fix_steps=[
            "Open a terminal.",
            "Type: sudo setenforce 1  (this turns it on right now).",
            "To keep it on after a restart, open /etc/selinux/config in a text "
            "editor (for example: sudo nano /etc/selinux/config).",
            "Find the line starting with SELINUX= and change it to: SELINUX=enforcing",
            "Save the file, then restart the computer.",
        ],
        applicable_os=_LINUX_OS,
        check=_check_selinux,
    ),
    Rule(
        id="firewall_inactive",
        title="The firewall is turned off",
        severity="high",
        description="firewalld is the built-in program that controls which network traffic is allowed in or out.",
        danger="With no firewall running, anyone who can reach this computer over the network can try to connect to anything on it, not just the things it's actually supposed to offer.",
        fix_steps=[
            "Open a terminal.",
            "Type: sudo systemctl enable --now firewalld",
            "That turns it on right now AND keeps it on after restarts.",
        ],
        applicable_os=_LINUX_OS,
        check=_check_firewall,
    ),
    Rule(
        id="ssh_root_login_permitted",
        title="Anyone can log in directly as the super-admin (root) user over the network",
        severity="high",
        description="SSH (the remote-login program) is currently allowing direct logins as 'root', the account with total control over the computer.",
        danger="If someone guesses or steals the root password, they instantly have complete control. Requiring a normal login first (and switching to admin power only when needed) means an attacker has to break through two locks instead of one.",
        fix_steps=[
            "Open a terminal with admin access.",
            "Open /etc/ssh/sshd_config in a text editor (for example: sudo nano /etc/ssh/sshd_config).",
            "Find the line with PermitRootLogin and change it to: PermitRootLogin no",
            "Save the file.",
            "Type: sudo systemctl restart sshd",
            "IMPORTANT: make sure you can log in as a normal user and use 'sudo' before you do this, or you could lock yourself out!",
        ],
        applicable_os=_LINUX_OS,
        check=_check_ssh_root_login,
    ),
    Rule(
        id="ssh_password_auth_enabled",
        title="Remote login (SSH) allows just typing a password",
        severity="medium",
        description="SSH can log people in with a typed password, or with a 'key' -- a special file that acts like an enormously long, impossible-to-guess password.",
        danger="Passwords can be guessed, stolen, or reused from a leak on another website. A stolen or leaked SSH key by itself is much less useful to an attacker without the matching private half, which never leaves your computer.",
        fix_steps=[
            "FIRST, set up an SSH key for yourself and make sure you can log in with it -- don't skip this or you may lock yourself out!",
            "Then open /etc/ssh/sshd_config in a text editor.",
            "Find PasswordAuthentication and change it to: PasswordAuthentication no",
            "Save the file, then type: sudo systemctl restart sshd",
        ],
        applicable_os=_LINUX_OS,
        check=_check_ssh_password_auth,
    ),
    Rule(
        id="ssh_empty_passwords_permitted",
        title="SSH would allow logging in with a BLANK password",
        severity="critical",
        description="The setting that controls whether an account with no password at all is allowed to log in over the network is turned on.",
        danger="This is one of the easiest ways to break into a computer -- no guessing required, just press Enter.",
        fix_steps=[
            "Open /etc/ssh/sshd_config in a text editor.",
            "Find PermitEmptyPasswords and change it to: PermitEmptyPasswords no",
            "Save the file, then type: sudo systemctl restart sshd",
        ],
        applicable_os=_LINUX_OS,
        check=_check_ssh_empty_passwords,
    ),
    Rule(
        id="ssh_x11_forwarding_enabled",
        title="SSH allows forwarding graphical program windows (X11 forwarding)",
        severity="low",
        description="This lets a program running on this computer show its window on the screen of whoever connected in over SSH.",
        danger="It's rarely needed on a server, and it adds an extra way a compromised remote display could be used against this machine.",
        fix_steps=[
            "Open /etc/ssh/sshd_config in a text editor.",
            "Find X11Forwarding and change it to: X11Forwarding no",
            "Save the file, then type: sudo systemctl restart sshd",
        ],
        applicable_os=_LINUX_OS,
        check=_check_ssh_x11_forwarding,
    ),
    Rule(
        id="empty_password_users",
        title="One or more accounts have no password set at all",
        severity="critical",
        description="Some user accounts on this computer have a completely blank password.",
        danger="Anyone who can reach the login screen (or physically sit down at the machine) can log in as that account without typing anything.",
        fix_steps=[
            "Open a terminal with admin access.",
            "For each account listed, either give it a real password: sudo passwd <the account name>",
            "...or, if that account shouldn't be able to log in at all, lock it instead: sudo usermod -L <the account name>",
        ],
        applicable_os=_LINUX_OS,
        check=_check_empty_password_users,
    ),
    Rule(
        id="duplicate_uid0_accounts",
        title="More than one account has full super-admin power",
        severity="critical",
        description="On Linux, the account with ID number 0 (normally just 'root') has complete, unrestricted power. This computer has another account sharing that same power.",
        danger="Only 'root' should have this. An attacker who finds the extra account could quietly use it to have full control while being less obvious than logging in as 'root' directly.",
        fix_steps=[
            "Open a terminal with admin access.",
            "Look at the file /etc/passwd (you can view it with: cat /etc/passwd) and find the extra account with :0: in it.",
            "If that account shouldn't have admin power, ask an experienced admin to help remove it or change its ID number -- this one is easy to get wrong, so double-check before changing anything.",
        ],
        applicable_os=_LINUX_OS,
        check=_check_duplicate_uid0,
    ),
    Rule(
        id="auto_updates_disabled",
        title="Automatic security updates are turned off",
        severity="high",
        description="dnf-automatic is the program that can download and install security fixes by itself on a schedule.",
        danger="New security holes are found in software all the time. Without automatic updates, this computer could stay open to a hole that's already publicly known and already fixed -- just not installed yet.",
        fix_steps=[
            "Open a terminal with admin access.",
            "Type: sudo dnf install -y dnf-automatic",
            "Type: sudo systemctl enable --now dnf-automatic.timer",
        ],
        applicable_os=_LINUX_OS,
        check=_check_auto_updates,
    ),
    Rule(
        id="auditd_inactive",
        title="The security activity log (auditd) is not running",
        severity="medium",
        description="auditd keeps a detailed diary of important things that happen on the computer -- who logged in, what changed, and when.",
        danger="Without it, if something bad does happen, there's a lot less evidence available to figure out what an attacker actually did.",
        fix_steps=[
            "Open a terminal with admin access.",
            "Type: sudo systemctl enable --now auditd",
        ],
        applicable_os=_LINUX_OS,
        check=_check_auditd,
    ),
    Rule(
        id="weak_password_minlen",
        title="Passwords are allowed to be very short",
        severity="medium",
        description="The minimum password length setting (pwquality) is shorter than recommended.",
        danger="Short passwords can be guessed by a computer program in seconds to minutes. Longer passwords take dramatically longer to crack.",
        fix_steps=[
            "Open /etc/security/pwquality.conf in a text editor with admin access.",
            "Find (or add) the line: minlen = 14",
            "Save the file. New passwords set after this will need to follow the new rule.",
        ],
        applicable_os=_LINUX_OS,
        check=_check_password_minlen,
    ),
    Rule(
        id="world_writable_files",
        title="Some important-looking files can be changed by anyone",
        severity="medium",
        description="A 'world-writable' file is one that any user on the computer -- not just its owner -- is allowed to edit.",
        danger="If a program a hacker snuck onto the computer can edit one of these files, and that file gets run or trusted later (like a startup script), the hacker's changes run too.",
        fix_steps=[
            "Open a terminal with admin access.",
            "For each file listed, first make sure it ISN'T supposed to be writable by everyone (some files, like ones in /tmp, genuinely are).",
            "If it shouldn't be, type: sudo chmod o-w <the file path>",
        ],
        applicable_os=_LINUX_OS,
        check=_check_world_writable,
    ),
    Rule(
        id="insecure_legacy_service_running",
        title="An old, unencrypted remote-access service is running",
        severity="high",
        description="A service like telnet, rsh, rlogin, or an unencrypted FTP server is currently running on this computer.",
        danger="These send passwords and data over the network in plain text. Anyone quietly listening on the same network -- which is much easier than most people realize -- can read everything, including passwords, instantly.",
        fix_steps=[
            "Open a terminal with admin access.",
            "For each old service listed, turn it off: sudo systemctl disable --now <the service name>",
            "Use SSH (and SFTP for file transfer) instead -- they do the same job, encrypted.",
        ],
        applicable_os=_LINUX_OS,
        check=_check_legacy_services,
    ),
    Rule(
        id="time_sync_inactive",
        title="The computer's clock isn't being kept in sync",
        severity="low",
        description="chronyd is the service that keeps this computer's clock accurate by checking it against trusted time servers.",
        danger="Security logs and secure connections depend on an accurate clock. If the clock drifts, it becomes much harder to piece together what happened during a security incident, since timestamps won't line up with other systems.",
        fix_steps=[
            "Open a terminal with admin access.",
            "Type: sudo systemctl enable --now chronyd",
        ],
        applicable_os=_LINUX_OS,
        check=_check_time_sync,
    ),
    Rule(
        id="password_never_expires",
        title="Passwords are set to never expire",
        severity="medium",
        description="The system-wide setting for how long a password can be used before it must be changed (PASS_MAX_DAYS) is disabled or set extremely high.",
        danger="If a password is ever stolen without anyone noticing, it stays useful to the thief forever instead of only until the next required change.",
        fix_steps=[
            "Open /etc/login.defs in a text editor with admin access.",
            "Find PASS_MAX_DAYS and change it to a reasonable number, like: PASS_MAX_DAYS 90",
            "For existing accounts, also run: sudo chage -M 90 <account name>",
        ],
        applicable_os=_LINUX_OS,
        check=_check_password_expiry,
    ),
    Rule(
        id="no_account_lockout_policy",
        title="There's no limit on how many times someone can guess a password wrong",
        severity="high",
        description="faillock (or an equivalent) locks an account for a while after too many wrong password attempts in a row. This computer doesn't appear to have that configured.",
        danger="Without a limit, an attacker (or, more likely, an automated program) can sit there guessing passwords millions of times in a row -- like trying every combination on a bike lock with nothing stopping them.",
        fix_steps=[
            "Open a terminal with admin access.",
            "On RHEL/Rocky 8, 9, or 10, type: sudo authselect enable-feature with-faillock",
            "Then type: sudo authselect apply-changes",
        ],
        applicable_os=_LINUX_OS,
        check=_check_account_lockout,
    ),
    Rule(
        id="passwordless_sudo",
        title="Some accounts can run admin commands without ever typing a password",
        severity="high",
        description="One or more entries in the sudoers configuration use NOPASSWD, meaning that account can run admin-level commands with zero password prompt.",
        danger="If that account's login session is ever hijacked -- even briefly, like an unlocked, unattended laptop -- the attacker instantly has full admin power with no extra proof required at all.",
        fix_steps=[
            "Open a terminal with admin access.",
            "Type: sudo visudo   (this safely opens the sudoers file for editing)",
            "Find the NOPASSWD entries listed and either remove NOPASSWD entirely, or narrow the line down to only the exact specific command that truly needs it.",
            "Save and exit -- visudo will check your changes for mistakes before saving.",
        ],
        applicable_os=_LINUX_OS,
        check=_check_passwordless_sudo,
    ),
]
