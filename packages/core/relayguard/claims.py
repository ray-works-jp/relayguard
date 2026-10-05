"""Claim typing helpers for StructuredState (SCHEMA.md §§2-3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# StructuredState array field -> Claim type name (SCHEMA.md §3). Order is stable.
CLAIM_ARRAYS: dict[str, str] = {
    "sender_intent": "TextClaim",
    "requests": "TextClaim",
    "questions": "Question",
    "monetary_terms": "MonetaryTerm",
    "dates": "DateTerm",
    "quantities": "QuantityTerm",
    "contract_terms": "ClauseTerm",
    "prohibitions": "ClauseTerm",
    "guarantees": "ClauseTerm",
    "refund_terms": "ClauseTerm",
    "cancellation_terms": "ClauseTerm",
    "license_terms": "RightsLicenseTerm",
    "rights": "RightsLicenseTerm",
    "requested_commitments": "Commitment",
    "commitments": "Commitment",
    "personal_data": "TextClaim",
    "customer_emotion": "Emotion",
    "legal_claims": "LegalClaim",
    "reputational_risks": "Risk",
    "prior_commitment_conflicts": "Risk",
    "risks": "Risk",
    "ambiguities": "Risk",
    "missing_information": "Risk",
    "attachment_dependencies": "Risk",
    "prompt_injection_risks": "Risk",
    "recommended_actions": "TextClaim",
}

# "重大" (SCHEMA.md §3): money, currency, dates/deadlines, quantity, rights, license,
# prohibitions, guarantees, refunds, contracts, commitments, personal data disclosure.
CRITICAL_ARRAYS: frozenset[str] = frozenset(
    {
        "monetary_terms",
        "dates",
        "quantities",
        "contract_terms",
        "prohibitions",
        "guarantees",
        "refund_terms",
        "cancellation_terms",
        "license_terms",
        "rights",
        "requested_commitments",
        "commitments",
        "personal_data",
    }
)

# Value<T> fields that must be explicit for a critical claim (DELEGATION.md §14.1).
# The only exception is DateTerm.timezone when DateTerm.type == "date" (pure calendar day);
# see delegation._has_critical_value_gap. unknown / ambiguous / not_stated are all gaps.
REQUIRED_VALUE_FIELDS: dict[str, tuple[str, ...]] = {
    "MonetaryTerm": ("amount", "currency", "condition"),
    "DateTerm": ("date", "timezone"),
    "QuantityTerm": ("quantity", "unit", "condition"),
    "ClauseTerm": ("text", "modality", "condition", "scope"),
    "RightsLicenseTerm": ("scope", "exclusivity", "sublicensing", "commercial_use", "condition"),
    "Commitment": ("action", "object", "modality", "condition", "scope"),
    "TextClaim": ("text",),
}

VALUE_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    "TextClaim": ("text",),
    "ClauseTerm": ("text", "modality", "condition", "scope"),
    "MonetaryTerm": ("amount", "currency", "condition"),
    "DateTerm": ("date", "timezone"),
    "QuantityTerm": ("quantity", "unit", "condition"),
    "RightsLicenseTerm": ("scope", "exclusivity", "sublicensing", "commercial_use", "condition"),
    "Commitment": ("action", "object", "modality", "condition", "scope"),
    "Question": ("text",),
    "Emotion": ("target",),
    "LegalClaim": ("claim_type",),
    "Risk": ("description",),
}


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    array: str
    kind: str
    body: dict[str, Any]

    @property
    def critical(self) -> bool:
        return self.array in CRITICAL_ARRAYS


def iter_claims(state: dict[str, Any]) -> list[ClaimRecord]:
    records: list[ClaimRecord] = []
    for array, kind in CLAIM_ARRAYS.items():
        for claim in state[array]:
            records.append(ClaimRecord(claim["id"], array, kind, claim))
    return records
