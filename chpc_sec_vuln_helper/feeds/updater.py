"""Keeps the local vulnerability feed(s) current -- the "is there an
update available?" prompt this whole module exists for, in the same
spirit as a game checking for a roster update on launch: check once,
ask, either fetch it or tell you exactly how to get it yourself.

RHEL/Rocky: a stable, official, directly-downloadable URL exists
(Red Hat's OVAL feed), so this can genuinely attempt an automatic
fetch when the network is reachable.

Windows: there's no equivalent stable download URL for MSRC's data --
only a manual browser export from the Security Update Guide portal.
This module can't automate that step honestly, so instead it watches
an `incoming/` drop folder inside the feed directory: export the CSV
from your browser, drop it there, and the next prompt offers to import
it -- the closest honest equivalent of an automatic update for a
source that fundamentally requires a manual step.
"""
from __future__ import annotations

import bz2
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import feed_store
from .normalize_msrc_csv import MsrcCsvError, parse_msrc_csv
from .normalize_rhel_oval import parse_oval
from .schema import NormalizedVuln

RHEL_OVAL_URL_TEMPLATE = "https://www.redhat.com/security/data/oval/v2/RHEL{major}/rhel-{major}.oval.xml.bz2"
MSRC_PORTAL_URL = "https://msrc.microsoft.com/update-guide/"

DEFAULT_STALE_AFTER_DAYS = 30

InputFunc = Callable[[str], str]
PrintFunc = Callable[..., None]


class FetchError(Exception):
    pass


def check_network(url: str, timeout: float = 5.0) -> bool:
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=timeout)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False
    except Exception:
        return False


def fetch_rhel_oval(major_version: int, feed_dir: Path, timeout: float = 90.0) -> feed_store.FeedInfo:
    """Downloads and normalizes the official Red Hat OVAL feed for one
    RHEL major version. Used for Rocky too (see normalize_rhel_oval's
    module docstring for why that's a reasonable approximation).
    Raises FetchError with a clear message on any failure -- never
    fails silently or partially writes a feed file.
    """
    url = RHEL_OVAL_URL_TEMPLATE.format(major=major_version)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            compressed = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise FetchError(f"Could not download {url}: {exc}") from exc

    try:
        xml_text = bz2.decompress(compressed).decode("utf-8")
    except OSError as exc:
        raise FetchError(f"Downloaded {url} but could not decompress it: {exc}") from exc

    vulns = parse_oval(xml_text, os_family="rhel")
    if not vulns:
        raise FetchError(f"Downloaded and parsed {url} but found zero usable advisories -- the feed format may have changed.")

    return _save_rhel_and_rocky(feed_dir, major_version, vulns, url)


def _save_rhel_and_rocky(feed_dir: Path, major_version: int, vulns: list[NormalizedVuln], url: str) -> feed_store.FeedInfo:
    feed_store.save_feed(feed_dir, "rhel", major_version, vulns, url)

    rocky_vulns = []
    for v in vulns:
        v2 = NormalizedVuln.from_dict(v.to_dict())
        v2.os_family = "rocky"
        rocky_vulns.append(v2)
    feed_store.save_feed(feed_dir, "rocky", major_version, rocky_vulns, url + " (reused for Rocky Linux -- see README)")

    return feed_store.get_feed_info(feed_dir, "rhel", major_version)


def import_msrc_csv_file(csv_path: Path, feed_dir: Path) -> list[feed_store.FeedInfo]:
    """Normalizes a manually-exported MSRC CSV and saves it, split by
    Windows major version (10 vs 11) since one export commonly covers
    both. Returns the FeedInfo for each version actually present.
    """
    csv_text = csv_path.read_text(encoding="utf-8-sig")  # -sig: MSRC exports are usually UTF-8 with a BOM
    vulns = parse_msrc_csv(csv_text)  # raises MsrcCsvError with a clear message on unrecognized columns

    by_version: dict[int, list[NormalizedVuln]] = {}
    for v in vulns:
        for major in v.os_major_versions:
            by_version.setdefault(major, []).append(v)

    infos = []
    for major, version_vulns in by_version.items():
        feed_store.save_feed(feed_dir, "windows", major, version_vulns, f"manual export: {csv_path.name}")
        infos.append(feed_store.get_feed_info(feed_dir, "windows", major))
    return infos


def _incoming_dir(feed_dir: Path) -> Path:
    return feed_dir / "incoming"


def find_pending_msrc_export(feed_dir: Path) -> Path | None:
    incoming = _incoming_dir(feed_dir)
    if not incoming.exists():
        return None
    candidates = sorted(incoming.glob("*.csv"))
    return candidates[-1] if candidates else None


