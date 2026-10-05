"""QuestionAnswer contract (SCHEMA.md v0.5 §13) and its delegation effect (§15).

An answer is a separately provenanced record bound to an approved question. It never comes
from the approval alone, from human_notes, or from an LLM, it is covered by decision_hash,
and it never clears an L3 cause.
"""

from __future__ import annotations

import copy
import json
import logging

import pytest
from builders import FIXTURE_ACTOR, FIXTURE_TIME, Json, rehash, rehash_decision, to_bytes
from helpers import assert_assessed, assert_rejected, fixed_runtime, run
from sg001_cases import (
    l2_answer_from_source_evidence,
    l2_answered_receipt_confirmation,
    l2_required_question_unknown,
    l3_injection_marked_resolved,
    l3_legal_claim,
)

from relayguard.shadow_core import run_shadow_core


def _answer(document: Json) -> Json:
    answer: Json = document["approved_decision"]["question_answers"][0]
    return answer


def _item(document: Json, claim_id: str) -> Json:
    item: Json = next(i for i in document["approved_decision"]["items"] if i["source_claim_id"] == claim_id)
    return item


def test_recorded_answer_is_accepted_and_bound_to_the_decision_hash() -> None:
    document = l2_answered_receipt_confirmation()
    assessment = assert_assessed(run(document))
    assert "ANSWER_REVIEW_REQUIRED" in assessment["reason_codes"]

    tampered = copy.deepcopy(document)
    _answer(tampered)["answer_text"] = "No, nothing arrived."
    assert_rejected(run(tampered), "InternalIntegrityError")

    # Every hash-covered part of the record: content, references and provenance.
    for field, value in (("related_claim_ids", ["c_intent"]),):
        changed = copy.deepcopy(document)
        _answer(changed)[field] = value
        assert_rejected(run(changed), "InternalIntegrityError")
    provenance_changed = copy.deepcopy(document)
    _answer(provenance_changed)["provenance"]["reason_ja"] = "別の理由"
    assert_rejected(run(provenance_changed), "InternalIntegrityError")


def test_answer_changes_the_decision_hash_and_thus_the_binding() -> None:
    without = l2_required_question_unknown()
    with_answer = copy.deepcopy(without)
    _item(with_answer, "c_q1")["decision"] = "approve"
    with_answer["approved_decision"]["question_answers"] = [
        {
            "question_id": "c_q1",
            "answer_text": "The store is open on the holiday.",
            "basis": "user_assertion",
            "evidence_ids": [],
            "related_claim_ids": [],
            "provenance": {"actor_id": FIXTURE_ACTOR, "decided_at": FIXTURE_TIME, "reason_ja": "テスト用fixtureの回答"},
        }
    ]
    rehash_decision(with_answer)
    assert with_answer["approved_decision"]["decision_hash"] != without["approved_decision"]["decision_hash"]
    assessment = assert_assessed(run(with_answer))
    assert assessment["level"] == "L2_PRE_APPROVAL"
    assert "ANSWER_REVIEW_REQUIRED" in assessment["reason_codes"]


@pytest.mark.parametrize("decision", ["unknown", "do_not_answer"])
def test_answer_cannot_coexist_with_unknown_or_do_not_answer(decision: str) -> None:
    document = l2_answered_receipt_confirmation()
    _item(document, "c_q1")["decision"] = decision
    if decision == "do_not_answer":
        document["approved_decision"]["explicitly_unanswered"] = ["c_q1"]
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


def test_answer_for_an_unknown_or_non_question_claim_is_rejected() -> None:
    ghost = l2_answered_receipt_confirmation()
    _answer(ghost)["question_id"] = "c_ghost"
    assert_rejected(run(rehash_decision(ghost)), "PolicyViolation")

    not_a_question = l2_answered_receipt_confirmation()
    _answer(not_a_question)["question_id"] = "c_intent"
    assert_rejected(run(rehash_decision(not_a_question)), "PolicyViolation")


def test_duplicate_or_unsorted_answers_are_rejected() -> None:
    document = l2_answer_from_source_evidence()
    duplicate = copy.deepcopy(document)
    duplicate["approved_decision"]["question_answers"].append(copy.deepcopy(_answer(duplicate)))
    assert_rejected(run(rehash_decision(duplicate)), "PolicyViolation")

    unsorted_doc = copy.deepcopy(document)
    first = copy.deepcopy(_answer(unsorted_doc))
    second = copy.deepcopy(first)
    first["question_id"] = "c_q1"
    second["question_id"] = "c_intent"  # not a Question either, but ordering is checked first
    unsorted_doc["approved_decision"]["question_answers"] = [first, second]
    assert_rejected(run(rehash_decision(unsorted_doc)), "PolicyViolation")


def test_answer_actor_must_be_the_approving_actor() -> None:
    document = l2_answered_receipt_confirmation()
    _answer(document)["provenance"]["actor_id"] = "someone_else"
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


def test_user_assertion_cannot_claim_source_evidence() -> None:
    document = l2_answered_receipt_confirmation()
    _answer(document)["evidence_ids"] = ["ev01"]
    assert_rejected(run(rehash_decision(document)), "SchemaInvalid")


