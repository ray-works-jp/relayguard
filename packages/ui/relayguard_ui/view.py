"""Read-only view models for templates. No state changes, no authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from relayguard.claims import iter_claims
from relayguard.diff_engine import build_units
from relayguard.generator import BOILERPLATE_LINES

from .labels import (
    ARRAY_LABELS,
    DATE_TYPE_LABELS,
    FIELD_LABELS,
    FINDING_LABELS,
    LEVEL_NEXT_ACTIONS,
    MONEY_TYPE_LABELS,
    NEXT_ACTIONS,
    NO_REQUEST_NOTE,
    REASON_LABELS,
    SEVERITY_LABELS,
    STATE_NEXT_ACTIONS,
    STOP_AFTER_EDIT,
    STOP_AFTER_GENERATE,
    STOP_NEUTRAL,
    VALUE_STATUS_LABELS,
)
from .service import CaseRecord

_SUMMARY_FIELDS = (
    "text", "action", "object", "amount", "currency", "date", "timezone", "quantity", "unit", "scope",
    "exclusivity", "sublicensing", "commercial_use", "modality", "condition", "claim_type", "description", "target",
)  # fmt: skip


@dataclass(frozen=True)
class ClaimRow:
    claim_id: str
    array: str
    array_label: str
    kind: str
    headline: str  # one readable Japanese line; the typed fields stay behind a toggle
    fields: list[tuple[str, str, bool]]  # (label, display, uncertain)
    extra: list[tuple[str, str]]
    quotes: list[str]
    decision: str
    uncertain: bool


def _display(value: Any) -> tuple[str, bool]:
    if isinstance(value, dict) and "status" in value:
        if value["status"] == "explicit":
            return str(value["value"]), False
        label = VALUE_STATUS_LABELS[value["status"]]
        return f"［{label}］ {value.get('raw_text') or ''}".strip(), value["status"] in ("unknown", "ambiguous")
    return str(value), False


HEADLINE_MAX = 100
_HEADLINE_FIELDS = ("text", "action", "description", "claim_type", "target", "scope")


def _value_or_mark(body: dict[str, Any], name: str) -> str:
    """The value if the mail states it, otherwise the Japanese mark for why it does not."""
    value = body.get(name)
    if not isinstance(value, dict):
        return str(value) if value is not None else ""
    if value["status"] == "explicit":
        return str(value["value"])
    return f"［{VALUE_STATUS_LABELS[value['status']]}］"


def _shorten(text: str) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= HEADLINE_MAX else clean[: HEADLINE_MAX - 1] + "…"


def _headline(kind: str, body: dict[str, Any]) -> str:
    """One line a person can act on, without reading the typed fields underneath."""
    if kind == "MonetaryTerm":
        money = f"{_value_or_mark(body, 'amount')} {_value_or_mark(body, 'currency')}".strip()
        kind_ja = MONEY_TYPE_LABELS.get(str(body.get("type", "")), "")
        return _shorten(f"{money}（{kind_ja}）" if kind_ja else money)
    if kind == "DateTerm":
        when = f"{_value_or_mark(body, 'date')} {_value_or_mark(body, 'timezone')}".strip()
        kind_ja = DATE_TYPE_LABELS.get(str(body.get("type", "")), "")
        return _shorten(f"{when}（{kind_ja}）" if kind_ja else when)
    if kind == "QuantityTerm":
        return _shorten(f"{_value_or_mark(body, 'quantity')} {_value_or_mark(body, 'unit')}".strip())
    for name in _HEADLINE_FIELDS:
        if name in body:
            shown = _value_or_mark(body, name)
            if shown:
                return _shorten(shown)
    return ""


def claim_rows(record: CaseRecord) -> list[ClaimRow]:
    state = record.interpretation["state"]
    quotes_by_id = {ev["evidence_id"]: ev["quote"] for ev in state["evidence"]}
    decisions: dict[str, str] = {}
    if record.decision is not None:
        decisions = {item["source_claim_id"]: item["decision"] for item in record.decision["items"]}
    rows: list[ClaimRow] = []
    for claim in iter_claims(state):
        body = claim.body
        fields: list[tuple[str, str, bool]] = []
        uncertain = False
        for name in _SUMMARY_FIELDS:
            if name in body:
                shown, flag = _display(body[name])
                fields.append((FIELD_LABELS.get(name, name), shown, flag))
                uncertain = uncertain or flag
        extra: list[tuple[str, str]] = []
        for name in ("type", "actor", "intensity", "required_answer", "affects_critical", "resolved", "authorization_state"):
            if name in body:
                extra.append((FIELD_LABELS.get(name, name), str(body[name])))
        rows.append(
            ClaimRow(
                claim_id=claim.claim_id,
                array=claim.array,
                array_label=ARRAY_LABELS.get(claim.array, claim.array),
                kind=claim.kind,
                headline=_headline(claim.kind, body),
                fields=fields,
                extra=extra,
                quotes=[quotes_by_id[e] for e in body["evidence_ids"] if e in quotes_by_id],
                decision=decisions.get(claim.claim_id, "unknown"),
                uncertain=uncertain,
            )
        )
    return rows


def answers_by_question(record: CaseRecord) -> dict[str, dict[str, Any]]:
    if record.decision is None:
        return {}
    return {a["question_id"]: a for a in record.decision["question_answers"]}


@dataclass(frozen=True)
class FindingRow:
    label: str
    severity: str
    severity_key: str
    blocking: bool
    explanation: str
    next_action: str
    quotes: list[str]
    claim_ids: list[str]


def finding_rows(record: CaseRecord) -> list[FindingRow]:
    if record.verification is None:
        return []
    quotes: dict[str, str] = {}
    if record.extraction is not None:
        quotes = {ev["evidence_id"]: ev["quote"] for ev in record.extraction["state"]["evidence"]}
    rows = []
    for finding in record.verification["proposal"]["findings"]:
        rows.append(
            FindingRow(
                label=FINDING_LABELS.get(finding["type"], finding["type"]),
                severity=SEVERITY_LABELS.get(finding["severity"], finding["severity"]),
                severity_key=finding["severity"],
                blocking=finding["blocking"],
                explanation=finding["explanation_ja"],
                next_action=NEXT_ACTIONS.get(finding["type"], ""),
                quotes=sorted({quotes[e] for e in finding["evidence_ids"] if e in quotes}),
                # Which claim the finding is about: three identical "answer missing" lines are
                # unreadable without it (seen for real on a newsletter with three questions).
                claim_ids=sorted(set(finding["expected_claim_ids"]) | set(finding["actual_claim_ids"])),
            )
        )
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(rows, key=lambda r: order.get(r.severity_key, 9))


def reason_labels(codes: list[str]) -> list[tuple[str, str]]:
    return [(code, REASON_LABELS.get(code, code)) for code in codes]


_REQUEST_ARRAYS = ("questions", "requests", "requested_commitments", "monetary_terms", "dates", "quantities")


def nothing_is_requested(record: CaseRecord) -> bool:
    """True when the mail asks for nothing: no question, request, commitment, amount, date or quantity.

    Display only - it never blocks and never decides. Notifications and marketing mail land here,
    and the operator decides whether the mail needs a reply at all.
    """
    state = record.interpretation["state"]
    return not any(state.get(array) for array in _REQUEST_ARRAYS)


def no_request_note(record: CaseRecord) -> str:
    return NO_REQUEST_NOTE if nothing_is_requested(record) else ""


def next_steps(record: CaseRecord) -> list[str]:
    """The ordered "what to do now" lines shown above the findings."""
    steps: list[str] = []
    assessment = record.post_assessment or record.pre_assessment
    if assessment is not None and assessment["level"] == "L3_STOP":
        steps.append(LEVEL_NEXT_ACTIONS["L3_STOP"])
    for row in finding_rows(record):
        if row.blocking and row.next_action and row.next_action not in steps:
            steps.append(row.next_action)
    if not steps and str(record.state) in STATE_NEXT_ACTIONS:
        steps.append(STATE_NEXT_ACTIONS[str(record.state)])
    elif not steps and record.verification is not None and record.verification["policy_status"] == "SAFE_CANDIDATE":
        level = (record.post_assessment or {}).get("level", "L2_PRE_APPROVAL")
        steps.append(LEVEL_NEXT_ACTIONS.get(str(level), LEVEL_NEXT_ACTIONS["L2_PRE_APPROVAL"]))
    return steps


def reply_origin_event(record: CaseRecord) -> str:
    """ "edited" or "generated" for the reply on screen, or "" when that cannot be told.

    Read from the audit chain: only a latest draft event naming the current draft_id AND draft_hash
    counts; anything else is shown with neutral wording. Display only - never a stop cause.
    """
    if record.draft is None:
        return ""
    for event in reversed(record.audit):
        if event["event_type"] in ("draft.generated", "draft.edited"):
            if event["entity_id"] == record.draft["draft_id"] and event["entity_hash"] == record.draft["draft_hash"]:
                return "edited" if event["event_type"] == "draft.edited" else "generated"
            return ""
    return ""


def reply_edited(record: CaseRecord) -> bool:
    return reply_origin_event(record) == "edited"


def stop_guidance(record: CaseRecord) -> str:
    """What to look at after a failed check; the findings and their actions stay the authority."""
    origin = reply_origin_event(record)
    return STOP_AFTER_EDIT if origin == "edited" else STOP_AFTER_GENERATE if origin == "generated" else STOP_NEUTRAL


STEP_LABELS = ("メールを取り込む", "あなたが判断する", "返信案を作って検査", "最終承認してコピー")


@dataclass(frozen=True)
class Progress:
    """Where the case stands in the four steps, and the one thing to do now. Display only."""

    statuses: list[tuple[str, str]]  # (label, "done" | "current" | "todo" | "stopped")
    hint: str


def progress(record: CaseRecord) -> Progress:
    """Map the case state onto the operator's four steps. Reads the state; never changes or decides it."""
    state = str(record.state)
    if state == "STOPPED":
        at, mark, hint = 2, "stopped", LEVEL_NEXT_ACTIONS["L3_STOP"]
    elif state == "BLOCKED":
        at, mark, hint = 2, "stopped", stop_guidance(record)
    elif state == "DELEGATION_ASSESSED":
        at, mark, hint = 2, "current", "「英語の返信案を作って検査する」を押してください。"
    elif state == "SAFE_CANDIDATE":
        # Same wording as next_steps, which this replaces on a pass (the panel is hidden then).
        level = str((record.post_assessment or {}).get("level", "L2_PRE_APPROVAL"))
        at, mark, hint = 3, "current", LEVEL_NEXT_ACTIONS.get(level, LEVEL_NEXT_ACTIONS["L2_PRE_APPROVAL"])
    elif state == "FINAL_APPROVED":
        at, mark, hint = 3, "current", STATE_NEXT_ACTIONS["FINAL_APPROVED"]
    elif state == "COPIED":
        at, mark, hint = 4, "done", STATE_NEXT_ACTIONS["COPIED"]
    elif record.origin != "user":
        at, mark, hint = 1, "current", "合成データのため判断は変更できません。"
    else:
        at, mark, hint = (
            1,
            "current",
            ("表の項目ごとに「承認する／保留／回答しない」を選び、質問には英語の回答を書いて「この判断で確定する」を押してください。"),
        )
    statuses = [(label, "done" if i < at else mark if i == at else "todo") for i, label in enumerate(STEP_LABELS)]
    return Progress(statuses=statuses, hint=hint)