def manual_rhel_instructions(major_version: int, feed_dir: Path) -> str:
    url = RHEL_OVAL_URL_TEMPLATE.format(major=major_version)
    return (
        f"On a machine WITH internet access:\n"
        f"  1. Download:  curl -O {url}\n"
        f"  2. Copy the downloaded .bz2 file onto this airgapped machine\n"
        f"     (however you move files over -- USB drive, etc.)\n"
        f"  3. On this machine, run:\n"
        f"     chpc-sec-vuln-helper update-feed --import-rhel-oval <path-to-file>.bz2 --os-version {major_version}\n"
        f"\n"
        f"(Rocky Linux {major_version} reuses this same RHEL {major_version} feed --\n"
        f"see the README for why that's a reasonable approximation.)"
    )


def manual_msrc_instructions(feed_dir: Path) -> str:
    incoming = _incoming_dir(feed_dir)
    return (
        f"There's no direct download URL for Microsoft's vulnerability data --\n"
        f"it has to come from a browser export:\n"
        f"  1. On a machine WITH internet access, open:\n"
        f"     {MSRC_PORTAL_URL}\n"
        f"  2. Filter to Windows 10 and/or Windows 11, then click Export -> CSV\n"
        f"  3. Copy the exported .csv file onto this airgapped machine, into:\n"
        f"     {incoming}\n"
        f"  4. Next time you run a scan (or run\n"
        f"     'chpc-sec-vuln-helper update-feed' again), this tool will notice\n"
        f"     it waiting there and offer to import it -- or import it directly now:\n"
        f"     chpc-sec-vuln-helper update-feed --import-msrc-csv <path-to-file>.csv"
    )


def prompt_update_if_stale(
    feed_dir: Path,
    os_family: str,
    os_major_version: int,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> None:
    """The "roster update" check: called at the start of a scan. Never
    raises -- a feed-update hiccup should never be the reason a scan
    can't run at all.
    """
    if os_family == "windows":
        _prompt_windows(feed_dir, os_major_version, input_func, print_func)
        return
    _prompt_rhel_family(feed_dir, os_family, os_major_version, stale_after_days, input_func, print_func)


def _prompt_rhel_family(feed_dir, os_family, os_major_version, stale_after_days, input_func, print_func) -> None:
    info = feed_store.get_feed_info(feed_dir, os_family, os_major_version)
    if info is None:
        print_func(f"No vulnerability feed found yet for {os_family} {os_major_version}.")
    elif info.age_days() > stale_after_days:
        print_func(f"Your {os_family} {os_major_version} vulnerability feed is {info.age_days()} days old.")
    else:
        return  # fresh enough, nothing to do

    answer = input_func("Check for an updated feed now? [Y/n]: ").strip().lower()
    if answer not in ("", "y", "yes"):
        return

    url = RHEL_OVAL_URL_TEMPLATE.format(major=os_major_version)
    if not check_network(url):
        print_func("No internet access detected. To update manually:\n")
        print_func(manual_rhel_instructions(os_major_version, feed_dir))
        return

    print_func(f"Internet access detected -- downloading {url} ...")
    try:
        new_info = fetch_rhel_oval(os_major_version, feed_dir)
        print_func(f"Updated: {new_info.vuln_count} advisories, fetched just now.")
    except FetchError as exc:
        print_func(f"Automatic update failed ({exc}). To update manually:\n")
        print_func(manual_rhel_instructions(os_major_version, feed_dir))


def _prompt_windows(feed_dir, os_major_version, input_func, print_func) -> None:
    pending = find_pending_msrc_export(feed_dir)
    info = feed_store.get_feed_info(feed_dir, "windows", os_major_version)

    if pending is not None:
        print_func(f"Found a waiting MSRC export: {pending.name}")
        answer = input_func("Import it now? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            try:
                infos = import_msrc_csv_file(pending, feed_dir)
                for i in infos:
                    print_func(f"Imported: windows {i.os_major_version} -- {i.vuln_count} advisories.")
            except MsrcCsvError as exc:
                print_func(f"Could not import {pending.name}: {exc}")
        return

    if info is None:
        print_func(f"No vulnerability feed found yet for Windows {os_major_version}.")
        answer = input_func("Show instructions for getting one? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            print_func(manual_msrc_instructions(feed_dir))
        return

    if info.age_days() > DEFAULT_STALE_AFTER_DAYS:
        print_func(f"Your Windows {os_major_version} vulnerability feed is {info.age_days()} days old.")
        answer = input_func("Show instructions for getting a newer one? [Y/n]: ").strip().lower()
        if answer in ("", "y", "yes"):
            print_func(manual_msrc_instructions(feed_dir))
