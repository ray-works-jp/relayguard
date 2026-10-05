"""Synthetic offline fixture builder for SG-001 tests (no real people, no real mail).

The builder deliberately re-implements Decision bookkeeping (items, approved_commitments,
explicitly_unanswered) instead of calling production helpers, so production Domain checks
are exercised against an independent construction.
"""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from typing import Any

from relayguard.canonical import decision_hash, source_hash
from relayguard.claims import CLAIM_ARRAYS

Json = dict[str, Any]

CLAIM_ARRAY_ORDER: list[str] = [
    "sender_intent", "requests", "questions", "monetary_terms", "dates", "quantities",
    "contract_terms", "prohibitions", "guarantees", "refund_terms", "cancellation_terms",
    "license_terms", "rights", "requested_commitments", "commitments", "personal_data",
    "customer_emotion", "legal_claims", "reputational_risks", "prior_commitment_conflicts",
    "risks", "ambiguities", "missing_information", "attachment_dependencies",
    "prompt_injection_risks", "recommended_actions",
]  # fmt: skip

FIXTURE_ACTOR = "fixture_actor_01"
FIXTURE_TIME = "2026-09-15T09:00:00.000Z"


def ex(value: Any, raw_text: str | None = None) -> Json:
    return {"status": "explicit", "value": value, "raw_text": raw_text if raw_text is not None else str(value)}


def absent(status: str = "not_stated", raw_text: str = "") -> Json:
    return {"status": status, "value": None, "raw_text": raw_text}


def text_claim(cid: str, text: str) -> Json:
    return {"id": cid, "evidence_ids": [], "text": ex(text)}


def question(cid: str, text: str, required: bool = True) -> Json:
    return {"id": cid, "evidence_ids": [], "text": ex(text), "required_answer": required}


def money(cid: str, amount: Json, currency: Json, mtype: str, condition: Json | None = None) -> Json:
    return {
        "id": cid, "evidence_ids": [], "amount": amount, "currency": currency,
        "type": mtype, "condition": condition or absent(),
    }  # fmt: skip


def date_term(cid: str, date: Json, dtype: str = "deadline", timezone: Json | None = None) -> Json:
    return {"id": cid, "evidence_ids": [], "type": dtype, "date": date, "timezone": timezone or absent()}


def quantity(cid: str, qty: Json, unit: Json, condition: Json | None = None) -> Json:
    return {"id": cid, "evidence_ids": [], "quantity": qty, "unit": unit, "condition": condition or absent()}


def clause(
    cid: str, text: str, modality: Json | None = None, monetary: list[str] | None = None,
    deadlines: list[str] | None = None, commitments: list[str] | None = None,
) -> Json:  # fmt: skip
    return {
        "id": cid, "evidence_ids": [], "text": ex(text), "modality": modality or ex("will"),
        "condition": absent(), "scope": absent(), "monetary_term_ids": monetary or [],
        "deadline_ids": deadlines or [], "commitment_ids": commitments or [],
    }  # fmt: skip


def rights_term(cid: str, scope: str, exclusivity: Json, sublicensing: Json, commercial_use: Json) -> Json:
    return {
        "id": cid, "evidence_ids": [], "scope": ex(scope), "exclusivity": exclusivity,
        "sublicensing": sublicensing, "commercial_use": commercial_use, "condition": absent(),
    }  # fmt: skip


def commitment(
    cid: str, actor: str, action: str, obj: str, modality: str = "will",
    deadline_id: str | None = None, monetary: list[str] | None = None, state: str = "requested",
) -> Json:  # fmt: skip
    return {
        "id": cid, "evidence_ids": [], "actor": actor, "action": ex(action), "object": ex(obj),
        "modality": ex(modality), "condition": absent(), "scope": absent(), "deadline_id": deadline_id,
        "monetary_term_ids": monetary or [], "authorization_state": state,
    }  # fmt: skip


def emotion(cid: str, etype: str, target: str, intensity: str = "high") -> Json:
    return {"id": cid, "evidence_ids": [], "type": etype, "intensity": intensity, "target": ex(target)}


def legal(cid: str, claim_type: str) -> Json:
    return {"id": cid, "evidence_ids": [], "claim_type": ex(claim_type), "requires_human_review": True}


def risk(cid: str, rtype: str, description: str, affects_critical: bool, resolved: bool) -> Json:
    return {
        "id": cid, "evidence_ids": [], "type": rtype, "description": ex(description),
        "affects_critical": affects_critical, "resolved": resolved,
    }  # fmt: skip


def empty_state() -> Json:
    state: Json = {name: [] for name in CLAIM_ARRAY_ORDER}
    state["human_review_required"] = False
    state["confidence"] = Decimal("0.9")
    state["evidence"] = []
    return state


