"""Final Approval server-side revalidation (IMPLEMENTATION.md §5.10/§24, SCHEMA.md §9, DELEGATION.md §13)."""

from __future__ import annotations

import copy

import pytest
from builders import CaseBuilder, Json, question
from pipeline_support import assess_document, generate, runtimes, verify_text

from relayguard.errors import Rejection
from relayguard.final_approval import VerifiedDraft, approval_hash, final_approve
from relayguard.generator import edited_draft
from relayguard.integrity import DomainContext
from relayguard.schema_validation import validate_verification_contract


def answered_case(answer: str = "Yes, the catalogue arrived.") -> Json:
    b = CaseBuilder("case_fa_01", "Did the catalogue arrive?")
    b.add("questions", question("c_q1", "Did the catalogue arrive?"), "Did the catalogue arrive?")
    b.answer("c_q1", answer)
    return b.build()


def pipeline(answer: str = "Yes, the catalogue arrived.") -> tuple[DomainContext, Json, Json, Json, Json]:
    ctx, pre = assess_document(answered_case(answer))
    draft = generate(ctx, pre)
    _, verification, post = verify_text(ctx, pre, draft)
    assert verification["policy_status"] == "SAFE_CANDIDATE"
    return ctx, pre, draft, verification, post


def approve(ctx: DomainContext, pre: Json, draft: Json, verification: Json, post: Json, approver: str = "op_local") -> Json:
    record = VerifiedDraft(pre_assessment=pre, draft=draft, verification=verification, post_assessment=post)
    return final_approve(ctx, record, approver_id=approver, runtime=runtimes("fa")[3])


def test_happy_path_approval_is_bound_and_hashed() -> None:
    ctx, pre, draft, verification, post = pipeline()
    approval = approve(ctx, pre, draft, verification, post)
    validate_verification_contract("FinalApproval", approval)
    assert approval["binding"]["draft_hash"] == draft["draft_hash"]
    assert approval["verification_id"] == verification["verification_id"]
    assert approval["assessment_id"] == post["assessment_id"]
    assert approval["approved_by"] == "op_local"
    assert approval["approval_hash"] == approval_hash(approval)


def test_blocked_verification_cannot_be_approved() -> None:
    ctx, pre, draft, _, _ = pipeline()
    tampered = edited_draft(
        draft, draft["reply_text"].replace("Thank you for your message.", "Thank you for your message.\nWe will refund USD 500.00.")
    )
    _, verification, post = verify_text(ctx, pre, tampered)
    assert verification["policy_status"] == "BLOCK"
    with pytest.raises(Rejection) as exc:
        approve(ctx, pre, tampered, verification, post)
    assert exc.value.code == "SafetyBlock"


def test_client_forged_safe_status_on_blocked_draft_is_rejected() -> None:
    ctx, pre, draft, _, _ = pipeline()
    tampered = edited_draft(draft, draft["reply_text"] + "We guarantee delivery.\n")
    _, verification, post = verify_text(ctx, pre, tampered)
    forged = copy.deepcopy(verification)
    forged["policy_status"] = "SAFE_CANDIDATE"
    forged_post = copy.deepcopy(post)
    forged_post["level"] = pre["level"]
    forged_post["minimum_level"] = pre["minimum_level"]
    with pytest.raises(Rejection) as exc:
        approve(ctx, pre, tampered, forged, forged_post)
    assert exc.value.code in ("SafetyBlock", "InternalIntegrityError")


def test_old_verification_is_void_after_draft_edit() -> None:
    ctx, pre, draft, verification, post = pipeline()
    edited = edited_draft(draft, draft["reply_text"] + "\n")
    with pytest.raises(Rejection) as exc:
        approve(ctx, pre, edited, verification, post)
    assert exc.value.code == "StaleState"


def test_verification_for_other_decision_is_rejected() -> None:
    _, _, draft, verification, post = pipeline()
    ctx2, pre2 = assess_document(answered_case("No, it has not arrived yet."))
    with pytest.raises(Rejection) as exc:
        approve(ctx2, pre2, draft, verification, post)
    assert exc.value.code == "StaleState"


def test_draft_hash_tamper_is_rejected() -> None:
    ctx, pre, draft, verification, post = pipeline()
    tampered = dict(draft, reply_text=draft["reply_text"].replace("arrived", "arrived damaged"))
    with pytest.raises(Rejection) as exc:
        approve(ctx, pre, tampered, verification, post)
    assert exc.value.code == "InternalIntegrityError"


def test_l3_post_level_is_never_approvable() -> None:
    ctx, pre, draft, verification, post = pipeline()
    l3 = copy.deepcopy(post)
    l3["level"] = "L3_STOP"
    l3["minimum_level"] = "L3_STOP"
    l3["human_review_required"] = True
    with pytest.raises(Rejection) as exc:
        approve(ctx, pre, draft, verification, l3)
    assert exc.value.code == "SafetyBlock"


def test_policy_version_mismatch_is_rejected() -> None:
    ctx, pre, draft, verification, post = pipeline()
    other = copy.deepcopy(verification)
    other["policy_version"] = "delegation-0.3"
    with pytest.raises(Rejection) as exc:
        approve(ctx, pre, draft, other, post)
    assert exc.value.code == "StaleState"


def test_invalid_approver_id_is_rejected_by_contract() -> None:
    ctx, pre, draft, verification, post = pipeline()
    with pytest.raises(Rejection):
        approve(ctx, pre, draft, verification, post, approver="op local!")
