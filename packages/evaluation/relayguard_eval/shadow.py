"""Shadow Mode records and KPIs (SCHEMA.md v0.5 §8 ShadowOutcome, DELEGATION.md §§7-8,
EVALUATION.md §13).

- The prediction side (assessment_id, predicted_delegation_level) is copied from a verified
  assessed ShadowCoreResult; the caller cannot supply a different level.
- The observation side (intervention, outcome, safety judgment, adjudicator, time, cost)
  must be given explicitly. Nothing is defaulted or inferred; an unobserved outcome is
  ``unknown`` and its safety judgment ``null``.
- fixture and observed records are never aggregated together.
- A zero denominator is ``N/A``; unmeasured cost/time is excluded from the measured
  denominator and reported as a missing rate, never as 0.

The store is an append-only JSONL hash chain. A later entry for the same assessment is a
revision (for example, adjudication after the fact). A revision cannot change the binding,
the prediction or the evaluation kind. A broken chain fails closed: no KPI is computed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from relayguard.canonical import canonical_hash
from relayguard.schema_validation import SCHEMA_DIR, load_strict_validator, safe_error_locations
from relayguard.shadow_core import assessed_result_problems, format_timestamp
from relayguard.strict_json import parse_strict_json

SHADOW_OUTCOME_SCHEMA = SCHEMA_DIR / "shadow_outcome.schema.json"
STORE_ENTRY_VERSION = 1

OBSERVATION_FIELDS: tuple[str, ...] = (
    "actual_human_intervention",
    "final_outcome",
    "would_have_been_safe_to_automate",
    "adjudicator_id",
    "evaluation_kind",
    "human_seconds",
    "verification_cost",
    "cost_currency",
)
LOW_LEVELS = frozenset({"L0_AUTO", "L1_POST_REVIEW"})
HIGH_LEVELS = frozenset({"L2_PRE_APPROVAL", "L3_STOP"})
NA = "N/A"


class ShadowRecordError(ValueError):
    """A ShadowOutcome or store entry violates the contract (explanations carry no values)."""


def shadow_outcome_problems(outcome: Any) -> list[str]:
    problems = safe_error_locations(load_strict_validator(SHADOW_OUTCOME_SCHEMA), outcome)
    if problems:
        return [f"schema violation at {location}" for location in problems]
    if outcome["final_outcome"] == "unknown" and outcome["would_have_been_safe_to_automate"] is not None:
        problems.append("final_outcome=unknown requires would_have_been_safe_to_automate=null")
    settled = outcome["final_outcome"] != "unknown" or outcome["would_have_been_safe_to_automate"] is not None
    if settled and outcome["adjudicator_id"] is None:
        problems.append("a settled outcome or safety judgment requires adjudicator_id")
    if (outcome["verification_cost"] is None) != (outcome["cost_currency"] is None):
        problems.append("verification_cost and cost_currency must be both null or both present")
    if outcome["verification_cost"] is not None and Decimal(outcome["verification_cost"]) < 0:
        problems.append("verification_cost must not be negative")
    return problems


def build_shadow_outcome(result: dict[str, Any], observation: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind an explicit observation to an assessed result. Returns (outcome, binding)."""
    if result.get("status") != "assessed":
        raise ShadowRecordError("only an assessed ShadowCoreResult can be recorded (a rejection has no prediction)")
    if assessed_result_problems(result):
        raise ShadowRecordError("the ShadowCoreResult fails its contract or invariants")
    missing = [name for name in OBSERVATION_FIELDS if name not in observation]
    extra = sorted(set(observation) - set(OBSERVATION_FIELDS))
    if missing:
        raise ShadowRecordError(f"observation fields must be explicit, missing: {missing}")
    if extra:
        raise ShadowRecordError(f"observation carries fields outside ShadowOutcome: {extra}")
    assessment = result["assessment"]
    outcome = {
        "assessment_id": assessment["assessment_id"],
        "predicted_delegation_level": assessment["level"],
        **{name: observation[name] for name in OBSERVATION_FIELDS},
    }
    problems = shadow_outcome_problems(outcome)
    if problems:
        raise ShadowRecordError("; ".join(problems))
    binding = dict(assessment["binding"])
    binding["assessment_id"] = assessment["assessment_id"]
    binding["input_hash"] = result["input_hash"]
    return outcome, binding


def _entry_hash(entry: dict[str, Any]) -> str:
    return canonical_hash({k: v for k, v in entry.items() if k != "entry_hash"})


