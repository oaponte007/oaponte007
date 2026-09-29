"""Loads the template library: each template is a pair of files under
scriptwright/library/ sharing a stem --

  <id>.json      -- metadata: title, description, tags, and the questions
                     (variables / toggles / toggle_groups) the wizard asks
  <id>.sh.tmpl   -- the actual bash text, with {{VAR}} / {{#TOGGLE}}...{{/TOGGLE}}
                     placeholders (see engine.py)

Adding a new template to the library is just adding one more such pair --
nothing here needs to change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LIBRARY_DIR = Path(__file__).resolve().parent / "library"


class LibraryError(ValueError):
    pass


@dataclass
class Variable:
    name: str
    prompt: str
    type: str = "string"  # string | int | path | choice
    default: Any = None
    choices: list[str] | None = None
    min: int | None = None
    max: int | None = None
    help: str = ""
    allow_empty: bool = False

    def __post_init__(self) -> None:
        if self.type not in ("string", "int", "path", "choice"):
            raise LibraryError(f"variable {self.name!r}: unknown type {self.type!r}")
        if self.type == "choice" and not self.choices:
            raise LibraryError(f"variable {self.name!r}: type 'choice' needs 'choices'")


@dataclass
class Toggle:
    name: str
    prompt: str
    default: bool = False
    help: str = ""


@dataclass
class ToggleGroupOption:
    value: str
    label: str
    toggle: str


@dataclass
class ToggleGroup:
    name: str
    prompt: str
    options: list[ToggleGroupOption]
    default: str
    help: str = ""

    def toggle_names(self) -> list[str]:
        return [o.toggle for o in self.options]

    def toggle_for_value(self, value: str) -> str:
        for o in self.options:
            if o.value == value:
                return o.toggle
        raise LibraryError(f"toggle_group {self.name!r} has no option {value!r}")


@dataclass
class Template:
    id: str
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    variables: list[Variable] = field(default_factory=list)
    toggles: list[Toggle] = field(default_factory=list)
    toggle_groups: list[ToggleGroup] = field(default_factory=list)
    body: str = ""
    json_path: Path | None = None
    template_path: Path | None = None

    def variable(self, name: str) -> Variable:
        for v in self.variables:
            if v.name == name:
                return v
        raise LibraryError(f"{self.id}: no such variable {name!r}")

    def default_toggles(self) -> dict[str, bool]:
        resolved = {t.name: t.default for t in self.toggles}
        for group in self.toggle_groups:
            for opt in group.options:
                resolved[opt.toggle] = opt.value == group.default
        return resolved

    def default_variables(self) -> dict[str, str]:
        return {v.name: ("" if v.default is None else str(v.default)) for v in self.variables}


def _load_one(json_path: Path) -> Template:
    tmpl_path = json_path.with_suffix("").with_suffix(".sh.tmpl") if json_path.name.endswith(".json") else None
    # json_path is e.g. library/foo.json -> template is library/foo.sh.tmpl
    tmpl_path = json_path.parent / (json_path.stem + ".sh.tmpl")
    if not tmpl_path.exists():
        raise LibraryError(f"{json_path.name}: missing matching {tmpl_path.name}")

    data = json.loads(json_path.read_text())
    try:
        variables = [Variable(**v) for v in data.get("variables", [])]
        toggles = [Toggle(**t) for t in data.get("toggles", [])]
        toggle_groups = []
        for g in data.get("toggle_groups", []):
            options = [ToggleGroupOption(**o) for o in g["options"]]
            toggle_groups.append(ToggleGroup(
                name=g["name"], prompt=g["prompt"], options=options,
                default=g["default"], help=g.get("help", ""),
            ))
        return Template(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            tags=data.get("tags", []),
            variables=variables,
            toggles=toggles,
            toggle_groups=toggle_groups,
            body=tmpl_path.read_text(),
            json_path=json_path,
            template_path=tmpl_path,
        )
    except (KeyError, TypeError) as exc:
        raise LibraryError(f"{json_path.name}: malformed metadata ({exc})") from exc


def load_all(library_dir: Path = LIBRARY_DIR) -> dict[str, Template]:
    templates: dict[str, Template] = {}
    for json_path in sorted(library_dir.glob("*.json")):
        tmpl = _load_one(json_path)
        if tmpl.id != json_path.stem:
            raise LibraryError(f"{json_path.name}: id {tmpl.id!r} must match filename stem {json_path.stem!r}")
        if tmpl.id in templates:
            raise LibraryError(f"duplicate template id {tmpl.id!r}")
        templates[tmpl.id] = tmpl
    return templates


def get_template(template_id: str, library_dir: Path = LIBRARY_DIR) -> Template:
    templates = load_all(library_dir)
    if template_id not in templates:
        raise LibraryError(f"no such template {template_id!r}. Run 'scriptwright list' to see available templates.")
    return templates[template_id]
