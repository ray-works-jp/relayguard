"""AC-2 references/evidence/duplicates, AC-4 hash/target/case/version binding, policy_version,
source size limit and Domain value constraints (SCHEMA.md §§2-5, SD-07)."""

from __future__ import annotations

import copy
from collections.abc import Callable

import pytest
from builders import Json, commitment, money, quantity, rehash, rehash_decision, text_claim
from helpers import assert_rejected, run
from sg001_cases import (
    l0_receipt_confirmation,
    l2_deadline_modified,
    l2_refund_commitment,
    structural_coverage,
)

Mutator = Callable[[Json], None]


def _mutated(base: Callable[[], Json], mutate: Mutator, *, recompute: bool) -> Json:
    document = base()
    mutate(document)
    return rehash(document) if recompute else document


# --- hash / binding / version / case (AC-4) -------------------------------------------------

HASH_AND_BINDING: dict[str, tuple[Mutator, str]] = {
    "content_hash_tampered": (
        lambda d: d["source_message"].__setitem__("content_hash", "0" * 64),
        "InternalIntegrityError",
    ),
    "body_changed_after_hash": (
        lambda d: d["source_message"].__setitem__("body", d["source_message"]["body"] + " "),
        "InternalIntegrityError",
    ),
    "subject_null_vs_value": (
        lambda d: d["source_message"].__setitem__("subject", None),
        "InternalIntegrityError",
    ),
    "interpretation_source_hash_mismatch": (
        lambda d: d["interpretation"].__setitem__("source_hash", "1" * 64),
        "StaleState",
    ),
    "interpretation_other_message": (
        lambda d: d["interpretation"].__setitem__("source_message_id", "other_case_msg"),
        "StaleState",
    ),
    "decision_other_interpretation": (
        lambda d: d["approved_decision"].__setitem__("source_interpretation_id", "other_interp"),
        "StaleState",
    ),
    "decision_stale_interpretation_version": (
        lambda d: d["approved_decision"].__setitem__("source_interpretation_version", 2),
        "StaleState",
    ),
    "decision_source_hash_mismatch": (
        lambda d: d["approved_decision"].__setitem__("source_hash", "2" * 64),
        "StaleState",
    ),
    "decision_hash_tampered": (
        lambda d: d["approved_decision"].__setitem__("decision_hash", "3" * 64),
        "InternalIntegrityError",
    ),
    "decision_content_changed_after_hash": (
        lambda d: d["approved_decision"].__setitem__("approved_by", "someone_else"),
        "InternalIntegrityError",
    ),
    "interpretation_version_bumped_without_new_decision": (
        lambda d: d["interpretation"].__setitem__("version", 2),
        "StaleState",
    ),
}


@pytest.mark.parametrize("name", sorted(HASH_AND_BINDING))
def test_hash_and_binding_mismatch_rejected(name: str) -> None:
    mutate, code = HASH_AND_BINDING[name]
    document = _mutated(l2_refund_commitment, mutate, recompute=False)
    result = run(document)
    assert_rejected(result, code)


def test_decision_hash_covers_every_decision_field() -> None:
    base = structural_coverage()
    decision = base["approved_decision"]
    for key in decision:
        if key in ("decision_id", "version", "decision_hash"):
            continue
        document = copy.deepcopy(base)
        target = document["approved_decision"]
        if key == "items":
            target["items"][0]["provenance"]["reason_ja"] = "改変"
        elif key == "approved_commitments":
            target["approved_commitments"][0]["scope"]["raw_text"] = "tampered"
        elif key == "explicitly_unanswered":
            target["explicitly_unanswered"] = []
        elif key == "human_notes":
            target["human_notes"] = ["別メモ"]
        elif key in ("source_interpretation_version",):
            continue  # covered by StaleState binding checks
        elif key in ("approved_at",):
            target[key] = "2026-09-16T00:00:00.000Z"
        elif key in ("source_hash",):
            continue
        else:
            target[key] = "tampered_id"
        result = run(document)
        assert result["status"] == "rejected", key