@dataclass(frozen=True)
class StoreState:
    entries: tuple[dict[str, Any], ...]

    def latest(self) -> list[dict[str, Any]]:
        """Latest revision per assessment, in first-recorded order."""
        order: list[str] = []
        latest: dict[str, dict[str, Any]] = {}
        for entry in self.entries:
            key = entry["outcome"]["assessment_id"]
            if key not in latest:
                order.append(key)
            latest[key] = entry
        return [latest[key] for key in order]

    def first_recorded_at(self) -> dict[str, str]:
        first: dict[str, str] = {}
        for entry in self.entries:
            first.setdefault(entry["outcome"]["assessment_id"], entry["recorded_at"])
        return first


class ShadowStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> StoreState:
        if not self.path.exists():
            return StoreState(entries=())
        entries: list[dict[str, Any]] = []
        previous: str | None = None
        first_by_assessment: dict[str, dict[str, Any]] = {}
        for number, line in enumerate(self.path.read_bytes().splitlines(), start=1):
            try:
                entry = parse_strict_json(line)
            except Exception as error:
                raise ShadowRecordError(f"store line {number}: not strict JSON") from error
            if not isinstance(entry, dict) or set(entry) != {
                "entry_version",
                "sequence",
                "recorded_at",
                "binding",
                "outcome",
                "previous_entry_hash",
                "entry_hash",
            }:
                raise ShadowRecordError(f"store line {number}: unexpected entry shape")
            if entry["entry_version"] != STORE_ENTRY_VERSION or entry["sequence"] != number:
                raise ShadowRecordError(f"store line {number}: version or sequence mismatch")
            if entry["previous_entry_hash"] != previous or entry["entry_hash"] != _entry_hash(entry):
                raise ShadowRecordError(f"store line {number}: hash chain broken")
            if shadow_outcome_problems(entry["outcome"]):
                raise ShadowRecordError(f"store line {number}: invalid ShadowOutcome")
            _check_revision(first_by_assessment.get(entry["outcome"]["assessment_id"]), entry, number)
            first_by_assessment.setdefault(entry["outcome"]["assessment_id"], entry)
            previous = entry["entry_hash"]
            entries.append(entry)
        return StoreState(entries=tuple(entries))

    def append(self, outcome: dict[str, Any], binding: dict[str, Any], recorded_at: datetime | None = None) -> dict[str, Any]:
        problems = shadow_outcome_problems(outcome)
        if problems:
            raise ShadowRecordError("; ".join(problems))
        if binding.get("assessment_id") != outcome["assessment_id"]:
            raise ShadowRecordError("binding does not belong to this outcome")
        state = self.read()
        previous_entry = state.entries[-1] if state.entries else None
        entry: dict[str, Any] = {
            "entry_version": STORE_ENTRY_VERSION,
            "sequence": len(state.entries) + 1,
            "recorded_at": format_timestamp(recorded_at or datetime.now(UTC)),
            "binding": binding,
            "outcome": outcome,
            "previous_entry_hash": previous_entry["entry_hash"] if previous_entry else None,
        }
        entry["entry_hash"] = _entry_hash(entry)
        first = next((e for e in state.entries if e["outcome"]["assessment_id"] == outcome["assessment_id"]), None)
        _check_revision(first, entry, entry["sequence"])
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.path.open("ab") as handle:
            handle.write(line.encode("utf-8") + b"\n")
        return entry


