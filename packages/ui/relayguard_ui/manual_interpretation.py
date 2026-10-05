"""Build an Interpretation from what the operator marked by hand - no LLM, no API key, no network.

The LLM interpreter is optional and costs money; this path is the offline floor. The operator
reads the mail themselves and registers the few things that matter (questions, amounts,
deadlines, what the sender asks us to commit to), each anchored to an exact quote from the mail.

The result goes through exactly the same Schema -> Domain -> Evidence validation as any imported
Interpretation, so nothing here weakens a check: a quote that is not in the mail is rejected, and
a value left blank stays "unknown" instead of being guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from relayguard.errors import Rejection

MONEY_TYPES = ("price", "discount", "credit", "refund", "payment", "fee", "other")
DATE_TYPES = ("deadline", "date")
_ZERO_HASH = "0" * 64
_EMPTY_ARRAYS = (
    "sender_intent", "requests", "questions", "monetary_terms", "dates", "quantities", "contract_terms", "prohibitions",
    "guarantees", "refund_terms", "cancellation_terms", "license_terms", "rights", "requested_commitments", "commitments",
    "personal_data", "customer_emotion", "legal_claims", "reputational_risks", "prior_commitment_conflicts", "risks",
    "ambiguities", "missing_information", "attachment_dependencies", "prompt_injection_risks", "recommended_actions",
)  # fmt: skip


@dataclass(frozen=True)
class ManualEntry:
    """One thing the operator marked in the mail. `quote` must appear in the mail verbatim."""

    kind: str  # "question" | "money" | "date" | "commitment"
    quote: str
    text: str = ""  # question text / commitment action / object
    amount: str = ""
    currency: str = ""
    money_type: str = "other"
    date: str = ""
    timezone: str = ""
    date_type: str = "deadline"


@dataclass
class _Builder:
    state: dict[str, Any] = field(default_factory=dict)
    seq: int = 0

    def evidence(self, quote: str, claim_id: str) -> str:
        self.seq += 1
        evidence_id = f"ev_m{self.seq:02d}"
        self.state["evidence"].append(
            {
                "evidence_id": evidence_id,
                "source_kind": "source_message",
                "source_id": "msg_pending",
                "source_hash": _ZERO_HASH,
                "quote": quote,
                "supports": [claim_id],
                "confidence": None,
            }
        )
        return evidence_id


def _explicit(value: str, raw_text: str) -> dict[str, Any]:
    return {"status": "explicit", "value": value, "raw_text": raw_text}


def _unknown(raw_text: str) -> dict[str, Any]:
    return {"status": "unknown", "value": None, "raw_text": raw_text}


def _not_stated() -> dict[str, Any]:
    return {"status": "not_stated", "value": None, "raw_text": ""}


def _value(value: str, raw_text: str) -> dict[str, Any]:
    return _explicit(value, raw_text) if value else _unknown(raw_text)


def _check_quote(quote: str, haystack: str, position: int) -> None:
    if not quote.strip():
        raise Rejection("UnsupportedInput", f"{position}番目の項目: 原文の引用が空です。メール本文から該当部分をコピーしてください。")
    if quote not in haystack:
        raise Rejection(
            "UnsupportedInput",
            f"{position}番目の項目: 引用「{quote[:40]}」がメール本文に見つかりません。原文から一字一句そのままコピーしてください。",
        )


def build_interpretation(subject: str | None, body: str, entries: list[ManualEntry]) -> dict[str, Any]:
    """Assemble a schema-shaped Interpretation. Raises Rejection when a quote is not in the mail."""
    if not entries:
        raise Rejection("UnsupportedInput", "登録する項目が1つもありません。返信に必要な項目を少なくとも1つ登録してください。")
    haystack = f"{subject or ''}\n{body}"
    builder = _Builder(state={array: [] for array in _EMPTY_ARRAYS} | {"evidence": []})
    state = builder.state
    for position, entry in enumerate(entries, start=1):
        _check_quote(entry.quote, haystack, position)
        claim_id = f"c_m{position:02d}"
        evidence_id = builder.evidence(entry.quote, claim_id)
        base = {"id": claim_id, "evidence_ids": [evidence_id]}
        if entry.kind == "question":
            state["questions"].append({**base, "text": _explicit(entry.text or entry.quote, entry.quote), "required_answer": True})
        elif entry.kind == "money":
            if entry.money_type not in MONEY_TYPES:
                raise Rejection("UnsupportedInput", f"{position}番目の項目: 金額の種別が不正です。")
            state["monetary_terms"].append(
                {
                    **base,
                    "amount": _value(entry.amount, entry.quote),
                    "currency": _value(entry.currency.upper(), entry.quote),
                    "type": entry.money_type,
                    "condition": _explicit(entry.text, entry.quote) if entry.text else _not_stated(),
                }
            )
        elif entry.kind == "date":
            if entry.date_type not in DATE_TYPES:
                raise Rejection("UnsupportedInput", f"{position}番目の項目: 日付の種別が不正です。")
            state["dates"].append(
                {
                    **base,
                    "type": entry.date_type,
                    "date": _value(entry.date, entry.quote),
                    "timezone": _value(entry.timezone, entry.quote),
                }
            )
        elif entry.kind == "commitment":
            state["requested_commitments"].append(
                {
                    **base,
                    "actor": "user",
                    "action": _explicit(entry.text or entry.quote, entry.quote),
                    "object": _explicit(entry.quote, entry.quote),
                    "modality": _explicit("will", entry.quote),
                    "condition": _not_stated(),
                    "scope": _not_stated(),
                    "deadline_id": None,
                    "monetary_term_ids": [],
                    "authorization_state": "requested",
                }
            )
        else:
            raise Rejection("UnsupportedInput", f"{position}番目の項目: 種類が不正です。")
    state["human_review_required"] = True
    state["confidence"] = None
    return {
        "interpretation_id": "int_manual",
        "version": 1,
        "source_message_id": "msg_pending",
        "source_hash": _ZERO_HASH,
        "state": state,
    }


def entries_from_form(form: dict[str, str]) -> list[ManualEntry]:
    """Read the repeated rows of the manual form (kind_1, quote_1, ...), skipping blank rows."""
    entries: list[ManualEntry] = []
    for index in range(1, 13):
        kind = form.get(f"kind_{index}", "").strip()
        quote = form.get(f"quote_{index}", "").strip()
        if not kind or kind == "none":
            continue
        entries.append(
            ManualEntry(
                kind=kind,
                quote=quote,
                text=form.get(f"text_{index}", "").strip(),
                amount=form.get(f"amount_{index}", "").strip(),
                currency=form.get(f"currency_{index}", "").strip(),
                money_type=form.get(f"money_type_{index}", "other").strip() or "other",
                date=form.get(f"date_{index}", "").strip(),
                timezone=form.get(f"timezone_{index}", "").strip(),
                date_type=form.get(f"date_type_{index}", "deadline").strip() or "deadline",
            )
        )
    return entries
