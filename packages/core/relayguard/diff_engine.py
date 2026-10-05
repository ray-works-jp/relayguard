"""Deterministic typed Reply Diff (IMPLEMENTATION.md §5.7, SCHEMA.md §7).

Compares the Approved Decision (via the Domain-validated context) with the Decision-blind
ReplyExtraction. Pure code: no LLM, no confidence, no Generator self-report.

Model: the reply is allowed to consist only of
- Generator boilerplate lines (no values, no commitments), and
- "approved units": one per approved commitment (its rendered block) and one per recorded
  QuestionAnswer (its answer_text lines).
Each unit carries the typed values it may state (money / dates / quantities / e-mail
addresses) and the keyword classes it may contain, derived from typed approved claims only.

Checks (all findings are blocking; value/condition/authority/commitment changes are
critical and can never be made non-blocking):
1. closed world: every reply line belongs to boilerplate or an approved unit,
2. typed tokens: every extracted money/date/quantity/e-mail on a line is allowed by a unit
   on that line; symbols, partial dates and unclassified numbers are never allowed,
3. keyword classes / commitments / legal / injection in the reply need a unit allowing them,
4. omission: every approved unit is present, including its typed values and condition,
5. answer coverage: every required question is answered or explicitly unanswered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .claims import CLAIM_ARRAYS
from .generator import BOILERPLATE_LINES, answer_lines, draft_binding, effective_claim, render_commitment_block
from .integrity import DomainContext
from .reply_extractor import split_lines

CHECKED_FIELDS: tuple[str, ...] = (
    "amount", "currency", "date", "deadline", "timezone", "quantity", "rights", "exclusivity", "sublicensing",
    "refund", "guarantee", "commitment", "prohibition", "condition", "personal_data", "required_answer_coverage",
    "closed_world_lines", "binding",
)  # fmt: skip

COMMITMENT_UNIT_CLASSES: frozenset[str] = frozenset(
    {
        "commitments",
        "requested_commitments",
        "guarantees",
        "refund_terms",
        "contract_terms",
        "cancellation_terms",
        "license_terms",
        "prohibitions",
    }
)
_ANSWER_CLASS_BY_ARRAY: dict[str, set[str]] = {
    "guarantees": {"guarantees"},
    "refund_terms": {"refund_terms"},
    "contract_terms": {"contract_terms"},
    "cancellation_terms": {"cancellation_terms"},
    "prohibitions": {"prohibitions"},
    "license_terms": {"license_terms"},
    "rights": {"license_terms"},
    "commitments": {"commitments", "requested_commitments"},
    "requested_commitments": {"commitments", "requested_commitments"},
}
_CLASS_FINDING: dict[str, str] = {
    "guarantees": "guarantee_added",
    "refund_terms": "refund_added",
    "contract_terms": "unsupported_claim",
    "cancellation_terms": "unsupported_claim",
    "license_terms": "license_changed",
    "prohibitions": "unsupported_claim",
    "commitments": "commitment_added",
    "requested_commitments": "commitment_added",
}
_CLASS_LABEL_JA: dict[str, str] = {
    "guarantees": "保証・確約表現",
    "refund_terms": "返金・補償・クレジット",
    "contract_terms": "値引き・無償化・契約条件",
    "cancellation_terms": "解約・キャンセル",
    "license_terms": "ライセンス・権利",
    "prohibitions": "禁止事項",
    "commitments": "こちら側の約束・行動表明",
    "requested_commitments": "相手側への義務付け",
}


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str
    claim_id: str


@dataclass(frozen=True)
class DateValue:
    iso: str
    timezone: str | None
    claim_id: str


@dataclass(frozen=True)
class QuantityValue:
    amount: Decimal
    unit: str
    claim_id: str


@dataclass
class Unit:
    kind: str  # "commitment" | "answer"
    source_id: str
    lines: list[str]
    classes: set[str] = field(default_factory=set)
    money: list[Money] = field(default_factory=list)
    dates: list[DateValue] = field(default_factory=list)
    quantities: list[QuantityValue] = field(default_factory=list)
    emails: set[str] = field(default_factory=set)
    required_question: bool = False


def _money_of(term: dict[str, Any], claim_id: str) -> Money | None:
    if term["amount"]["status"] != "explicit" or term["currency"]["status"] != "explicit":
        return None
    return Money(Decimal(term["amount"]["value"]), term["currency"]["value"], claim_id)


def _date_of(term: dict[str, Any], claim_id: str) -> DateValue | None:
    if term["date"]["status"] != "explicit":
        return None
    tz = term["timezone"]["value"] if term["timezone"]["status"] == "explicit" else None
    return DateValue(term["date"]["value"], tz, claim_id)


def _quantity_of(term: dict[str, Any], claim_id: str) -> QuantityValue | None:
    if term["quantity"]["status"] != "explicit" or term["unit"]["status"] != "explicit":
        return None
    return QuantityValue(Decimal(term["quantity"]["value"]), _unit_key(term["unit"]["value"]), claim_id)


def _unit_key(unit: str) -> str:
    key = unit.strip().lower()
    if key in ("%", "percent", "per cent", "パーセント"):
        return "percent"
    return key[:-1] if key.endswith("s") and len(key) > 3 else key


def approved_quantities(ctx: DomainContext) -> list[QuantityValue]:
    values: list[QuantityValue] = []
    for record in ctx.claims.values():
        if record.kind == "QuantityTerm":
            term = effective_claim(ctx, record.claim_id)
            value = _quantity_of(term, record.claim_id) if term is not None else None
            if value is not None:
                values.append(value)
    return values


def build_units(ctx: DomainContext) -> list[Unit]:
    """Approved units derived from typed approved Decision content only."""
    units: list[Unit] = []
    quantities = approved_quantities(ctx)
    for commitment in ctx.decision["approved_commitments"]:
        unit = Unit("commitment", commitment["id"], render_commitment_block(ctx, commitment), set(COMMITMENT_UNIT_CLASSES))
        for term_id in commitment["monetary_term_ids"]:
            term = effective_claim(ctx, term_id)
            money = _money_of(term, term_id) if term is not None else None
            if money is not None:
                unit.money.append(money)
        if commitment["deadline_id"] is not None:
            term = effective_claim(ctx, commitment["deadline_id"])
            date_value = _date_of(term, commitment["deadline_id"]) if term is not None else None
            if date_value is not None:
                unit.dates.append(date_value)
        unit.quantities.extend(quantities)
        units.append(unit)

    for answer in ctx.decision["question_answers"]:
        question = ctx.claims[answer["question_id"]].body
        unit = Unit("answer", answer["question_id"], answer_lines(answer["answer_text"]), required_question=question["required_answer"])
        for related_id in answer["related_claim_ids"]:
            record = ctx.claims[related_id]
            term = effective_claim(ctx, related_id)
            if term is None:
                continue
            unit.classes |= _ANSWER_CLASS_BY_ARRAY.get(record.array, set())
            if record.kind == "MonetaryTerm" and (money := _money_of(term, related_id)) is not None:
                unit.money.append(money)
            elif record.kind == "DateTerm" and (date_value := _date_of(term, related_id)) is not None:
                unit.dates.append(date_value)
            elif record.kind == "QuantityTerm" and (quantity := _quantity_of(term, related_id)) is not None:
                unit.quantities.append(quantity)
            elif record.array == "personal_data" and term["text"]["status"] == "explicit":
                unit.emails.add(str(term["text"]["value"]))
        units.append(unit)
    return units


class _Findings:
    """Deterministic-diff findings. Every diff finding is blocking; critical is always blocking."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(  # noqa: PLR0913 - keyword-only claim/evidence references
        self,
        ftype: str,
        severity: str,
        explanation_ja: str,
        *,
        expected: list[str] | None = None,
        actual: list[str] | None = None,
        evidence: list[str] | None = None,
    ) -> None:
        self.items.append(
            {
                "finding_id": f"fd_{len(self.items) + 1:03d}",
                "type": ftype,
                "severity": severity,
                "blocking": True,
                "origin": "deterministic_diff",
                "expected_claim_ids": sorted(set(expected or [])),
                "actual_claim_ids": sorted(set(actual or [])),
                "evidence_ids": sorted(set(evidence or [])),
                "explanation_ja": explanation_ja,
            }
        )


