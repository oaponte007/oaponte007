# CHPC_sec_vuln_helper

Audits RHEL/Rocky (8, 9, 10) and Windows (10, 11) hosts for security
weaknesses on a fully airgapped machine, and produces a branded,
plain-English report — a `.docx` and/or a self-contained `.html` (open
it in any browser, then Print → Save as PDF) — that anyone can act on,
even with no IT background. Fixing what it finds is left entirely up
to you; nothing this tool does changes anything on the scanned
machine.

Two independent kinds of findings, always labeled apart so you know
which is which:

- **Baseline/hardening findings** — real settings checked against a
  known-good baseline (SELinux, firewall, SSH config, password policy,
  Windows Defender, BitLocker, ...). Fully self-contained, no data
  feed needed, never goes stale.
- **CVE findings** — installed package/patch versions matched against
  an official offline vulnerability feed (Red Hat's OVAL data for
  RHEL/Rocky, Microsoft's Security Update Guide export for Windows)
  that you import periodically. Only as current as your last import —
  the report always says exactly how old the feed was when it ran.

## The three steps

1. **`collect`** — run on the target machine itself. Gathers real,
   current state into one JSON file. Zero dependencies: Python 3
   standard library on Linux, built-in PowerShell on Windows. This is
   the piece that has to work on the actual airgapped box.
2. **`update-feed`** — keeps the CVE data current, with a "roster
   update" style prompt: checks if your feed is missing or old, offers
   to fetch it automatically if online, or prints exact manual
   instructions if not. See **Keeping the CVE feed current**, below.
3. **`scan`** — evaluates a collected JSON file against the baseline
   rules and (if present) the CVE feed, and writes the branded report.
   Needs `python-docx` for the `.docx` output specifically — see
   **Requirements**.

These three steps don't have to run on the same machine. A common
pattern: `collect` on the airgapped target, copy the resulting JSON
off (however you move files today), then `update-feed` and `scan` on
an admin workstation that has `python-docx` installed and can build
the pretty report.

## Requirements

- **`collect`**: nothing beyond what ships with the OS. Python 3.9+
  (already on RHEL/Rocky), or built-in PowerShell (already on
  Windows 10/11). No `pip install`, no network.
- **`update-feed`**: same — nothing extra to fetch/import a feed file.
  A live *download* additionally needs network access, obviously; the
  manual-import path never does.
- **`scan`**: Python 3.9+, and `python-docx` **only if you want the
  `.docx` report** (`pip install python-docx`). The `.html` report has
  no extra dependency at all and works everywhere; if `python-docx`
  isn't installed, `scan` automatically falls back to HTML-only rather
  than failing.

If the machine building the report is *also* airgapped, get
`python-docx` onto it the same way you'd get anything else there: on a
connected machine, run `pip download python-docx -d wheels/`, copy the
`wheels/` folder over, then `pip install --no-index --find-links wheels/ python-docx`.

## Running it

### On a RHEL/Rocky 8, 9, or 10 target (collect)

```bash
sudo python3 -m chpc_sec_vuln_helper collect -o collected.json
```

(`sudo` matters — some checks, like accounts with no password, need
root to read `/etc/shadow`; anything that can't be checked without
more privilege is skipped and noted, never guessed at.)

Or use the launcher directly: `sudo chmod +x chpc_sec_vuln_helper/bin/chpc-sec-vuln-helper && sudo ./chpc_sec_vuln_helper/bin/chpc-sec-vuln-helper collect -o collected.json`

### On a Windows 10 or 11 target (collect)

Run as Administrator for full coverage:

```powershell
powershell -ExecutionPolicy Bypass -File chpc_sec_vuln_helper\collectors\windows_collector.ps1 -OutputPath collected.json
```

### Keeping the CVE feed current

```bash
python3 -m chpc_sec_vuln_helper update-feed --os-family rhel --os-version 9
```

- **If this machine has internet access**: it downloads Red Hat's
  official OVAL feed directly and imports it (Rocky Linux reuses the
  same feed — see **Why Rocky uses the RHEL feed**, below).
- **If it doesn't**: it prints the exact URL to fetch on a connected
  machine, where to copy the downloaded file, and the import command
  to run once it's here.

For Windows, there's no equivalent direct-download URL — Microsoft's
data only comes from a manual browser export. Drop the exported CSV
into `<feed-dir>/incoming/`, and the next `update-feed` (or `scan`)
run will notice it waiting there and offer to import it:

```bash
python3 -m chpc_sec_vuln_helper update-feed --import-msrc-csv path/to/export.csv
```

Check what's currently loaded:

```bash
python3 -m chpc_sec_vuln_helper list-feeds
```

### Scanning and building the report

```bash
python3 -m chpc_sec_vuln_helper scan collected.json --out security_report --format both
```

This is also where the "roster update" prompt appears if the loaded
feed is missing or more than 30 days old — answer once, or pass
`--yes` to skip the prompt and just use whatever's already loaded
(useful for scripting/automation), or `--no-feed-prompt` to suppress
it entirely.

## Why Rocky uses the RHEL feed

Rocky Linux is a binary-compatible downstream rebuild of RHEL — same
source packages, same versions, same fixes, typically released within
hours of the upstream RHEL advisory. Rocky's own security team
explicitly points users at RHEL's own advisories for exactly this
reason. Maintaining a second, separate OVAL parser for Rocky's smaller
advisory feed would mean more code with no real gain in accuracy.

## A note on honesty

This tool cannot promise to find "all" vulnerabilities — no offline
tool can, without a live, constantly-updated CVE database, which is
exactly the thing an airgapped machine doesn't have. What it promises
instead: baseline checks that are always accurate (they check real
settings, not a database), and CVE matching that's exactly as current
as the feed you last imported, with the report always stating that
date plainly rather than implying more confidence than the data
actually supports.

## Development

```bash
python3 -m pytest tests_chpc_sec_vuln_helper/
```

74 tests: the RPM version-comparison algorithm (verified against RPM's
own canonical test vectors), the baseline rule engine (both rule
sets, against deliberately good/bad synthetic configs, plus a check
that a non-RHEL/Rocky host correctly gets zero findings instead of
being silently mislabeled), the RHEL OVAL and MSRC CSV normalizers and
matchers (against realistic synthetic feed samples — this could not
be tested against a real downloaded feed in the environment this was
built in; spot-check it against a live feed the first chance you get),
the feed store and updater (including the offline-fallback path,
which matters most for the actual airgap use case), and the report
generators (both `.docx` and `.html`, including that a single advisory
affecting multiple packages renders as one finding, not several
near-duplicates).

The `windows_collector.ps1` script could not be executed or
syntax-tested in the Linux environment it was written in either --
written carefully against well-established, stable cmdlets, but
spot-check its output on a real Windows 10/11 machine before relying
on it.
