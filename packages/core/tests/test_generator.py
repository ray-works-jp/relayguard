"""Deterministic Generator (packages/core/relayguard/generator.py).

Ported from the pre-2026-09-17 generator tests to the Domain-context API. Every original
safety intent is kept: determinism, hash binding, answers/commitments only from the Approved
Decision, L3 refusal, unapproved commitment refusal, stale binding refusal, approver and
language/style contract. Japanese output was removed because SCHEMA.md §6 fixes the
generator response_language to "en".
"""

from __future__ import annotations

import copy
import hashlib

import pytest
from builders import CaseBuilder, Json, commitment, date_term, emotion, ex, legal, money, question, rehash, to_bytes
from pipeline_support import assess, assess_document, generate, runtimes

from relayguard.errors import Rejection
from relayguard.generator import (
    BOILERPLATE_LINES,
    EMOTION_LINE,
    StyleConstraints,
    compute_draft_hash,
    draft_binding,
    edited_draft,
    generate_draft,
)
from relayguard.schema_validation import validate_draft, validate_draft_binding
from relayguard.shadow_core import run_shadow_core


def refund_case(answer: str = "Yes, the photo was received.") -> Json:
    b = CaseBuilder(
        "case_gen_01",
        "Order A-1001 arrived with a broken mug. Because the mug was damaged in transit, "
        "we ask you to refund USD 120.00 for the mug only by 2026-10-01 JST. Did you receive the photo?",
    )
    b.add("monetary_terms", money("c_m1", ex("120.00", "USD 120.00"), ex("USD"), "refund", ex("damaged in transit")), "USD 120.00")
    b.add("dates", date_term("c_d1", ex("2026-10-01"), "deadline", ex("JST")), "by 2026-10-01 JST")
    commit = commitment("c_commit", "user", "refund USD 120.00", "the broken mug from order A-1001", deadline_id="c_d1", monetary=["c_m1"])
    commit["condition"] = ex("the mug was damaged in transit")
    commit["scope"] = ex("the mug only")
    b.add("requested_commitments", commit, "refund USD 120.00", "for the mug only")
    b.add("questions", question("c_q1", "Did you receive the photo?"), "Did you receive the photo?")
    b.answer("c_q1", answer)
    return b.build()


def test_deterministic_generation_same_inputs_same_output() -> None:
    ctx, pre = assess_document(refund_case())
    first = generate(ctx, pre, seed="a")
    second = generate(ctx, pre, seed="a")
    assert first == second
    assert first["reply_text"] == generate(ctx, pre, seed="b")["reply_text"]
    validate_draft(first)


def test_draft_hash_binding_changes_on_any_character_mutation() -> None:
    ctx, pre = assess_document(refund_case())
    draft = generate(ctx, pre)
    assert draft["draft_hash"] == hashlib.sha256(draft["reply_text"].encode("utf-8")).hexdigest()
    for mutated in (draft["reply_text"] + " ", draft["reply_text"].replace("120.00", "120.01"), draft["reply_text"].replace("\n", "\r\n")):
        assert compute_draft_hash(mutated) != draft["draft_hash"]


def test_generation_incorporates_approved_question_answers_verbatim() -> None:
    ctx, pre = assess_document(refund_case("Yes, the photo was received.\nThank you for sending it."))
    lines = generate(ctx, pre)["reply_text"].splitlines()
    assert "Yes, the photo was received." in lines
    assert "Thank you for sending it." in lines


def test_generation_renders_every_approved_commitment_value() -> None:
    ctx, pre = assess_document(refund_case())
    text = generate(ctx, pre)["reply_text"]
    assert "We will: refund USD 120.00" in text
    assert "- Condition: the mug was damaged in transit" in text
    assert "- Scope: the mug only" in text
    assert "- Amount: USD 120.00 (refund), condition: damaged in transit" in text
    assert "- Deadline: 2026-10-01 (timezone: JST)" in text


def test_rejected_commitment_is_not_rendered() -> None:
    document = refund_case()
    b_items = document["approved_decision"]["items"]
    for item in b_items:
        if item["source_claim_id"] == "c_commit":
            item["decision"] = "do_not_answer"
    document["approved_decision"]["approved_commitments"] = []
    ctx, pre = assess_document(rehash(document))
    text = generate(ctx, pre)["reply_text"]
    assert "refund" not in text.lower()
    assert "120.00" not in text


def test_generator_rejects_l3_stop_assessment() -> None:
    b = CaseBuilder("case_gen_l3", "We will sue you unless you refund now.")
    b.add("legal_claims", legal("c_legal", "threat of lawsuit"), "We will sue you")
    ctx, pre = assess(to_bytes(b.build()))
    assert pre["level"] == "L3_STOP"
    with pytest.raises(Rejection) as exc:
        generate(ctx, pre)
    assert exc.value.code == "SafetyBlock"