@pytest.mark.parametrize("policy_version", ["delegation-0.3", "delegation-0.5", "DELEGATION-0.4", "delegation-0.4 ", "delegation-0.2"])
def test_unknown_policy_version_rejected(policy_version: str) -> None:
    document = l0_receipt_confirmation()
    document["policy_version"] = policy_version
    result = run(document)
    # SCHEMA §12: unsupported policy_version is a PolicyViolation.
    assert_rejected(result, "PolicyViolation")


# --- references / evidence / duplicates (AC-2) ---------------------------------------------


def _state(d: Json) -> Json:
    state: Json = d["interpretation"]["state"]
    return state


def _drop_money_evidence(d: Json) -> None:
    _state(d)["monetary_terms"][0]["evidence_ids"] = []
    _state(d)["evidence"].pop(0)


REFERENCE_CASES: dict[str, tuple[Callable[[], Json], Mutator, str]] = {
    "evidence_quote_fabricated": (
        l2_refund_commitment,
        lambda d: _state(d)["evidence"][0].__setitem__("quote", "USD 12.00"),
        "InternalIntegrityError",
    ),
    "evidence_quote_whitespace_variant": (
        l2_refund_commitment,
        lambda d: _state(d)["evidence"][0].__setitem__("quote", "USD  120.00"),
        "InternalIntegrityError",
    ),
    "evidence_other_source_id": (
        l2_refund_commitment,
        lambda d: _state(d)["evidence"][0].__setitem__("source_id", "case_other_msg"),
        "InternalIntegrityError",
    ),
    "evidence_reply_kind_before_draft": (
        l2_refund_commitment,
        lambda d: _state(d)["evidence"][0].__setitem__("source_kind", "reply"),
        "InternalIntegrityError",
    ),
    "evidence_supports_unknown_claim": (
        l2_refund_commitment,
        lambda d: _state(d)["evidence"][0].__setitem__("supports", ["c_m1", "c_ghost"]),
        "InternalIntegrityError",
    ),
    "evidence_supports_not_mutual": (
        l2_refund_commitment,
        lambda d: _state(d)["evidence"][0].__setitem__("supports", ["c_m1", "c_commit"]),
        "InternalIntegrityError",
    ),
    "claim_evidence_unknown": (
        l2_refund_commitment,
        lambda d: _state(d)["monetary_terms"][0].__setitem__("evidence_ids", ["ev01", "ev99"]),
        "InternalIntegrityError",
    ),
    "claim_evidence_not_mutual": (
        l2_refund_commitment,
        lambda d: _state(d)["monetary_terms"][0].__setitem__("evidence_ids", ["ev01", "ev02"]),
        "InternalIntegrityError",
    ),
    "critical_claim_without_evidence": (
        l2_refund_commitment,
        _drop_money_evidence,
        "SchemaInvalid",
    ),
    "duplicate_evidence_id": (
        l2_refund_commitment,
        lambda d: _state(d)["evidence"][1].__setitem__("evidence_id", "ev01"),
        "SchemaInvalid",
    ),
    "duplicate_claim_id_across_types": (
        l0_receipt_confirmation,
        lambda d: _state(d)["questions"][0].__setitem__("id", "c_intent"),
        "SchemaInvalid",
    ),
    "monetary_ref_unknown": (
        l2_refund_commitment,
        lambda d: _state(d)["requested_commitments"][0].__setitem__("monetary_term_ids", ["c_nope"]),
        "InternalIntegrityError",
    ),
    "monetary_ref_wrong_type": (
        l2_refund_commitment,
        lambda d: _state(d)["requested_commitments"][0].__setitem__("monetary_term_ids", ["c_commit"]),
        "InternalIntegrityError",
    ),
    "deadline_ref_wrong_type": (
        l2_refund_commitment,
        lambda d: _state(d)["requested_commitments"][0].__setitem__("deadline_id", "c_m1"),
        "InternalIntegrityError",
    ),
    "clause_commitment_ref_wrong_type": (
        structural_coverage,
        lambda d: _state(d)["contract_terms"][0].__setitem__("commitment_ids", ["c_price"]),
        "InternalIntegrityError",
    ),
    "clause_deadline_ref_unknown": (
        structural_coverage,
        lambda d: _state(d)["contract_terms"][0].__setitem__("deadline_ids", ["c_other_case_date"]),
        "InternalIntegrityError",
    ),
}


