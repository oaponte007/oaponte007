"""The templating engine: everything here is a single regex-based pass over
plain text. No Jinja2/mustache dependency on purpose -- an airgapped box
may have no way to `pip install` anything, so the whole tool (this file
included) only ever imports the Python 3 standard library.

Placeholder syntax, deliberately chosen so it can never collide with real
bash syntax:
  {{VAR_NAME}}              -- replaced with the variable's value
  {{#TOGGLE_NAME}} ... {{/TOGGLE_NAME}}
                            -- kept if TOGGLE_NAME is true, removed (the
                               whole block, including the markers) if false
"""
from __future__ import annotations

import re

_TOGGLE_RE = re.compile(r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}", re.DOTALL)
_VAR_RE = re.compile(r"\{\{(\w+)\}\}")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


class RenderError(ValueError):
    pass


def render(template_text: str, variables: dict[str, str], toggles: dict[str, bool]) -> str:
    """Resolve every toggle block, then every variable. Raises RenderError
    naming the exact placeholder if something the template needs was never
    supplied -- a generated script should never silently ship a literal
    ``{{SOMETHING}}`` in it.
    """

    def _resolve_toggle(match: re.Match) -> str:
        name = match.group(1)
        if name not in toggles:
            raise RenderError(f"template references unknown toggle {{{{#{name}}}}}")
        return match.group(2) if toggles[name] else ""

    # A single re.sub pass only resolves the outermost {{#TOGGLE}} of any
    # nested pair (its captured body is inserted as literal text, not
    # re-scanned) -- templates like node_drain_resume nest a scheduler
    # toggle around an action toggle, so re-apply to a fixed point instead
    # of assuming one pass is enough.
    text = template_text
    for _ in range(20):
        new_text, count = _TOGGLE_RE.subn(_resolve_toggle, text)
        text = new_text
        if count == 0:
            break
    else:
        raise RenderError("toggle blocks did not resolve after 20 passes (circular nesting?)")

    def _resolve_var(match: re.Match) -> str:
        name = match.group(1)
        if name not in variables:
            raise RenderError(f"template references unknown variable {{{{{name}}}}}")
        return str(variables[name])

    text = _VAR_RE.sub(_resolve_var, text)

    leftover_toggle = re.search(r"\{\{[#/]\w+\}\}", text)
    if leftover_toggle:
        raise RenderError(f"unresolved toggle marker left in output: {leftover_toggle.group(0)}")

    return _BLANK_RUN_RE.sub("\n\n", text)


def referenced_names(template_text: str) -> tuple[set[str], set[str]]:
    """Returns (variable_names, toggle_names) actually referenced in the
    raw template text -- used by tests to catch metadata/template drift
    (a variable declared in the .json that the .sh.tmpl never uses, or
    vice versa). Scans the raw text directly rather than stripping toggle
    bodies first, so names used inside nested toggle blocks are still
    found: ``{{#X}}`` / ``{{/X}}`` markers never match _VAR_RE (the ``#``
    or ``/`` isn't a word character right after ``{{``), so a plain scan
    for each pattern already separates the two correctly regardless of
    nesting depth.
    """
    toggle_names = set(re.findall(r"\{\{[#/](\w+)\}\}", template_text))
    var_names = set(_VAR_RE.findall(template_text))
    return var_names, toggle_names
