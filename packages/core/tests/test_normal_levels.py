"""AC-1 (normal L0-L3 per DELEGATION.md §12), AC-3 (reproducibility), AC-6 (result/audit metadata)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from builders import Json, to_bytes
from helpers import assert_assessed, fixed_runtime, run
from sg001_cases import CASES

from relayguard.audit import verify_chain
from relayguard.canonical import canonical_hash
from relayguard.shadow_core import assessed_result_problems, run_shadow_core


@pytest.mark.parametrize("name", sorted(CASES))
def test_normal_fixture_matches_expected(name: str) -> None:
    build, expected = CASES[name]
    document = build()
    result = run(document)
    assessment = assert_assessed(result)

    assert assessment["level"] == expected.level
    assert assessment["minimum_level"] == expected.level
    assert tuple(assessment["reason_codes"]) == expected.reason_codes
    if expected.risk_factors is not None:
        assert assessment["risk_factors"] == expected.risk_factors
    assert assessment["human_review_required"] is (expected.level != "L0_AUTO")
    assert assessment["phase"] == "pre_generation"
    assert assessment["draft_binding"] is None
    assert assessment["shadow_mode"] is True
    assert result["external_action_performed"] is False
    assert assessed_result_problems(result) == []


def test_all_four_levels_are_covered() -> None:
    assert {expected.level for _, expected in CASES.values()} == {
        "L0_AUTO",
        "L1_POST_REVIEW",
        "L2_PRE_APPROVAL",
        "L3_STOP",
    }


@pytest.mark.parametrize("name", sorted(CASES))
def test_binding_and_audit_metadata(name: str) -> None:
    document: Json = CASES[name][0]()
    result = run(document)
    assessment = assert_assessed(result)
    source = document["source_message"]
    interpretation = document["interpretation"]
    decision = document["approved_decision"]

    assert result["case_id"] == document["case_id"]
    assert result["schema_version"] == "0.5"
    assert result["input_hash"] == canonical_hash(document)
    assert assessment["binding"] == {
        "case_id": document["case_id"],
        "source_hash": source["content_hash"],
        "interpretation_id": interpretation["interpretation_id"],
        "interpretation_version": interpretation["version"],
        "decision_id": decision["decision_id"],
        "decision_version": decision["version"],
        "decision_hash": decision["decision_hash"],
        "policy_version": "delegation-0.4",
    }

    audit = result["audit"]
    assert verify_chain(document["case_id"], audit)
    assert audit[0]["previous_hash"] is None
    assert [e["event_type"] for e in audit] == [
        "source_message.received",
        "interpretation.supplied_by_fixture",
        "decision.approval_supplied_by_fixture",
        "delegation.pre_generation_assessed",
    ]
    assert [e["entity_hash"] for e in audit] == [
        source["content_hash"],
        canonical_hash(interpretation),
        decision["decision_hash"],
        canonical_hash(assessment),
    ]
    assert audit[3]["entity_id"] == assessment["assessment_id"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_same_input_and_policy_give_same_decision(name: str) -> None:
    document = CASES[name][0]()
    first = run(document, fixed_runtime("x", datetime(2026, 9, 15, 1, tzinfo=UTC)))
    second = run(document, fixed_runtime("y", datetime(2027, 1, 1, 23, 59, 59, 999000, tzinfo=UTC)))
    a, b = assert_assessed(first), assert_assessed(second)

    # Execution time / IDs differ; that is not decision non-determinism.
    assert a["assessment_id"] != b["assessment_id"]
    assert first["audit"][0]["created_at"] != second["audit"][0]["created_at"]
    for key in ("level", "minimum_level", "reason_codes", "risk_factors", "binding", "human_review_required"):
        assert a[key] == b[key]
    assert first["input_hash"] == second["input_hash"]


def test_default_runtime_produces_valid_ids_and_timestamps() -> None:
    result = run_shadow_core(to_bytes(CASES["l0_receipt_confirmation"][0]()))
    assert assessed_result_problems(result) == []


def test_audit_tampering_is_detected() -> None:
    result = run(CASES["legacy_l2_refund_commitment"][0]())
    tampered = dict(result)
    tampered["audit"] = [dict(e) for e in result["audit"]]
    tampered["audit"][2]["actor_id"] = "someone_else"
    assert "audit chain invalid" in assessed_result_problems(tampered)

    reordered = dict(result, audit=list(reversed(result["audit"])))
    assert "audit chain invalid" in assessed_result_problems(reordered)

    downgraded = dict(result, assessment=dict(result["assessment"], level="L0_AUTO", human_review_required=False))
    problems = assessed_result_problems(downgraded)
    assert "level below minimum_level" in problems
    assert "audit does not bind the assessment" in problems
