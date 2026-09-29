"""Pluggable syntax checkers: each takes a written-out file path and
returns (passed, message) without ever executing what the file does --
only a parse/syntax check. Each app (bash/python/ansible/...) picks the
one that fits what it generates. Every one degrades gracefully (returns
"passed" with an explanatory message) if the tool it needs isn't on this
machine -- generating a script should never fail just because the box
building it doesn't happen to have, say, `ansible-playbook` installed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def bash_syntax_check(script_path: Path) -> tuple[bool, str]:
    """`bash -n`: parses the script without running any of it."""
    try:
        result = subprocess.run(
            ["bash", "-n", str(script_path)], capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        return True, "bash not found on this machine -- skipped syntax check"
    if result.returncode == 0:
        return True, ""
    return False, result.stderr.strip()


def python_syntax_check(script_path: Path) -> tuple[bool, str]:
    """`python3 -m py_compile`: compiles to bytecode without running it."""
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(script_path)],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        return True, ""
    return False, (result.stderr or result.stdout).strip()


def yaml_syntax_check(script_path: Path) -> tuple[bool, str]:
    """Prefers `ansible-playbook --syntax-check` (also validates module
    names/argument shapes, not just YAML), falls back to a plain YAML
    parse via PyYAML if ansible isn't installed on this machine, and
    skips gracefully if neither is available. The message always says
    which of the three actually ran, on success as well as failure, so
    a caller never reports "ansible-playbook --syntax-check" for a
    result that really came from the PyYAML fallback.
    """
    try:
        result = subprocess.run(
            ["ansible-playbook", "--syntax-check", str(script_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, "ansible-playbook --syntax-check"
        return False, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        pass

    try:
        import yaml
    except ImportError:
        return True, "neither ansible-playbook nor PyYAML found on this machine -- skipped syntax check"

    try:
        with open(script_path) as f:
            list(yaml.safe_load_all(f))
    except yaml.YAMLError as exc:
        return False, str(exc)
    return True, "plain YAML structural check via PyYAML (ansible-playbook not found on this machine)"
