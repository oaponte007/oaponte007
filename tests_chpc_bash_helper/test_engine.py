import pytest

from chpc_bash_helper.engine import RenderError, referenced_names, render


def test_variable_substitution():
    out = render("hello {{NAME}}", {"NAME": "world"}, {})
    assert out == "hello world"


def test_toggle_true_keeps_block():
    out = render("a{{#T}}b{{/T}}c", {}, {"T": True})
    assert out == "abc"


def test_toggle_false_removes_block():
    out = render("a{{#T}}b{{/T}}c", {}, {"T": False})
    assert out == "ac"


def test_nested_toggles_both_true():
    text = "{{#OUTER}}x{{#INNER}}y{{/INNER}}z{{/OUTER}}"
    assert render(text, {}, {"OUTER": True, "INNER": True}) == "xyz"


def test_nested_toggles_outer_true_inner_false():
    text = "{{#OUTER}}x{{#INNER}}y{{/INNER}}z{{/OUTER}}"
    assert render(text, {}, {"OUTER": True, "INNER": False}) == "xz"


def test_nested_toggles_outer_false_short_circuits_inner():
    # inner is never even evaluated -- the whole outer block, INNER
    # marker included, disappears -- so INNER need not be in the dict.
    text = "{{#OUTER}}x{{#INNER}}y{{/INNER}}z{{/OUTER}}"
    assert render(text, {}, {"OUTER": False}) == ""


def test_multiple_non_nested_blocks_same_name():
    text = "{{#T}}a{{/T}} middle {{#T}}b{{/T}}"
    assert render(text, {}, {"T": True}) == "a middle b"
    assert render(text, {}, {"T": False}) == " middle "


def test_unknown_variable_raises():
    with pytest.raises(RenderError):
        render("{{MISSING}}", {}, {})


def test_unknown_toggle_raises():
    with pytest.raises(RenderError):
        render("{{#MISSING}}x{{/MISSING}}", {}, {})


def test_blank_run_collapsed():
    out = render("a{{#T}}\n\n\n{{/T}}b", {}, {"T": True})
    assert "\n\n\n" not in out


def test_referenced_names_flat():
    var_names, toggle_names = referenced_names("{{A}} {{#B}}{{C}}{{/B}}")
    assert var_names == {"A", "C"}
    assert toggle_names == {"B"}


def test_referenced_names_nested():
    text = "{{#OUTER}}{{X}}{{#INNER}}{{Y}}{{/INNER}}{{/OUTER}}"
    var_names, toggle_names = referenced_names(text)
    assert var_names == {"X", "Y"}
    assert toggle_names == {"OUTER", "INNER"}
