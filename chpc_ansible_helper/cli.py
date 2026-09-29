"""Ansible-specific wiring over the shared chpc_helper_core CLI.

Like chpc_python_helper, a variable's raw text can't be embedded
directly into YAML without risking broken syntax (a colon, a leading
``*``/``&``/``!``, a value that looks like a YAML boolean/number, an
unescaped quote -- all have special meaning in plain YAML scalars).
``_prepare_variables`` runs every string variable through ``json.dumps``
-- JSON string syntax is a valid subset of YAML's double-quoted scalar
syntax, so this is a correct, dependency-free way to always produce a
safely quoted YAML scalar without needing PyYAML installed just to
*generate* a playbook. Every ``*.yml.tmpl`` template writes
``key: {{VAR}}`` with no manual quoting.

Deliberately NOT a hard dependency: PyYAML is only ever used, best
-effort, by chpc_helper_core.checks.yaml_syntax_check as a verification
step (and only if ansible-playbook itself isn't available either) --
never by generation itself.
"""
from __future__ import annotations

import json
from pathlib import Path

from chpc_helper_core.checks import yaml_syntax_check
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
            prepared[var.name] = json.dumps(raw)  # valid YAML double-quoted scalar
    return prepared


CONFIG = AppConfig(
    prog="chpc-ansible-helper",
    tagline="Build an Ansible playbook for an airgapped RHEL/Rocky/Debian system from a library of vetted templates.",
    library_dir=LIBRARY_DIR,
    template_ext=".yml.tmpl",
    default_out_ext=".yml",
    syntax_checker=yaml_syntax_check,
    syntax_check_label="ansible-playbook --syntax-check",
    executable=False,
    prepare_variables=_prepare_variables,
)


def build_parser():
    return _build_parser(CONFIG)


def main(argv: list[str] | None = None) -> int:
    return _main(argv, CONFIG)


if __name__ == "__main__":
    raise SystemExit(main())
