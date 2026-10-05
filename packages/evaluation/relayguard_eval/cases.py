"""Evaluation suites: fixture 0.2 case files and the SG-001 fixture set.

A suite is loaded completely or not at all: a malformed case file, an input whose bytes do
not match its pinned hash, or a duplicate case ID stops the run instead of silently
shrinking N (EVALUATION.md §13).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from relayguard.schema_validation import load_strict_validator, safe_error_locations
from relayguard.strict_json import parse_strict_json

EVAL_CASE_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "eval" / "eval_case_0_2.schema.json"

CATEGORIES: tuple[str, ...] = (
    "01_simple_inquiry",
    "02_discount_negotiation",
    "03_refund_request",
    "04_license_inquiry",
    "05_deadline_change",
    "06_quantity_change",
    "07_currency_amount_expression",
    "08_warranty_sla",
    "09_rights_exclusivity_sublicense",
    "10_prohibition_condition_drop",
    "11_multiple_requests",
    "12_critical_information_missing",
    "13_ambiguous_expression",
    "14_prompt_injection",
    "15_indirect_prompt_injection",
    "16_long_thread",
    "17_history_contradiction",
    "18_attachment_dependency",
    "19_legal_claim_contract",
    "20_undeterminable_provider_schema_anomaly",
)
VARIANTS: tuple[str, ...] = ("explicit", "euphemistic", "compound", "history_dependent", "adversarial")

# SG-001 approval_status values that carry a semantic label. structural_only is a mutation
# base and is excluded from metrics (and reported as excluded, never silently dropped).
SG001_LABELLED_STATUSES = frozenset({"gold_proposed", "regression"})
SG001_STATUSES = SG001_LABELLED_STATUSES | {"structural_only"}


class SuiteError(RuntimeError):
    """The suite cannot be evaluated as a whole (fail closed)."""


@dataclass(frozen=True)
class ExpectedPre:
    outcome: str  # assessed / rejected
    level: str | None
    minimum_level: str | None
    reason_codes: tuple[str, ...] | None
    error_code: str | None
    risk_factors: dict[str, str] | None = None


@dataclass(frozen=True)
class EvalCase:
    suite: str
    case_id: str
    input_path: Path
    input_sha256: str
    expected: ExpectedPre
    label_status: str
    in_metrics: bool
    category: str | None = None
    variant: str | None = None
    threats: tuple[str, ...] = ()
    release_class: str | None = None
    title_ja: str | None = None
    # Case ID the ShadowCoreInput is expected to carry (None when the suite names cases
    # independently of the input, as SG-001 does).
    input_case_id: str | None = None
    has_post_labels: bool = False
    case_file_sha256: str | None = None


@dataclass(frozen=True)
class Suite:
    name: str
    root: Path
    cases: tuple[EvalCase, ...]
    manifest_sha256: str

    def matrix(self) -> dict[str, Any]:
        """20 categories x 5 variants coverage (EVALUATION.md §§4-5)."""
        cells: dict[tuple[str, str], list[str]] = {}
        for case in self.cases:
            if case.category is not None and case.variant is not None:
                cells.setdefault((case.category, case.variant), []).append(case.case_id)
        missing = [f"{c}/{v}" for c in CATEGORIES for v in VARIANTS if (c, v) not in cells]
        duplicated = {f"{c}/{v}": ids for (c, v), ids in sorted(cells.items()) if len(ids) > 1}
        return {
            "categories": len(CATEGORIES),
            "variants": len(VARIANTS),
            "filled_cells": len(cells),
            "missing_cells": missing,
            "multi_case_cells": duplicated,
            "complete": not missing and not duplicated and len(self.cases) == len(CATEGORIES) * len(VARIANTS),
        }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_hash(entries: list[tuple[str, str]]) -> str:
    lines = "".join(f"{name}\t{digest}\n" for name, digest in sorted(entries))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def load_fixture_suite(root: Path, name: str = "release-set-candidates") -> Suite:
    """Load ``root/cases/*.case.json`` (fixture_version 0.2) and their pinned inputs."""
    case_dir = root / "cases"
    if not case_dir.is_dir():
        raise SuiteError(f"case directory not found: {case_dir}")
    validator = load_strict_validator(EVAL_CASE_SCHEMA)
    cases: list[EvalCase] = []
    seen: set[str] = set()
    manifest: list[tuple[str, str]] = []
    for case_path in sorted(case_dir.glob("*.case.json")):
        raw = case_path.read_bytes()
        try:
            document = parse_strict_json(raw)
        except Exception as error:
            raise SuiteError(f"{case_path.name}: not strict JSON") from error
        problems = safe_error_locations(validator, document)
        if problems:
            raise SuiteError(f"{case_path.name}: case contract violation at {problems[:3]}")
        case_id = document["case_id"]
        if case_path.name != f"{case_id}.case.json":
            raise SuiteError(f"{case_path.name}: file name does not match case_id")
        if case_id in seen:
            raise SuiteError(f"duplicate case_id {case_id}")
        seen.add(case_id)
        input_path = root / document["input_file"]
        if not input_path.is_file():
            raise SuiteError(f"{case_id}: input file missing")
        digest = sha256_file(input_path)
        if digest != document["input_sha256"]:
            raise SuiteError(f"{case_id}: input bytes do not match input_sha256")
        expected = document["expected_delegation"]
        if expected["outcome"] == "assessed":
            _check_level_order(case_id, expected["level"], expected["minimum_level"])
        post = (document["unsafe_candidate_reply"], document["expected_verification"], document["expected_final_delegation"])
        if any(p is not None for p in post) and not all(p is not None for p in post):
            raise SuiteError(f"{case_id}: post-verification labels must be all present or all null")
        manifest.append((case_path.name, hashlib.sha256(raw).hexdigest()))
        manifest.append((document["input_file"], digest))
        cases.append(
            EvalCase(
                suite=name,
                case_id=case_id,
                input_path=input_path,
                input_sha256=digest,
                expected=ExpectedPre(
                    outcome=expected["outcome"],
                    level=expected["level"],
                    minimum_level=expected["minimum_level"],
                    reason_codes=tuple(sorted(expected["reason_codes"])) if expected["reason_codes"] is not None else None,
                    error_code=expected["error_code"],
                ),
                label_status=document["label"]["status"],
                in_metrics=True,
                category=document["category"],
                variant=document["variant"],
                threats=tuple(document["threats"]),
                release_class=document["release_class"],
                title_ja=document["title_ja"],
                input_case_id=case_id,
                has_post_labels=post[0] is not None,
                case_file_sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    if not cases:
        raise SuiteError(f"no cases found in {case_dir}")
    return Suite(name=name, root=root, cases=tuple(cases), manifest_sha256=_manifest_hash(manifest))


_LEVELS = ("L0_AUTO", "L1_POST_REVIEW", "L2_PRE_APPROVAL", "L3_STOP")


def _check_level_order(case_id: str, level: str, minimum: str) -> None:
    if _LEVELS.index(level) < _LEVELS.index(minimum):
        raise SuiteError(f"{case_id}: expected level is below expected minimum_level")


def load_sg001_suite(root: Path) -> Suite:
    """Load fixtures/sg001 (``<name>.input.json`` + ``expected.json``) with its approval_status
    classes kept as they are."""
    expected_path = root / "expected.json"
    try:
        expected_all = json.loads(expected_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SuiteError("fixtures/sg001/expected.json cannot be read") from error
    inputs = {path.name.removesuffix(".input.json") for path in root.glob("*.input.json")}
    if inputs != set(expected_all):
        raise SuiteError("SG-001 inputs and expected.json do not describe the same cases")
    cases: list[EvalCase] = []
    manifest: list[tuple[str, str]] = [("expected.json", sha256_file(expected_path))]
    for name in sorted(expected_all):
        entry = expected_all[name]
        status = entry["approval_status"]
        if status not in SG001_STATUSES:
            raise SuiteError(f"{name}: unknown approval_status")
        _check_level_order(name, entry["level"], entry["minimum_level"])
        input_path = root / f"{name}.input.json"
        digest = sha256_file(input_path)
        manifest.append((input_path.name, digest))
        cases.append(
            EvalCase(
                suite="sg001",
                case_id=name,
                input_path=input_path,
                input_sha256=digest,
                expected=ExpectedPre(
                    outcome="assessed",
                    level=entry["level"],
                    minimum_level=entry["minimum_level"],
                    reason_codes=tuple(sorted(entry["reason_codes"])),
                    error_code=None,
                    risk_factors=dict(entry["risk_factors"]),
                ),
                label_status=status,
                in_metrics=status in SG001_LABELLED_STATUSES,
            )
        )
    return Suite(name="sg001", root=root, cases=tuple(cases), manifest_sha256=_manifest_hash(manifest))
