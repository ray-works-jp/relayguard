"""Verifier + Policy status + post-verification Delegation (IMPLEMENTATION.md §5.8-5.9, SCHEMA.md §7-8).

The Verifier here is a deterministic rule verifier (no LLM). It receives the original
source, the Approved Decision, the pre-generation assessment, the final reply and the
Decision-blind extraction; it never receives Generator rationale or represented_state.

Authority order (ADR-016, DELEGATION.md §12.2/§12.8):
- binding / hash mismatch -> Rejection(StaleState / InternalIntegrityError), no Verification,
- deterministic diff findings are final: a critical finding is BLOCK and post level L3_STOP,
  and no verifier finding can remove or downgrade it,
- the proposal is advisory; ``policy_status`` is assigned here by Domain rules only,
- post level >= max(pre level, post minimum); it is never lower than the pre assessment.

The natural-language meaning of free text is NOT verified. Safety for free text comes from
the closed-world rule in diff_engine (the reply may only contain approved lines), so an
edit that introduces new wording is blocked instead of being "understood".
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .canonical import sha256_hex
from .delegation import LEVEL_ORDER, POLICY_VERSION, Level, level_rank, max_level
from .diff_engine import compute_diff
from .errors import Rejection
from .generator import EMOTION_LINE, context_binding, draft_binding
from .integrity import DomainContext
from .reply_extractor import split_lines
from .schema_validation import validate_draft, validate_verification_contract

VERIFIER_VERSION = "rg-verifier-det-1"

_LOW_RISK_CODES = {"LOW_RISK_INFORMATIONAL": "L0_AUTO", "LOW_RISK_POST_REVIEW": "L1_POST_REVIEW"}
_FINDING_REASON: dict[str, str] = {
    "legal_claim_detected": "LEGAL_CLAIM",
    "prompt_injection_risk": "UNRESOLVED_PROMPT_INJECTION",
    "attachment_dependency": "ATTACHMENT_REQUIRED_MISSING",
}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class VerifierRuntime:
    new_id: Callable[[str], str] = field(default=_new_id)


def check_draft_bindings(ctx: DomainContext, pre_assessment: dict[str, Any], draft: dict[str, Any], extraction: dict[str, Any]) -> None:
    """SCHEMA.md §5: every binding must equal the latest server-side object exactly."""
    validate_draft(draft)
    validate_verification_contract("DelegationAssessment", pre_assessment)
    validate_verification_contract("ReplyExtraction", extraction)
    if ctx.policy_version != POLICY_VERSION:
        raise Rejection("PolicyViolation", "未対応のpolicy_versionです。")
    current = context_binding(ctx)
    if pre_assessment["phase"] != "pre_generation" or pre_assessment["binding"] != current:
        raise Rejection("StaleState", "事前Delegation判定が現在のDecisionに束縛されていません。")
    if draft["binding"] != current:
        raise Rejection("StaleState", "Draftが現在のDecision（version/hash/policy）から生成されていません。")
    if draft["draft_hash"] != sha256_hex(draft["reply_text"].encode("utf-8")):
        raise Rejection("InternalIntegrityError", "draft_hashが返信本文と一致しません。")
    if extraction["binding"] != draft_binding(draft):
        raise Rejection("StaleState", "Reply Extractionが対象Draftに束縛されていません。Draft編集後は再抽出が必要です。")
    for evidence in extraction["state"]["evidence"]:
        if (
            evidence["source_kind"] != "reply"
            or evidence["source_id"] != draft["draft_id"]
            or evidence["source_hash"] != draft["draft_hash"]
            or evidence["quote"] not in draft["reply_text"]
        ):
            raise Rejection("InternalIntegrityError", "Reply ExtractionのEvidenceが対象Draftの本文に一致しません。")


def _rule_findings(ctx: DomainContext, pre_assessment: dict[str, Any], draft: dict[str, Any], start: int) -> list[dict[str, Any]]:
    state = ctx.interpretation["state"]
    findings: list[dict[str, Any]] = []

    def add(ftype: str, severity: str, explanation: str, expected: list[str], blocking: bool = True) -> None:
        findings.append(
            {
                "finding_id": f"fd_{start + len(findings) + 1:03d}",
                "type": ftype,
                "severity": severity,
                "blocking": True if severity == "critical" else blocking,
                "origin": "verifier",
                "expected_claim_ids": sorted(set(expected)),
                "actual_claim_ids": [],
                "evidence_ids": [],
                "explanation_ja": explanation,
            }
        )

    if state["legal_claims"]:
        add(
            "legal_claim_detected",
            "critical",
            "原文に法的主張があります。AI処理を停止し手動対応してください。",
            [c["id"] for c in state["legal_claims"]],
        )
    unresolved_injection = [r["id"] for r in state["prompt_injection_risks"] if not r["resolved"]]
    if unresolved_injection:
        add("prompt_injection_risk", "critical", "原文に未解決のプロンプトインジェクションの疑いがあります。", unresolved_injection)
    if state["attachment_dependencies"]:
        add(
            "attachment_dependency",
            "critical",
            "添付ファイルに依存する内容があり、添付は解析しません。",
            [r["id"] for r in state["attachment_dependencies"]],
        )
    if state["customer_emotion"] and EMOTION_LINE not in split_lines(draft["reply_text"]):
        add(
            "customer_emotion_missed",
            "medium",
            "相手の感情（不満・不信など）への配慮文がありません。",
            [e["id"] for e in state["customer_emotion"]],
            blocking=False,
        )
    if level_rank(pre_assessment["level"]) < level_rank(pre_assessment["minimum_level"]):
        add("delegation_level_too_low", "critical", "事前判定のlevelがminimum_levelを下回っています。", [])
    return findings


def post_verification_assessment(
    pre_assessment: dict[str, Any], draft: dict[str, Any], findings: list[dict[str, Any]], complete: bool, runtime: VerifierRuntime
) -> dict[str, Any]:
    minimum: Level = pre_assessment["minimum_level"]
    codes = set(pre_assessment["reason_codes"])
    if not complete:
        minimum = "L3_STOP"
        codes.add("INCOMPLETE_PIPELINE")
    for finding in findings:
        if finding["severity"] == "critical":
            minimum = "L3_STOP"
            codes.add(_FINDING_REASON.get(finding["type"], "CRITICAL_DIFF"))
        elif finding["blocking"]:
            minimum = max_level([minimum, "L2_PRE_APPROVAL"])
            codes.add("VERIFIER_BLOCK")
    level = max_level([pre_assessment["level"], minimum])
    for code, code_level in _LOW_RISK_CODES.items():
        if code in codes and code_level != level:
            codes.discard(code)
    if not codes:
        codes.add("UNCLASSIFIED_RISK")
    risk_factors = dict(pre_assessment["risk_factors"])
    if level == "L3_STOP" and any(f["severity"] == "critical" for f in findings):
        risk_factors["uncertainty"] = "high"
    assessment = {
        "assessment_id": runtime.new_id("asm_post"),
        "binding": copy.deepcopy(pre_assessment["binding"]),
        "phase": "post_verification",
        "draft_binding": draft_binding(draft),
        "level": level,
        "minimum_level": minimum,
        "reason_codes": sorted(codes),
        "risk_factors": risk_factors,
        "shadow_mode": True,
        "human_review_required": level != "L0_AUTO",
    }
    validate_verification_contract("DelegationAssessment", assessment)
    if level_rank(level) < level_rank(pre_assessment["level"]) or level not in LEVEL_ORDER:
        raise Rejection("DelegationConflict", "事後判定が事前判定より低いレベルになりました。")
    return assessment


def verify_draft(
    ctx: DomainContext,
    pre_assessment: dict[str, Any],
    draft: dict[str, Any],
    extraction: dict[str, Any],
    *,
    runtime: VerifierRuntime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (Verification, post-verification DelegationAssessment)."""
    runtime = runtime or VerifierRuntime()
    check_draft_bindings(ctx, pre_assessment, draft, extraction)
    try:
        diff = compute_diff(ctx, draft, extraction)
    except Rejection:
        raise
    except Exception:  # noqa: BLE001 - an incomplete diff is never "no difference"
        diff = {"binding": draft_binding(draft), "findings": [], "checked_fields": [], "complete": False}
    validate_verification_contract("DiffResult", diff)

    findings = [*diff["findings"], *_rule_findings(ctx, pre_assessment, draft, len(diff["findings"]))]
    post = post_verification_assessment(pre_assessment, draft, findings, diff["complete"], runtime)
    blocking = [f for f in findings if f["blocking"]]
    required = {r.claim_id for r in ctx.claims.values() if r.kind == "Question" and r.body["required_answer"]}
    covered = {a["question_id"] for a in ctx.decision["question_answers"]} | set(ctx.decision["explicitly_unanswered"])
    extraction_state = extraction["state"]
    new_commitment_ids = {cid for f in findings if f["type"] == "commitment_added" for cid in f["actual_claim_ids"]}
    proposal = {
        "binding": draft_binding(draft),
        "overall_status": "blocked" if blocking else ("minor_differences" if findings else "matched"),
        "findings": findings,
        "unanswered_items": sorted(required - covered),
        "new_commitments": [c for c in extraction_state["commitments"] if c["id"] in new_commitment_ids],
        "uncertain_items": sorted(
            claim["id"]
            for array in ("monetary_terms", "dates", "quantities")
            for claim in extraction_state[array]
            if any(isinstance(v, dict) and v.get("status") == "ambiguous" for v in claim.values())
        ),
        "delegation_reassessment": {"level": post["level"], "reason_codes": post["reason_codes"]},
        "human_review_required": True,
    }
    policy_blocked = (
        not diff["complete"]
        or bool(blocking)
        or post["level"] == "L3_STOP"
        or bool(required - covered)
        or pre_assessment["level"] == "L3_STOP"
    )
    verification = {
        "verification_id": runtime.new_id("ver"),
        "binding": draft_binding(draft),
        "extraction_id": extraction["extraction_id"],
        "verifier_execution_id": runtime.new_id("vex"),
        "diff": diff,
        "proposal": proposal,
        "policy_status": "BLOCK" if policy_blocked else "SAFE_CANDIDATE",
        "policy_version": ctx.policy_version,
    }
    validate_verification_contract("Verification", verification)
    return verification, post
