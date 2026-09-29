"""Python-specific wiring over the shared chpc_helper_core CLI.

The one thing genuinely different from chpc_bash_helper: a variable's
raw text can't be embedded directly into a Python string literal the
way it can into bash or YAML -- an unescaped quote or backslash in a
node name or command would corrupt the generated script's syntax (or
worse). ``_prepare_variables`` runs every variable through ``repr()``
(or, for ``int``-typed variables, a validated bare numeral) before
rendering, so every ``*.py.tmpl`` template writes ``NAME = {{VAR}}``
with no manual quoting and gets a safely escaped Python literal out the
other end.
"""
from __future__ import annotations

from pathlib import Path

from chpc_helper_core.checks import python_syntax_check
from chpc_helper_core.cli import AppConfig
from chpc_helper_core.cli import build_parser as _build_parser
from chpc_helper_core.cli import main as _main
from chpc_helper_core.library import Template

LIBRARY_DIR = Path(__file__).resolve().parent / "library"


def _prepare_variables(template: Template, variables: dict[str, str]) -> dict[str, str]:
    prepared: dict[str, str] = {}
    for var in template.variables:
        raw = variables[var.name]
        if var.type == "int":
            prepared[var.name] = str(int(raw))  # bare numeral, no quotes
        else:
            prepared[var.name] = repr(raw)
    return prepared


CONFIG = AppConfig(
    prog="chpc-python-helper",
    tagline="Build a Python 3 script for an airgapped RHEL/Rocky/Debian system from a library of vetted templates.",
    library_dir=LIBRARY_DIR,
    template_ext=".py.tmpl",
    default_out_ext=".py",
    syntax_checker=python_syntax_check,
    syntax_check_label="python3 -m py_compile",
    executable=True,
    prepare_variables=_prepare_variables,
)


def build_parser():
    return _build_parser(CONFIG)


def main(argv: list[str] | None = None) -> int:
    return _main(argv, CONFIG)


if __name__ == "__main__":
    raise SystemExit(main())
