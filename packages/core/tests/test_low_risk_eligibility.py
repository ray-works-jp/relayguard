"""Regression for Architect CHANGES_REQUESTED (2026-09-15): L0/L1 require positive
confirmation (DELEGATION.md §12.6-8). "No rule fired" alone must never yield L0, and
approve does not resolve an unknown / ambiguous original."""

from __future__ import annotations

import copy
from collections.abc import Callable
from decimal import Decimal

import pytest
from builders import (
    Json,
    absent,
    clause,
    commitment,
    emotion,
    ex,
    legal,
    money,
    new_item,
    rehash,
    rights_term,
    risk,
    text_claim,
)
from helpers import assert_assessed, run
from sg001_cases import (
    CASES,
    l0_calendar_day_notice,
    l1_style_feedback_notice,
    reg_empty_interpretation,
    reg_request_text_ambiguous,
    reg_required_question_text_unknown,
)

from relayguard.claims import CLAIM_ARRAYS
from relayguard.delegation import L0_ALLOWED_ARRAYS

LOW = ("L0_AUTO", "L1_POST_REVIEW")


@pytest.mark.parametrize(
    "build",
    [reg_empty_interpretation, reg_required_question_text_unknown, reg_request_text_ambiguous],
    ids=["empty_interpretation", "required_question_text_unknown", "request_text_ambiguous"],
)
def test_reported_dangerous_l0_cases_are_not_low_risk(build: Callable[[], Json]) -> None:
    assessment = assert_assessed(run(build()))
    assert assessment["level"] == "L2_PRE_APPROVAL"
    assert assessment["minimum_level"] == "L2_PRE_APPROVAL"
    assert "LOW_RISK_INFORMATIONAL" not in assessment["reason_codes"]
    assert "UNCLASSIFIED_RISK" in assessment["reason_codes"]
    assert assessment["human_review_required"] is True


def _item(document: Json, claim_id: str) -> Json:
    found: Json = next(i for i in document["approved_decision"]["items"] if i["source_claim_id"] == claim_id)
    return found


UNRESOLVED_TEXT_CASES = [
    (base_name, array, claim_id, status, decision)
    for base_name, targets in (
        ("l0_base", [("sender_intent", "c_intent")]),
        ("l1_base", [("sender_intent", "c_intent"), ("customer_emotion", "c_emotion")]),
    )
    for array, claim_id in targets
    for status in (("unknown", "ambiguous") if array == "customer_emotion" else ("unknown", "ambiguous", "not_stated"))
    for decision in ("approve", "do_not_answer", "modify")
]
BASES: dict[str, Callable[[], Json]] = {"l0_base": l0_calendar_day_notice, "l1_base": l1_style_feedback_notice}


@pytest.mark.parametrize(("base_name", "array", "claim_id", "status", "decision"), UNRESOLVED_TEXT_CASES)
def test_unresolved_text_is_never_low_risk(base_name: str, array: str, claim_id: str, status: str, decision: str) -> None:
    document = BASES[base_name]()
    claim = next(c for c in document["interpretation"]["state"][array] if c["id"] == claim_id)
    field = "target" if array == "customer_emotion" else "text"
    original = copy.deepcopy(claim)
    claim[field] = absent(status, "")
    item = _item(document, claim_id)
    item["decision"] = decision
    if decision == "modify":
        # The user supplies explicit text; the unknown original is still not resolved.
        item["replacement"] = {"kind": {"questions": "Question", "sender_intent": "TextClaim"}.get(array, "Emotion"), "value": original}
    unanswered = document["approved_decision"]["explicitly_unanswered"]
    unanswered.clear()
    unanswered.extend(
        i["source_claim_id"]
        for i in document["approved_decision"]["items"]
        if i["decision"] == "do_not_answer" and i["source_claim_id"].startswith("c_q")
    )
    assessment = assert_assessed(run(rehash(document)))
    assert assessment["level"] not in LOW, (array, status, decision, assessment["reason_codes"])


def _add(document: Json, array: str, claim: Json, decision: str = "approve") -> Json:
    quote = f"Extra sentence for {claim['id']}."
    document["source_message"]["body"] += " " + quote
    state = document["interpretation"]["state"]
    evidence_id = f"ev_{claim['id']}"
    claim["evidence_ids"] = [evidence_id]
    state[array].append(claim)
    state["evidence"].append(
        {
            "evidence_id": evidence_id,
            "source_kind": "source_message",
            "source_id": document["source_message"]["message_id"],
            "source_hash": "",
            "quote": quote,
            "supports": [claim["id"]],
            "confidence": Decimal("0.99"),
        }
    )
    document["approved_decision"]["items"].append(new_item(claim["id"], decision))
    if array in ("requested_commitments", "commitments") and decision == "approve":
        approved = copy.deepcopy(claim)
        approved["authorization_state"] = "approved"
        document["approved_decision"]["approved_commitments"].append(approved)
    return rehash(document)


