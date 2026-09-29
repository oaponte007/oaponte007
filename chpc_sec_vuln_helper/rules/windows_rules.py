"""Baseline/hardening rules for Windows 10 and 11. Every check reads
the collected-data dict produced by collectors/windows_collector.ps1
-- see that script's header comment for the exact field names.
"""
from __future__ import annotations

from .engine import Rule, fail, ok

_WINDOWS_OS = ["windows"]


def _check_defender(data):
    defender = data.get("defender")
    if defender is None:
        return None
    if not defender.get("enabled", True):
        return fail("Windows Defender is turned off.")
    if not defender.get("real_time_protection", True):
        return fail("Windows Defender real-time protection is turned off.")
    return ok()


def _check_firewall(data):
    active = data.get("firewall_active")
    if active is None:
        return None
    if not active:
        return fail("At least one Windows Firewall profile is turned off.")
    return ok()


def _check_smb1(data):
    enabled = data.get("smb1_enabled")
    if enabled is None:
        return None
    if enabled:
        return fail("SMBv1 (the old file-sharing protocol) is enabled.")
    return ok()


def _check_rdp(data):
    rdp = data.get("rdp")
    if rdp is None:
        return None
    if rdp.get("enabled") and not rdp.get("network_level_authentication", True):
        return fail("Remote Desktop is enabled without Network Level Authentication required.")
    return ok()


def _check_auto_updates(data):
    enabled = data.get("auto_updates_enabled")
    if enabled is None:
        return None
    if not enabled:
        return fail("Automatic Windows Updates are disabled or paused.")
    return ok()


def _check_min_password_length(data):
    policy = data.get("local_password_policy")
    if policy is None or policy.get("min_length") is None:
        return None
    if policy["min_length"] < 14:
        return fail(f"Minimum password length is {policy['min_length']} (should be 14 or more).")
    return ok()


def _check_lockout_threshold(data):
    policy = data.get("local_password_policy")
    if policy is None or policy.get("lockout_threshold") is None:
        return None
    threshold = policy["lockout_threshold"]
    if threshold == 0:
        return fail("Account lockout threshold is 0 -- unlimited password attempts are allowed.")
    return ok()


def _check_guest_account(data):
    enabled = data.get("guest_account_enabled")
    if enabled is None:
        return None
    if enabled:
        return fail("The built-in Guest account is enabled.")
    return ok()


def _check_uac(data):
    enabled = data.get("uac_enabled")
    if enabled is None:
        return None
    if not enabled:
        return fail("User Account Control (UAC) is turned off.")
    return ok()


def _check_bitlocker(data):
    status = data.get("bitlocker_system_drive_status")
    if status is None:
        return None
    if status not in ("on", "encrypted", "fullyencrypted"):
        return fail(f"BitLocker on the system drive is not fully on (status: {status}).")
    return ok()


def _check_smartscreen(data):
    enabled = data.get("smartscreen_enabled")
    if enabled is None:
        return None
    if not enabled:
        return fail("Windows SmartScreen is turned off.")
    return ok()


def _check_powershell_execution_policy(data):
    policy = data.get("powershell_execution_policy")
    if policy is None:
        return None
    if policy.lower() == "unrestricted":
        return fail("PowerShell execution policy is 'Unrestricted' -- any script can run without asking.")
    return ok()


def _check_remote_registry(data):
    running = data.get("remote_registry_running")
    if running is None:
        return None
    if running:
        return fail("The Remote Registry service is running.")
    return ok()


def _check_autoplay(data):
    enabled = data.get("autoplay_enabled")
    if enabled is None:
        return None
    if enabled:
        return fail("AutoPlay for removable media (like USB drives) is enabled.")
    return ok()