@pytest.mark.parametrize("name", sorted(REFERENCE_CASES))
def test_reference_and_evidence_violations_rejected(name: str) -> None:
    base, mutate, code = REFERENCE_CASES[name]
    document = base()
    mutate(document)
    assert_rejected(run(rehash(document)), code)


# --- Decision integrity / approval forgery -------------------------------------------------


def test_decision_must_cover_every_claim() -> None:
    document = l2_refund_commitment()
    document["approved_decision"]["items"].pop(0)
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


def test_decision_item_for_unknown_claim_rejected() -> None:
    document = l2_refund_commitment()
    document["approved_decision"]["items"][0]["source_claim_id"] = "c_ghost"
    assert_rejected(run(rehash_decision(document)), "InternalIntegrityError")


def test_duplicate_decision_item_for_same_claim_rejected() -> None:
    document = l2_refund_commitment()
    extra = copy.deepcopy(document["approved_decision"]["items"][0])
    extra["item_id"] = "item_dup"
    extra["decision"] = "unknown"
    document["approved_decision"]["items"].append(extra)
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


def test_duplicate_item_id_rejected() -> None:
    document = l2_refund_commitment()
    items = document["approved_decision"]["items"]
    items[1]["item_id"] = items[0]["item_id"]
    assert_rejected(run(rehash_decision(document)), "SchemaInvalid")


def test_replacement_kind_or_id_mismatch_rejected() -> None:
    base = l2_deadline_modified()
    wrong_kind = copy.deepcopy(base)
    item = wrong_kind["approved_decision"]["items"][0]
    item["replacement"] = {"kind": "TextClaim", "value": text_claim("c_d1", "2026-10-08")}
    assert_rejected(run(rehash_decision(wrong_kind)), "SchemaInvalid")

    wrong_id = copy.deepcopy(base)
    wrong_id["approved_decision"]["items"][0]["replacement"]["value"]["id"] = "c_other"
    assert_rejected(run(rehash_decision(wrong_id)), "SchemaInvalid")


def test_replacement_cannot_fabricate_evidence() -> None:
    document = l2_refund_commitment()
    replacement = copy.deepcopy(document["interpretation"]["state"]["monetary_terms"][0])
    replacement["evidence_ids"] = ["ev02"]  # evidence of a different claim
    item = document["approved_decision"]["items"][0]
    item["decision"] = "modify"
    item["replacement"] = {"kind": "MonetaryTerm", "value": replacement}
    assert_rejected(run(rehash_decision(document)), "InternalIntegrityError")


def test_replacement_reference_must_exist() -> None:
    document = l2_refund_commitment()
    replacement = copy.deepcopy(document["interpretation"]["state"]["requested_commitments"][0])
    replacement["monetary_term_ids"] = ["c_ghost"]
    item = document["approved_decision"]["items"][1]
    item["decision"] = "modify"
    item["replacement"] = {"kind": "Commitment", "value": replacement}
    approved = copy.deepcopy(replacement)
    approved["authorization_state"] = "approved"
    document["approved_decision"]["approved_commitments"] = [approved]
    assert_rejected(run(rehash_decision(document)), "InternalIntegrityError")


def test_approved_commitments_cannot_include_unapproved_item() -> None:
    document = l0_receipt_confirmation()
    fake = commitment("c_fake", "user", "refund", "everything", state="approved")
    document["approved_decision"]["approved_commitments"] = [fake]
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


def test_approved_commitments_cannot_omit_approved_item() -> None:
    document = l2_refund_commitment()
    document["approved_decision"]["approved_commitments"] = []
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


