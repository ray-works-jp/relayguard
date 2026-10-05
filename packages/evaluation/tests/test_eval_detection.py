"""The harness must detect dangerous regressions, not only agree with a correct implementation.
Each test injects a defect into the Shadow Core at runtime (never on disk) and checks that the
evaluation run reports it."""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable
from typing import Any

import pytest
from eval_support import CANDIDATES

from relayguard import shadow_core
from relayguard.delegation import POLICY_VERSION, PolicyOutcome, assess_pre_generation
from relayguard.integrity import DomainContext, validate_domain
from relayguard_eval.cases import load_fixture_suite
from relayguard_eval.report import build_report
from relayguard_eval.runner import run_suite


def _patch_policy(monkeypatch: pytest.MonkeyPatch, policy: Callable[[DomainContext], PolicyOutcome]) -> None:
    monkeypatch.setitem(shadow_core.POLICIES, POLICY_VERSION, policy)


def test_fail_open_policy_is_reported_as_blockers(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_auto(ctx: DomainContext) -> PolicyOutcome:
        real = assess_pre_generation(ctx)
        return PolicyOutcome("L0_AUTO", "L0_AUTO", ("LOW_RISK_INFORMATIONAL",), real.risk_factors, False)

    _patch_policy(monkeypatch, always_auto)
    report = build_report(run_suite(load_fixture_suite(CANDIDATES)))
    blockers = report["release_blockers"]
    metrics = report["delegation_metrics"]
    assert blockers["l2_l3_misclassified_as_l0_l1"]["count"] == 84
    assert blockers["prompt_injection_policy_bypass"]["count"] == blockers["prompt_injection_policy_bypass"]["cases_checked"] > 0
    assert blockers["numeric_mutation_miss"]["pre_generation_under_classification"]["count"] > 0
    assert metrics["false_automation_rate"]["count"] == 84
    assert metrics["l2_l3_recall"]["value"] == "0.0000"
    assert report["gate"]["release_gate"] == "NOT_EVALUATED"
    # Rejections are decided before the policy runs and stay rejected.
    assert metrics["predicted_distribution"]["rejected"] == 10


def test_raising_the_level_is_over_classification_not_a_blocker(monkeypatch: pytest.MonkeyPatch) -> None:
    def always_stop(ctx: DomainContext) -> PolicyOutcome:
        real = assess_pre_generation(ctx)
        return PolicyOutcome("L3_STOP", "L3_STOP", ("UNCLASSIFIED_RISK",), real.risk_factors, True)

    _patch_policy(monkeypatch, always_stop)
    report = build_report(run_suite(load_fixture_suite(CANDIDATES)))
    assert report["release_blockers"]["l2_l3_misclassified_as_l0_l1"]["count"] == 0
    assert report["delegation_metrics"]["false_escalation_rate"]["numerator"] == 6
    assert report["delegation_metrics"]["under_classified_count"] == 0
    assert len({f["case_id"] for f in report["failures"]}) == 90  # every assessed case mismatches


def test_logging_mail_text_is_reported_as_pii_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    original = validate_domain
    leaky = logging.getLogger("relayguard.shadow_core")

    def validate_and_leak(document: dict[str, Any]) -> DomainContext:
        leaky.info("debug body=%s", document["source_message"]["body"])
        return original(document)

    monkeypatch.setattr(shadow_core, "validate_domain", validate_and_leak)
    report = build_report(run_suite(load_fixture_suite(CANDIDATES)))
    leak = report["release_blockers"]["raw_pii_operational_log_leak"]
    # Every input that reaches Domain validation leaks its body.
    assert leak["count"] >= 90
    assert "RG-EVAL-080" in leak["case_ids"]


def test_nondeterministic_policy_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    flip = itertools.count()

    def unstable(ctx: DomainContext) -> PolicyOutcome:
        real = assess_pre_generation(ctx)
        if next(flip) % 2:
            return PolicyOutcome("L3_STOP", "L3_STOP", (*real.reason_codes, "UNCLASSIFIED_RISK"), real.risk_factors, True)
        return real

    _patch_policy(monkeypatch, unstable)
    report = build_report(run_suite(load_fixture_suite(CANDIDATES)))
    assert len(report["safety_checks"]["nondeterministic_cases"]) >= 80
