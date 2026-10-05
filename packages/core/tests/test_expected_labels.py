"""Expected-label discipline for the Architect review (ADR-024 / ADR-025).

- every case carries all four RiskFactors axes, derived from DELEGATION.md §12 / §15;
- approving a question is not an answer: only a recorded QuestionAnswer settles it, and a
  recorded answer keeps SG-001 at minimum L2 (ANSWER_REVIEW_REQUIRED);
- the structure-only fixture is not offered as a semantic label.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from builders import Json, question, rehash
from helpers import assert_assessed, run
from sg001_cases import CASES, l0_calendar_day_notice, l0_required_question_do_not_answer, l1_style_feedback_notice

AXES = ("impact", "uncertainty", "irreversibility", "customer_sensitivity")
VALUES = ("low", "medium", "high", "unknown")
STATUSES = ("gold_proposed", "spec_blocked", "regression", "structural_only")
FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "sg001"


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_case_states_all_four_axes(name: str) -> None:
    expected = CASES[name][1]
    assert set(expected.risk_factors) == set(AXES), name
    assert all(value in VALUES for value in expected.risk_factors.values()), name
    assert expected.approval_status in STATUSES, name


def test_expected_file_carries_the_review_fields() -> None:
    published = json.loads((FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))
    assert set(published) == set(CASES)
    for name, entry in published.items():
        assert entry["risk_factors"] is not None, name
        assert set(entry["risk_factors"]) == set(AXES), name
        assert entry["approval_status"] in STATUSES, name
        assert entry["minimum_level"] == entry["level"], name


def test_review_population_is_balanced() -> None:
    statuses = [expected.approval_status for _, expected in CASES.values()]
    gold = {name for name, (_, e) in CASES.items() if e.approval_status == "gold_proposed"}
    levels = {CASES[name][1].level for name in gold}
    assert levels == {"L0_AUTO", "L1_POST_REVIEW", "L2_PRE_APPROVAL", "L3_STOP"}, levels
    assert statuses.count("structural_only") == 1
    assert "structural_coverage" not in gold


def test_gold_candidates_settle_every_required_question_explicitly() -> None:
    """A Gold case resolves each required question in a represented way: a recorded
    QuestionAnswer, an explicit do_not_answer, or a pending unknown. A bare approve would
    leave the answer unrecorded (§15)."""
    for name, (build, expected) in CASES.items():
        if expected.approval_status != "gold_proposed":
            continue
        document = build()
        answered = {a["question_id"] for a in document["approved_decision"]["question_answers"]}
        required = {c["id"] for c in document["interpretation"]["state"]["questions"] if c["required_answer"]}
        for item in document["approved_decision"]["items"]:
            if item["source_claim_id"] in required:
                assert item["decision"] in ("do_not_answer", "unknown") or item["source_claim_id"] in answered, (
                    name,
                    item["decision"],
                )


@pytest.mark.parametrize("decision", ["approve", "modify"])
def test_approved_required_question_is_not_an_answer(decision: str) -> None:
    document = l0_calendar_day_notice()
    state = document["interpretation"]["state"]
    document["source_message"]["body"] += " Can you confirm the closure?"
    claim = question("c_q1", "Confirm the closure?")
    claim["evidence_ids"] = ["ev_q"]
    state["questions"].append(claim)
    state["evidence"].append(
        {
            "evidence_id": "ev_q",
            "source_kind": "source_message",
            "source_id": document["source_message"]["message_id"],
            "source_hash": "",
            "quote": "Can you confirm the closure?",
            "supports": ["c_q1"],
            "confidence": None,
        }
    )
    item: Json = {
        "item_id": "item_c_q1",
        "source_claim_id": "c_q1",
        "decision": decision,
        "replacement": {"kind": "Question", "value": copy.deepcopy(claim)} if decision == "modify" else None,
        "provenance": document["approved_decision"]["items"][0]["provenance"],
    }
    if decision == "modify":
        item["replacement"]["value"]["evidence_ids"] = []
    document["approved_decision"]["items"].append(item)
    assessment = assert_assessed(run(rehash(document)))
    assert assessment["level"] == "L2_PRE_APPROVAL"
    assert "UNCLASSIFIED_RISK" in assessment["reason_codes"]
    assert "ANSWER_REVIEW_REQUIRED" not in assessment["reason_codes"]
    assert assessment["risk_factors"]["impact"] == "unknown"


def test_explicit_do_not_answer_still_reaches_l0() -> None:
    assessment = assert_assessed(run(l0_required_question_do_not_answer()))
    assert assessment["level"] == "L0_AUTO"
    assert assessment["risk_factors"] == {
        "impact": "low",
        "uncertainty": "low",
        "irreversibility": "low",
        "customer_sensitivity": "low",
    }


def test_non_required_question_does_not_block_low_risk() -> None:
    document = l0_calendar_day_notice()
    state = document["interpretation"]["state"]
    document["source_message"]["body"] += " Anything else you need?"
    claim = question("c_opt", "Anything else?", required=False)
    claim["evidence_ids"] = ["ev_opt"]
    state["questions"].append(claim)
    state["evidence"].append(
        {
            "evidence_id": "ev_opt",
            "source_kind": "source_message",
            "source_id": document["source_message"]["message_id"],
            "source_hash": "",
            "quote": "Anything else you need?",
            "supports": ["c_opt"],
            "confidence": None,
        }
    )
    document["approved_decision"]["items"].append(
        {
            "item_id": "item_c_opt",
            "source_claim_id": "c_opt",
            "decision": "approve",
            "replacement": None,
            "provenance": document["approved_decision"]["items"][0]["provenance"],
        }
    )
    assert assert_assessed(run(rehash(document)))["level"] == "L0_AUTO"


def test_impact_medium_is_reachable_only_through_a_recorded_answer() -> None:
    """§15 retires the "medium is unreachable" assumption: an individual answer with no new
    critical obligation is medium, while a case without answers never claims it."""
    medium = set()
    for name, (build, expected) in CASES.items():
        document = build()
        assessed = assert_assessed(run(document))
        assert assessed["risk_factors"]["impact"] == expected.risk_factors["impact"], name
        if assessed["risk_factors"]["impact"] == "medium":
            medium.add(name)
            assert document["approved_decision"]["question_answers"], name
        elif not document["approved_decision"]["question_answers"]:
            assert assessed["risk_factors"]["impact"] != "medium", name
    assert medium, "no fixture exercises impact=medium"


@pytest.mark.parametrize(
    ("name", "axis", "value"),
    [
        ("l2_clause_approved_unidentifiable", "impact", "unknown"),
        ("l2_clause_approved_unidentifiable", "irreversibility", "unknown"),
        ("l2_counterparty_commitment_accepted", "impact", "low"),
        ("l2_counterparty_commitment_accepted", "irreversibility", "low"),
        ("l3_commitment_actor_unknown", "impact", "unknown"),
        ("l3_commitment_actor_unknown", "irreversibility", "unknown"),
        ("l2_refund_commitment_stated", "impact", "high"),
        ("l2_refund_commitment_stated", "irreversibility", "high"),
        ("l1_style_feedback_notice", "customer_sensitivity", "medium"),
        ("l3_legal_claim", "customer_sensitivity", "high"),
        ("l3_policy_exception_marked_resolved", "uncertainty", "high"),
        ("l0_calendar_day_notice", "impact", "low"),
        ("l2_answered_receipt_confirmation", "impact", "medium"),
        ("l2_answer_from_source_evidence", "impact", "medium"),
        ("l2_answer_from_source_evidence", "uncertainty", "medium"),
        ("l2_anger_with_past_delay", "customer_sensitivity", "medium"),
        ("l3_attachment_required", "impact", "unknown"),
        ("l3_attachment_required", "irreversibility", "unknown"),
        ("l3_prior_commitment_conflict", "impact", "unknown"),
        ("l3_prior_commitment_conflict", "irreversibility", "unknown"),
    ],
)
def test_axis_derivation_per_case(name: str, axis: str, value: str) -> None:
    assert assert_assessed(run(CASES[name][0]()))["risk_factors"][axis] == value


def test_calendar_day_gold_case_has_no_open_request() -> None:
    """Architect item 3: the calendar-day example must not carry an open request or an
    unstated value; the earlier input is kept as a regression case instead."""
    document = l0_calendar_day_notice()
    state = document["interpretation"]["state"]
    assert state["questions"] == []
    assert state["requests"] == []
    assert state["dates"][0]["type"] == "date"
    assert state["dates"][0]["timezone"]["status"] == "not_stated"
    assert CASES["reg_calendar_date_with_open_request"][1].approval_status == "regression"


def test_structural_fixture_is_consistent_with_its_source_text() -> None:
    """Architect item 4: the structure fixture must not carry values absent from the body."""
    document = CASES["structural_coverage"][0]()
    body = document["source_message"]["body"]
    state = document["interpretation"]["state"]
    assert state["monetary_terms"][0]["condition"]["value"] in body
    kickoff = next(c for c in state["commitments"] if c["id"] == "c_kickoff")
    assert kickoff["actor"] == "counterparty"
    assert "Our team agreed to hold a kickoff call." in body
    assert CASES["structural_coverage"][1].approval_status == "structural_only"


def test_emotion_gold_case_is_not_raised_by_emotion_alone() -> None:
    assessment = assert_assessed(run(l1_style_feedback_notice()))
    assert assessment["level"] == "L1_POST_REVIEW"
    assert set(assessment["reason_codes"]) == {"CUSTOMER_SENSITIVITY", "LOW_RISK_POST_REVIEW"}


def test_anger_with_past_mishandling_is_l2() -> None:
    """ADR-025 / DP §12.7: anger combined with an earlier mishandled delay is minimum L2,
    and "no question" alone never makes a case L1."""
    document = CASES["l2_anger_with_past_delay"][0]()
    assessment = assert_assessed(run(document))
    assert assessment["level"] == "L2_PRE_APPROVAL"
    assert set(assessment["reason_codes"]) == {"CUSTOMER_SENSITIVITY"}
    assert document["interpretation"]["state"]["questions"] == []
    assert document["interpretation"]["state"]["reputational_risks"], "past mishandling must be extracted"


def test_recorded_answer_keeps_the_case_at_l2() -> None:
    for name in ("l2_answered_receipt_confirmation", "l2_answer_from_source_evidence"):
        document = CASES[name][0]()
        assessment = assert_assessed(run(document))
        assert assessment["level"] == "L2_PRE_APPROVAL", name
        assert "ANSWER_REVIEW_REQUIRED" in assessment["reason_codes"], name
        assert assessment["risk_factors"]["uncertainty"] in ("medium", "high"), name
        assert document["approved_decision"]["question_answers"], name