class CaseBuilder:
    def __init__(self, case_id: str, body: str, subject: str | None = "Order inquiry") -> None:
        self.case_id = case_id
        self.source: Json = {
            "message_id": f"{case_id}_msg",
            "subject": subject,
            "body": body,
            "source_language": "en",
            "user_language": "ja",
            "content_hash": "",
        }
        self.state = empty_state()
        self.decisions: dict[str, tuple[str, Json | None]] = {}
        self.answers: list[Json] = []
        self.human_notes: list[str] = []
        self._evidence_seq = 0

    def add(self, array: str, claim: Json, *quotes: str) -> str:
        claim = copy.deepcopy(claim)
        for quote in quotes:
            self._evidence_seq += 1
            evidence_id = f"ev{self._evidence_seq:02d}"
            claim["evidence_ids"].append(evidence_id)
            self.state["evidence"].append(
                {
                    "evidence_id": evidence_id,
                    "source_kind": "source_message",
                    "source_id": self.source["message_id"],
                    "source_hash": "",
                    "quote": quote,
                    "supports": [claim["id"]],
                    "confidence": Decimal("0.95"),
                }
            )
        self.state[array].append(claim)
        return str(claim["id"])

    def decide(self, claim_id: str, decision: str, replacement: Json | None = None) -> CaseBuilder:
        self.decisions[claim_id] = (decision, replacement)
        return self

    def answer(
        self,
        question_id: str,
        answer_text: str,
        *,
        basis: str = "user_assertion",
        evidence_ids: list[str] | None = None,
        related_claim_ids: list[str] | None = None,
    ) -> CaseBuilder:
        """Record a QuestionAnswer (SCHEMA §13). The fixture actor is the approving actor."""
        self.answers.append(
            {
                "question_id": question_id,
                "answer_text": answer_text,
                "basis": basis,
                "evidence_ids": sorted(evidence_ids or []),
                "related_claim_ids": sorted(related_claim_ids or []),
                "provenance": {
                    "actor_id": FIXTURE_ACTOR,
                    "decided_at": FIXTURE_TIME,
                    "reason_ja": "テスト用fixtureの回答（実ユーザー承認ではない）",
                },
            }
        )
        return self

    def build(self, policy_version: str = "delegation-0.4", schema_version: str = "0.5") -> Json:
        interpretation: Json = {
            "interpretation_id": f"{self.case_id}_interp",
            "version": 1,
            "source_message_id": self.source["message_id"],
            "source_hash": "",
            "state": copy.deepcopy(self.state),
        }
        items: list[Json] = []
        approved: list[Json] = []
        unanswered: list[str] = []
        kinds = kind_by_claim(interpretation["state"])
        for array in CLAIM_ARRAY_ORDER:
            for claim in interpretation["state"][array]:
                decision, replacement = self.decisions.get(claim["id"], ("approve", None))
                items.append(
                    {
                        "item_id": f"item_{claim['id']}",
                        "source_claim_id": claim["id"],
                        "decision": decision,
                        "replacement": (
                            {"kind": kinds[claim["id"]], "value": copy.deepcopy(replacement)} if replacement is not None else None
                        ),
                        "provenance": {
                            "actor_id": FIXTURE_ACTOR,
                            "decided_at": FIXTURE_TIME,
                            "reason_ja": "テスト用fixtureの判断（実ユーザー承認ではない）",
                        },
                    }
                )
                if array in ("requested_commitments", "commitments") and decision in ("approve", "modify"):
                    chosen = copy.deepcopy(replacement if decision == "modify" else claim)
                    assert chosen is not None
                    chosen["authorization_state"] = "approved"
                    approved.append(chosen)
                if array == "questions" and decision == "do_not_answer":
                    unanswered.append(claim["id"])
        document: Json = {
            "schema_version": schema_version,
            "case_id": self.case_id,
            "source_message": copy.deepcopy(self.source),
            "interpretation": interpretation,
            "approved_decision": {
                "decision_id": f"{self.case_id}_decision",
                "version": 1,
                "source_interpretation_id": interpretation["interpretation_id"],
                "source_interpretation_version": 1,
                "source_hash": "",
                "items": items,
                "question_answers": sorted(self.answers, key=lambda a: str(a["question_id"])),
                "approved_commitments": approved,
                "explicitly_unanswered": unanswered,
                "human_notes": list(self.human_notes),
                "approved_by": FIXTURE_ACTOR,
                "approved_at": FIXTURE_TIME,
                "decision_hash": "",
            },
            "policy_version": policy_version,
        }
        return rehash(document)


def new_item(claim_id: str, decision: str = "approve") -> Json:
    return {
        "item_id": f"item_{claim_id}",
        "source_claim_id": claim_id,
        "decision": decision,
        "replacement": None,
        "provenance": {
            "actor_id": FIXTURE_ACTOR,
            "decided_at": FIXTURE_TIME,
            "reason_ja": "テスト用fixtureの判断（実ユーザー承認ではない）",
        },
    }


def kind_by_claim(state: Json) -> dict[str, str]:
    return {claim["id"]: CLAIM_ARRAYS[array] for array in CLAIM_ARRAY_ORDER for claim in state[array]}


def rehash(document: Json) -> Json:
    """Recompute every derived hash so a test can isolate one non-hash violation."""
    source = document["source_message"]
    source["content_hash"] = source_hash(source)
    interpretation = document["interpretation"]
    interpretation["source_hash"] = source["content_hash"]
    for evidence in interpretation["state"]["evidence"]:
        evidence["source_hash"] = source["content_hash"]
    decision = document["approved_decision"]
    decision["source_hash"] = source["content_hash"]
    decision["decision_hash"] = decision_hash(decision)
    return document


def rehash_decision(document: Json) -> Json:
    decision = document["approved_decision"]
    decision["decision_hash"] = decision_hash(decision)
    return document


def to_bytes(document: Any, indent: int | None = None) -> bytes:
    text = json.dumps(_decimals_to_markers(document), ensure_ascii=False, indent=indent)
    return _restore_markers(text).encode("utf-8")


_MARK = "@@RG_DECIMAL@@"


def _decimals_to_markers(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{_MARK}{format(value, 'f')}"
    if isinstance(value, dict):
        return {k: _decimals_to_markers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimals_to_markers(v) for v in value]
    return value


def _restore_markers(text: str) -> str:
    return re.sub(r'"@@RG_DECIMAL@@(-?[0-9.]+)"', lambda match: match.group(1), text)
