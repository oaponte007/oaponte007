"""Parses checks.conf -- the NHC-style DSL (see config/chpc_checks.example.conf).

    # comment
    <hostmask> || <builtin_check_name> [--flag value ...]
    <hostmask> || command || <any shell command line>

`hostmask` is matched against the local hostname with shell-glob semantics
(`*` matches everything, `gpu*` matches only hosts starting with "gpu"),
the same convention real NHC uses for a checks file shared across a whole
fleet via config management.

The `command || ...` form is special-cased: only the first two `||`
separators are meaningful, so the shell command itself may contain `||`,
`&&`, or pipes without confusing the parser.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import List

from .base import CheckSpec

_COMMAND_RE = re.compile(r"^\s*command\s*\|\|\s*(.*)$", re.S)


def parse_line(line: str) -> CheckSpec:
    if "||" not in line:
        raise ValueError(f"malformed checks.conf line (missing '||'): {line!r}")
    hostmask, rest = line.split("||", 1)
    hostmask = hostmask.strip()
    rest = rest.strip()
    if not hostmask:
        raise ValueError(f"malformed checks.conf line (empty hostmask): {line!r}")

    m = _COMMAND_RE.match(rest)
    if m:
        shell_cmd = m.group(1).strip()
        if not shell_cmd:
            raise ValueError(f"command check has no command: {line!r}")
        return CheckSpec(hostmask=hostmask, name="command", args=[shell_cmd], raw=line)

    try:
        parts = shlex.split(rest)
    except ValueError as exc:
        raise ValueError(f"malformed checks.conf line ({exc}): {line!r}") from exc
    if not parts:
        raise ValueError(f"malformed checks.conf line (no check name): {line!r}")
    name, check_args = parts[0], parts[1:]
    return CheckSpec(hostmask=hostmask, name=name, args=check_args, raw=line)


def parse_file(path: Path) -> List[CheckSpec]:
    specs = []
    for lineno, raw_line in enumerate(Path(path).read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            specs.append(parse_line(line))
        except ValueError as exc:
            raise ValueError(f"{path}:{lineno}: {exc}") from exc
    return specs
