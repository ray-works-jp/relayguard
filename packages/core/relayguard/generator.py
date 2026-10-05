"""Deterministic reply Generator (IMPLEMENTATION.md §5.5, SCHEMA.md §§5-6).

Input is a Domain-validated context (``integrity.validate_domain``) plus its pre-generation
DelegationAssessment. The English reply is rendered only from Approved Decision content:

- fixed courtesy lines (no values, no commitments, no modal verbs),
- each ``question_answers[].answer_text`` verbatim, line by line,
- each ``approved_commitments[]`` as a structured block whose values come from the typed
  Commitment and its linked MonetaryTerm / DateTerm (effective approve/modify values).

No LLM is used, so there is no model rationale to leak. ``represented_state`` is the
Generator's self-report and is never passed to the Reply Extractor or the Verifier.
L3_STOP, a stale binding or an unrenderable commitment is a Rejection (no partial draft).
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .canonical import canonical_hash, sha256_hex
from .errors import Rejection
from .integrity import DomainContext
from .schema_validation import validate_draft, validate_draft_proposal

RESPONSE_LANGUAGE = "en"  # SCHEMA.md §6: generator response_language is "en"
GENERATOR_VERSION = "rg-generator-det-1"

GREETING_LINE = "Hello,"
THANKS_LINE = "Thank you for your message."
EMOTION_LINE = "Thank you for sharing your concerns with us."
CLOSING_LINE = "Best regards,"
# Lines that carry no value, commitment, modality or claim. The Verifier accepts only
# these as non-Decision lines.
BOILERPLATE_LINES: frozenset[str] = frozenset({GREETING_LINE, THANKS_LINE, EMOTION_LINE, CLOSING_LINE})

_COMMITMENT_HEADS: dict[str, dict[str, str]] = {
    "user": {"will": "We will:", "may": "We may:", "must": "We must:", "must_not": "We will not:"},
    "counterparty": {"will": "We note that you will:", "may": "We note that you may:", "must": "We note that you must:",
                     "must_not": "We note that you will not:"},
    "third_party": {"will": "We note that a third party will:", "may": "We note that a third party may:",
                    "must": "We note that a third party must:", "must_not": "We note that a third party will not:"},
}  # fmt: skip


def _default_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class GeneratorRuntime:
    new_id: Callable[[str], str] = field(default=_default_id)


@dataclass(frozen=True)
class StyleConstraints:
    tone: str = "professional"
    concise: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"tone": self.tone, "concise": self.concise}


def compute_draft_hash(reply_text: str) -> str:
    """SCHEMA.md §5: SHA-256 of the exact UTF-8 bytes of the final reply text."""
    return sha256_hex(reply_text.encode("utf-8"))


def binding_from_assessment(ctx: DomainContext, assessment: dict[str, Any]) -> dict[str, Any]:
    """Return the assessment Binding after checking it matches the validated context exactly."""
    binding = assessment.get("binding")
    expected = context_binding(ctx)
    if binding != expected:
        raise Rejection("StaleState", "DelegationAssessmentのbindingが現在のSource/Interpretation/Decisionと一致しません。")
    return copy.deepcopy(expected)


def context_binding(ctx: DomainContext) -> dict[str, Any]:
    return {
        "case_id": ctx.case_id,
        "source_hash": ctx.source["content_hash"],
        "interpretation_id": ctx.interpretation["interpretation_id"],
        "interpretation_version": ctx.interpretation["version"],
        "decision_id": ctx.decision["decision_id"],
        "decision_version": ctx.decision["version"],
        "decision_hash": ctx.decision["decision_hash"],
        "policy_version": ctx.policy_version,
    }


def effective_claim(ctx: DomainContext, claim_id: str) -> dict[str, Any] | None:
    """Approved value of a claim: original on approve, replacement on modify, else None."""
    record = ctx.claims.get(claim_id)
    item = ctx.items_by_claim.get(claim_id)
    if record is None or item is None:
        return None
    if item["decision"] == "approve":
        return record.body
    if item["decision"] == "modify":
        value: dict[str, Any] = item["replacement"]["value"]
        return value
    return None


def _explicit(value: dict[str, Any], what: str) -> str:
    if not isinstance(value, dict) or value.get("status") != "explicit":
        raise Rejection("SafetyBlock", f"承認済みcommitmentの{what}が確定値ではないため返信を生成できません。")
    return str(value["value"])


def _money_line(term: dict[str, Any]) -> str:
    amount = _explicit(term["amount"], "金額")
    currency = _explicit(term["currency"], "通貨")
    line = f"- Amount: {currency} {amount} ({term['type']})"
    condition = term["condition"]
    if condition.get("status") == "explicit":
        line += f", condition: {condition['value']}"
    return line


def _date_line(term: dict[str, Any]) -> str:
    label = "Deadline" if term["type"] == "deadline" else "Date"
    date = _explicit(term["date"], "日付")
    timezone = term["timezone"]
    if timezone.get("status") == "explicit":
        return f"- {label}: {date} (timezone: {timezone['value']})"
    if term["type"] == "deadline":
        raise Rejection("SafetyBlock", "承認済み期限のtimezoneが確定していないため返信を生成できません。")
    return f"- {label}: {date}"


def render_commitment_block(ctx: DomainContext, commitment: dict[str, Any]) -> list[str]:
    """Render one approved commitment. Every value must be explicit and approved."""
    heads = _COMMITMENT_HEADS.get(commitment["actor"])
    if heads is None:
        raise Rejection("SafetyBlock", "actorが不明なcommitmentは返信へ含められません。")
    modality = _explicit(commitment["modality"], "modality")
    lines = [
        f"{heads[modality]} {_explicit(commitment['action'], 'action')}",
        f"- Regarding: {_explicit(commitment['object'], 'object')}",
        f"- Scope: {_explicit(commitment['scope'], 'scope')}",
        f"- Condition: {_explicit(commitment['condition'], 'condition')}",
    ]
    for term_id in commitment["monetary_term_ids"]:
        term = effective_claim(ctx, term_id)
        if term is None:
            raise Rejection("SafetyBlock", "承認済みcommitmentが未承認の金額条件を参照しています。")
        lines.append(_money_line(term))
    if commitment["deadline_id"] is not None:
        term = effective_claim(ctx, commitment["deadline_id"])
        if term is None:
            raise Rejection("SafetyBlock", "承認済みcommitmentが未承認の期限を参照しています。")
        lines.append(_date_line(term))
    return lines


def answer_lines(answer_text: str) -> list[str]:
    return [line.strip() for line in answer_text.splitlines() if line.strip()]


def has_customer_emotion(ctx: DomainContext) -> bool:
    return bool(ctx.interpretation["state"]["customer_emotion"])


def render_reply(ctx: DomainContext, style: StyleConstraints) -> str:
    paragraphs: list[list[str]] = [[GREETING_LINE]]
    opening = [THANKS_LINE]
    if has_customer_emotion(ctx):
        opening.append(EMOTION_LINE)
    paragraphs.append(opening)
    for answer in ctx.decision["question_answers"]:
        paragraphs.append(answer_lines(answer["answer_text"]))
    for commitment in ctx.decision["approved_commitments"]:
        paragraphs.append(render_commitment_block(ctx, commitment))
    paragraphs.append([CLOSING_LINE])
    separator = "\n" if style.concise else "\n\n"
    return separator.join("\n".join(lines) for lines in paragraphs if lines) + "\n"


def generate_draft(
    ctx: DomainContext,
    pre_assessment: dict[str, Any],
    *,
    style: StyleConstraints | None = None,
    runtime: GeneratorRuntime | None = None,
) -> dict[str, Any]:
    """Build a Draft (SCHEMA.md §6) bound to the pre-generation assessment's Binding."""
    runtime = runtime or GeneratorRuntime()
    style = style or StyleConstraints()
    if style.tone != "professional":
        raise Rejection("SchemaInvalid", "Style.toneはprofessionalのみ対応します。")
    if pre_assessment.get("phase") != "pre_generation" or pre_assessment.get("draft_binding") is not None:
        raise Rejection("PolicyViolation", "返信案の生成には事前（pre_generation）Delegation判定が必要です。")
    if pre_assessment.get("level") == "L3_STOP" or pre_assessment.get("minimum_level") == "L3_STOP":
        raise Rejection("SafetyBlock", "L3_STOPの案件は返信案を生成しません。手動対応へ引き継いでください。")
    binding = binding_from_assessment(ctx, pre_assessment)

    reply_text = render_reply(ctx, style)
    proposal = {"reply_text": reply_text, "binding": binding, "represented_state": copy.deepcopy(ctx.interpretation["state"])}
    proposal["represented_state"]["commitments"] = copy.deepcopy(ctx.decision["approved_commitments"])
    validate_draft_proposal(proposal)

    draft = {
        "draft_id": runtime.new_id("draft"),
        "binding": binding,
        "reply_text": reply_text,
        "draft_hash": compute_draft_hash(reply_text),
        "model_execution_id": runtime.new_id("gen"),
    }
    validate_draft(draft)
    return draft


def edited_draft(previous: dict[str, Any], reply_text: str, *, runtime: GeneratorRuntime | None = None) -> dict[str, Any]:
    """A user edit creates a new Draft (new id/hash). Old extraction/verification/approval are void."""
    runtime = runtime or GeneratorRuntime()
    if not reply_text.strip():
        raise Rejection("UnsupportedInput", "返信本文が空です。")
    draft = {
        "draft_id": runtime.new_id("draft"),
        "binding": copy.deepcopy(previous["binding"]),
        "reply_text": reply_text,
        "draft_hash": compute_draft_hash(reply_text),
        "model_execution_id": runtime.new_id("edit"),
    }
    validate_draft(draft)
    return draft


def draft_binding(draft: dict[str, Any]) -> dict[str, Any]:
    return {"decision": copy.deepcopy(draft["binding"]), "draft_id": draft["draft_id"], "draft_hash": draft["draft_hash"]}


def draft_entity_hash(draft: dict[str, Any]) -> str:
    return canonical_hash(draft)
