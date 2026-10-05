"""Domain / cross-field validation of a schema-valid ShadowCoreInput (SCHEMA.md §§2-5, SD-07).

Every violation raises Rejection; nothing is repaired, defaulted or coerced.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .canonical import decision_hash, source_hash
from .claims import VALUE_FIELDS_BY_KIND, ClaimRecord, iter_claims
from .errors import Rejection

# subject + body UTF-8 upper bound (IMPLEMENTATION.md §23).
MAX_SOURCE_BYTES = 64 * 1024

_PLACEHOLDER_TEXTS: frozenset[str] = frozenset(
    {
        "",
        "unknown",
        "not_stated",
        "not stated",
        "ambiguous",
        "explicit",
        "null",
        "undefined",
        "n/a",
        "tbd",
        "todo",
        "placeholder",
        "?",
        "???",
    }
)


@dataclass(frozen=True)
class DomainContext:
    case_id: str
    policy_version: str
    source: dict[str, Any]
    interpretation: dict[str, Any]
    decision: dict[str, Any]
    claims: dict[str, ClaimRecord]
    items_by_claim: dict[str, dict[str, Any]]
    answers_by_question: dict[str, dict[str, Any]]


def check_source_size(source: dict[str, Any]) -> None:
    subject = source["subject"] or ""
    size = len(subject.encode("utf-8")) + len(source["body"].encode("utf-8"))
    if size > MAX_SOURCE_BYTES:
        raise Rejection(
            "UnsupportedInput",
            "件名と本文の合計が上限64 KiBを超えています。切り捨てずに処理を停止しました。",
        )


def _check_value_semantics(kind: str, claim: dict[str, Any]) -> None:
    for field in VALUE_FIELDS_BY_KIND[kind]:
        value = claim[field]
        is_text = value["status"] == "explicit" and isinstance(value["value"], str)
        if is_text and value["value"].strip().lower() in _PLACEHOLDER_TEXTS:
            raise Rejection(
                "SchemaInvalid",
                "explicitな値に意味を確定できないplaceholderが入っています。statusで表現してください。",
            )
    if kind == "MonetaryTerm":
        amount = claim["amount"]
        if amount["status"] == "explicit" and Decimal(amount["value"]) < 0:
            raise Rejection("SchemaInvalid", "金額に負数は使用できません（本MVPで意味が未定義）。")
    if kind == "QuantityTerm":
        quantity = claim["quantity"]
        if quantity["status"] == "explicit":
            number = Decimal(quantity["value"])
            if number < 0:
                raise Rejection("SchemaInvalid", "数量に負数は使用できません（本MVPで意味が未定義）。")
            unit = claim["unit"]
            if unit["status"] == "explicit" and unit["value"] == "percent" and number > 100:
                raise Rejection("SchemaInvalid", "unit=percentの数量は0〜100である必要があります。")


def _check_references(kind: str, claim: dict[str, Any], claims: dict[str, ClaimRecord]) -> None:
    def expect(ref_id: str, expected_kind: str) -> None:
        record = claims.get(ref_id)
        if record is None:
            raise Rejection("InternalIntegrityError", "存在しないClaim IDへの参照があります。")
        if record.kind != expected_kind:
            raise Rejection("InternalIntegrityError", "参照先Claimの型が契約と一致しません。")

    if kind in ("ClauseTerm", "Commitment"):
        for ref in claim["monetary_term_ids"]:
            expect(ref, "MonetaryTerm")
    if kind == "ClauseTerm":
        for ref in claim["deadline_ids"]:
            expect(ref, "DateTerm")
        for ref in claim["commitment_ids"]:
            expect(ref, "Commitment")
    if kind == "Commitment" and claim["deadline_id"] is not None:
        expect(claim["deadline_id"], "DateTerm")


def _index_claims(state: dict[str, Any]) -> dict[str, ClaimRecord]:
    claims: dict[str, ClaimRecord] = {}
    for record in iter_claims(state):
        if record.claim_id in claims:
            raise Rejection("SchemaInvalid", "同一Interpretation内でClaim IDが重複しています。")
        claims[record.claim_id] = record
    return claims


def _check_evidence(source: dict[str, Any], state: dict[str, Any], claims: dict[str, ClaimRecord]) -> None:
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for evidence in state["evidence"]:
        if evidence["evidence_id"] in evidence_by_id:
            raise Rejection("SchemaInvalid", "Evidence IDが重複しています。")
        evidence_by_id[evidence["evidence_id"]] = evidence

    texts = [source["body"]] + ([source["subject"]] if source["subject"] is not None else [])
    for evidence in state["evidence"]:
        if evidence["source_kind"] != "source_message":
            raise Rejection(
                "InternalIntegrityError",
                "事前判定の段階では返信由来Evidenceを参照できません（対象Draftが存在しません）。",
            )
        if evidence["source_id"] != source["message_id"]:
            raise Rejection("InternalIntegrityError", "Evidenceが別の原文を参照しています。")
        if evidence["source_hash"] != source["content_hash"]:
            raise Rejection("InternalIntegrityError", "Evidenceのsource_hashが原文hashと一致しません。")
        if not any(evidence["quote"] in text for text in texts):
            raise Rejection("InternalIntegrityError", "Evidence.quoteが原文の完全一致部分文字列ではありません。")
        for claim_id in evidence["supports"]:
            record = claims.get(claim_id)
            if record is None:
                raise Rejection("InternalIntegrityError", "Evidence.supportsに存在しないClaim IDがあります。")
            if evidence["evidence_id"] not in record.body["evidence_ids"]:
                raise Rejection("InternalIntegrityError", "Evidence.supportsとClaim.evidence_idsが相互対応していません。")

    for record in claims.values():
        for evidence_id in record.body["evidence_ids"]:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise Rejection("InternalIntegrityError", "Claimが存在しないEvidence IDを参照しています。")
            if record.claim_id not in evidence["supports"]:
                raise Rejection("InternalIntegrityError", "Claim.evidence_idsとEvidence.supportsが相互対応していません。")
        if record.critical and not record.body["evidence_ids"]:
            raise Rejection("SchemaInvalid", "重大Claimに原文Evidenceがありません。")


def build_approved_commitments(claims: dict[str, ClaimRecord], items_by_claim: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Domain construction of approved_commitments from approve/modify items only."""
    built: list[dict[str, Any]] = []
    for record in claims.values():
        if record.kind != "Commitment":
            continue
        item = items_by_claim[record.claim_id]
        if item["decision"] == "approve":
            commitment = copy.deepcopy(record.body)
        elif item["decision"] == "modify":
            commitment = copy.deepcopy(item["replacement"]["value"])
        else:
            continue
        commitment["authorization_state"] = "approved"
        built.append(commitment)
    return built