def _claims_by_line(extraction: dict[str, Any]) -> list[tuple[str, str, dict[str, Any], str]]:
    """(array, line, claim, evidence_id) for every extracted claim."""
    state = extraction["state"]
    quotes = {ev["evidence_id"]: ev["quote"] for ev in state["evidence"]}
    rows: list[tuple[str, str, dict[str, Any], str]] = []
    for array in CLAIM_ARRAYS:
        for claim in state[array]:
            for evidence_id in claim["evidence_ids"]:
                rows.append((array, quotes[evidence_id], claim, evidence_id))
    return rows


@dataclass(frozen=True)
class _Scope:
    """Units allowed on the claim's line, plus all units (used only to name the difference)."""

    on_line: list[Unit]
    all_units: list[Unit]


def _check_money(f: _Findings, claim: dict[str, Any], scope: _Scope, evidence_id: str, used: set[str]) -> None:
    if claim["currency"]["status"] != "explicit":
        f.add(
            "currency_changed",
            "critical",
            "通貨が記号・通貨名のみで表記され、ISO通貨コードで確定できません（$をUSDとは推測しません）。",
            actual=[claim["id"]],
            evidence=[evidence_id],
        )
        return
    if claim["amount"]["status"] != "explicit":
        f.add("amount_changed", "critical", "金額表記を10進数として確定できません。", actual=[claim["id"]], evidence=[evidence_id])
        return
    amount, currency = Decimal(claim["amount"]["value"]), claim["currency"]["value"]
    for money in (m for unit in scope.on_line for m in unit.money):
        if money.amount == amount and money.currency == currency:
            used.add(money.claim_id)
            return
    candidates = [m for unit in (scope.on_line or scope.all_units) for m in unit.money]
    expected = [m.claim_id for m in candidates]
    if any(m.currency == currency for m in candidates):
        f.add(
            "amount_changed",
            "critical",
            "返信の金額が承認済みの金額と一致しません。",
            expected=expected,
            actual=[claim["id"]],
            evidence=[evidence_id],
        )
    elif candidates:
        f.add(
            "currency_changed",
            "critical",
            "返信の通貨が承認済みの通貨と一致しません。",
            expected=expected,
            actual=[claim["id"]],
            evidence=[evidence_id],
        )
    else:
        f.add(
            "unsupported_claim",
            "critical",
            "承認済みDecisionに型付きの根拠がない金額が返信に含まれています。",
            actual=[claim["id"]],
            evidence=[evidence_id],
        )