BENIGN_OUTSIDE_L0: dict[str, Callable[[], Json]] = {
    "contract_terms": lambda: clause("c_x", "Existing contract continues"),
    "prohibitions": lambda: clause("c_x", "No resale", ex("must_not")),
    "guarantees": lambda: clause("c_x", "Standard warranty"),
    "refund_terms": lambda: clause("c_x", "Refund policy"),
    "cancellation_terms": lambda: clause("c_x", "Cancellation policy"),
    "license_terms": lambda: rights_term("c_x", "existing license", ex(False), ex(False), ex(False)),
    "rights": lambda: rights_term("c_x", "existing rights", ex(False), ex(False), ex(False)),
    "requested_commitments": lambda: commitment("c_x", "user", "reply", "email"),
    "commitments": lambda: commitment("c_x", "counterparty", "send", "document", state="not_approved"),
    "personal_data": lambda: text_claim("c_x", "Sample Person"),
    "customer_emotion": lambda: emotion("c_x", "other", "tone", intensity="low"),
    "legal_claims": lambda: legal("c_x", "mention of terms"),
    "reputational_risks": lambda: risk("c_x", "reputational", "minor", False, True),
    "prior_commitment_conflicts": lambda: risk("c_x", "contradiction", "minor", False, True),
    "risks": lambda: risk("c_x", "other", "minor", False, True),
    "ambiguities": lambda: risk("c_x", "ambiguity", "minor", False, True),
    "missing_information": lambda: risk("c_x", "missing_information", "minor", False, True),
    "attachment_dependencies": lambda: risk("c_x", "attachment", "minor", False, True),
    "prompt_injection_risks": lambda: risk("c_x", "injection", "minor", False, True),
    "recommended_actions": lambda: text_claim("c_x", "Reply politely"),
}


def test_every_non_l0_category_is_listed() -> None:
    assert set(BENIGN_OUTSIDE_L0) == set(CLAIM_ARRAYS) - L0_ALLOWED_ARRAYS


@pytest.mark.parametrize("array", sorted(BENIGN_OUTSIDE_L0))
def test_claim_outside_l0_categories_blocks_l0(array: str) -> None:
    assessment = assert_assessed(run(_add(l0_calendar_day_notice(), array, BENIGN_OUTSIDE_L0[array]())))
    assert assessment["level"] != "L0_AUTO", array
    if array not in ("customer_emotion", "reputational_risks"):
        assert assessment["level"] not in LOW, array


def test_mention_only_value_modified_or_giveaway_type_blocks_l0() -> None:
    price = money("c_price", ex("30.00"), ex("USD"), "price", ex("for the March plan"))
    assert assert_assessed(run(_add(l0_calendar_day_notice(), "monetary_terms", copy.deepcopy(price))))["level"] == "L0_AUTO"
    for mtype in ("discount", "credit", "refund"):
        other = dict(copy.deepcopy(price), type=mtype)
        assert assert_assessed(run(_add(l0_calendar_day_notice(), "monetary_terms", other)))["level"] not in LOW

    document = _add(l0_calendar_day_notice(), "monetary_terms", copy.deepcopy(price))
    item = _item(document, "c_price")
    item["decision"] = "modify"
    item["replacement"] = {"kind": "MonetaryTerm", "value": dict(copy.deepcopy(price), evidence_ids=[], condition=absent())}
    assert assert_assessed(run(rehash(document)))["level"] not in LOW


def test_emotion_without_any_content_is_not_l1() -> None:
    document = l1_style_feedback_notice()
    state = document["interpretation"]["state"]
    state["sender_intent"] = []
    state["evidence"] = [e for e in state["evidence"] if e["supports"] != ["c_intent"]]
    document["approved_decision"]["items"] = [i for i in document["approved_decision"]["items"] if i["source_claim_id"] != "c_intent"]
    assert assert_assessed(run(rehash(document)))["level"] == "L2_PRE_APPROVAL"


def test_low_risk_results_across_all_fixtures_satisfy_positive_eligibility() -> None:
    for name, (build, _) in CASES.items():
        document = build()
        assessment = assert_assessed(run(document))
        if assessment["level"] not in LOW:
            continue
        state = document["interpretation"]["state"]
        content = [c for a in ("sender_intent", "requests", "questions") for c in state[a]]
        assert content, name
        assert all(c["text"]["status"] == "explicit" for c in content), name
        assert all(i["decision"] != "unknown" for i in document["approved_decision"]["items"]), name
        # A required question is only "処理済み" through an explicit do_not_answer.
        answered = {i["source_claim_id"] for i in document["approved_decision"]["items"] if i["decision"] == "do_not_answer"}
        assert all(not q["required_answer"] or q["id"] in answered for q in state["questions"]), name
