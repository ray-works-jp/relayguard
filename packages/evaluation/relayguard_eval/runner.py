"""Evaluation Runner: runs every case of a suite through the Shadow Core and compares the
pre-generation stage with the case labels.

Reproducible by construction: the runtime clock and IDs are fixed per case, so the same
code, policy and inputs give byte-identical reports. Each case also runs a second time with
a different clock and ID seed; a difference in level / minimum / reasons / risk factors is a
determinism failure (REQUIREMENTS.md SG-001 AC-3), while differing IDs and times are not.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from relayguard import SCHEMA_VERSION
from relayguard.currency import SUPPORTED_CURRENCY_SET_VERSION
from relayguard.delegation import POLICY_VERSION
from relayguard.shadow_core import ShadowCoreRuntime, run_shadow_core
from relayguard.strict_json import parse_strict_json

from .cases import EvalCase, Suite

# Restrictiveness used to tell under-classification from over-classification. A rejection
# is never automatable, so it ranks above L3.
OUTCOME_RANK: dict[str, int] = {"L0_AUTO": 0, "L1_POST_REVIEW": 1, "L2_PRE_APPROVAL": 2, "L3_STOP": 3, "rejected": 4}

NOT_RUN = "NOT_RUN"
MATCH = "MATCH"
MISMATCH = "MISMATCH"

POST_STAGE_NOT_RUN_REASON = "Generator / Reply Extractor / Verifier / Final Approvalは未実装（SHADOW_GATE後の範囲）"

_PRIMARY_CLOCK = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
_SECONDARY_CLOCK = datetime(2027, 6, 30, 12, 34, 56, tzinfo=UTC)

# Keys whose string values are free text taken from mail, interpretation or the user. They
# must never reach operational telemetry (IMPLEMENTATION.md §15, EVALUATION.md §8).
_SENSITIVE_KEYS = frozenset({"subject", "body", "quote", "raw_text", "value", "answer_text", "human_notes", "reason_ja"})
_MIN_PROBE_LENGTH = 6


def outcome_key(status: str, level: str | None) -> str:
    return "rejected" if status == "rejected" else str(level)


def pipeline_versions() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "currency_set_version": SUPPORTED_CURRENCY_SET_VERSION,
        # No LLM runs before SHADOW_GATE: the Interpretation and Decision are fixture-supplied.
        "prompt_version": None,
        "model": "fixture",
        "provider": None,
    }


def _runtime(seed: str, clock: datetime) -> ShadowCoreRuntime:
    counter = itertools.count(1)
    return ShadowCoreRuntime(clock=lambda: clock, new_id=lambda prefix: f"{prefix}_{seed}_{next(counter)}")


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def capture_relayguard_logs() -> Generator[_Capture]:
    logger = logging.getLogger("relayguard")
    handler = _Capture()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _sensitive_strings(raw: bytes) -> list[str]:
    """Free-text probes from the input. For unparseable input every line is a probe."""
    try:
        document = parse_strict_json(raw)
    except Exception:  # noqa: BLE001 - broken inputs are probed as plain text
        text = raw.decode("utf-8", errors="replace")
        return [line.strip() for line in text.splitlines() if len(line.strip()) >= _MIN_PROBE_LENGTH]
    probes: list[str] = []

    def walk(value: Any, key: str | None) -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and key in _SENSITIVE_KEYS:
            candidates = [value, *value.splitlines()]
            probes.extend(c.strip() for c in candidates if len(c.strip()) >= _MIN_PROBE_LENGTH)

    walk(document, None)
    return sorted(set(probes))


def log_leaks(messages: list[str], raw: bytes) -> bool:
    """True when free text from the input appears in operational log messages. A probe must
    stand alone: an occurrence inside an ID-like token (for example a case ID containing the
    word "refund") is not a leak of mail content."""
    log_text = "\n".join(messages)
    return any(
        re.search(rf"(?<![A-Za-z0-9_-]){re.escape(probe)}(?![A-Za-z0-9_-])", log_text) is not None for probe in _sensitive_strings(raw)
    )


def _decision_view(result: dict[str, Any]) -> dict[str, Any]:
    if result["status"] != "assessed":
        return {"status": result["status"], "error_code": result["failure"]["code"]}
    assessment = result["assessment"]
    return {
        "status": "assessed",
        "level": assessment["level"],
        "minimum_level": assessment["minimum_level"],
        "reason_codes": assessment["reason_codes"],
        "risk_factors": assessment["risk_factors"],
        "human_review_required": assessment["human_review_required"],
    }


@dataclass
class CaseResult:
    case: EvalCase
    actual: dict[str, Any]
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    deterministic: bool = True
    pii_log_leak: bool = False
    external_action_performed: bool = False
    assessment_id: str | None = None
    input_hash: str | None = None
    # Full ShadowCoreResult of the primary run (not serialized into the report).
    shadow_result: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def pre_stage(self) -> str:
        return MATCH if not self.mismatches else MISMATCH

    @property
    def expected_key(self) -> str:
        return outcome_key(self.case.expected.outcome, self.case.expected.level)

    @property
    def actual_key(self) -> str:
        return outcome_key(self.actual["status"], self.actual.get("level"))

    @property
    def under_classified(self) -> bool:
        return OUTCOME_RANK[self.actual_key] < OUTCOME_RANK[self.expected_key]

    def to_json(self) -> dict[str, Any]:
        case = self.case
        return {
            "case_id": case.case_id,
            "suite": case.suite,
            "category": case.category,
            "variant": case.variant,
            "threats": list(case.threats),
            "release_class": case.release_class,
            "label_status": case.label_status,
            "in_metrics": case.in_metrics,
            "input_sha256": case.input_sha256,
            "case_file_sha256": case.case_file_sha256,
            "expected": {
                "outcome": case.expected.outcome,
                "level": case.expected.level,
                "minimum_level": case.expected.minimum_level,
                "reason_codes": list(case.expected.reason_codes) if case.expected.reason_codes is not None else None,
                "error_code": case.expected.error_code,
                "risk_factors": case.expected.risk_factors,
            },
            "actual": self.actual,
            "assessment_id": self.assessment_id,
            "input_hash": self.input_hash,
            "stages": {
                "pre_generation": self.pre_stage,
                "post_verification": NOT_RUN,
                "final_delegation": NOT_RUN,
            },
            "post_labels_present": case.has_post_labels,
            "mismatches": self.mismatches,
            "under_classified": self.under_classified,
            "deterministic": self.deterministic,
            "pii_log_leak": self.pii_log_leak,
            "external_action_performed": self.external_action_performed,
        }


def _compare(case: EvalCase, actual: dict[str, Any]) -> list[dict[str, Any]]:
    expected = case.expected
    mismatches: list[dict[str, Any]] = []

    def add(field_name: str, want: Any, got: Any) -> None:
        mismatches.append({"stage": "pre_generation", "field": field_name, "expected": want, "actual": got})

    if actual["status"] != expected.outcome:
        add("status", expected.outcome, actual["status"])
        return mismatches
    if expected.outcome == "rejected":
        if expected.error_code is not None and actual["error_code"] != expected.error_code:
            add("error_code", expected.error_code, actual["error_code"])
        return mismatches
    if actual["level"] != expected.level:
        add("level", expected.level, actual["level"])
    if actual["minimum_level"] != expected.minimum_level:
        add("minimum_level", expected.minimum_level, actual["minimum_level"])
    if expected.reason_codes is not None and tuple(sorted(actual["reason_codes"])) != expected.reason_codes:
        add("reason_codes", list(expected.reason_codes), actual["reason_codes"])
    if expected.risk_factors is not None and actual["risk_factors"] != expected.risk_factors:
        add("risk_factors", expected.risk_factors, actual["risk_factors"])
    return mismatches


def run_case(case: EvalCase) -> CaseResult:
    raw = case.input_path.read_bytes()
    with capture_relayguard_logs() as capture:
        first = run_shadow_core(raw, _runtime(f"{case.case_id}_a", _PRIMARY_CLOCK))
        second = run_shadow_core(raw, _runtime(f"{case.case_id}_b", _SECONDARY_CLOCK))
    actual = _decision_view(first)
    result = CaseResult(case=case, actual=actual, shadow_result=first)
    result.deterministic = _decision_view(second) == actual
    result.external_action_performed = bool(first["external_action_performed"] or second["external_action_performed"])
    result.pii_log_leak = log_leaks(capture.messages, raw)
    if first["status"] == "assessed":
        result.assessment_id = first["assessment"]["assessment_id"]
        result.input_hash = first["input_hash"]
        if case.input_case_id is not None and first["case_id"] != case.input_case_id:
            result.mismatches.append(
                {"stage": "pre_generation", "field": "case_id", "expected": case.input_case_id, "actual": first["case_id"]}
            )
    result.mismatches.extend(_compare(case, actual))
    return result


@dataclass(frozen=True)
class RunOutput:
    suite: Suite
    results: tuple[CaseResult, ...]


def run_suite(suite: Suite) -> RunOutput:
    return RunOutput(suite=suite, results=tuple(run_case(case) for case in suite.cases))


def dumps_report(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