ORIGIN_LABELS: dict[str, str] = {
    "boilerplate": "定型",
    "answer": "あなたの文",
    "commitment": "承認済み",
    "unknown": "由来なし",
}

# The operator's own words for what this panel shows (human decision, 2026-09-19).
ORIGIN_INTRO = (
    "各行の左の印は、その行を誰が書いたかを示します。「あなたの文」はあなたが入力した英文そのままで、それ以外は機械が組み立てた行です。"
)

ORIGIN_LEGEND: dict[str, str] = {
    "boilerplate": "機械の決まり文句。値も約束も含まず、案件によって変わりません。",
    "answer": "あなたが書いた英文がそのまま入っています。",
    "commitment": "中身はあなたが承認した内容で、文面は機械が組み立てています。",
    "unknown": "あなたが承認したどの内容にも対応しません。この行があると検査で停止します。",
}


@dataclass(frozen=True)
class ReplyLine:
    """One line of the reply draft with who it came from.

    Display only. The classification is the same one the closed-world check in diff_engine uses
    (an approved unit's line, or generator boilerplate); it decides nothing and blocks nothing.
    """

    text: str
    origin: str  # "boilerplate" | "answer" | "commitment" | "unknown" | "blank"
    label: str
    source_id: str


def reply_origin_lines(record: CaseRecord) -> list[ReplyLine]:
    """Every line of the draft, marked with where it came from."""
    if record.draft is None or record.ctx is None:
        return []
    units_by_line: dict[str, tuple[str, str]] = {}
    for unit in build_units(record.ctx):
        for line in unit.lines:
            units_by_line.setdefault(line, (unit.kind, unit.source_id))
    lines: list[ReplyLine] = []
    for raw in str(record.draft["reply_text"]).splitlines():
        text = raw.strip()
        if not text:
            lines.append(ReplyLine("", "blank", "", ""))
            continue
        # Same order as the closed-world check: an approved unit first, then boilerplate.
        if text in units_by_line:
            kind, source_id = units_by_line[text]
            origin = kind if kind in ORIGIN_LABELS else "unknown"
            lines.append(ReplyLine(text, origin, ORIGIN_LABELS[origin], source_id))
        elif text in BOILERPLATE_LINES:
            lines.append(ReplyLine(text, "boilerplate", ORIGIN_LABELS["boilerplate"], ""))
        else:
            lines.append(ReplyLine(text, "unknown", ORIGIN_LABELS["unknown"], ""))
    return lines


def reply_origin_summary(record: CaseRecord) -> list[tuple[str, str, int]]:
    """(origin, label, count) for the lines that carry text, in a fixed order."""
    counts: dict[str, int] = {}
    for line in reply_origin_lines(record):
        if line.origin != "blank":
            counts[line.origin] = counts.get(line.origin, 0) + 1
    return [(origin, ORIGIN_LABELS[origin], counts[origin]) for origin in ORIGIN_LABELS if origin in counts]
