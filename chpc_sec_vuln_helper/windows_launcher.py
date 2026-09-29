"""Double-click entry point for Windows: a plain-text menu wrapping the same
collect / update-feed / scan steps the command line (`python -m
chpc_sec_vuln_helper ...`) exposes -- for anyone who would rather not type
PowerShell or Python commands at all.

This file is what gets frozen into a standalone chpc-sec-vuln-helper.exe by
build_windows_exe.bat (PyInstaller). It calls straight into the same
functions cli.py uses, so both entry points always behave identically --
this is a second front door, not a second implementation.

Building the .exe has to happen ON a Windows machine (see
build_windows_exe.bat) -- there is no way to produce a working Windows
binary from a Linux/Mac dev machine.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import cli
from .feeds import feed_store


def _bundled_collector_script() -> Path:
    # When frozen by PyInstaller, data files added with --add-data land
    # under sys._MEIPASS; when running unfrozen (e.g. `python -m
    # chpc_sec_vuln_helper.windows_launcher`), use the real package path.
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    candidates = [
        base / "collectors" / "windows_collector.ps1",
        Path(__file__).resolve().parent / "collectors" / "windows_collector.ps1",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "Could not find collectors/windows_collector.ps1 -- if you built this "
        ".exe yourself, make sure build_windows_exe.bat's --add-data path is correct."
    )


def _prompt(msg: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{msg}{suffix}: ").strip()
    return answer or default


def do_collect() -> None:
    print("\n== Collect ==")
    print("This runs the same collector as collectors\\windows_collector.ps1,")
    print("via PowerShell, and needs no other installs.")
    out = _prompt("Output file", "collected.json")
    script = _bundled_collector_script()
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script), "-OutputPath", out],
    )
    if result.returncode != 0:
        print(f"Collector exited with code {result.returncode} -- see the messages above.")


def do_update_feed() -> None:
    print("\n== Update vulnerability feed ==")
    family = _prompt("OS family (rhel / rocky) -- leave blank to import a file instead", "")
    feed_dir = feed_store.DEFAULT_FEED_DIR
    if family:
        version = _prompt("OS major version (e.g. 9)", "")
        if not version.isdigit():
            print("That doesn't look like a number -- cancelled.")
            return
        from .feeds import updater
        updater.prompt_update_if_stale(feed_dir, family, int(version), input_func=input, print_func=print)
        return
    path_str = _prompt("Path to a downloaded RHEL OVAL (.xml/.xml.bz2) or MSRC CSV file", "")
    if not path_str:
        print("Nothing to do.")
        return
    path = Path(path_str)
    if not path.exists():
        print(f"No such file: {path}")
        return
    if path.suffix.lower() == ".csv":
        from .feeds import updater
        infos = updater.import_msrc_csv_file(path, feed_dir)
        for i in infos:
            print(f"Imported: windows {i.os_major_version} -- {i.vuln_count} advisories.")
    else:
        version = _prompt("OS major version this OVAL file is for (e.g. 9)", "")
        if not version.isdigit():
            print("That doesn't look like a number -- cancelled.")
            return
        import bz2
        from .feeds import updater
        from .feeds.normalize_rhel_oval import parse_oval
        raw = path.read_bytes()
        xml_text = bz2.decompress(raw).decode("utf-8") if path.suffix == ".bz2" else raw.decode("utf-8")
        vulns = parse_oval(xml_text)
        info = updater._save_rhel_and_rocky(feed_dir, int(version), vulns, f"manual import: {path.name}")
        print(f"Imported: rhel {version} and rocky {version} -- {info.vuln_count} advisories.")


def do_list_feeds() -> None:
    print("\n== Loaded feeds ==")
    infos = feed_store.list_feeds(feed_store.DEFAULT_FEED_DIR)
    if not infos:
        print("No feeds loaded yet.")
        return
    for info in infos:
        print(f"{info.os_family:8s} {info.os_major_version:<4} {info.vuln_count:5d} advisories  "
              f"fetched {info.fetched_at}  ({info.age_days()}d old)")


def do_scan() -> None:
    print("\n== Scan + build report ==")
    collected = _prompt("Path to the collected JSON file", "collected.json")
    if not Path(collected).exists():
        print(f"No such file: {collected}")
        return
    out = _prompt("Report output path (without extension)", "security_report")
    fmt = _prompt("Format: docx / html / both", "both").lower()
    if fmt not in ("docx", "html", "both"):
        fmt = "both"

    class _Args:
        pass

    args = _Args()
    args.collected_json = collected
    args.feed_dir = str(feed_store.DEFAULT_FEED_DIR)
    args.out = out
    args.format = fmt
    args.no_feed_prompt = False
    args.yes = False
    cli.cmd_scan(args)


def main() -> int:
    print("Coastal HPC -- chpc_sec_vuln_helper")
    print("Where High Performance Meets High Security.\n")
    actions = {
        "1": ("Collect this machine's state", do_collect),
        "2": ("Update the vulnerability feed", do_update_feed),
        "3": ("List loaded feeds", do_list_feeds),
        "4": ("Scan a collected file and build the report", do_scan),
        "5": ("Quit", None),
    }
    while True:
        print("\nWhat would you like to do?")
        for key, (label, _) in actions.items():
            print(f"  {key}) {label}")
        choice = input("> ").strip()
        entry = actions.get(choice)
        if entry is None:
            print("Please enter one of the numbers above.")
            continue
        label, func = entry
        if func is None:
            return 0
        try:
            func()
        except Exception as exc:  # noqa: BLE001 -- top-level menu loop, must never crash silently
            print(f"\nSomething went wrong: {exc}")
        input("\nPress Enter to return to the menu...")


if __name__ == "__main__":
    raise SystemExit(main())