def test_generator_rejects_forged_low_level_on_l3_minimum() -> None:
    b = CaseBuilder("case_gen_l3b", "We will sue you unless you refund now.")
    b.add("legal_claims", legal("c_legal", "threat of lawsuit"), "We will sue you")
    ctx, pre = assess(to_bytes(b.build()))
    forged = copy.deepcopy(pre)
    forged["level"] = "L0_AUTO"
    with pytest.raises(Rejection) as exc:
        generate(ctx, forged)
    assert exc.value.code == "SafetyBlock"


def test_unapproved_commitment_claimed_approved_in_interpretation_is_rejected_upstream() -> None:
    document = refund_case()
    document["interpretation"]["state"]["requested_commitments"][0]["authorization_state"] = "approved"
    result = run_shadow_core(to_bytes(rehash(document)))
    assert result["status"] == "rejected"
    assert result["failure"]["code"] == "PolicyViolation"


def test_generator_rejects_stale_assessment_binding() -> None:
    ctx, pre = assess_document(refund_case())
    stale = copy.deepcopy(pre)
    stale["binding"]["decision_hash"] = "f" * 64
    with pytest.raises(Rejection) as exc:
        generate(ctx, stale)
    assert exc.value.code == "StaleState"
    other_ctx, _ = assess_document(refund_case("Yes, received on time."))
    with pytest.raises(Rejection) as exc2:
        generate(other_ctx, pre)
    assert exc2.value.code == "StaleState"


def test_generator_requires_pre_generation_phase() -> None:
    ctx, pre = assess_document(refund_case())
    post_like = copy.deepcopy(pre)
    post_like["phase"] = "post_verification"
    with pytest.raises(Rejection) as exc:
        generate(ctx, post_like)
    assert exc.value.code == "PolicyViolation"


def test_missing_approved_by_is_rejected_by_schema() -> None:
    document = refund_case()
    document["approved_decision"]["approved_by"] = ""
    result = run_shadow_core(to_bytes(rehash(document)))
    assert result["status"] == "rejected"
    assert result["failure"]["code"] == "SchemaInvalid"


def test_generator_rejects_unsupported_tone() -> None:
    ctx, pre = assess_document(refund_case())
    with pytest.raises(Rejection) as exc:
        generate_draft(ctx, pre, style=StyleConstraints(tone="casual"), runtime=runtimes()[0])
    assert exc.value.code == "SchemaInvalid"


def test_output_language_is_english_only() -> None:
    ctx, pre = assess_document(refund_case())
    text = generate(ctx, pre)["reply_text"]
    assert all(ord(ch) < 128 for ch in text)


def test_draft_binding_contract() -> None:
    ctx, pre = assess_document(refund_case())
    draft = generate(ctx, pre)
    binding = draft_binding(draft)
    validate_draft_binding(binding)
    assert binding["decision"] == pre["binding"]
    assert binding["draft_hash"] == draft["draft_hash"]


def test_style_constraints_concise_uses_single_newlines() -> None:
    ctx, pre = assess_document(refund_case())
    concise = generate_draft(ctx, pre, style=StyleConstraints(concise=True), runtime=runtimes()[0])["reply_text"]
    assert "\n\n" not in concise
    assert concise.splitlines() == [line for line in generate(ctx, pre)["reply_text"].splitlines() if line]


def test_emotion_acknowledgement_line_only_when_emotion_present() -> None:
    ctx, pre = assess_document(refund_case())
    assert EMOTION_LINE not in generate(ctx, pre)["reply_text"]
    b = CaseBuilder("case_gen_emotion", "This is the third time the delivery is late. I am really upset.")
    b.add("customer_emotion", emotion("c_em", "anger", "late delivery", "medium"), "I am really upset.")
    ctx2, pre2 = assess_document(b.build())
    assert EMOTION_LINE in generate(ctx2, pre2)["reply_text"]
    assert EMOTION_LINE in BOILERPLATE_LINES


def test_edit_creates_new_draft_identity() -> None:
    ctx, pre = assess_document(refund_case())
    draft = generate(ctx, pre)
    edited = edited_draft(draft, draft["reply_text"] + "PS.\n", runtime=runtimes("e")[0])
    assert edited["draft_id"] != draft["draft_id"]
    assert edited["draft_hash"] != draft["draft_hash"]
    assert edited["binding"] == draft["binding"]
    with pytest.raises(Rejection):
        edited_draft(draft, "   \n")
