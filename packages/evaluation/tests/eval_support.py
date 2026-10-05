"""Shared helpers for evaluation harness tests (synthetic data only)."""

from __future__ import annotations

import itertools
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from relayguard.shadow_core import ShadowCoreRuntime, run_shadow_core
from relayguard_eval.cases import EvalCase, ExpectedPre
from relayguard_eval.runner import CaseResult

ROOT = Path(__file__).resolve().parents[3]
CANDIDATES = ROOT / "eval" / "release-set-candidates"
SG001 = ROOT / "fixtures" / "sg001"


def copy_suite(tmp_path: Path) -> Path:
    target = tmp_path / "suite"
    shutil.copytree(CANDIDATES, target)
    return target


def assessed_result(input_path: Path, seed: str = "t") -> dict[str, Any]:
    counter = itertools.count(1)
    runtime = ShadowCoreRuntime(
        clock=lambda: datetime(2026, 9, 16, 1, 2, 3, tzinfo=UTC),
        new_id=lambda prefix: f"{prefix}_{seed}_{next(counter)}",
    )
    result = run_shadow_core(input_path.read_bytes(), runtime)
    assert result["status"] == "assessed", result
    return result


def synthetic_result(
    expected: str,
    actual: str,
    *,
    threats: tuple[str, ...] = (),
    error_code: str | None = None,
    actual_error: str = "SchemaInvalid",
    case_id: str = "SYN-1",
    leak: bool = False,
) -> CaseResult:
    """A CaseResult built by hand for metric tests. ``expected``/``actual`` are a level or 'rejected'."""
    if expected == "rejected":
        pre = ExpectedPre("rejected", None, None, None, error_code)
    else:
        pre = ExpectedPre("assessed", expected, expected, ("UNCLASSIFIED_RISK",), None)
    case = EvalCase(
        suite="synthetic",
        case_id=case_id,
        input_path=Path("unused"),
        input_sha256="0" * 64,
        expected=pre,
        label_status="builder_candidate",
        in_metrics=True,
        threats=threats,
    )
    if actual == "rejected":
        view: dict[str, Any] = {"status": "rejected", "error_code": actual_error}
    else:
        view = {"status": "assessed", "level": actual, "minimum_level": actual, "reason_codes": ["UNCLASSIFIED_RISK"], "risk_factors": {}}
    result = CaseResult(case=case, actual=view, pii_log_leak=leak)
    if expected != actual:
        result.mismatches.append({"stage": "pre_generation", "field": "level", "expected": expected, "actual": actual})
    return result


def observation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "actual_human_intervention": True,
        "final_outcome": "unknown",
        "would_have_been_safe_to_automate": None,
        "adjudicator_id": None,
        "evaluation_kind": "observed",
        "human_seconds": None,
        "verification_cost": None,
        "cost_currency": None,
    }
    base.update(overrides)
    return base