def _check_question_answers(
    decision: dict[str, Any],
    claims: dict[str, ClaimRecord],
    items_by_claim: dict[str, dict[str, Any]],
    evidence_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """SCHEMA §13: an answer is a separate, provenanced record bound to an approved
    question. It never comes from an LLM, from human_notes, or from the approval alone."""
    answers: dict[str, dict[str, Any]] = {}
    previous: str | None = None
    for answer in decision["question_answers"]:
        question_id = answer["question_id"]
        if previous is not None and question_id <= previous:
            raise Rejection("PolicyViolation", "question_answersはquestion_idのASCII昇順・一意である必要があります。")
        previous = question_id
        record = claims.get(question_id)
        if record is None or record.kind != "Question":
            raise Rejection("PolicyViolation", "QuestionAnswerが存在しないQuestionを参照しています。")
        item = items_by_claim[question_id]
        if item["decision"] not in ("approve", "modify"):
            raise Rejection(
                "PolicyViolation",
                "回答を記録できるのは対応するDecisionItemがapprove/modifyの質問だけです（unknown/do_not_answerとの併存は不可）。",
            )
        if answer["provenance"]["actor_id"] != decision["approved_by"]:
            raise Rejection("PolicyViolation", "QuestionAnswerの承認主体がDecisionのapproved_byと一致しません。")
        if answer["answer_text"].strip().lower() in _PLACEHOLDER_TEXTS:
            raise Rejection("SchemaInvalid", "回答本文がplaceholderです。意味のある回答を記録してください。")
        if answer["basis"] == "source_evidence":
            if not set(answer["evidence_ids"]) <= evidence_ids:
                raise Rejection("InternalIntegrityError", "回答が存在しないEvidenceを参照しています。")
        elif answer["evidence_ids"]:
            raise Rejection(
                "PolicyViolation",
                "basis=user_assertionの回答に原文Evidenceを付けることはできません（出典の偽装）。",
            )
        related = answer["related_claim_ids"]
        if related != sorted(related):
            raise Rejection("PolicyViolation", "related_claim_idsはASCII昇順である必要があります。")
        for claim_id in related:
            if claim_id not in claims:
                raise Rejection("InternalIntegrityError", "回答が存在しないClaimを参照しています。")
            if items_by_claim[claim_id]["decision"] not in ("approve", "modify"):
                raise Rejection(
                    "PolicyViolation",
                    "回答が承認されていないClaimを参照しています（approve/modifyのみ参照可）。",
                )
        answers[question_id] = answer

    unanswered = set(decision["explicitly_unanswered"])
    if unanswered & set(answers):
        raise Rejection("PolicyViolation", "同じ質問をdo_not_answerと回答済みの両方にできません。")
    return answers


def _check_decision(
    decision: dict[str, Any], claims: dict[str, ClaimRecord], evidence_ids: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    item_ids: set[str] = set()
    items_by_claim: dict[str, dict[str, Any]] = {}
    for item in decision["items"]:
        if item["item_id"] in item_ids:
            raise Rejection("SchemaInvalid", "DecisionItem IDが重複しています。")
        item_ids.add(item["item_id"])
        record = claims.get(item["source_claim_id"])
        if record is None:
            raise Rejection("InternalIntegrityError", "DecisionItemが存在しないClaimを参照しています。")
        if record.claim_id in items_by_claim:
            raise Rejection("PolicyViolation", "同じClaimに複数のDecisionItemがあります。")
        items_by_claim[record.claim_id] = item

        replacement = item["replacement"]
        if item["decision"] == "modify":
            if replacement is None:
                raise Rejection("SchemaInvalid", "modifyにはreplacementが必須です。")
            if replacement["kind"] != record.kind:
                raise Rejection("SchemaInvalid", "replacementの型が元Claimの型と一致しません。")
            value = replacement["value"]
            if value["id"] != record.claim_id:
                raise Rejection("SchemaInvalid", "replacementのidが元Claimのidと一致しません。")
            if not set(value["evidence_ids"]) <= set(record.body["evidence_ids"]):
                raise Rejection(
                    "InternalIntegrityError",
                    "replacementが元Claimに紐付かないEvidenceを参照しています（Evidence捏造は禁止）。",
                )
            _check_value_semantics(record.kind, value)
            _check_references(record.kind, value, claims)
        elif replacement is not None:
            raise Rejection("SchemaInvalid", "modify以外のDecisionItemではreplacementはnullです。")

    if set(items_by_claim) != set(claims):
        raise Rejection(
            "PolicyViolation",
            "DecisionがInterpretationの全Claimを扱っていません。未選択をapproveとして補完しません。",
        )

    expected_commitments = {c["id"]: c for c in build_approved_commitments(claims, items_by_claim)}
    actual_commitments: dict[str, dict[str, Any]] = {}
    for commitment in decision["approved_commitments"]:
        if commitment["id"] in actual_commitments:
            raise Rejection("SchemaInvalid", "approved_commitmentsのIDが重複しています。")
        actual_commitments[commitment["id"]] = commitment
    if actual_commitments != expected_commitments:
        raise Rejection(
            "PolicyViolation",
            "approved_commitmentsがapprove/modifyされた項目からDomainが構築する内容と一致しません（承認の偽装・欠落）。",
        )

    unanswered = {
        claim_id for claim_id, item in items_by_claim.items() if item["decision"] == "do_not_answer" and claims[claim_id].kind == "Question"
    }
    if set(decision["explicitly_unanswered"]) != unanswered:
        raise Rejection(
            "PolicyViolation",
            "explicitly_unansweredがdo_not_answerを選択したQuestion IDの集合と一致しません。",
        )
    answers = _check_question_answers(decision, claims, items_by_claim, evidence_ids)
    return items_by_claim, answers


def validate_domain(document: dict[str, Any]) -> DomainContext:
    source = document["source_message"]
    interpretation = document["interpretation"]
    decision = document["approved_decision"]

    if source_hash(source) != source["content_hash"]:
        raise Rejection("InternalIntegrityError", "SourceMessage.content_hashが原文から再計算したhashと一致しません。")
    if interpretation["source_message_id"] != source["message_id"] or interpretation["source_hash"] != source["content_hash"]:
        raise Rejection("StaleState", "Interpretationが供給された原文（ID/hash）に束縛されていません。")
    if (
        decision["source_interpretation_id"] != interpretation["interpretation_id"]
        or decision["source_interpretation_version"] != interpretation["version"]
        or decision["source_hash"] != source["content_hash"]
    ):
        raise Rejection("StaleState", "Approved DecisionがInterpretation（ID/version/source hash）に束縛されていません。")
    if decision_hash(decision) != decision["decision_hash"]:
        raise Rejection("InternalIntegrityError", "decision_hashがDecision内容から再計算したhashと一致しません。")

    state = interpretation["state"]
    claims = _index_claims(state)
    for record in claims.values():
        _check_value_semantics(record.kind, record.body)
        _check_references(record.kind, record.body, claims)
        if record.kind == "Commitment" and record.body["authorization_state"] == "approved":
            raise Rejection(
                "PolicyViolation",
                "Interpretation（原文解釈）のCommitmentをapprovedにすることはできません。承認はDecisionのみです。",
            )
    _check_evidence(source, state, claims)
    evidence_ids = {evidence["evidence_id"] for evidence in state["evidence"]}
    items_by_claim, answers = _check_decision(decision, claims, evidence_ids)

    return DomainContext(
        case_id=document["case_id"],
        policy_version=document["policy_version"],
        source=source,
        interpretation=interpretation,
        decision=decision,
        claims=claims,
        items_by_claim=items_by_claim,
        answers_by_question=answers,
    )