WINDOWS_RULES: list[Rule] = [
    Rule(
        id="defender_disabled",
        title="Windows Defender (the built-in antivirus) isn't fully protecting this computer",
        severity="critical",
        description="Windows Defender, or its real-time protection specifically, is turned off.",
        danger="Without active antivirus protection, malicious programs -- viruses, ransomware, spyware -- can run completely unchecked.",
        fix_steps=[
            "Click the Start button.",
            "Type: Windows Security, and open it.",
            "Click 'Virus & threat protection'.",
            "If 'Real-time protection' is off, turn it back on.",
            "If it's greyed out, that usually means another antivirus program is installed and in charge instead -- that's fine as long as SOMETHING is protecting you.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_defender,
    ),
    Rule(
        id="firewall_disabled",
        title="Windows Firewall is turned off for at least one network type",
        severity="high",
        description="Windows Firewall controls which network traffic is allowed in or out, separately for private, public, and domain networks.",
        danger="With the firewall off, anything on the network can try to connect to anything on this computer, not just the things it's supposed to offer.",
        fix_steps=[
            "Click the Start button and type: Windows Security, then open it.",
            "Click 'Firewall & network protection'.",
            "For each network type shown (Domain, Private, Public), make sure the firewall is turned On.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_firewall,
    ),
    Rule(
        id="smb1_enabled",
        title="The old, unsafe file-sharing protocol (SMBv1) is turned on",
        severity="critical",
        description="SMBv1 is an outdated way for computers to share files and printers over a network.",
        danger="SMBv1 is the exact protocol the WannaCry ransomware worm used in 2017 to spread itself automatically to hundreds of thousands of computers in a single day. Modern Windows doesn't need it turned on.",
        fix_steps=[
            "Click the Start button and type: PowerShell.",
            "Right-click 'Windows PowerShell' and choose 'Run as administrator'.",
            "Type: Disable-WindowsOptionalFeature -Online -FeatureName SMB1Protocol -NoRestart",
            "Restart the computer when convenient.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_smb1,
    ),
    Rule(
        id="rdp_without_nla",
        title="Remote Desktop is on but doesn't require the extra login check (NLA)",
        severity="high",
        description="Remote Desktop lets someone control this computer from elsewhere. Network Level Authentication (NLA) makes them prove who they are BEFORE a full remote session even starts.",
        danger="Without NLA, more of the connection process happens before any identity check, giving an attacker more to attack. Remote Desktop is one of the most common ways ransomware gangs first get into a network.",
        fix_steps=[
            "Click the Start button and type: Remote Desktop settings, then open it.",
            "If you don't actually need Remote Desktop, turn it off entirely.",
            "If you do need it, make sure 'Require devices to use Network Level Authentication' is checked (this may be under Advanced settings or System Properties > Remote).",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_rdp,
    ),
    Rule(
        id="auto_updates_disabled",
        title="Automatic Windows Updates are turned off or paused",
        severity="high",
        description="Windows Update installs security fixes automatically on a schedule.",
        danger="New security holes are found in software constantly. Without automatic updates, this computer can stay open to a hole that's already publicly known -- and already fixed -- for weeks or months longer than necessary.",
        fix_steps=[
            "Click the Start button and open Settings.",
            "Click 'Windows Update'.",
            "Click 'Advanced options' and make sure updates aren't paused.",
            "Turn on 'Receive updates for other Microsoft products' too, if you see that option.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_auto_updates,
    ),
    Rule(
        id="weak_min_password_length",
        title="Passwords are allowed to be very short",
        severity="medium",
        description="The local security policy's minimum password length is shorter than recommended.",
        danger="Short passwords can be guessed by a computer program in seconds to minutes.",
        fix_steps=[
            "Click the Start button and type: cmd.",
            "Right-click 'Command Prompt' and choose 'Run as administrator'.",
            "Type: net accounts /minpwlen:14",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_min_password_length,
    ),
    Rule(
        id="no_lockout_threshold",
        title="There's no limit on how many times someone can guess a password wrong",
        severity="high",
        description="The account lockout threshold (how many wrong password attempts before the account locks) is set to 0 -- unlimited.",
        danger="Without a limit, an attacker (or, more likely, an automated program) can sit there guessing passwords over and over, as many times as it wants.",
        fix_steps=[
            "Click the Start button and type: cmd.",
            "Right-click 'Command Prompt' and choose 'Run as administrator'.",
            "Type: net accounts /lockoutthreshold:5",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_lockout_threshold,
    ),
    Rule(
        id="guest_account_enabled",
        title="The built-in 'Guest' account is turned on",
        severity="high",
        description="Windows has a built-in Guest account meant for temporary, no-login access.",
        danger="It's a well-known account name with no real owner watching it. Attackers specifically check whether it's enabled as an easy way in.",
        fix_steps=[
            "Click the Start button and type: cmd.",
            "Right-click 'Command Prompt' and choose 'Run as administrator'.",
            "Type: net user guest /active:no",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_guest_account,
    ),
    Rule(
        id="uac_disabled",
        title="User Account Control (UAC) is turned off",
        severity="critical",
        description="UAC is the pop-up window that asks 'Are you sure you want to allow this?' before a program can make big changes to the computer.",
        danger="Without it, ANY program -- including one secretly placed on the computer by a hacker -- can silently make admin-level changes without ever asking you.",
        fix_steps=[
            "Click the Start button and type: UAC, then open 'Change User Account Control settings'.",
            "Move the slider up from the bottom (at least to the second notch).",
            "Click OK.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_uac,
    ),
    Rule(
        id="bitlocker_disabled",
        title="The hard drive isn't encrypted (BitLocker is off)",
        severity="high",
        description="BitLocker scrambles everything on the hard drive so it can only be read with the right key.",
        danger="If this laptop or computer is ever lost or stolen, anyone can take the hard drive out, plug it into another computer, and read every file on it -- photos, documents, even saved passwords -- without ever needing to know the Windows login password.",
        fix_steps=[
            "Click the Start button and type: BitLocker, then open 'Manage BitLocker'.",
            "Turn it on for the main drive (usually C:).",
            "Follow the setup wizard.",
            "IMPORTANT: when it asks, SAVE THE RECOVERY KEY somewhere safe (printed out, or in your Microsoft account) -- you will need it if something goes wrong, and there is no other way to get your files back without it.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_bitlocker,
    ),
    Rule(
        id="smartscreen_disabled",
        title="Windows SmartScreen is turned off",
        severity="medium",
        description="SmartScreen warns before opening a file or website with a bad reputation.",
        danger="Without it, one of Windows' built-in warnings before running a known-bad download or visiting a known-bad website is gone.",
        fix_steps=[
            "Click the Start button and type: Windows Security, then open it.",
            "Click 'App & browser control'.",
            "Turn 'Reputation-based protection' back on.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_smartscreen,
    ),
    Rule(
        id="powershell_unrestricted",
        title="PowerShell will run any script without asking",
        severity="high",
        description="PowerShell's execution policy controls whether scripts need to be verified before they're allowed to run. It's currently set to 'Unrestricted'.",
        danger="This makes it much easier for a malicious script -- for example, one hidden in an email attachment or a bad download -- to run instantly with no warning at all.",
        fix_steps=[
            "Click the Start button and type: PowerShell.",
            "Right-click 'Windows PowerShell' and choose 'Run as administrator'.",
            "Type: Set-ExecutionPolicy RemoteSigned",
            "Type Y and press Enter to confirm.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_powershell_execution_policy,
    ),
    Rule(
        id="remote_registry_running",
        title="The 'Remote Registry' service is running",
        severity="medium",
        description="This service lets other computers on the network read and change deep system settings on this one, remotely.",
        danger="It's rarely needed on a normal computer and is a favorite target once an attacker is already on the same network -- it can be used to quietly change important settings from another machine.",
        fix_steps=[
            "Click the Start button and type: Services, then open it.",
            "Find 'Remote Registry' in the list.",
            "Right-click it, choose Properties.",
            "Set 'Startup type' to Disabled, click Stop if it's running, then click OK.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_remote_registry,
    ),
    Rule(
        id="autoplay_enabled",
        title="AutoPlay for USB drives and other removable media is turned on",
        severity="medium",
        description="AutoPlay automatically opens or runs something when a USB drive or disc is plugged in or inserted.",
        danger="This is a classic way malware spreads -- a bad USB drive plugged into the computer can start running a program automatically, before anyone clicks anything.",
        fix_steps=[
            "Click the Start button and type: AutoPlay settings, then open it.",
            "Turn off 'Use AutoPlay for all media and devices'.",
        ],
        applicable_os=_WINDOWS_OS,
        check=_check_autoplay,
    ),
]