def _check_date(f: _Findings, claim: dict[str, Any], scope: _Scope, evidence_id: str, used: set[str]) -> None:
    if claim["date"]["status"] != "explicit":
        f.add(
            "date_changed",
            "critical",
            "年月日が確定しない日付・相対的な期日表現が返信に含まれています。",
            actual=[claim["id"]],
            evidence=[evidence_id],
        )
        return
    reply_tz = claim["timezone"]["value"] if claim["timezone"]["status"] == "explicit" else None
    for approved in (d for unit in scope.on_line for d in unit.dates):
        if approved.iso == claim["date"]["value"] and approved.timezone == reply_tz:
            used.add(approved.claim_id)
            return
    candidates = [d for unit in (scope.on_line or scope.all_units) for d in unit.dates]
    if candidates:
        f.add(
            "date_changed",
            "critical",
            "返信の日付・期限（またはtimezone）が承認済みの値と一致しません。",
            expected=[d.claim_id for d in candidates],
            actual=[claim["id"]],
            evidence=[evidence_id],
        )
    else:
        f.add(
            "unsupported_claim",
            "critical",
            "承認済みDecisionに型付きの根拠がない日付が返信に含まれています。",
            actual=[claim["id"]],
            evidence=[evidence_id],
        )


def _check_quantity(f: _Findings, claim: dict[str, Any], scope: _Scope, evidence_id: str) -> None:
    if claim["quantity"]["status"] != "explicit" or claim["unit"]["status"] != "explicit":
        f.add("quantity_changed", "critical", "数量を確定できません。", actual=[claim["id"]], evidence=[evidence_id])
        return
    amount, unit_key = Decimal(claim["quantity"]["value"]), _unit_key(claim["unit"]["value"])
    if not any(q.amount == amount and q.unit == unit_key for unit in scope.on_line for q in unit.quantities):
        candidates = [q for unit in (scope.on_line or scope.all_units) for q in unit.quantities]
        f.add(
            "quantity_changed",
            "critical",
            "承認済みの数量・割合（単位を含む）と一致しない数量が返信に含まれています。",
            expected=[q.claim_id for q in candidates],
            actual=[claim["id"]],
            evidence=[evidence_id],
        )


