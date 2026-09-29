"""The interactive question-and-answer flow: for a chosen template, ask
every declared variable, toggle, and toggle_group in order, validate each
answer, show a summary, then render + write + syntax-check the script.

Every prompting function takes an injectable ``input_func``/``print_func``
(defaulting to the real ``input``/``print``) purely so tests can drive the
whole wizard by feeding it canned answers instead of needing a pty.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path
from typing import Callable

from . import engine
from .checks import bash_syntax_check
from .library import Template, Toggle, ToggleGroup, Variable

InputFunc = Callable[[str], str]
PrintFunc = Callable[..., None]
SyntaxChecker = Callable[[Path], tuple[bool, str]]
VariablePreparer = Callable[[Template, dict[str, str]], dict[str, str]]


def identity_prepare_variables(template: Template, variables: dict[str, str]) -> dict[str, str]:
    """Default VariablePreparer: pass variables through unchanged. bash
    and YAML templates embed a variable's raw text directly (no quoting
    needed), so this is what they use. Python templates need something
    smarter -- see chpc_python_helper's prepare_variables -- because
    embedding arbitrary text inside a Python string literal without
    escaping it is a real syntax/injection hazard that bash/YAML don't
    have in the same way.
    """
    return variables


class WizardAbort(Exception):
    """Raised when the user cancels (e.g. Ctrl-D / empty EOF) mid-wizard."""


def _ask(prompt: str, input_func: InputFunc) -> str:
    try:
        return input_func(prompt)
    except EOFError as exc:
        raise WizardAbort("input ended before the wizard finished") from exc


def prompt_variable(var: Variable, input_func: InputFunc = input, print_func: PrintFunc = print) -> str:
    default_display = f" [{var.default}]" if var.default not in (None, "") else ""
    if var.help:
        print_func(f"  {var.help}")
    if var.type == "choice":
        print_func(f"  choices: {', '.join(var.choices)}")

    while True:
        raw = _ask(f"{var.prompt}{default_display}: ", input_func).strip()
        if raw == "" and var.default is not None:
            raw = str(var.default)
        if raw == "" and not var.allow_empty:
            print_func("  This can't be empty.")
            continue
        if var.type == "int":
            try:
                value = int(raw)
            except ValueError:
                print_func("  Please enter a whole number.")
                continue
            if var.min is not None and value < var.min:
                print_func(f"  Must be >= {var.min}.")
                continue
            if var.max is not None and value > var.max:
                print_func(f"  Must be <= {var.max}.")
                continue
            return str(value)
        if var.type == "choice":
            choices_lower = {c.lower(): c for c in var.choices}
            if raw.lower() not in choices_lower:
                print_func(f"  Please pick one of: {', '.join(var.choices)}")
                continue
            return choices_lower[raw.lower()]
        return raw


def prompt_toggle(toggle: Toggle, input_func: InputFunc = input, print_func: PrintFunc = print) -> bool:
    if toggle.help:
        print_func(f"  {toggle.help}")
    default_str = "Y/n" if toggle.default else "y/N"
    while True:
        raw = _ask(f"{toggle.prompt}? [{default_str}]: ", input_func).strip().lower()
        if raw == "":
            return toggle.default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print_func("  Please answer y or n.")


def prompt_toggle_group(group: ToggleGroup, input_func: InputFunc = input, print_func: PrintFunc = print) -> str:
    if group.help:
        print_func(f"  {group.help}")
    labels = {o.value: o.label for o in group.options}
    values = list(labels.keys())
    for i, v in enumerate(values, 1):
        marker = " (default)" if v == group.default else ""
        print_func(f"    {i}. {labels[v]}{marker}")
    while True:
        raw = _ask(f"{group.prompt} [{group.default}]: ", input_func).strip()
        if raw == "":
            return group.default
        if raw.isdigit() and 1 <= int(raw) <= len(values):
            return values[int(raw) - 1]
        matches = [v for v in values if v.lower() == raw.lower()]
        if matches:
            return matches[0]
        print_func(f"  Please enter one of: {', '.join(values)} (or its number).")


def run_wizard(
    template: Template,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
) -> tuple[dict[str, str], dict[str, bool]]:
    """Walks through every question this template declares. Returns
    (variables, toggles) ready for engine.render().
    """
    print_func(f"\n=== {template.title} ===")
    print_func(template.description)
    print_func("(press Enter to accept the [default] shown, where there is one)\n")

    variables: dict[str, str] = {}
    for var in template.variables:
        variables[var.name] = prompt_variable(var, input_func, print_func)

    toggles: dict[str, bool] = {}
    for toggle in template.toggles:
        toggles[toggle.name] = prompt_toggle(toggle, input_func, print_func)

    for group in template.toggle_groups:
        chosen_value = prompt_toggle_group(group, input_func, print_func)
        for opt in group.options:
            toggles[opt.toggle] = (opt.value == chosen_value)

    return variables, toggles


def render_script(template: Template, variables: dict[str, str], toggles: dict[str, bool]) -> str:
    return engine.render(template.body, variables, toggles)


def write_script(rendered_text: str, out_path: Path, executable: bool = True) -> None:
    out_path.write_text(rendered_text)
    if executable:
        mode = out_path.stat().st_mode
        out_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_interactive(
    template: Template,
    out_path: Path,
    input_func: InputFunc = input,
    print_func: PrintFunc = print,
    syntax_checker: SyntaxChecker = bash_syntax_check,
    executable: bool = True,
    syntax_check_label: str = "bash -n",
    prepare_variables: VariablePreparer = identity_prepare_variables,
) -> Path:
    variables, toggles = run_wizard(template, input_func, print_func)
    variables = prepare_variables(template, variables)
    rendered = render_script(template, variables, toggles)

    print_func(f"\n--- about to write {out_path} ---")
    ok = _ask("Write this script now? [Y/n]: ", input_func).strip().lower()
    if ok not in ("", "y", "yes"):
        raise WizardAbort("cancelled before writing")

    write_script(rendered, out_path, executable=executable)
    passed, message = syntax_checker(out_path)
    exec_note = "executable, " if executable else ""
    if passed:
        # Prefer the checker's own message (it may name which of several
        # fallback methods actually ran, e.g. yaml_syntax_check) over the
        # static label, which only describes the *primary* tool.
        label = message or syntax_check_label
        print_func(f"Wrote {out_path} ({exec_note}passed `{label}` syntax check).")
    else:
        print_func(f"Wrote {out_path}, but `{syntax_check_label}` reported a problem:\n{message}", file=sys.stderr)
    print_func(
        "Review it before running -- especially anything that drains a "
        "node, deletes files, or changes accounts -- it's your script now."
    )
    return out_path