def test_source_evidence_needs_a_real_evidence_reference() -> None:
    empty = l2_answer_from_source_evidence()
    _answer(empty)["evidence_ids"] = []
    assert_rejected(run(rehash_decision(empty)), "SchemaInvalid")

    ghost = l2_answer_from_source_evidence()
    _answer(ghost)["evidence_ids"] = ["ev99"]
    assert_rejected(run(rehash_decision(ghost)), "InternalIntegrityError")


def test_related_claims_must_exist_and_be_approved() -> None:
    ghost = l2_answer_from_source_evidence()
    _answer(ghost)["related_claim_ids"] = ["c_ghost"]
    assert_rejected(run(rehash_decision(ghost)), "InternalIntegrityError")

    unapproved = l2_answer_from_source_evidence()
    _item(unapproved, "c_intent")["decision"] = "unknown"
    assert_rejected(run(rehash_decision(unapproved)), "PolicyViolation")

    unsorted_doc = l2_answer_from_source_evidence()
    _answer(unsorted_doc)["related_claim_ids"] = ["c_q1", "c_intent"]
    assert_rejected(run(rehash_decision(unsorted_doc)), "PolicyViolation")


@pytest.mark.parametrize("text", ["", " ", "unknown", "n/a"])
def test_empty_or_placeholder_answer_is_rejected(text: str) -> None:
    document = l2_answered_receipt_confirmation()
    _answer(document)["answer_text"] = text
    result = run(rehash_decision(document))
    assert_rejected(result, "SchemaInvalid")


def test_answer_does_not_release_an_l3_cause() -> None:
    for build, claim in ((l3_legal_claim, "c_legal"), (l3_injection_marked_resolved, "c_inj")):
        document = build()
        state = document["interpretation"]["state"]
        document["source_message"]["body"] += " Can you confirm the details?"
        state["questions"].append(
            {
                "id": "c_q_confirm",
                "evidence_ids": ["ev_confirm"],
                "text": {"status": "explicit", "value": "Confirm the details?", "raw_text": ""},
                "required_answer": True,
            }
        )
        state["evidence"].append(
            {
                "evidence_id": "ev_confirm",
                "source_kind": "source_message",
                "source_id": document["source_message"]["message_id"],
                "source_hash": "",
                "quote": "Can you confirm the details?",
                "supports": ["c_q_confirm"],
                "confidence": None,
            }
        )
        document["approved_decision"]["items"].append(
            {
                "item_id": "item_c_q_confirm",
                "source_claim_id": "c_q_confirm",
                "decision": "approve",
                "replacement": None,
                "provenance": {"actor_id": FIXTURE_ACTOR, "decided_at": FIXTURE_TIME, "reason_ja": "確認"},
            }
        )
        document["approved_decision"]["question_answers"] = [
            {
                "question_id": "c_q_confirm",
                "answer_text": "The details are confirmed and the matter is settled.",
                "basis": "user_assertion",
                "evidence_ids": [],
                "related_claim_ids": [],
                "provenance": {"actor_id": FIXTURE_ACTOR, "decided_at": FIXTURE_TIME, "reason_ja": "テスト用fixtureの回答"},
            }
        ]
        assessment = assert_assessed(run(rehash(document)))
        assert assessment["level"] == "L3_STOP", claim
        assert "ANSWER_REVIEW_REQUIRED" in assessment["reason_codes"], claim


def test_answer_text_never_reaches_the_operational_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    document = l2_answered_receipt_confirmation()
    private_text = "Taro Example lives at 1-2-3 Sample-cho and can be reached at 090-0000-0000"
    _answer(document)["answer_text"] = private_text
    result = run_shadow_core(to_bytes(rehash_decision(document)), fixed_runtime())
    assert result["status"] == "assessed"
    assert private_text not in caplog.text
    assert private_text not in json.dumps(result, ensure_ascii=False)
    assert "Sample-cho" not in caplog.text


def test_source_evidence_basis_does_not_certify_the_answer_as_known_information() -> None:
    """SCHEMA §13: a quote match proves neither the meaning nor the truth of the answer, so
    the basis never lowers impact to "known information only" (low)."""
    cited = assert_assessed(run(l2_answer_from_source_evidence()))
    asserted_doc = l2_answer_from_source_evidence()
    _answer(asserted_doc)["basis"] = "user_assertion"
    _answer(asserted_doc)["evidence_ids"] = []
    asserted = assert_assessed(run(rehash_decision(asserted_doc)))
    for assessment in (cited, asserted):
        assert assessment["level"] == "L2_PRE_APPROVAL"
        assert assessment["risk_factors"]["impact"] == "medium"
        assert assessment["risk_factors"]["uncertainty"] == "medium"
    assert cited["reason_codes"] == asserted["reason_codes"]


@pytest.mark.parametrize("status", ["unknown", "ambiguous"])
def test_answer_does_not_resolve_an_unclear_question_text(status: str) -> None:
    """SCHEMA §13: when the original question text is unknown / ambiguous, recording an answer
    does not count as resolving it."""
    document = l2_answered_receipt_confirmation()
    question_claim = document["interpretation"]["state"]["questions"][0]
    question_claim["text"] = {"status": status, "value": None, "raw_text": ""}
    assessment = assert_assessed(run(rehash(document)))
    assert assessment["level"] == "L2_PRE_APPROVAL"
    assert {"ANSWER_REVIEW_REQUIRED", "UNCLASSIFIED_RISK"} <= set(assessment["reason_codes"])
