from chpc_bash_helper.library import load_all
from chpc_bash_helper.match import rank

TEMPLATES = load_all()


def test_drain_description_matches_node_drain_resume_first():
    matches = rank("I need to drain a slurm node and note the reason", TEMPLATES)
    assert matches
    assert matches[0].template.id == "node_drain_resume"


def test_retry_description_matches_retry_wrapper_first():
    matches = rank("retry a flaky command with backoff", TEMPLATES)
    assert matches
    assert matches[0].template.id == "retry_wrapper"


def test_cron_description_matches_cron_installer():
    matches = rank("schedule a recurring cron job for a script", TEMPLATES)
    ids = [m.template.id for m in matches]
    assert "cron_installer" in ids


def test_empty_description_has_no_matches():
    assert rank("", TEMPLATES) == []
    assert rank("   ", TEMPLATES) == []


def test_nonsense_description_has_no_matches():
    assert rank("xyzzy plugh qwertyuiop", TEMPLATES) == []


def test_scores_are_sorted_descending():
    matches = rank("cron job systemd timer schedule", TEMPLATES)
    scores = [m.score for m in matches]
    assert scores == sorted(scores, reverse=True)
