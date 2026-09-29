"""CHPC_sec_vuln_helper -- audits RHEL/Rocky (8, 9, 10) and Windows
(10, 11) hosts for security weaknesses on a fully airgapped machine,
and produces a branded, plain-English report a non-technical reader
can act on.

Two independent kinds of findings, always clearly labeled apart:

- **Baseline/hardening findings**: CIS-benchmark-style checks of actual
  settings (SELinux, firewall, SSH config, password policy, Windows
  Defender, ...). Fully self-contained -- no data feed needed, always
  accurate, works forever with zero maintenance.
- **CVE findings**: installed package/patch versions matched against
  an official offline vulnerability feed (Red Hat's OVAL data for
  RHEL/Rocky, Microsoft's Security Update Guide export for Windows)
  that you import periodically. Only as current as your last import --
  this tool is upfront about that rather than pretending otherwise.

Collecting data on the target machine needs nothing beyond what ships
with the OS (Python 3 stdlib on Linux, built-in PowerShell on Windows).
Generating the branded .docx report needs `python-docx`, on whichever
machine you run that step from -- not necessarily the airgapped target
itself. See README.md.
"""

__version__ = "0.1.0"
