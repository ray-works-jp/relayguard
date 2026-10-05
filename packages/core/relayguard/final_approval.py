"""Final Approval and Copy boundary (IMPLEMENTATION.md §5.10/§24, SCHEMA.md §9, DELEGATION.md §13).

Server-side revalidation only; a client-supplied "approved" state is never trusted.
The MVP stops here: the approved reply may be copied by the human. Nothing is sent.

Required (all must hold, otherwise Rejection and no FinalApproval):
- the Draft was generated from the current Decision (binding equals the latest binding),
- the Verification references this Draft (id + hash) and this Decision,
- the post-verification assessment references the same Draft and Decision,
- Verification.policy_status == SAFE_CANDIDATE and no blocking finding,
- post level != L3_STOP, pre level != L3_STOP,
- draft_hash matches the reply text byte-for-byte,
- the approver is the authenticated operator supplied by the trusted caller.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .canonical import canonical_hash, sha256_hex
from .errors import Rejection
from .generator import context_binding, draft_binding
from .integrity import DomainContext
from .schema_validation import validate_verification_contract
from .shadow_core import format_timestamp


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class ApprovalRuntime:
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    new_id: Callable[[str], str] = field(default=_new_id)


def approval_hash(approval: dict[str, Any]) -> str:
    return canonical_hash({k: v for k, v in approval.items() if k != "approval_hash"})


@dataclass(frozen=True)
class VerifiedDraft:
    """The server-side records one Final Approval must bind together."""

    pre_assessment: dict[str, Any]
    draft: dict[str, Any]
    verification: dict[str, Any]
    post_assessment: dict[str, Any]


def check_approvable(ctx: DomainContext, record: VerifiedDraft) -> None:
    pre_assessment, draft = record.pre_assessment, record.draft
    verification, post_assessment = record.verification, record.post_assessment
    current = context_binding(ctx)
    expected_draft_binding = draft_binding(draft)
    if draft["draft_hash"] != sha256_hex(draft["reply_text"].encode("utf-8")):
        raise Rejection("InternalIntegrityError", "draft_hashが返信本文と一致しません。")
    if draft["binding"] != current or pre_assessment["binding"] != current or post_assessment["binding"] != current:
        raise Rejection("StaleState", "Draft・判定が最新のDecision（version/hash/policy）に束縛されていません。")
    if verification["binding"] != expected_draft_binding or post_assessment["draft_binding"] != expected_draft_binding:
        raise Rejection("StaleState", "Verification・事後判定が対象Draftを参照していません。再検証が必要です。")
    if verification["policy_version"] != ctx.policy_version:
        raise Rejection("StaleState", "Verificationのpolicy_versionが現在のpolicyと一致しません。")
    if pre_assessment["level"] == "L3_STOP" or post_assessment["level"] == "L3_STOP":
        raise Rejection("SafetyBlock", "L3_STOPの案件は最終承認・コピーできません。")
    if verification["policy_status"] != "SAFE_CANDIDATE":
        raise Rejection("SafetyBlock", "定義済み検査を通過していない返信案は最終承認できません。")
    if any(finding["blocking"] for finding in verification["proposal"]["findings"]):
        raise Rejection("SafetyBlock", "blocking findingが残っているため最終承認できません。")


def final_approve(
    ctx: DomainContext,
    record: VerifiedDraft,
    *,
    approver_id: str,
    runtime: ApprovalRuntime | None = None,
) -> dict[str, Any]:
    """Return FinalApproval. ``approver_id`` must come from the trusted session, not the form."""
    runtime = runtime or ApprovalRuntime()
    validate_verification_contract("Verification", record.verification)
    validate_verification_contract("DelegationAssessment", record.post_assessment)
    check_approvable(ctx, record)
    approval: dict[str, Any] = {
        "approval_id": runtime.new_id("fap"),
        "binding": draft_binding(record.draft),
        "verification_id": record.verification["verification_id"],
        "assessment_id": record.post_assessment["assessment_id"],
        "approved_by": approver_id,
        "approved_at": format_timestamp(runtime.clock()),
    }
    approval["approval_hash"] = approval_hash(approval)
    validate_verification_contract("FinalApproval", approval)
    return approval