def test_approved_commitments_from_unknown_item_rejected() -> None:
    document = l2_refund_commitment()
    document["approved_decision"]["items"][1]["decision"] = "unknown"
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


def test_approved_commitment_content_must_match() -> None:
    document = l2_refund_commitment()
    document["approved_decision"]["approved_commitments"][0]["object"]["value"] = "all orders"
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


def test_approved_commitment_state_must_be_approved() -> None:
    document = l2_refund_commitment()
    document["approved_decision"]["approved_commitments"][0]["authorization_state"] = "requested"
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


def test_duplicate_approved_commitment_rejected() -> None:
    document = l2_refund_commitment()
    commitments = document["approved_decision"]["approved_commitments"]
    commitments.append(copy.deepcopy(commitments[0]))
    assert_rejected(run(rehash_decision(document)), "SchemaInvalid")


def test_explicitly_unanswered_must_match_do_not_answer_questions() -> None:
    missing = l2_deadline_modified()
    missing["approved_decision"]["explicitly_unanswered"] = ["c_d1"]
    assert_rejected(run(rehash_decision(missing)), "PolicyViolation")

    document = structural_coverage()
    document["approved_decision"]["explicitly_unanswered"] = []
    assert_rejected(run(rehash_decision(document)), "PolicyViolation")


# --- value constraints ---------------------------------------------------------------------


@pytest.mark.parametrize("placeholder", ["unknown", "UNKNOWN", " n/a ", "TBD", "null", "not_stated", "   "])
def test_explicit_placeholder_rejected(placeholder: str) -> None:
    document = l0_receipt_confirmation()
    document["interpretation"]["state"]["sender_intent"][0]["text"]["value"] = placeholder
    assert_rejected(run(rehash(document)), "SchemaInvalid")


def test_known_none_text_is_not_a_placeholder() -> None:
    document = l0_receipt_confirmation()
    document["interpretation"]["state"]["sender_intent"][0]["text"]["value"] = "None"
    assert run(rehash(document))["status"] == "assessed"


@pytest.mark.parametrize("mtype", ["price", "refund", "discount", "credit", "payment", "fee", "other"])
def test_negative_money_rejected(mtype: str) -> None:
    document = l2_refund_commitment()
    claim = document["interpretation"]["state"]["monetary_terms"][0]
    claim.update(money("c_m1", {"status": "explicit", "value": "-1", "raw_text": ""}, claim["currency"], mtype))
    claim["evidence_ids"] = ["ev01"]
    assert_rejected(run(rehash(document)), "SchemaInvalid")


@pytest.mark.parametrize(
    ("value", "unit", "ok"), [("-1", "seats", False), ("100", "percent", True), ("100.01", "percent", False), ("0", "percent", True)]
)
def test_quantity_constraints(value: str, unit: str, ok: bool) -> None:
    document = structural_coverage()
    claim = document["interpretation"]["state"]["quantities"][0]
    claim.update(
        quantity("c_seats", {"status": "explicit", "value": value, "raw_text": ""}, {"status": "explicit", "value": unit, "raw_text": ""})
    )
    claim["evidence_ids"] = ["ev06"]
    result = run(rehash(document))
    assert (result["status"] == "assessed") is ok, result


def test_source_size_limit() -> None:
    at_limit = l0_receipt_confirmation()
    body = at_limit["source_message"]["body"]
    subject = at_limit["source_message"]["subject"]
    pad = 64 * 1024 - len(body.encode()) - len(subject.encode())
    at_limit["source_message"]["body"] = body + "x" * pad
    assert run(rehash(at_limit))["status"] == "assessed"

    over = copy.deepcopy(at_limit)
    over["source_message"]["body"] += "x"
    result = run(rehash(over))
    assert_rejected(result, "UnsupportedInput")

    multibyte = l0_receipt_confirmation()
    multibyte["source_message"]["body"] += "あ" * (64 * 1024 // 3)
    assert_rejected(run(rehash(multibyte)), "UnsupportedInput")