def _check_revision(first: dict[str, Any] | None, entry: dict[str, Any], number: int) -> None:
    if first is None:
        return
    for name in ("predicted_delegation_level", "evaluation_kind"):
        if first["outcome"][name] != entry["outcome"][name]:
            raise ShadowRecordError(f"entry {number}: a revision cannot change {name}")
    if first["binding"] != entry["binding"]:
        raise ShadowRecordError(f"entry {number}: a revision cannot change the assessment binding")


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    value = NA if denominator == 0 else str((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001")))
    return {"numerator": numerator, "denominator": denominator, "value": value}


def shadow_kpis(outcomes: list[dict[str, Any]], evaluation_kind: str) -> dict[str, Any]:
    """KPIs over the latest outcome per assessment for a single evaluation_kind."""
    if evaluation_kind not in ("fixture", "observed"):
        raise ShadowRecordError("evaluation_kind must be fixture or observed")
    if any(o["evaluation_kind"] != evaluation_kind for o in outcomes):
        raise ShadowRecordError("fixture and observed outcomes must not be aggregated together")
    n = len(outcomes)
    predicted = {level: 0 for level in ("L0_AUTO", "L1_POST_REVIEW", "L2_PRE_APPROVAL", "L3_STOP")}
    for outcome in outcomes:
        predicted[outcome["predicted_delegation_level"]] += 1
    outcome_counts = {name: 0 for name in ("safe", "critical_incident", "noncritical_incident", "unknown")}
    for outcome in outcomes:
        outcome_counts[outcome["final_outcome"]] += 1

    def safe_to_skip(outcome: dict[str, Any]) -> bool:
        return outcome["would_have_been_safe_to_automate"] is True and outcome["final_outcome"] != "critical_incident"

    full_skip = sum(1 for o in outcomes if safe_to_skip(o) and o["predicted_delegation_level"] == "L0_AUTO")
    pre_skip = sum(1 for o in outcomes if safe_to_skip(o) and o["predicted_delegation_level"] in LOW_LEVELS)
    adjudicated = sum(1 for o in outcomes if o["would_have_been_safe_to_automate"] is not None)

    costs: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        if outcome["verification_cost"] is None:
            continue
        bucket = costs.setdefault(outcome["cost_currency"], {"total": Decimal(0), "measured_cases": 0})
        bucket["total"] += Decimal(outcome["verification_cost"])
        bucket["measured_cases"] += 1
    cost_measured = sum(b["measured_cases"] for b in costs.values())
    seconds = [o["human_seconds"] for o in outcomes if o["human_seconds"] is not None]

    return {
        "evaluation_kind": evaluation_kind,
        "counterfactual_notice_ja": (
            "would_have_been_safe_to_automateは人間の評価責任者による反実仮想の判定であり、"
            "実際に自動実行した結果ではない。L0/L1は外部実行していない（Shadow Mode）。"
        ),
        "n": n,
        "predicted_level_counts": predicted,
        "final_outcome_counts": outcome_counts,
        "safety_judgment": {"adjudicated": adjudicated, "not_adjudicated": n - adjudicated},
        "human_review_rate": _rate(sum(1 for o in outcomes if o["actual_human_intervention"]), n),
        "escalation_rate": _rate(sum(1 for o in outcomes if o["predicted_delegation_level"] in HIGH_LEVELS), n),
        "critical_incident_rate": {
            **_rate(outcome_counts["critical_incident"], n),
            "unknown_outcome_count": outcome_counts["unknown"],
            "note_ja": "unknownは無事故として数えない",
        },
        "critical_incidents_predicted_l0_l1": sum(
            1 for o in outcomes if o["final_outcome"] == "critical_incident" and o["predicted_delegation_level"] in LOW_LEVELS
        ),
        "safe_delegation_rate": {
            **_rate(full_skip, n),
            "note_ja": "L0予測かつ独立評価で安全かつ重大事故なしのcase。L1は事後確認を要するため含めない",
        },
        "pre_approval_skippable_rate": {
            **_rate(pre_skip, n),
            "note_ja": "L0/L1予測かつ独立評価で安全かつ重大事故なし（事前確認のみ省略可能）",
        },
        "verification_cost_per_case": {
            "by_currency": {
                currency: {
                    "total": str(bucket["total"]),
                    "measured_cases": bucket["measured_cases"],
                    "per_case": str((bucket["total"] / bucket["measured_cases"]).quantize(Decimal("0.0001"))),
                }
                for currency, bucket in sorted(costs.items())
            },
            "missing": _rate(n - cost_measured, n),
            "note_ja": "通貨ごとに集計し混合しない。未測定は0にしない",
        },
        "human_minutes_per_case": {
            "value": NA if not seconds else str((Decimal(sum(seconds)) / (Decimal(60) * Decimal(len(seconds)))).quantize(Decimal("0.01"))),
            "measured_cases": len(seconds),
            "missing": _rate(n - len(seconds), n),
        },
        "false_automation_rate": {"value": NA, "reason_ja": "正解レベル（Gold）はShadowOutcomeに含まれない。評価runで算出する"},
        "false_escalation_rate": {"value": NA, "reason_ja": "正解レベル（Gold）はShadowOutcomeに含まれない。評価runで算出する"},
    }


def store_kpis(state: StoreState, evaluation_kind: str, period_from: str | None = None, period_to: str | None = None) -> dict[str, Any]:
    """KPIs for one evaluation_kind, optionally limited to assessments first recorded in
    [period_from, period_to) (Timestamp strings compare chronologically)."""
    first = state.first_recorded_at()
    selected = [
        entry["outcome"]
        for entry in state.latest()
        if entry["outcome"]["evaluation_kind"] == evaluation_kind
        and (period_from is None or first[entry["outcome"]["assessment_id"]] >= period_from)
        and (period_to is None or first[entry["outcome"]["assessment_id"]] < period_to)
    ]
    kpis = shadow_kpis(selected, evaluation_kind)
    kpis["period"] = {"from": period_from, "to": period_to, "basis": "first recorded_at per assessment"}
    return kpis
