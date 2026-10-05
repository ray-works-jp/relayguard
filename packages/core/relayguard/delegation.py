"""Delegation Policy Engine, policy_version=delegation-0.4 (DELEGATION.md §§4,6,12,14,15).

Pre-generation assessment only (SG-001). Deterministic: the same DomainContext always
yields the same level / minimum_level / reason_codes / risk_factors. No confidence value
is read, so confidence can never lower a level.

Principles applied to the Approved Decision:
- L3 first, and an L2 reason never lowers it. Every fired reason is recorded (§14).
- Required critical values must be explicit; the only exception is DateTerm.timezone
  when type == "date" (§14.1). Original claim and replacement are both checked, so a
  Decision alone never clears an original critical gap (SCHEMA §12.1).
- approve cannot be distinguished from "new vs existing", so it is minimum L2 with
  UNCLASSIFIED_RISK; only a modify with a substantive difference records the specific
  change reason (§14.2).
- policy_exception is always L3 + POLICY_EXCEPTION in SG-001 (§14.3, SCHEMA §12.2).
- Nothing fired -> L0 only with positive low-risk eligibility (§12.6-8). A question is
  answered only through a recorded QuestionAnswer (SCHEMA §13); approving the question is
  not an answer. Any recorded answer keeps the case at minimum L2 with
  ANSWER_REVIEW_REQUIRED, because SG-001 has no independent meaning verification (§15).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from .claims import REQUIRED_VALUE_FIELDS, ClaimRecord
from .integrity import DomainContext

POLICY_VERSION = "delegation-0.4"

Level = Literal["L0_AUTO", "L1_POST_REVIEW", "L2_PRE_APPROVAL", "L3_STOP"]
LEVEL_ORDER: tuple[Level, ...] = ("L0_AUTO", "L1_POST_REVIEW", "L2_PRE_APPROVAL", "L3_STOP")
L0: Level = "L0_AUTO"
L1: Level = "L1_POST_REVIEW"
L2: Level = "L2_PRE_APPROVAL"
L3: Level = "L3_STOP"

Axis = Literal["low", "medium", "high", "unknown"]

CHANGE_CODES: frozenset[str] = frozenset(
    {
        "REFUND_OR_CREDIT",
        "CONTRACTUAL_CHANGE",
        "RIGHTS_OR_LICENSE_CHANGE",
        "NEW_GUARANTEE",
        "MATERIAL_MONEY_CHANGE",
        "MATERIAL_DEADLINE_CHANGE",
        "QUANTITY_CHANGE",
        "PERSONAL_DATA_DISCLOSURE",
        "NEW_COMMITMENT",
    }
)
UNRESOLVED_CRITICAL_CODES: frozenset[str] = frozenset(
    {
        "CRITICAL_MISSING_INFORMATION",
        "UNRESOLVED_PROMPT_INJECTION",
        "ATTACHMENT_REQUIRED_MISSING",
        "CONTRADICTORY_COMMITMENTS",
        # SG-001 cannot verify whether the exception is permitted (§14.3), so the
        # uncertainty axis is high rather than low.
        "POLICY_EXCEPTION",
    }
)

# §14.2: the change reason is recorded only when a modify carries a substantive
# difference; a plain approve is "unidentifiable" and stays UNCLASSIFIED_RISK.
_MODIFY_CHANGE_CODES: dict[str, str] = {
    "contract_terms": "CONTRACTUAL_CHANGE",
    "cancellation_terms": "CONTRACTUAL_CHANGE",
    "prohibitions": "CONTRACTUAL_CHANGE",
    "guarantees": "NEW_GUARANTEE",
    "refund_terms": "REFUND_OR_CREDIT",
    "license_terms": "RIGHTS_OR_LICENSE_CHANGE",
    "rights": "RIGHTS_OR_LICENSE_CHANGE",
    "personal_data": "PERSONAL_DATA_DISCLOSURE",
}
_REFUND_MONEY_TYPES = frozenset({"refund", "credit"})
_EMOTION_COMBINING_TYPES = frozenset({"cancellation_intent", "public_complaint"})

# Positive low-risk eligibility (DP §12.6-7). Anything outside these sets is never L0/L1.
_CONTENT_ARRAYS = frozenset({"sender_intent", "requests", "questions"})
_MENTION_ONLY_ARRAYS = frozenset({"monetary_terms", "dates", "quantities"})
_MENTION_MONEY_TYPES = frozenset({"price", "payment", "fee", "other"})
L0_ALLOWED_ARRAYS: frozenset[str] = _CONTENT_ARRAYS | _MENTION_ONLY_ARRAYS
L1_ALLOWED_ARRAYS: frozenset[str] = L0_ALLOWED_ARRAYS | {"customer_emotion", "reputational_risks"}


def level_rank(level: Level) -> int:
    return LEVEL_ORDER.index(level)


def max_level(levels: list[Level]) -> Level:
    return max(levels, key=level_rank)


@dataclass(frozen=True)
class RuleHit:
    code: str
    level: Level
    # "" when the rule fired on an identified situation. "term" when it fired because a
    # critical term could not be classified as new or existing (an obligation or right
    # change cannot be ruled out). "answer" when a required question carries no recorded
    # answer. Both make impact undetermined; only "term" makes irreversibility so.
    undetermined: str = ""


@dataclass(frozen=True)
class PolicyOutcome:
    level: Level
    minimum_level: Level
    reason_codes: tuple[str, ...]
    risk_factors: dict[str, Axis]
    human_review_required: bool


def _risk_variants(ctx: DomainContext, record: ClaimRecord) -> list[dict[str, Any]]:
    """Original claim plus the user replacement (if any): L3 causes are never removed."""
    variants = [record.body]
    item = ctx.items_by_claim[record.claim_id]
    if item["decision"] == "modify":
        variants.append(item["replacement"]["value"])
    return variants


def _effective(ctx: DomainContext, record: ClaimRecord) -> dict[str, Any]:
    item = ctx.items_by_claim[record.claim_id]
    if item["decision"] == "modify":
        value: dict[str, Any] = item["replacement"]["value"]
        return value
    return record.body


def _decision(ctx: DomainContext, record: ClaimRecord) -> str:
    decision: str = ctx.items_by_claim[record.claim_id]["decision"]
    return decision


def _substantive_diff(original: dict[str, Any], replacement: dict[str, Any]) -> bool:
    """§14.2: compare content, ignoring id / evidence_ids-only differences."""
    ignored = ("id", "evidence_ids")
    left = {k: v for k, v in original.items() if k not in ignored}
    right = {k: v for k, v in replacement.items() if k not in ignored}
    return left != right


def _is_changed(ctx: DomainContext, record: ClaimRecord) -> bool:
    return _decision(ctx, record) == "modify" and _substantive_diff(record.body, _effective(ctx, record))


def _accepted(ctx: DomainContext, record: ClaimRecord) -> bool:
    return _decision(ctx, record) in ("approve", "modify")


def _has_critical_value_gap(kind: str, claim: dict[str, Any]) -> bool:
    """DELEGATION.md §14.1: every required value must be explicit. The single exception is
    DateTerm.timezone when type == "date" and the status is not_stated; unknown / ambiguous
    timezone is never exempt, and type == "deadline" is never exempt."""
    if kind == "Commitment" and claim["actor"] == "unknown":
        return True
    for field in REQUIRED_VALUE_FIELDS.get(kind, ()):
        status = claim[field]["status"]
        if status == "explicit":
            continue
        if kind == "DateTerm" and field == "timezone" and claim["type"] == "date" and status == "not_stated":
            continue
        return True
    return False


def _has_noncritical_value_gap(kind: str, claim: dict[str, Any]) -> bool:
    if kind in ("TextClaim", "Question"):
        return bool(claim["text"]["status"] != "explicit")
    if kind == "Emotion":
        return claim["target"]["status"] in ("unknown", "ambiguous")
    if kind == "Risk":
        return bool(claim["description"]["status"] != "explicit")
    return False


def _risk_hits(ctx: DomainContext, record: ClaimRecord) -> Iterator[RuleHit]:
    variants = _risk_variants(ctx, record)
    array = record.array
    types = {v["type"] for v in variants}
    affects_critical = any(v["affects_critical"] for v in variants)

    if "policy_exception" in types:
        # §14.3: no trusted path to verify an exception in SG-001, so always L3.
        yield RuleHit("POLICY_EXCEPTION", L3)
    if array == "prompt_injection_risks" or "injection" in types:
        yield RuleHit("UNRESOLVED_PROMPT_INJECTION", L3)
    if array == "attachment_dependencies" or "attachment" in types:
        # §15: the contract content hidden in the attachment cannot be classified.
        yield RuleHit("ATTACHMENT_REQUIRED_MISSING", L3, undetermined="term")
    if array == "prior_commitment_conflicts" or ("contradiction" in types and affects_critical):
        # §15: the effect of the conflicting earlier obligation cannot be determined.
        yield RuleHit("CONTRADICTORY_COMMITMENTS", L3, undetermined="term")
    gap_like = array in ("ambiguities", "missing_information") or bool(types & {"ambiguity", "missing_information"})
    if gap_like and affects_critical:
        yield RuleHit("CRITICAL_MISSING_INFORMATION", L3)

    always_l3 = array in ("prompt_injection_risks", "attachment_dependencies", "prior_commitment_conflicts") or bool(
        types & {"injection", "attachment", "policy_exception"}
    )
    if always_l3:
        return
    if affects_critical:
        if not (gap_like or "contradiction" in types):
            yield RuleHit("UNCLASSIFIED_RISK", L3)
        return

    # Non-critical risk: resolved only if the user accepted a resolved=true state.
    resolved = _accepted(ctx, record) and _effective(ctx, record)["resolved"] is True
    if not resolved:
        yield RuleHit("UNCLASSIFIED_RISK", L2)
    elif array == "reputational_risks" or "reputational" in types:
        yield RuleHit("CUSTOMER_SENSITIVITY", L1)


def _linked_money_hits(ctx: DomainContext, monetary_ids: list[str]) -> Iterator[RuleHit]:
    for money_id in monetary_ids:
        money = ctx.claims[money_id]
        yield RuleHit("MATERIAL_MONEY_CHANGE", L2)
        if money.body["type"] in _REFUND_MONEY_TYPES:
            yield RuleHit("REFUND_OR_CREDIT", L2)


def _identifiability_hit(ctx: DomainContext, record: ClaimRecord) -> RuleHit:
    """§14.2: approve (and a modify without substantive difference) cannot be told apart
    from a mention of an existing term, so it is minimum L2 + UNCLASSIFIED_RISK. Only a
    substantive modify records the specific change reason."""
    if _is_changed(ctx, record):
        return RuleHit(_MODIFY_CHANGE_CODES[record.array], L2)
    return RuleHit("UNCLASSIFIED_RISK", L2, undetermined="term")


def _claim_hits(ctx: DomainContext, record: ClaimRecord) -> Iterator[RuleHit]:
    """Rule hits for one claim, in a fixed order: kind short-cuts, unanswered question,
    value gaps / pending decision, then the change reasons of an accepted term."""
    decision = _decision(ctx, record)  # looked up first for every claim, as before the split
    if record.kind == "LegalClaim":
        yield RuleHit("LEGAL_CLAIM", L3)
        return
    if record.kind == "Risk":
        yield from _risk_hits(ctx, record)
        return
    yield from _unanswered_question_hits(ctx, record)
    yield from _value_gap_hits(ctx, record, decision)
    if _accepted(ctx, record):
        yield from _accepted_term_hits(ctx, record, _effective(ctx, record))


def _unanswered_question_hits(ctx: DomainContext, record: ClaimRecord) -> Iterator[RuleHit]:
    if (
        record.kind == "Question"
        and record.body["required_answer"]
        and _accepted(ctx, record)
        and record.claim_id not in ctx.answers_by_question
    ):
        # §15: approving the question is not the answer. Without a QuestionAnswer (or an
        # explicit do_not_answer) the intent is not settled.
        yield RuleHit("UNCLASSIFIED_RISK", L2, undetermined="answer")


def _value_gap_hits(ctx: DomainContext, record: ClaimRecord, decision: str) -> Iterator[RuleHit]:
    kind = record.kind
    if record.critical:
        if any(_has_critical_value_gap(kind, v) for v in _risk_variants(ctx, record)):
            yield RuleHit("CRITICAL_MISSING_INFORMATION", L3)
        if decision == "unknown":
            # A pending decision on a critical item: intent is not confirmed.
            yield RuleHit("CRITICAL_MISSING_INFORMATION", L3)
    else:
        if decision == "unknown":
            # Unresolved non-critical item, including a required question left unknown.
            yield RuleHit("UNCLASSIFIED_RISK", L2)
        if any(_has_noncritical_value_gap(kind, v) for v in _risk_variants(ctx, record)):
            # approve does not resolve an unknown / ambiguous original (DP §12.2, §12.5).
            yield RuleHit("UNCLASSIFIED_RISK", L2)


def _accepted_term_hits(ctx: DomainContext, record: ClaimRecord, effective: dict[str, Any]) -> Iterator[RuleHit]:
    kind = record.kind
    if kind == "MonetaryTerm":
        yield from _money_term_hits(ctx, record, effective)
    elif kind == "DateTerm":
        if _is_changed(ctx, record):
            yield RuleHit("MATERIAL_DEADLINE_CHANGE", L2)
    elif kind == "QuantityTerm":
        if _is_changed(ctx, record):
            yield RuleHit("QUANTITY_CHANGE", L2)
    elif kind == "ClauseTerm":
        yield _identifiability_hit(ctx, record)
        yield from _linked_money_hits(ctx, effective["monetary_term_ids"])
        if effective["deadline_ids"]:
            yield RuleHit("MATERIAL_DEADLINE_CHANGE", L2)
    elif kind == "RightsLicenseTerm":
        yield _identifiability_hit(ctx, record)
    elif kind == "Commitment":
        yield from _commitment_hits(ctx, record, effective)
    elif kind == "TextClaim" and record.array == "personal_data":
        yield _identifiability_hit(ctx, record)


def _money_term_hits(ctx: DomainContext, record: ClaimRecord, effective: dict[str, Any]) -> Iterator[RuleHit]:
    if _is_changed(ctx, record):
        yield RuleHit("MATERIAL_MONEY_CHANGE", L2)
    if record.body["type"] in _REFUND_MONEY_TYPES or effective["type"] in _REFUND_MONEY_TYPES:
        yield RuleHit("REFUND_OR_CREDIT", L2)
    if "discount" in (record.body["type"], effective["type"]):
        yield RuleHit("MATERIAL_MONEY_CHANGE", L2)


def _commitment_hits(ctx: DomainContext, record: ClaimRecord, effective: dict[str, Any]) -> Iterator[RuleHit]:
    # §14.2: taking on a user obligation is NEW_COMMITMENT; accepting a
    # counterparty / third_party promise stays unidentifiable.
    actors = {variant["actor"] for variant in _risk_variants(ctx, record)}
    if "user" in actors:
        yield RuleHit("NEW_COMMITMENT", L2)
    else:
        # actor=unknown leaves it undetermined whether the user takes on an obligation;
        # counterparty / third_party is identified as not the user's own promise.
        yield RuleHit("UNCLASSIFIED_RISK", L2, undetermined="term" if "unknown" in actors else "")
    yield from _linked_money_hits(ctx, effective["monetary_term_ids"])
    if effective["deadline_id"] is not None:
        yield RuleHit("MATERIAL_DEADLINE_CHANGE", L2)


def _emotion_hits(ctx: DomainContext) -> Iterator[RuleHit]:
    state = ctx.interpretation["state"]
    emotions = state["customer_emotion"]
    if not emotions:
        return
    emotion_types = {e["type"] for e in emotions}
    for record in ctx.claims.values():
        if record.kind == "Emotion" and _decision(ctx, record) == "modify":
            emotion_types.add(_effective(ctx, record)["type"])
    combined = bool(emotion_types & _EMOTION_COMBINING_TYPES) or any(
        state[array]
        for array in (
            "monetary_terms",
            "refund_terms",
            "contract_terms",
            "cancellation_terms",
            "prior_commitment_conflicts",
            "reputational_risks",
        )
    )
    yield RuleHit("CUSTOMER_SENSITIVITY", L2 if combined else L1)


def collect_hits(ctx: DomainContext) -> list[RuleHit]:
    hits: list[RuleHit] = []
    for record in ctx.claims.values():
        hits.extend(_claim_hits(ctx, record))
    hits.extend(_emotion_hits(ctx))
    if ctx.answers_by_question:
        # §15: SG-001 has no independent meaning verification of free text, so any recorded
        # answer keeps the case at minimum L2 for review.
        hits.append(RuleHit("ANSWER_REVIEW_REQUIRED", L2))
    if ctx.interpretation["state"]["human_review_required"]:
        # Interpreter flagged human judgment; never treated as low risk.
        hits.append(RuleHit("UNCLASSIFIED_RISK", L2))
    return hits


def _risk_factors(ctx: DomainContext, hits: list[RuleHit]) -> dict[str, Axis]:
    codes = {h.code for h in hits}
    pending_critical = any(record.critical and _decision(ctx, record) == "unknown" for record in ctx.claims.values())

    undetermined = {hit.undetermined for hit in hits} - {""}
    obligation_undetermined = pending_critical or "term" in undetermined

    impact: Axis
    irreversibility: Axis
    if codes & CHANGE_CODES:
        # An identified new critical promise or change.
        impact = "high"
    elif undetermined or pending_critical:
        # Pending critical decision, unclassifiable term, or a required question that was
        # approved without a recorded answer: the axis is never reported as low.
        impact = "unknown"
    elif ctx.answers_by_question:
        # §15: an individual answer that carries no identified new critical obligation.
        # basis=source_evidence does not make it "known information only": SG-001 cannot
        # verify that the answer text means what the cited quote says (SCHEMA §13).
        impact = "medium"
    else:
        # Receipt or notification only.
        impact = "low"
    if codes & (CHANGE_CODES - {"NEW_COMMITMENT"}):
        irreversibility = "high"
    elif "NEW_COMMITMENT" in codes:
        irreversibility = "medium"
    elif obligation_undetermined:
        irreversibility = "unknown"
    else:
        irreversibility = "low"

    uncertainty: Axis
    if codes & UNRESOLVED_CRITICAL_CODES or any(h.code == "UNCLASSIFIED_RISK" and h.level == L3 for h in hits):
        uncertainty = "high"
    elif "UNCLASSIFIED_RISK" in codes or ctx.answers_by_question:
        # §15: the meaning of a recorded answer is unverified in SG-001, so uncertainty is
        # at least medium whenever an answer is present.
        uncertainty = "medium"
    else:
        uncertainty = "low"

    state = ctx.interpretation["state"]
    emotion_types = {e["type"] for e in state["customer_emotion"]}
    sensitivity: Axis
    if "LEGAL_CLAIM" in codes or "public_complaint" in emotion_types:
        sensitivity = "high"
    elif state["customer_emotion"] or state["reputational_risks"]:
        sensitivity = "medium"
    else:
        sensitivity = "low"

    return {
        "impact": impact,
        "uncertainty": uncertainty,
        "irreversibility": irreversibility,
        "customer_sensitivity": sensitivity,
    }


def _low_risk_eligible(ctx: DomainContext, allowed_arrays: frozenset[str]) -> bool:
    """Positive confirmation of DP §12.6 (L0) / §12.7 (L1). Absence of fired rules alone is
    never enough: every claim must belong to an allowed low-risk category with confirmed
    intent, and there must be something known to answer or acknowledge."""
    if ctx.answers_by_question:
        # §15: a recorded answer is a decision about content; L0/L1 is out of reach.
        return False
    has_content = False
    for record in ctx.claims.values():
        if record.array not in allowed_arrays:
            return False
        decision = _decision(ctx, record)
        if decision == "unknown":
            return False
        if record.kind == "Question" and record.body["required_answer"] and decision != "do_not_answer":
            # §15: L0/L1 is limited to receipt / notification / intentional non-answer.
            return False
        if record.array in _MENTION_ONLY_ARRAYS:
            # Counterparty merely stating a value: no modification, no giveaway money type.
            if decision == "modify":
                return False
            if record.kind == "MonetaryTerm" and record.body["type"] not in _MENTION_MONEY_TYPES:
                return False
        for variant in _risk_variants(ctx, record):
            if record.critical and _has_critical_value_gap(record.kind, variant):
                return False
            if _has_noncritical_value_gap(record.kind, variant):
                return False
        if record.array in _CONTENT_ARRAYS:
            has_content = True
    return has_content


def assess_pre_generation(ctx: DomainContext) -> PolicyOutcome:
    hits = collect_hits(ctx)
    minimum = max_level([h.level for h in hits]) if hits else L0
    if (minimum == L0 and not _low_risk_eligible(ctx, L0_ALLOWED_ARRAYS)) or (
        minimum == L1 and not _low_risk_eligible(ctx, L1_ALLOWED_ARRAYS)
    ):
        hits.append(RuleHit("UNCLASSIFIED_RISK", L2))
        minimum = L2
    codes = {h.code for h in hits}
    if minimum == L1:
        codes.add("LOW_RISK_POST_REVIEW")
    elif minimum == L0:
        codes.add("LOW_RISK_INFORMATIONAL")
    # Pre-generation has no model proposal: level is exactly the Domain minimum.
    level = minimum
    return PolicyOutcome(
        level=level,
        minimum_level=minimum,
        reason_codes=tuple(sorted(codes)),
        risk_factors=_risk_factors(ctx, hits),
        human_review_required=level != L0,
    )
