"""Renders every template with every toggle/toggle-group choice exercised
at least once, through the same json.dumps()-based variable preparation
the real CLI uses, and checks the result is at least valid YAML (via
PyYAML's safe_load_all -- the same fallback chpc_helper_core.checks.
yaml_syntax_check itself uses when ansible-playbook isn't installed on
the machine running this). This would have caught the groups['{{TARGET_
HOSTS}}'] nested-placeholder-inside-a-Jinja-string bug from an earlier
draft of host_key_sync before it ever shipped.
"""
import re

import pytest
import yaml

_UNRESOLVED_PLACEHOLDER_RE = re.compile(r"\{\{\w+\}\}")

from chpc_ansible_helper.cli import _prepare_variables
from chpc_ansible_helper.library import load_all
from chpc_helper_core.engine import referenced_names, render

TEMPLATES = load_all()


def _assert_valid_yaml(text: str, label: str) -> None:
    try:
        list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        raise AssertionError(f"invalid YAML for variant '{label}': {exc}\n--- rendered playbook ---\n{text}") from exc


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


def _adversarial_variables(tmpl):
    """Every string/path/choice variable gets a value containing a
    colon-space sequence and embedded quotes -- the exact shape that
    breaks a plain YAML scalar if a template ever concatenates literal
    text onto a {{VAR}} placeholder instead of using it as the entire
    value of its key (json.dumps() only produces a *safe standalone*
    quoted scalar; it can't protect a value some other text was glued
    onto). Defaults alone would never have caught the cron_installer/
    retry_wrapper bugs this guards, since none of the shipped defaults
    happen to contain a colon.
    """
    variables = tmpl.default_variables()
    for var in tmpl.variables:
        if var.type == "choice":
            continue  # must remain one of its declared choices
        if var.type == "int":
            continue
        variables[var.name] = 'weird: value "with" quotes'
    return variables


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
@pytest.mark.parametrize("variables_kind", ["defaults", "adversarial"])
def test_every_choice_renders_valid_yaml(template_id, variables_kind):
    tmpl = TEMPLATES[template_id]
    raw_variables = tmpl.default_variables() if variables_kind == "defaults" else _adversarial_variables(tmpl)
    prepared_variables = _prepare_variables(tmpl, raw_variables)
    for label, toggles in _toggle_variants(tmpl):
        rendered = render(tmpl.body, prepared_variables, toggles)
        # A real Jinja2 expression like "{{ item }}" (WITH a space) is
        # supposed to survive rendering -- Ansible evaluates that at
        # playbook run time, not this tool. Only OUR no-space {{VAR}}
        # placeholder syntax must be fully resolved by now.
        leftover = _UNRESOLVED_PLACEHOLDER_RE.search(rendered)
        assert leftover is None, f"{template_id} ({label}): leftover placeholder {leftover.group(0) if leftover else ''!r} in output"
        _assert_valid_yaml(rendered, f"{template_id}:{variables_kind}:{label}")


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
def test_no_raw_placeholder_nested_inside_a_jinja_expression(template_id):
    """Guards the rule every *.yml.tmpl must follow: a {{VARIABLE}} (my
    no-space placeholder) may only appear as a direct value (after
    ``key:``) or inside a real Jinja2 expression's own {{ ... }} (WITH
    spaces) as a bare already-assigned var name -- never re-embedded a
    second time as {{VAR}} nested inside a Jinja {{ ... }} block, where
    it would get replaced mid-expression before Ansible ever sees it.
    """
    import re
    tmpl = TEMPLATES[template_id]
    # a Jinja block "{{ ... }}" (space-delimited) that itself contains a
    # no-space {{WORD}} pattern nested inside it
    nested = re.search(r"\{\{\s[^{}]*\{\{\w+\}\}[^{}]*\s\}\}", tmpl.body)
    assert nested is None, (
        f"{template_id}: a {{{{VAR}}}} placeholder is nested inside a Jinja "
        f"{{{{ ... }}}} expression: {nested.group(0) if nested else ''!r} -- "
        f"assign it to a vars: entry first and reference the bare name instead."
    )


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_has_title_description_and_tags(template_id):
    tmpl = TEMPLATES[template_id]
    assert tmpl.title.strip()
    assert tmpl.description.strip()
    assert tmpl.tags, f"{template_id}: no tags -- 'describe' mode will never surface it"
