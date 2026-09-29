"""Renders every template with every toggle/toggle-group choice exercised
at least once, through the same repr()-based variable preparation the
real CLI uses, and checks the result with `python3 -m py_compile`. This
is what would have caught the OnCalendar={{TIMER_ON_CALENDAR}}-embedded-
inside-an-f-string bug in an earlier draft of cron_installer before it
ever shipped.
"""
import tempfile
from pathlib import Path

import pytest

from chpc_helper_core.checks import python_syntax_check
from chpc_helper_core.engine import referenced_names, render
from chpc_python_helper.cli import _prepare_variables
from chpc_python_helper.library import load_all

TEMPLATES = load_all()


def _py_compile(text: str, label: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(text)
        path = Path(f.name)
    try:
        passed, message = python_syntax_check(path)
        assert passed, f"py_compile failed for variant '{label}':\n{message}\n--- rendered script ---\n{text}"
    finally:
        path.unlink(missing_ok=True)


def _toggle_variants(tmpl):
    base = tmpl.default_toggles()
    yield "defaults", dict(base)

    for toggle in tmpl.toggles:
        variant = dict(base)
        variant[toggle.name] = not toggle.default
        yield f"toggle:{toggle.name}={not toggle.default}", variant

    for group in tmpl.toggle_groups:
        for opt in group.options:
            if opt.value == group.default:
                continue
            variant = dict(base)
            for o in group.options:
                variant[o.toggle] = (o.value == opt.value)
            yield f"group:{group.name}={opt.value}", variant


def test_library_loads_without_error():
    assert len(TEMPLATES) >= 16


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_every_choice_renders_valid_python(template_id):
    tmpl = TEMPLATES[template_id]
    raw_variables = tmpl.default_variables()
    prepared_variables = _prepare_variables(tmpl, raw_variables)
    for label, toggles in _toggle_variants(tmpl):
        rendered = render(tmpl.body, prepared_variables, toggles)
        assert "{{" not in rendered, f"{template_id} ({label}): leftover placeholder in output"
        _py_compile(rendered, f"{template_id}:{label}")


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_metadata_matches_template_placeholders(template_id):
    tmpl = TEMPLATES[template_id]
    var_names, toggle_names = referenced_names(tmpl.body)

    declared_vars = {v.name for v in tmpl.variables}
    declared_toggles = {t.name for t in tmpl.toggles}
    for group in tmpl.toggle_groups:
        declared_toggles |= set(group.toggle_names())

    assert var_names <= declared_vars, (
        f"{template_id}: template references undeclared variable(s) {var_names - declared_vars}"
    )
    assert toggle_names <= declared_toggles, (
        f"{template_id}: template references undeclared toggle(s) {toggle_names - declared_toggles}"
    )


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_no_raw_variable_placeholder_embedded_inside_a_string_body(template_id):
    """Guards the rule every *.py.tmpl must follow: a {{VARIABLE}} may
    only appear in a value context (assigned to a bare name, passed as
    an argument) -- never a second time inside an f-string/format body,
    where repr()'s quotes would leak into the surrounding text instead
    of being a valid Python literal. Heuristic: a variable placeholder
    should never appear with an f-string/format brace immediately
    adjacent to it on the same line as other literal text outside of a
    simple assignment.
    """
    tmpl = TEMPLATES[template_id]
    for lineno, line in enumerate(tmpl.body.splitlines(), 1):
        stripped = line.strip()
        if "{{" not in stripped:
            continue
        # A bare "NAME = {{VAR}}" (or "NAME = {{VAR}} + ...") assignment,
        # or a plain function-argument usage, is fine; a variable
        # placeholder sitting inside an f-string literal (an f"..."
        # containing both {{ and other text before a closing quote on
        # the same segment) is exactly the bug pattern this guards.
        if stripped.startswith("f\"") or stripped.startswith("f'"):
            # toggle markers ({{#...}}/{{/...}}) are plain text, always fine;
            # only flag an actual {{VAR}} (no leading # or /) inside an f-string.
            import re
            has_var_placeholder = re.search(r"\{\{(?!\#|/)\w+\}\}", stripped)
            assert not has_var_placeholder, (
                f"{template_id} line {lineno}: variable placeholder embedded inside "
                f"an f-string body (repr() quotes would leak in): {stripped!r}"
            )


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_has_title_description_and_tags(template_id):
    tmpl = TEMPLATES[template_id]
    assert tmpl.title.strip()
    assert tmpl.description.strip()
    assert tmpl.tags, f"{template_id}: no tags -- 'describe' mode will never surface it"
