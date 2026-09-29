"""Re-exports the shared interactive wizard. build_interactive()'s
defaults in chpc_helper_core (bash_syntax_check, executable=True,
"bash -n") already match what this app needs, so nothing bash-specific
has to be added here.
"""
from chpc_helper_core.wizard import (  # noqa: F401
    InputFunc,
    PrintFunc,
    WizardAbort,
    build_interactive,
    prompt_toggle,
    prompt_toggle_group,
    prompt_variable,
    render_script,
    run_wizard,
    write_script,
)
