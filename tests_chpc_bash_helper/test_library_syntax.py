"""The one test suite that actually matters most: every template, with
every toggle and toggle_group choice exercised at least once, must render
to a script that `bash -n` accepts. This is what would have caught the
mismatched-quote bug in an earlier draft of disk_cleanup before it ever
reached a real node.
"""
import subprocess
import tempfile
from pathlib import Path

import pytest

from chpc_bash_helper.engine import referenced_names, render
from chpc_bash_helper.library import load_all

TEMPLATES = load_all()


def _bash_n(text: str, label: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write(text)
        path = Path(f.name)
    try:
        result = subprocess.run(
            ["bash", "-n", str(path)], capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, (
            f"bash -n failed for variant '{label}':\n{result.stderr}\n"
            f"--- rendered script ---\n{text}"
        )
    finally:
        path.unlink(missing_ok=True)


def _toggle_variants(tmpl):
    """(label, toggles) pairs covering every plain toggle's non-default
    value and every toggle_group's non-default option at least once,
    each change made in isolation against an otherwise-default baseline.
    """
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
def test_every_choice_renders_valid_bash(template_id):
    tmpl = TEMPLATES[template_id]
    variables = tmpl.default_variables()
    for label, toggles in _toggle_variants(tmpl):
        rendered = render(tmpl.body, variables, toggles)
        assert "{{" not in rendered, f"{template_id} ({label}): leftover placeholder in output"
        _bash_n(rendered, f"{template_id}:{label}")


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
def test_has_title_description_and_tags(template_id):
    tmpl = TEMPLATES[template_id]
    assert tmpl.title.strip()
    assert tmpl.description.strip()
    assert tmpl.tags, f"{template_id}: no tags -- 'describe' mode will never surface it"
