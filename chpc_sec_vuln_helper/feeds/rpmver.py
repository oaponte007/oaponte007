"""RPM version comparison (the `rpmvercmp` algorithm), pure Python, no
dependencies -- this is what lets the CVE matcher correctly decide
whether an *installed* package version is older than the *fixed*
version an advisory names, exactly the same way `rpm`/`dnf` themselves
compare versions.

The algorithm (unchanged from RPM's own C implementation, ported
faithfully): walk both strings extracting alternating runs of digits
and non-digit "alpha" characters (anything else is a separator and is
skipped); compare each pair of runs -- numeric runs compare as
integers (after stripping leading zeros), alpha runs compare
byte-for-byte, and a numeric run is always considered newer than an
alpha run at the same position. Whichever string still has real
content after the other is exhausted is newer.
"""
from __future__ import annotations

import re

_ALNUM_RUN_RE = re.compile(r"(\d+|[a-zA-Z]+)")


def rpmvercmp(a: str, b: str) -> int:
    """Returns -1, 0, or 1, comparing two version or release strings
    the way RPM does (not the same as a plain string or float compare:
    "10" > "9", "1.0" == "1.0", "a" < "1", "2.0.1" > "2.0").
    """
    if a == b:
        return 0

    a_tokens = _ALNUM_RUN_RE.findall(a)
    b_tokens = _ALNUM_RUN_RE.findall(b)

    for a_tok, b_tok in zip(a_tokens, b_tokens):
        a_is_digit = a_tok[0].isdigit()
        b_is_digit = b_tok[0].isdigit()

        if a_is_digit and not b_is_digit:
            return 1  # a numeric segment always outranks an alpha segment
        if b_is_digit and not a_is_digit:
            return -1

        if a_is_digit:  # both digit runs
            a_stripped = a_tok.lstrip("0") or "0"
            b_stripped = b_tok.lstrip("0") or "0"
            if len(a_stripped) != len(b_stripped):
                return 1 if len(a_stripped) > len(b_stripped) else -1
            if a_stripped != b_stripped:
                return 1 if a_stripped > b_stripped else -1
        else:  # both alpha runs
            if a_tok != b_tok:
                return 1 if a_tok > b_tok else -1

    if len(a_tokens) != len(b_tokens):
        return 1 if len(a_tokens) > len(b_tokens) else -1
    return 0


def compare_evr(evr_a: str, evr_b: str) -> int:
    """Compares two full epoch:version-release strings (epoch and/or
    release may be absent -- a bare "1.2.3" is treated as epoch 0, no
    release). Returns -1, 0, or 1.
    """
    epoch_a, version_a, release_a = _split_evr(evr_a)
    epoch_b, version_b, release_b = _split_evr(evr_b)

    if epoch_a != epoch_b:
        return 1 if epoch_a > epoch_b else -1

    version_cmp = rpmvercmp(version_a, version_b)
    if version_cmp != 0:
        return version_cmp

    if release_a is None or release_b is None:
        return 0  # neither side specified a release to compare

    return rpmvercmp(release_a, release_b)


def _split_evr(evr: str) -> tuple[int, str, str | None]:
    epoch = 0
    rest = evr
    if ":" in rest:
        epoch_str, rest = rest.split(":", 1)
        epoch = int(epoch_str) if epoch_str.isdigit() else 0
    if "-" in rest:
        version, release = rest.rsplit("-", 1)
    else:
        version, release = rest, None
    return epoch, version, release


def is_vulnerable(installed_evr: str, fixed_evr: str) -> bool:
    """True if the installed version is strictly older than the
    version an advisory says fixes the issue.
    """
    return compare_evr(installed_evr, fixed_evr) < 0