# Fixed findings for claim arrays that are never allowed in a reply, whatever the Decision says.
_ALWAYS_BLOCKED: dict[str, tuple[str, str]] = {
    "legal_claims": ("legal_claim_detected", "返信に法的措置・訴訟等に関する表現があります。AI処理を停止し手動対応してください。"),
    "prompt_injection_risks": ("prompt_injection_risk", "返信に指示文（プロンプトインジェクションの疑い）が含まれています。"),
}


def compute_diff(ctx: DomainContext, draft: dict[str, Any], extraction: dict[str, Any]) -> dict[str, Any]:
    """Return DiffResult (SCHEMA.md §7). Binding checks are done by the caller (verifier).

    The steps run in the numbered order of the module docstring; finding IDs follow that order.
    """
    f = _Findings()
    units = build_units(ctx)
    reply_lines = split_lines(draft["reply_text"])
    units_by_line: dict[str, list[Unit]] = {}
    for unit in units:
        for line in unit.lines:
            units_by_line.setdefault(line, []).append(unit)
    rows = _claims_by_line(extraction)

    _check_closed_world(f, reply_lines, units_by_line, rows)
    used_values: set[str] = set()
    source_text = f"{ctx.source['subject'] or ''}\n{ctx.source['body']}"
    for row in rows:
        _check_claim(f, row, _Scope(units_by_line.get(row[1], []), units), used_values, source_text)
    _check_omissions(f, units, set(reply_lines), used_values)
    _check_answer_coverage(f, ctx)
    return {"binding": draft_binding(draft), "findings": f.items, "checked_fields": list(CHECKED_FIELDS), "complete": True}


def _check_closed_world(
    f: _Findings, reply_lines: list[str], units_by_line: dict[str, list[Unit]], rows: list[tuple[str, str, dict[str, Any], str]]
) -> None:
    """1. Every reply line belongs to boilerplate or an approved unit."""
    evidence_by_line: dict[str, list[str]] = {}
    claims_on_line: dict[str, list[str]] = {}
    for array, line, claim, evidence_id in rows:
        evidence_by_line.setdefault(line, []).append(evidence_id)
        if array not in ("questions", "sender_intent"):
            claims_on_line.setdefault(line, []).append(claim["id"])
    for line in reply_lines:
        if line in units_by_line or line in BOILERPLATE_LINES:
            continue
        f.add(
            "unsupported_claim",
            "critical" if claims_on_line.get(line) else "high",
            "承認済みDecision（回答・承認済み約束）に含まれない文が返信にあります。Decisionへ反映して再生成してください。",
            actual=claims_on_line.get(line, []),
            evidence=evidence_by_line.get(line, []),
        )


