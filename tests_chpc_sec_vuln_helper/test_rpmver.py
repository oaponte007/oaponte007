import pytest

from chpc_sec_vuln_helper.feeds.rpmver import compare_evr, is_vulnerable, rpmvercmp

# The canonical rpmvercmp test vectors (from RPM's own test suite).
VECTORS = [
    ("1.0", "1.0", 0), ("1.0", "2.0", -1), ("2.0", "1.0", 1),
    ("2.0.1", "2.0.1", 0), ("2.0", "2.0.1", -1), ("2.0.1", "2.0", 1),
    ("2.0.1a", "2.0.1a", 0), ("2.0.1a", "2.0.1", 1), ("2.0.1", "2.0.1a", -1),
    ("5.5p1", "5.5p1", 0), ("5.5p1", "5.5p2", -1), ("5.5p2", "5.5p1", 1),
    ("5.5p10", "5.5p10", 0), ("5.5p1", "5.5p10", -1), ("5.5p10", "5.5p1", 1),
    ("10xyz", "10.1xyz", -1), ("10.1xyz", "10xyz", 1),
    ("xyz10", "xyz10", 0), ("xyz10", "xyz10.1", -1), ("xyz10.1", "xyz10", 1),
    ("xyz.4", "xyz.41", -1), ("xyz.41", "xyz.4", 1),
    ("xyz.9", "xyz.10", -1), ("xyz.10", "xyz.9", 1),
    ("1.0", "1.a", 1), ("1.a", "1.0", -1),
]


@pytest.mark.parametrize("a,b,expected", VECTORS)
def test_rpmvercmp_canonical_vectors(a, b, expected):
    assert rpmvercmp(a, b) == expected


def test_compare_evr_missing_epoch_treated_as_zero():
    assert compare_evr("3.0.7-27.el9_5", "1:3.0.7-27.el9_5") == -1


def test_compare_evr_identical():
    assert compare_evr("2.4.51-7.el9", "2.4.51-7.el9") == 0


def test_compare_evr_older_release():
    assert compare_evr("1:3.0.7-27.el9_4", "1:3.0.7-27.el9_5") == -1


def test_is_vulnerable_true_when_older():
    assert is_vulnerable("1:3.0.7-18.el9_4", "1:3.0.7-27.el9_5") is True


def test_is_vulnerable_false_when_already_fixed():
    assert is_vulnerable("1:3.0.7-27.el9_5", "1:3.0.7-27.el9_5") is False
    assert is_vulnerable("1:3.0.7-30.el9_5", "1:3.0.7-27.el9_5") is False
