"""The baseline/hardening rule engine: each Rule checks one real,
current setting against a known-good baseline (CIS-benchmark style) --
no vulnerability feed involved, so these never go stale and never need
updating. A Rule's `check` function reads the collected-data dict
defensively (missing/None fields mean "couldn't determine this," never
a false failure) and returns a RuleResult.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

CollectedData = dict


@dataclass
class RuleResult:
    passed: bool
    evidence: str = ""


def ok() -> RuleResult:
    return RuleResult(passed=True)


def fail(evidence: str) -> RuleResult:
    return RuleResult(passed=False, evidence=evidence)


CheckFunc = Callable[[CollectedData], "RuleResult | None"]


@dataclass
class Rule:
    id: str
    title: str
    severity: str  # "critical" | "high" | "medium" | "low"
    description: str  # what this setting/issue actually is, plain language
    danger: str  # why it matters -- what could actually go wrong
    fix_steps: list[str]  # numbered, written for someone with no IT background
    applicable_os: list[str]  # any of "rhel", "rocky", "windows"
    check: CheckFunc


@dataclass
class Finding:
    rule: Rule
    evidence: str


def evaluate(rules: list[Rule], collected: CollectedData) -> list[Finding]:
    os_family = (collected.get("os") or {}).get("family")
    findings: list[Finding] = []
    for rule in rules:
        if os_family not in rule.applicable_os:
            continue
        try:
            result = rule.check(collected)
        except Exception:
            # A check that can't run (e.g. a field missing because the
            # collector couldn't read something without more privilege)
            # is a skip, never a crash of the whole scan.
            continue
        if result is not None and not result.passed:
            findings.append(Finding(rule=rule, evidence=result.evidence))
    return findings
