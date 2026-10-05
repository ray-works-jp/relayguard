"""Application service for the local reviewer app (IMPLEMENTATION.md §6, §9, §10, §23, §24).

Holds cases in process memory only. Raw source text, interpretation, decision and reply
text are never written to disk or to operational logs; the audit chain stores IDs and
hashes only. Every mutating operation:
- takes the per-case lock,
- checks the caller's ``revision`` (compare-and-set; a stale form is rejected),
- recomputes and validates bindings server-side via relayguard core,
- records a hash-only AuditEvent and advances the UI state machine.

No network access, no e-mail sending, no external action. The flow ends at COPIED.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from relayguard.audit import event_hash, verify_chain
from relayguard.canonical import canonical_bytes, canonical_hash, decision_hash, source_hash
from relayguard.claims import CLAIM_ARRAYS, iter_claims
from relayguard.delegation import POLICY_VERSION
from relayguard.errors import Rejection
from relayguard.final_approval import VerifiedDraft, final_approve
from relayguard.generator import GeneratorRuntime, StyleConstraints, compute_draft_hash, draft_binding, edited_draft, generate_draft
from relayguard.integrity import DomainContext, validate_domain
from relayguard.reply_extractor import ReplyExtractorRuntime, extract_reply
from relayguard.shadow_core import format_timestamp, run_shadow_core
from relayguard.strict_json import parse_strict_json
from relayguard.verifier import VerifierRuntime, verify_draft

logger = logging.getLogger("relayguard.ui.service")

SCHEMA_VERSION = "0.5"
DEFAULT_RETENTION = timedelta(hours=24)  # within IMPLEMENTATION.md §23 (<= 30 days)


class CaseState(StrEnum):
    INPUT_READY = "INPUT_READY"
    DECISION_REQUIRED = "DECISION_REQUIRED"
    DELEGATION_ASSESSED = "DELEGATION_ASSESSED"
    SAFE_CANDIDATE = "SAFE_CANDIDATE"
    BLOCKED = "BLOCKED"
    FINAL_APPROVED = "FINAL_APPROVED"
    COPIED = "COPIED"
    STOPPED = "STOPPED"  # L3_STOP: generation / approval / copy are never allowed


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


@dataclass
class CaseRecord:
    case_id: str
    origin: str  # "fixture" | "user"
    created_at: datetime
    source: dict[str, Any]
    interpretation: dict[str, Any]
    revision: int = 1
    state: CaseState = CaseState.INPUT_READY
    decision: dict[str, Any] | None = None
    ctx: DomainContext | None = None
    pre_assessment: dict[str, Any] | None = None
    draft: dict[str, Any] | None = None
    extraction: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    post_assessment: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)
    last_error: dict[str, str] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass(frozen=True)
class ServiceRuntime:
    clock: Callable[[], datetime] = field(default=_utc_now)
    new_id: Callable[[str], str] = field(default=_new_id)
    retention: timedelta = DEFAULT_RETENTION


class CaseService:
    def __init__(self, operator_id: str, runtime: ServiceRuntime | None = None) -> None:
        self.operator_id = operator_id
        self.runtime = runtime or ServiceRuntime()
        self._cases: dict[str, CaseRecord] = {}
        self._lock = threading.Lock()

    # ----- queries ---------------------------------------------------------------------
    def list_cases(self) -> list[CaseRecord]:
        self.purge_expired()
        with self._lock:
            return sorted(self._cases.values(), key=lambda c: c.created_at, reverse=True)

    def get(self, case_id: str) -> CaseRecord:
        # Retention holds on every path, not only on the case list: a direct URL to an expired
        # case must not open, edit or approve it (Builder QA finding QA-01, 2026-09-23).
        self.purge_expired()
        with self._lock:
            record = self._cases.get(case_id)
        if record is None:
            raise Rejection("PolicyViolation", "案件が見つかりません（保持期間切れ・削除済みの可能性があります）。")
        return record

    # ----- lifecycle -------------------------------------------------------------------
    def purge_expired(self) -> int:
        cutoff = self.runtime.clock() - self.runtime.retention
        with self._lock:
            expired = [cid for cid, c in self._cases.items() if c.created_at < cutoff]
            for cid in expired:
                del self._cases[cid]
        return len(expired)

    def delete(self, case_id: str) -> None:
        with self._lock:
            self._cases.pop(case_id, None)
        self._log("case.deleted", case_id)

    def import_shadow_input(self, raw: bytes) -> CaseRecord:
        """Import an offline ShadowCoreInput (synthetic fixture). Its Decision stays fixture-originated."""
        result = run_shadow_core(raw)
        if result["status"] != "assessed":
            failure = result["failure"]
            raise Rejection(failure["code"], failure["explanation_ja"])
        document = parse_strict_json(raw)
        ctx = validate_domain(document)
        case_id = self._unique_case_id(document["case_id"])
        record = CaseRecord(case_id, "fixture", self.runtime.clock(), document["source_message"], document["interpretation"])
        self._audit(record, ("system", None), "source_message.received", (record.source["message_id"], record.source["content_hash"]))
        self._audit(
            record,
            ("fixture", None),
            "interpretation.imported",
            (record.interpretation["interpretation_id"], canonical_hash(record.interpretation)),
        )
        self._install_decision(record, document["approved_decision"], "fixture", ctx_case_id=document["case_id"], ctx=ctx)
        with self._lock:
            self._cases[case_id] = record
        return record

    def import_interpretation(self, subject: str | None, body: str, interpretation_json: bytes) -> CaseRecord:
        """Source text + an externally produced Interpretation JSON (untrusted until Domain-validated)."""
        interpretation = parse_strict_json(interpretation_json)
        if not isinstance(interpretation, dict):
            raise Rejection("SchemaInvalid", "InterpretationはJSON objectである必要があります。")
        try:
            return self._import_interpretation(subject, body, interpretation)
        except (AttributeError, KeyError, TypeError, ValueError, RecursionError) as error:
            # Wrong types in untrusted JSON (a null state, a list where an id belongs) must be a
            # Rejection: it is then repairable by the interpreter and never a server error that
            # drops the pasted mail. Nothing was stored - the record is registered last.
            logger.warning("import rejected: %s", type(error).__name__)  # type only: messages can quote input
            raise Rejection("SchemaInvalid", "Interpretationの構造が契約と一致しません（値の型が不正です）。") from None

    def _import_interpretation(self, subject: str | None, body: str, interpretation: dict[str, Any]) -> CaseRecord:
        source: dict[str, Any] = {
            "message_id": self.runtime.new_id("msg"),
            "subject": subject or None,
            "body": body,
            "source_language": "en",
            "user_language": "ja",
            "content_hash": "",
        }
        source["content_hash"] = source_hash(source)
        interpretation["source_message_id"] = source["message_id"]
        interpretation["source_hash"] = source["content_hash"]
        for evidence in interpretation.get("state", {}).get("evidence", []):
            if isinstance(evidence, dict):
                evidence["source_id"] = source["message_id"]
                evidence["source_hash"] = source["content_hash"]
        for record_claim in _all_claims(interpretation):
            if record_claim.get("authorization_state") == "approved":
                raise Rejection("PolicyViolation", "Interpretation（原文解釈）のCommitmentをapprovedにすることはできません。")
        case_id = self.runtime.new_id("case")
        # Validate structure + evidence now with an empty-decision probe (every claim unknown).
        probe = build_decision(interpretation, source, {}, {}, actor_id=self.operator_id, clock=self.runtime.clock, notes="")
        self._validate_document(case_id, source, interpretation, probe)
        record = CaseRecord(case_id, "user", self.runtime.clock(), source, interpretation, state=CaseState.DECISION_REQUIRED)
        self._audit(record, ("user", self.operator_id), "source_message.received", (source["message_id"], source["content_hash"]))
        self._audit(
            record, ("system", None), "interpretation.validated", (interpretation["interpretation_id"], canonical_hash(interpretation))
        )
        with self._lock:
            self._cases[case_id] = record
        return record

    # ----- decision --------------------------------------------------------------------
    def submit_decision(
        self,
        case_id: str,
        revision: int,
        choices: dict[str, str],
        answers: dict[str, dict[str, Any]],
        notes: str = "",
    ) -> CaseRecord:
        record = self.get(case_id)
        with record.lock:
            self._check_revision(record, revision)
            if record.state in (CaseState.COPIED,):
                raise Rejection("PolicyViolation", "コピー済みの案件は変更できません。新しい案件として処理してください。")
            decision = build_decision(
                record.interpretation, record.source, choices, answers, actor_id=self.operator_id, clock=self.runtime.clock, notes=notes
            )
            version = (record.decision["version"] + 1) if record.decision else 1
            decision["version"] = version
            decision["decision_id"] = f"{case_id}_decision_v{version}"
            self._install_decision(record, decision, "user")
            return record

    # ----- generation / edit / verification --------------------------------------------
    def generate(self, case_id: str, revision: int, concise: bool = False) -> CaseRecord:
        record = self.get(case_id)
        with record.lock:
            self._check_revision(record, revision)
            ctx, pre = self._require_assessed(record)
            draft = generate_draft(ctx, pre, style=StyleConstraints(concise=concise), runtime=GeneratorRuntime(new_id=self.runtime.new_id))
            self._audit(record, ("system", None), "draft.generated", (draft["draft_id"], draft["draft_hash"]))
            self._verify(record, ctx, pre, draft)
            return record

    def edit_draft(self, case_id: str, revision: int, reply_text: str) -> CaseRecord:
        record = self.get(case_id)
        with record.lock:
            self._check_revision(record, revision)
            ctx, pre = self._require_assessed(record)
            if record.draft is None:
                raise Rejection("PolicyViolation", "編集対象の返信案がありません。")
            if record.state in (CaseState.COPIED,):
                raise Rejection("PolicyViolation", "コピー済みの案件は編集できません。")
            draft = edited_draft(record.draft, reply_text.replace("\r\n", "\n"), runtime=GeneratorRuntime(new_id=self.runtime.new_id))
            self._audit(record, ("user", self.operator_id), "draft.edited", (draft["draft_id"], draft["draft_hash"]))
            self._verify(record, ctx, pre, draft)
            return record

    def _verify(self, record: CaseRecord, ctx: DomainContext, pre: dict[str, Any], draft: dict[str, Any]) -> None:
        # A new draft voids every downstream artifact of the previous one (SCHEMA.md §5).
        record.draft, record.extraction, record.verification, record.post_assessment, record.approval = draft, None, None, None, None
        record.state = CaseState.BLOCKED
        record.revision += 1
        extraction = extract_reply(draft["reply_text"], draft_binding(draft), runtime=ReplyExtractorRuntime(new_id=self.runtime.new_id))
        self._audit(record, ("system", None), "reply.extracted", (extraction["extraction_id"], canonical_hash(extraction)))
        verification, post = verify_draft(ctx, pre, draft, extraction, runtime=VerifierRuntime(new_id=self.runtime.new_id))
        record.extraction, record.verification, record.post_assessment = extraction, verification, post
        self._audit(record, ("system", None), "verification.completed", (verification["verification_id"], canonical_hash(verification)))
        self._audit(record, ("system", None), "delegation.post_verification_assessed", (post["assessment_id"], canonical_hash(post)))
        record.state = CaseState.SAFE_CANDIDATE if verification["policy_status"] == "SAFE_CANDIDATE" else CaseState.BLOCKED
        self._log(
            "verification.completed",
            record.case_id,
            policy_status=verification["policy_status"],
            post_level=post["level"],
            finding_types=sorted({f["type"] for f in verification["proposal"]["findings"]}),
        )

    # ----- final approval / copy -------------------------------------------------------
    def final_approve(self, case_id: str, revision: int) -> CaseRecord:
        record = self.get(case_id)
        with record.lock:
            self._check_revision(record, revision)
            ctx, pre = self._require_assessed(record)
            if (
                record.state != CaseState.SAFE_CANDIDATE
                or record.draft is None
                or record.verification is None
                or record.post_assessment is None
            ):
                raise Rejection("PolicyViolation", "定義済み検査を通過した返信案（SAFE_CANDIDATE）のみ最終承認できます。")
            self._check_audit(record)
            verified = VerifiedDraft(pre, record.draft, record.verification, record.post_assessment)
            approval = final_approve(ctx, verified, approver_id=self.operator_id)
            record.approval = approval
            record.state = CaseState.FINAL_APPROVED
            record.revision += 1
            self._audit(record, ("user", self.operator_id), "final_approval.recorded", (approval["approval_id"], approval["approval_hash"]))
            self._log("final_approval.recorded", case_id, approval_id=approval["approval_id"])
            return record

    def mark_copied(self, case_id: str, revision: int) -> CaseRecord:
        record = self.get(case_id)
        with record.lock:
            self._check_revision(record, revision)
            if record.state != CaseState.FINAL_APPROVED or record.approval is None or record.draft is None:
                raise Rejection("PolicyViolation", "最終承認済みの返信案のみコピーできます。")
            self._check_approved_text(record)
            self._check_audit(record)
            record.state = CaseState.COPIED
            record.revision += 1
            self._audit(
                record, ("user", self.operator_id), "reply.copied_by_operator", (record.draft["draft_id"], record.draft["draft_hash"])
            )
            return record

    def copy_text(self, case_id: str) -> str:
        record = self.get(case_id)
        if record.state not in (CaseState.FINAL_APPROVED, CaseState.COPIED) or record.draft is None or record.approval is None:
            raise Rejection("PolicyViolation", "最終承認前の返信案はコピーできません。")
        self._check_approved_text(record)
        return str(record.draft["reply_text"])

    @staticmethod
    def _check_approved_text(record: CaseRecord) -> None:
        """The text handed out must be the text approved, byte for byte.

        Comparing the stored hashes alone trusts whatever reply_text sits next to them; re-hashing
        the text closes that gap, as final_approval.py already does at approval time (Builder QA
        finding QA-02, 2026-09-23).
        """
        if record.draft is None or record.approval is None:
            raise Rejection("PolicyViolation", "最終承認前の返信案はコピーできません。")
        approved = record.approval["binding"]["draft_hash"]
        if approved != record.draft["draft_hash"]:
            raise Rejection("StaleState", "最終承認と返信案が一致しません。")
        if approved != compute_draft_hash(record.draft["reply_text"]):
            raise Rejection("InternalIntegrityError", "最終承認された返信案の本文が変更されています。")

    # ----- internals -------------------------------------------------------------------
    def _install_decision(
        self, record: CaseRecord, decision: dict[str, Any], actor: str, *, ctx_case_id: str | None = None, ctx: DomainContext | None = None
    ) -> None:
        decision = copy.deepcopy(decision)
        if actor == "user":
            decision["decision_hash"] = decision_hash(decision)
        document = self._document(ctx_case_id or record.case_id, record.source, record.interpretation, decision)
        result = run_shadow_core(canonical_bytes(document))
        if result["status"] != "assessed":
            failure = result["failure"]
            self._log("decision.rejected", record.case_id, error_code=failure["code"])
            raise Rejection(failure["code"], failure["explanation_ja"])
        ctx = validate_domain(parse_strict_json(canonical_bytes(document)))
        pre = result["assessment"]
        if ctx_case_id is not None and ctx_case_id != record.case_id:
            raise Rejection("PolicyViolation", "取込み済みの案件IDと重複しています。")
        record.decision, record.ctx, record.pre_assessment = decision, ctx, pre
        record.draft = record.extraction = record.verification = record.post_assessment = record.approval = None
        record.revision += 1
        actor_type = "fixture" if actor == "fixture" else "user"
        actor_id = None if actor == "fixture" else self.operator_id
        self._audit(record, (actor_type, actor_id), "decision.approved", (decision["decision_id"], decision["decision_hash"]))
        self._audit(record, ("system", None), "delegation.pre_generation_assessed", (pre["assessment_id"], canonical_hash(pre)))
        record.state = CaseState.STOPPED if pre["level"] == "L3_STOP" else CaseState.DELEGATION_ASSESSED
        self._log("delegation.pre_generation_assessed", record.case_id, level=pre["level"], reason_codes=pre["reason_codes"])

    def _validate_document(self, case_id: str, source: dict[str, Any], interpretation: dict[str, Any], decision: dict[str, Any]) -> None:
        decision = copy.deepcopy(decision)
        decision["decision_hash"] = decision_hash(decision)
        result = run_shadow_core(canonical_bytes(self._document(case_id, source, interpretation, decision)))
        if result["status"] != "assessed":
            failure = result["failure"]
            raise Rejection(failure["code"], failure["explanation_ja"])

    @staticmethod
    def _document(case_id: str, source: dict[str, Any], interpretation: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "case_id": case_id,
            "source_message": source,
            "interpretation": interpretation,
            "approved_decision": decision,
            "policy_version": POLICY_VERSION,
        }

    def _unique_case_id(self, wanted: str) -> str:
        with self._lock:
            if wanted in self._cases:
                raise Rejection("PolicyViolation", "同じcase_idの案件が既に存在します。削除してから再取込みしてください。")
        return wanted

    @staticmethod
    def _require_assessed(record: CaseRecord) -> tuple[DomainContext, dict[str, Any]]:
        if record.ctx is None or record.pre_assessment is None:
            raise Rejection("PolicyViolation", "Decision承認と事前Delegation判定が完了していません。")
        if record.state == CaseState.STOPPED or record.pre_assessment["level"] == "L3_STOP":
            raise Rejection("SafetyBlock", "L3_STOPの案件は返信生成・承認・コピーできません。手動対応へ引き継いでください。")
        return record.ctx, record.pre_assessment

    @staticmethod
    def _check_revision(record: CaseRecord, revision: int) -> None:
        if revision != record.revision:
            raise Rejection("StaleState", "画面の情報が古くなっています。再読み込みしてから操作してください。")

    def _check_audit(self, record: CaseRecord) -> None:
        if not verify_chain(record.case_id, record.audit):
            raise Rejection("InternalIntegrityError", "監査チェーンに不整合があるため承認できません。")

    def _audit(self, record: CaseRecord, actor: tuple[str, str | None], event_type: str, entity: tuple[str, str]) -> None:
        (actor_type, actor_id), (entity_id, entity_hash) = actor, entity
        event: dict[str, Any] = {
            "event_id": self.runtime.new_id("evt"),
            "case_id": record.case_id,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "event_type": event_type,
            "entity_id": entity_id,
            "entity_hash": entity_hash,
            "previous_hash": record.audit[-1]["event_hash"] if record.audit else None,
            "created_at": format_timestamp(self.runtime.clock()),
        }
        event["event_hash"] = event_hash(event)
        record.audit.append(event)

    @staticmethod
    def _log(event: str, case_id: str, **fields: Any) -> None:
        # Operational log: metadata only (no subject/body/claim text/answers/reply text).
        payload = {"event": event, "case_id": case_id, "ts": round(time.time(), 3), **fields}
        logger.info(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def _all_claims(interpretation: dict[str, Any]) -> list[dict[str, Any]]:
    state = interpretation.get("state")
    if not isinstance(state, dict):
        return []
    claims: list[dict[str, Any]] = []
    for array in CLAIM_ARRAYS:
        value = state.get(array)
        if isinstance(value, list):
            claims.extend(c for c in value if isinstance(c, dict))
    return claims


def build_decision(  # noqa: PLR0913 - mirrors the Decision Sheet form fields
    interpretation: dict[str, Any],
    source: dict[str, Any],
    choices: dict[str, str],
    answers: dict[str, dict[str, Any]],
    *,
    actor_id: str,
    clock: Callable[[], datetime],
    notes: str,
) -> dict[str, Any]:
    """Domain construction of a Decision from Decision Sheet choices (SCHEMA.md §4, §13).

    Unselected claims become ``unknown`` (never approve by default). ``modify`` is not offered
    by this UI. Answers are accepted only for approved questions; everything else is left to
    Domain validation, which rejects invalid combinations instead of repairing them.
    """
    now = format_timestamp(clock())
    state = interpretation.get("state")
    if not isinstance(state, dict):
        raise Rejection("SchemaInvalid", "Interpretationの構造が不正です。")
    try:
        records = iter_claims(state)
    except KeyError, TypeError:
        raise Rejection("SchemaInvalid", "InterpretationのStructuredStateが構造契約に適合しません。") from None
    provenance = {"actor_id": actor_id, "decided_at": now, "reason_ja": "Decision Sheetでの操作者の選択"}
    items: list[dict[str, Any]] = []
    approved_commitments: list[dict[str, Any]] = []
    unanswered: list[str] = []
    question_answers: list[dict[str, Any]] = []
    for record in records:
        choice = choices.get(record.claim_id, "unknown")
        if choice not in ("approve", "unknown", "do_not_answer"):
            raise Rejection("PolicyViolation", "Decision Sheetの選択肢が不正です。")
        items.append(
            {
                "item_id": f"item_{record.claim_id}",
                "source_claim_id": record.claim_id,
                "decision": choice,
                "replacement": None,
                "provenance": dict(provenance),
            }
        )
        if record.kind == "Commitment" and choice == "approve":
            commitment = copy.deepcopy(record.body)
            commitment["authorization_state"] = "approved"
            approved_commitments.append(commitment)
        if record.kind == "Question" and choice == "do_not_answer":
            unanswered.append(record.claim_id)
        answer = answers.get(record.claim_id)
        if record.kind == "Question" and answer and str(answer.get("answer_text", "")).strip():
            question_answers.append(
                {
                    "question_id": record.claim_id,
                    "answer_text": str(answer["answer_text"]).strip(),
                    "basis": "user_assertion",
                    "evidence_ids": [],
                    "related_claim_ids": sorted(set(answer.get("related_claim_ids", []))),
                    "provenance": {**provenance, "reason_ja": "Decision Sheetで操作者が入力した回答"},
                }
            )
    decision: dict[str, Any] = {
        "decision_id": "pending",
        "version": 1,
        "source_interpretation_id": interpretation.get("interpretation_id"),
        "source_interpretation_version": interpretation.get("version"),
        "source_hash": source["content_hash"],
        "items": items,
        "question_answers": sorted(question_answers, key=lambda a: str(a["question_id"])),
        "approved_commitments": approved_commitments,
        "explicitly_unanswered": sorted(unanswered),
        "human_notes": [notes.strip()] if notes.strip() else [],
        "approved_by": actor_id,
        "approved_at": now,
        "decision_hash": "",
    }
    decision["decision_hash"] = decision_hash(decision)
    return decision
