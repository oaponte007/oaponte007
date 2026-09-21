"""slurm_monitor: an autonomous monitoring/remediation agent for Slurm clusters.

It watches node health via sinfo/scontrol, classifies drain/down reasons using
the rule table in classifier.py, attempts safe automated remediation, and
force-drains a node with an explanatory note whenever the *same node* reports
the *same problem* again within a rolling 24 hour window -- breaking the
resume/fail/resume loop instead of perpetuating it.
"""

__version__ = "0.1.0"
