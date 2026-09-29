"""bash-specific wiring over the shared chpc_helper_core CLI: this app's
library directory, its ``.sh.tmpl`` template extension, ``.sh`` output,
and ``bash -n`` as the syntax checker. See chpc_helper_core/cli.py for
what list/show/describe/build actually do -- it's identical across
every chpc-*-helper app.
"""
from __future__ import annotations

from pathlib import Path

from chpc_helper_core.checks import bash_syntax_check
from chpc_helper_core.cli import AppConfig
from chpc_helper_core.cli import build_parser as _build_parser
from chpc_helper_core.cli import main as _main

LIBRARY_DIR = Path(__file__).resolve().parent / "library"

CONFIG = AppConfig(
    prog="chpc-bash-helper",
    tagline="Build a bash script for an airgapped RHEL/Rocky/Debian system from a library of vetted templates.",
    library_dir=LIBRARY_DIR,
    template_ext=".sh.tmpl",
    default_out_ext=".sh",
    syntax_checker=bash_syntax_check,
    syntax_check_label="bash -n",
    executable=True,
)


def build_parser():
    return _build_parser(CONFIG)


def main(argv: list[str] | None = None) -> int:
    return _main(argv, CONFIG)


if __name__ == "__main__":
    raise SystemExit(main())
