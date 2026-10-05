"""Shadow Core minimum execution path (SG-001, SCHEMA.md v0.5 §10/§12/§13).

offline ShadowCoreInput bytes -> strict parse -> schema -> Domain/binding -> pre-generation
Delegation Assessment -> result + audit metadata. Fail closed: every failure becomes
``status=rejected``; no default level, no fabricated Decision, no external action.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from . import SCHEMA_VERSION
from .audit import AuditEntry, build_chain, verify_chain
from .canonical import canonical_hash
from .delegation import POLICY_VERSION, PolicyOutcome, assess_pre_generation, level_rank
from .errors import Rejection
from .integrity import DomainContext, check_source_size, validate_domain
from .schema_validation import shadow_core_result_errors, validate_shadow_core_input
from .strict_json import parse_strict_json

logger = logging.getLogger("relayguard.shadow_core")

# Installed policies. Policy definitions are never read from input.
POLICIES: dict[str, Callable[[DomainContext], PolicyOutcome]] = {
    POLICY_VERSION: assess_pre_generation,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class ShadowCoreRuntime:
    """Trusted caller context. SG-001 supports only offline fixture invocation, so the
    supplied Approved Decision is always recorded as fixture-originated, never as a real
    authenticated user approval."""

    clock: Callable[[], datetime] = field(default=_utc_now)
    new_id: Callable[[str], str] = field(default=_new_id)
    invocation: Literal["fixture"] = "fixture"


def format_timestamp(moment: datetime) -> str:
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _rejected(rejection: Rejection, case_id: str | None) -> dict[str, Any]:
    return {
        "status": "rejected",
        "schema_version": SCHEMA_VERSION,
        "failure": {
            "code": rejection.code,
            "explanation_ja": rejection.explanation_ja,
            "retryable": False,
            "case_id": case_id,
        },
        "external_action_performed": False,
    }


def _build_assessed(ctx: DomainContext, outcome: PolicyOutcome, input_hash: str, runtime: ShadowCoreRuntime) -> dict[str, Any]:
    source = ctx.source
    interpretation = ctx.interpretation
    decision = ctx.decision
    binding = {
        "case_id": ctx.case_id,
        "source_hash": source["content_hash"],
        "interpretation_id": interpretation["interpretation_id"],
        "interpretation_version": interpretation["version"],
        "decision_id": decision["decision_id"],
        "decision_version": decision["version"],
        "decision_hash": decision["decision_hash"],
        "policy_version": ctx.policy_version,
    }
    assessment: dict[str, Any] = {
        "assessment_id": runtime.new_id("asm"),
        "binding": binding,
        "phase": "pre_generation",
        "draft_binding": None,
        "level": outcome.level,
        "minimum_level": outcome.minimum_level,
        "reason_codes": list(outcome.reason_codes),
        "risk_factors": dict(outcome.risk_factors),
        "shadow_mode": True,
        "human_review_required": outcome.human_review_required,
    }
    entries = [
        AuditEntry("system", None, "source_message.received", source["message_id"], source["content_hash"]),
        AuditEntry(
            runtime.invocation,
            None,
            "interpretation.supplied_by_fixture",
            interpretation["interpretation_id"],
            canonical_hash(interpretation),
        ),
        AuditEntry(
            runtime.invocation,
            decision["approved_by"],
            "decision.approval_supplied_by_fixture",
            decision["decision_id"],
            decision["decision_hash"],
        ),
        AuditEntry(
            "system",
            None,
            "delegation.pre_generation_assessed",
            assessment["assessment_id"],
            canonical_hash(assessment),
        ),
    ]
    audit = build_chain(
        ctx.case_id,
        entries,
        [runtime.new_id("evt") for _ in entries],
        format_timestamp(runtime.clock()),
    )
    return {
        "status": "assessed",
        "schema_version": SCHEMA_VERSION,
        "case_id": ctx.case_id,
        "assessment": assessment,
        "input_hash": input_hash,
        "audit": audit,
        "external_action_performed": False,
    }


def assessed_result_problems(result: dict[str, Any]) -> list[str]:
    """Contract + invariant checks on an assessed result (used before returning it)."""
    problems = shadow_core_result_errors(result)
    if problems:
        return problems
    assessment = result["assessment"]
    if level_rank(assessment["level"]) < level_rank(assessment["minimum_level"]):
        problems.append("level below minimum_level")
    if assessment["reason_codes"] != sorted(assessment["reason_codes"]):
        problems.append("reason_codes not sorted")
    if assessment["phase"] != "pre_generation" or assessment["draft_binding"] is not None:
        problems.append("SG-001 produces pre_generation assessments only")
    if assessment["binding"]["case_id"] != result["case_id"]:
        problems.append("binding case mismatch")
    if assessment["binding"]["policy_version"] not in POLICIES:
        problems.append("unsupported policy_version in binding")
    if not verify_chain(result["case_id"], result["audit"]):
        problems.append("audit chain invalid")
    elif result["audit"][-1]["entity_hash"] != canonical_hash(assessment):
        problems.append("audit does not bind the assessment")
    if any(event["actor_type"] == "user" for event in result["audit"]):
        problems.append("fixture invocation must not record user approval")
    return problems


def _log(result: dict[str, Any], elapsed_ms: int) -> None:
    # Operational telemetry: metadata only. No subject/body/quotes/claim text/notes.
    record: dict[str, Any] = {"event": "shadow_core.completed", "status": result["status"], "latency_ms": elapsed_ms}
    if result["status"] == "assessed":
        assessment = result["assessment"]
        record.update(
            case_id=result["case_id"],
            input_hash=result["input_hash"],
            policy_version=assessment["binding"]["policy_version"],
            decision_version=assessment["binding"]["decision_version"],
            assessment_id=assessment["assessment_id"],
            level=assessment["level"],
            minimum_level=assessment["minimum_level"],
            reason_codes=assessment["reason_codes"],
        )
    else:
        record["error_code"] = result["failure"]["code"]
    logger.info(json.dumps(record, ensure_ascii=True, sort_keys=True))


def run_shadow_core(raw: bytes, runtime: ShadowCoreRuntime | None = None) -> dict[str, Any]:
    runtime = runtime or ShadowCoreRuntime()
    started = time.monotonic()
    case_id: str | None = None
    try:
        if runtime.invocation != "fixture":
            raise Rejection("PolicyViolation", "SG-001はoffline fixture呼出しのみ対応します。")
        document = parse_strict_json(raw)
        validate_shadow_core_input(document)
        case_id = document["case_id"]
        check_source_size(document["source_message"])
        policy = POLICIES.get(document["policy_version"])
        if policy is None:
            # SCHEMA §12: unsupported policy_version is PolicyViolation (schema version
            # violations are SchemaInvalid and are caught by the schema validator).
            raise Rejection(
                "PolicyViolation",
                "未対応のpolicy_versionです。インストール済みのDelegation Policyのみ使用できます。",
            )
        ctx = validate_domain(document)
        outcome = policy(ctx)
        result = _build_assessed(ctx, outcome, canonical_hash(document), runtime)
        problems = assessed_result_problems(result)
        if problems:
            raise Rejection("InternalIntegrityError", "判定結果が結果契約・不変条件を満たしません。結果を破棄しました。")
    except Rejection as rejection:
        result = _rejected(rejection, case_id)
    except Exception:  # noqa: BLE001 - fail closed on any unexpected error
        result = _rejected(
            Rejection("InternalIntegrityError", "内部エラーにより判定できませんでした。既定レベルは返しません。"),
            case_id,
        )
    _log(result, int((time.monotonic() - started) * 1000))
    return result
