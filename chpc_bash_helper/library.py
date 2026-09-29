"""Thin bash-specific wrapper around the shared chpc_helper_core.library
loader: fixes this app's library directory and template file extension
so callers keep the simple ``load_all()`` / ``get_template(id)`` calls.
"""
from __future__ import annotations

from pathlib import Path

from chpc_helper_core.library import (  # noqa: F401 (re-exported for callers/tests)
    LibraryError,
    Template,
    Toggle,
    ToggleGroup,
    ToggleGroupOption,
    Variable,
)
from chpc_helper_core.library import get_template as _get_template
from chpc_helper_core.library import load_all as _load_all

LIBRARY_DIR = Path(__file__).resolve().parent / "library"
TEMPLATE_EXT = ".sh.tmpl"


def load_all(library_dir: Path = LIBRARY_DIR) -> dict[str, Template]:
    return _load_all(library_dir, TEMPLATE_EXT)


def get_template(template_id: str, library_dir: Path = LIBRARY_DIR) -> Template:
    return _get_template(template_id, library_dir, TEMPLATE_EXT)