def _check_claim(f: _Findings, row: tuple[str, str, dict[str, Any], str], scope: _Scope, used_values: set[str], source_text: str) -> None:
    """2-3. One extracted claim: typed tokens and keyword classes, scoped to the units on its line."""
    array, _line, claim, evidence_id = row
    refs: dict[str, Any] = {"actual": [claim["id"]], "evidence": [evidence_id]}
    if array == "monetary_terms":
        _check_money(f, claim, scope, evidence_id, used_values)
    elif array == "dates":
        _check_date(f, claim, scope, evidence_id, used_values)
    elif array == "quantities":
        _check_quantity(f, claim, scope, evidence_id)
    elif array in _CLASS_FINDING:
        if not any(array in unit.classes for unit in scope.on_line):
            f.add(
                _CLASS_FINDING[array], "critical", f"型付きで承認されていない「{_CLASS_LABEL_JA[array]}」が返信に含まれています。", **refs
            )
    elif array == "personal_data":
        address = str(claim["text"]["value"])
        if not (address in source_text or any(address in email for unit in scope.on_line for email in unit.emails)):
            f.add(
                "unsupported_claim",
                "critical",
                "原文にも承認済み個人情報にもないメールアドレスが返信に含まれています（個人情報開示の可能性）。",
                **refs,
            )
    elif array in _ALWAYS_BLOCKED:
        ftype, message = _ALWAYS_BLOCKED[array]
        f.add(ftype, "critical", message, **refs)
    elif array == "risks":
        if claim["description"]["value"] == "reply_link":
            # Human decision 2026-09-18: a link is critical wherever it appears, including
            # inside an approved answer line. A link cannot be compared as a typed value, and
            # the recipient cannot tell an approved destination from a substituted one.
            f.add("unsupported_claim", "critical", "返信にリンクが含まれています。リンクは承認済み回答の中でも送信できません。", **refs)
        else:
            f.add("unsupported_claim", "critical", "型付き検証できない数値（または数を表す語）が返信に含まれています。", **refs)


def _check_omissions(f: _Findings, units: list[Unit], reply_line_set: set[str], used_values: set[str]) -> None:
    """4. Every approved unit is present, including its typed values and condition."""
    for unit in units:
        missing = [line for line in unit.lines if line not in reply_line_set]
        if unit.kind == "commitment":
            _check_commitment_present(f, unit, missing, used_values)
        elif missing:
            if unit.required_question:
                f.add(
                    "required_answer_missing",
                    "high",
                    "必要質問への承認済み回答が返信から欠落または改変されています。",
                    expected=[unit.source_id],
                )
            else:
                f.add("state_mismatch", "high", "承認済み回答が返信から欠落または改変されています。", expected=[unit.source_id])


def _check_commitment_present(f: _Findings, unit: Unit, missing: list[str], used_values: set[str]) -> None:
    if any(line.startswith("- Condition:") for line in missing):
        f.add("condition_removed", "critical", "承認済みの約束の条件が返信から欠落しています。", expected=[unit.source_id])
    if [line for line in missing if not line.startswith("- Condition:")]:
        f.add(
            "state_mismatch",
            "critical",
            "承認済みの約束（内容・金額・期限のいずれか）が返信から欠落または改変されています。",
            expected=[unit.source_id],
        )
    absent_values = [m.claim_id for m in unit.money if m.claim_id not in used_values]
    absent_values += [d.claim_id for d in unit.dates if d.claim_id not in used_values]
    if absent_values:
        f.add(
            "state_mismatch",
            "critical",
            "承認済みの約束に紐づく金額・期限が返信に記載されていません。",
            expected=[unit.source_id, *absent_values],
        )


def _check_answer_coverage(f: _Findings, ctx: DomainContext) -> None:
    """5. Every required question is answered or explicitly unanswered, at Decision level."""
    answered = {a["question_id"] for a in ctx.decision["question_answers"]}
    unanswered = set(ctx.decision["explicitly_unanswered"])
    for record in ctx.claims.values():
        if record.kind == "Question" and record.body["required_answer"] and record.claim_id not in answered | unanswered:
            f.add("required_answer_missing", "high", "必要質問に承認済み回答も明示的な未回答指定もありません。", expected=[record.claim_id])
