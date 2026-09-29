"""CHPC_ansible_helper -- builds Ansible playbooks for airgapped
RHEL/Rocky/Debian systems from a vetted template library, the same way
chpc_bash_helper/chpc_python_helper build bash/Python scripts: answer a
series of choices, or describe what you want in plain English. No
network, no AI model, and no extra Ansible collections -- every
template uses only ansible.builtin (ansible-core) modules.
"""

__version__ = "0.1.0"
