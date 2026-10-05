"""Evaluation Runner: fail-closed suite loading, reproducible reports, regression diff, CLI."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from eval_support import CANDIDATES, ROOT, SG001, copy_suite

from relayguard_eval.cases import SuiteError, load_fixture_suite, load_sg001_suite
from relayguard_eval.report import build_report, regression_diff, summary_markdown
from relayguard_eval.runner import dumps_report, run_suite


def _case_path(root: Path, number: int) -> Path:
    return root / "cases" / f"RG-EVAL-{number:03d}.case.json"


def test_tampered_input_bytes_stop_the_whole_suite(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    target = root / "inputs" / "RG-EVAL-011.input.json"
    target.write_bytes(target.read_bytes().replace(b"49.00", b"4.90"))
    with pytest.raises(SuiteError, match="input_sha256"):
        load_fixture_suite(root)


def test_case_contract_violations_stop_the_whole_suite(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = _case_path(root, 1)
    case = json.loads(path.read_text(encoding="utf-8"))
    case["expected_delegation"]["level"] = "AUTO"  # legacy enum is not a Delegation value
    path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SuiteError, match="contract violation"):
        load_fixture_suite(root)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label", {"status": "architect_approved", "basis": ["DELEGATION §12"], "rationale_ja": "自己承認"}),
        ("origin", "observed"),
        ("fixture_version", "0.1"),
        (
            "expected_delegation",
            {"outcome": "assessed", "level": "L0_AUTO", "minimum_level": "L0_AUTO", "reason_codes": [], "error_code": None},
        ),
    ],
)
def test_builder_cannot_self_approve_or_relabel_origin(tmp_path: Path, field: str, value: object) -> None:
    root = copy_suite(tmp_path)
    path = _case_path(root, 2)
    case = json.loads(path.read_text(encoding="utf-8"))
    case[field] = value
    path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SuiteError):
        load_fixture_suite(root)


def test_level_below_minimum_and_partial_post_labels_are_rejected(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = _case_path(root, 3)
    case = json.loads(path.read_text(encoding="utf-8"))
    case["expected_delegation"]["minimum_level"] = "L2_PRE_APPROVAL"
    path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SuiteError, match="below"):
        load_fixture_suite(root)

    root2 = copy_suite(tmp_path / "second")
    path2 = _case_path(root2, 4)
    case2 = json.loads(path2.read_text(encoding="utf-8"))
    case2["unsafe_candidate_reply"] = {"text": "We will refund you."}
    path2.write_text(json.dumps(case2, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SuiteError, match="all present or all null"):
        load_fixture_suite(root2)


def test_renamed_or_duplicated_case_files_are_rejected(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    _case_path(root, 5).rename(root / "cases" / "RG-EVAL-999.case.json")
    with pytest.raises(SuiteError, match="file name"):
        load_fixture_suite(root)


def test_sg001_suite_keeps_its_classes_and_excludes_structural_only() -> None:
    suite = load_sg001_suite(SG001)
    statuses = {case.label_status for case in suite.cases}
    assert statuses == {"gold_proposed", "regression", "structural_only"}
    excluded = [case.case_id for case in suite.cases if not case.in_metrics]
    assert excluded == ["structural_coverage"]
    report = build_report(run_suite(suite))
    assert report["suite"]["excluded_from_metrics"] == ["structural_coverage"]
    assert report["delegation_metrics"]["n"] == len(suite.cases) - 1
    assert not report["failures"]


def test_report_is_reproducible_and_carries_no_mail_text() -> None:
    suite = load_fixture_suite(CANDIDATES)
    first = dumps_report(build_report(run_suite(suite)))
    second = dumps_report(build_report(run_suite(load_fixture_suite(CANDIDATES))))
    assert first == second
    text = first.decode("utf-8")
    for probe in ("Taro Example", "XX0000000", "090-0000-0000", "2-4-6 Example-dori", "Ignore previous instructions"):
        assert probe not in text


def test_report_never_claims_a_gate_pass() -> None:
    report = build_report(run_suite(load_fixture_suite(CANDIDATES)))
    assert report["gate"] == {**report["gate"], "release_gate": "NOT_EVALUATED", "shadow_gate": "NOT_DETERMINED"}
    assert report["stages"]["post_verification"] == "NOT_RUN"
    assert all(entry["status"] in ("COUNTED", "NOT_RUN") for entry in report["release_blockers"].values())
    assert "PASS" not in json.dumps(report["release_blockers"])
    markdown = summary_markdown(report)
    assert "NOT_EVALUATED" in markdown
    assert "Builder" in markdown


def test_every_failure_records_stage_expected_actual_and_versions(tmp_path: Path) -> None:
    root = copy_suite(tmp_path)
    path = _case_path(root, 1)
    case = json.loads(path.read_text(encoding="utf-8"))
    case["expected_delegation"] = {
        "outcome": "assessed",
        "level": "L2_PRE_APPROVAL",
        "minimum_level": "L2_PRE_APPROVAL",
        "reason_codes": ["UNCLASSIFIED_RISK"],
        "error_code": None,
    }
    path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = build_report(run_suite(load_fixture_suite(root)))
    failures = [f for f in report["failures"] if f["case_id"] == "RG-EVAL-001"]
    assert {f["field"] for f in failures} == {"level", "minimum_level", "reason_codes"}
    for failure in failures:
        assert failure["stage"] == "pre_generation"
        assert {"schema_version", "policy_version", "prompt_version", "model"} <= set(failure["versions"])
    # The prediction (L0) is below the label (L2): counted as a blocker and as False Automation.
    assert report["release_blockers"]["l2_l3_misclassified_as_l0_l1"]["count"] == 1
    assert report["delegation_metrics"]["false_automation_rate"]["count"] == 1


def test_regression_diff_reports_result_label_and_input_changes() -> None:
    baseline = build_report(run_suite(load_fixture_suite(CANDIDATES)))
    current = copy.deepcopy(baseline)
    changed = next(c for c in current["cases"] if c["case_id"] == "RG-EVAL-001")
    changed["actual"]["level"] = "L2_PRE_APPROVAL"
    changed["under_classified"] = False
    relabelled = next(c for c in current["cases"] if c["case_id"] == "RG-EVAL-002")
    relabelled["expected"]["level"] = "L3_STOP"
    moved = next(c for c in current["cases"] if c["case_id"] == "RG-EVAL-003")
    moved["input_sha256"] = "f" * 64
    moved["under_classified"] = True
    current["cases"] = [c for c in current["cases"] if c["case_id"] != "RG-EVAL-100"]
    current["versions"] = {**current["versions"], "policy_version": "delegation-0.5"}

    diff = regression_diff(current, baseline)
    assert [c["case_id"] for c in diff["result_changes"]] == ["RG-EVAL-001"]
    assert diff["label_changes"] == ["RG-EVAL-002"]
    assert diff["input_changes"] == ["RG-EVAL-003"]
    assert diff["removed_cases"] == ["RG-EVAL-100"]
    assert diff["new_under_classifications"] == ["RG-EVAL-003"]
    assert diff["version_changes"] == {"policy_version": {"baseline": "delegation-0.4", "current": "delegation-0.5"}}

    with pytest.raises(ValueError, match="baseline"):
        regression_diff(current, {"report_kind": "something-else"})


def _cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join([str(ROOT / "packages" / "core"), str(ROOT / "packages" / "evaluation")]),
        PYTHONIOENCODING="utf-8",
    )
    return subprocess.run([sys.executable, "-m", "relayguard_eval", *args], capture_output=True, env=env, timeout=300, check=False)


def test_cli_run_writes_report_summary_and_diff(tmp_path: Path) -> None:
    out = tmp_path / "run"
    completed = _cli("run", "--suite", "sg001", "--out", str(out))
    assert completed.returncode == 0, completed.stderr
    again = _cli("run", "--suite", "sg001", "--out", str(tmp_path / "again"), "--baseline", str(out / "report.json"))
    assert again.returncode == 0, again.stderr
    assert (out / "report.json").read_bytes() == (tmp_path / "again" / "report.json").read_bytes()
    diff = json.loads((tmp_path / "again" / "regression_diff.json").read_text(encoding="utf-8"))
    assert diff["result_changes"] == [] and diff["same_suite"] is True
    assert "開発用評価" in (out / "summary.md").read_text(encoding="utf-8")


def test_cli_usage_errors() -> None:
    assert _cli("run", "--suite", "no-such-suite", "--out", "x").returncode == 2
    assert _cli().returncode == 2


@pytest.mark.parametrize(
    ("name", "loader"),
    [("release-set-candidates", lambda: load_fixture_suite(CANDIDATES)), ("sg001", lambda: load_sg001_suite(SG001))],
)
def test_committed_run_reports_match_the_current_code_and_suite(name: str, loader: object) -> None:
    """eval/runs/<suite>/report.json is review evidence; it must describe the current tree."""
    assert callable(loader)
    committed = ROOT / "eval" / "runs" / name / "report.json"
    fresh = dumps_report(build_report(run_suite(loader())))
    assert committed.read_bytes() == fresh, f"re-run: python -m relayguard_eval run --suite {name} --out eval/runs/{name}"
