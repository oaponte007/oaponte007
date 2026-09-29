"""Generic command-line entry point, shared by every chpc-*-helper app:

    <prog> list
    <prog> show <template-id>
    <prog> describe "drain a node and note why"
    <prog> build <template-id> [--out FILE]
    <prog> build <template-id> --var NAME=VALUE ... --toggle NAME=on|off ...
                                --toggle-group NAME=VALUE ... --out FILE --yes

The last form is non-interactive (every answer supplied on the command
line) -- useful for repeatable generation or for scripting the tool
itself, without needing a human at the prompts.

Each app (chpc_bash_helper, chpc_python_helper, chpc_ansible_helper, ...)
supplies an AppConfig describing what makes it different -- its library
directory, its template file extension, the default output extension,
and how to syntax-check what it generates -- and gets the exact same
list/show/describe/build behavior for free.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import wizard
from .checks import bash_syntax_check
from .library import LibraryError, Template, load_all
from .match import rank
from .wizard import SyntaxChecker, VariablePreparer, identity_prepare_variables


@dataclass(frozen=True)
class AppConfig:
    prog: str
    tagline: str
    library_dir: Path
    template_ext: str = ".sh.tmpl"
    default_out_ext: str = ".sh"
    syntax_checker: SyntaxChecker = bash_syntax_check
    syntax_check_label: str = "bash -n"
    executable: bool = True
    prepare_variables: VariablePreparer = identity_prepare_variables

    def load_templates(self) -> dict[str, Template]:
        return load_all(self.library_dir, self.template_ext)


def _print_template_summary(tmpl: Template) -> None:
    print(f"{tmpl.id:22s} {tmpl.title}")
    print(f"{'':22s} {tmpl.description}")
    if tmpl.tags:
        print(f"{'':22s} tags: {', '.join(tmpl.tags)}")


def _cmd_list(args: argparse.Namespace, config: AppConfig) -> int:
    templates = config.load_templates()
    if not templates:
        print("No templates found in the library.", file=sys.stderr)
        return 1
    print(f"{len(templates)} template(s) available:\n")
    for tmpl in templates.values():
        _print_template_summary(tmpl)
        print()
    return 0


def _cmd_show(args: argparse.Namespace, config: AppConfig) -> int:
    templates = config.load_templates()
    if args.template_id not in templates:
        print(f"No such template {args.template_id!r}. Run '{config.prog} list' to see available ones.", file=sys.stderr)
        return 1
    tmpl = templates[args.template_id]
    _print_template_summary(tmpl)
    print()
    if tmpl.variables:
        print("Questions this asks (variables):")
        for v in tmpl.variables:
            default = f" (default: {v.default})" if v.default not in (None, "") else ""
            print(f"  - {v.name}: {v.prompt}{default}")
    if tmpl.toggles:
        print("Yes/no choices (toggles):")
        for t in tmpl.toggles:
            print(f"  - {t.name}: {t.prompt}? (default: {'yes' if t.default else 'no'})")
    if tmpl.toggle_groups:
        print("Multiple-choice groups:")
        for g in tmpl.toggle_groups:
            opts = ", ".join(o.value for o in g.options)
            print(f"  - {g.name}: {g.prompt} [{opts}] (default: {g.default})")
    if args.raw:
        print("\n--- raw template text (unrendered) ---")
        print(tmpl.body)
    return 0


def _cmd_describe(args: argparse.Namespace, config: AppConfig) -> int:
    templates = config.load_templates()
    matches = rank(args.description, templates)
    if not matches:
        print(
            "Nothing in the library matched that description well enough.\n"
            f"Run '{config.prog} list' to browse everything available, or "
            f"'{config.prog} show <id>' to preview one.",
            file=sys.stderr,
        )
        return 1
    print(f"Best matches for: {args.description!r}\n")
    for m in matches[:5]:
        print(f"{m.template.id:22s} (matched: {', '.join(sorted(m.matched_words))})")
        print(f"{'':22s} {m.template.description}")
        print()
    print(f"Run: {config.prog} build {matches[0].template.id}")
    return 0


def _parse_kv(pairs: list[str], flag_name: str) -> dict[str, str]:
    result = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--{flag_name} expects NAME=VALUE, got {pair!r}")
        name, _, value = pair.partition("=")
        result[name] = value
    return result


def _parse_toggle_values(pairs: list[str]) -> dict[str, bool]:
    raw = _parse_kv(pairs, "toggle")
    result = {}
    for name, value in raw.items():
        low = value.strip().lower()
        if low in ("on", "true", "yes", "1"):
            result[name] = True
        elif low in ("off", "false", "no", "0"):
            result[name] = False
        else:
            raise SystemExit(f"--toggle {name}={value!r}: expected on/off")
    return result


def _cmd_build(args: argparse.Namespace, config: AppConfig) -> int:
    try:
        templates = config.load_templates()
    except LibraryError as exc:
        print(f"Library error: {exc}", file=sys.stderr)
        return 1

    if args.template_id not in templates:
        print(f"No such template {args.template_id!r}. Run '{config.prog} list' to see available ones.", file=sys.stderr)
        return 1
    tmpl = templates[args.template_id]
    out_path = Path(args.out) if args.out else Path(f"{tmpl.id}{config.default_out_ext}")

    non_interactive = bool(args.var or args.toggle or args.toggle_group or args.yes)
    if non_interactive:
        variables = tmpl.default_variables()
        variables.update(_parse_kv(args.var, "var"))
        toggles = tmpl.default_toggles()
        toggles.update(_parse_toggle_values(args.toggle))
        group_values = _parse_kv(args.toggle_group, "toggle-group")
        for group in tmpl.toggle_groups:
            chosen = group_values.get(group.name, group.default)
            for opt in group.options:
                toggles[opt.toggle] = (opt.value == chosen)
        try:
            variables = config.prepare_variables(tmpl, variables)
            rendered = wizard.render_script(tmpl, variables, toggles)
        except Exception as exc:  # engine.RenderError or a bad --var value
            print(f"Could not render {tmpl.id}: {exc}", file=sys.stderr)
            return 1
        wizard.write_script(rendered, out_path, executable=config.executable)
        passed, message = config.syntax_checker(out_path)
        if passed:
            # Prefer the checker's own message when it has one (it may
            # name which fallback method actually ran) over the static label.
            label = message or config.syntax_check_label
            print(f"Wrote {out_path} (passed `{label}` syntax check).")
        else:
            print(f"Wrote {out_path}, but `{config.syntax_check_label}` reported a problem:\n{message}", file=sys.stderr)
        return 0 if passed else 1

    try:
        wizard.build_interactive(
            tmpl, out_path,
            syntax_checker=config.syntax_checker,
            executable=config.executable,
            syntax_check_label=config.syntax_check_label,
            prepare_variables=config.prepare_variables,
        )
    except wizard.WizardAbort as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1
    return 0


def build_parser(config: AppConfig) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=config.prog, description=config.tagline)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list every template in the library")
    p_list.set_defaults(func=lambda args: _cmd_list(args, config))

    p_show = sub.add_parser("show", help="show what a template asks and (optionally) its raw text")
    p_show.add_argument("template_id")
    p_show.add_argument("--raw", action="store_true", help="also print the unrendered template text")
    p_show.set_defaults(func=lambda args: _cmd_show(args, config))

    p_describe = sub.add_parser("describe", help="describe what you want in plain English, get matching templates")
    p_describe.add_argument("description")
    p_describe.set_defaults(func=lambda args: _cmd_describe(args, config))

    p_build = sub.add_parser("build", help="build a script from a template (interactive wizard, or non-interactive with flags)")
    p_build.add_argument("template_id")
    p_build.add_argument("--out", help=f"output path (default: <template-id>{config.default_out_ext} in the current directory)")
    p_build.add_argument("--var", action="append", default=[], metavar="NAME=VALUE", help="answer one variable non-interactively; repeatable")
    p_build.add_argument("--toggle", action="append", default=[], metavar="NAME=on|off", help="answer one toggle non-interactively; repeatable")
    p_build.add_argument("--toggle-group", action="append", default=[], metavar="NAME=VALUE", help="answer one toggle group non-interactively; repeatable")
    p_build.add_argument("--yes", action="store_true", help="use every default without prompting (equivalent to passing no --var/--toggle at all, but non-interactive)")
    p_build.set_defaults(func=lambda args: _cmd_build(args, config))

    return parser


def main(argv: list[str] | None, config: AppConfig) -> int:
    parser = build_parser(config)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        # e.g. `<prog> list | head` -- the reader closed early, not an
        # error worth a traceback.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
