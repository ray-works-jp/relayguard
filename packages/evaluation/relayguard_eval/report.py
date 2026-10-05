"""Evaluation report: reproducible JSON, Japanese summary and regression diff.

The report never contains source text, interpretation text or answers; it carries case IDs,
hashes, levels, reason codes and error codes only. It contains no wall-clock time, so the
same code + policy + suite produce byte-identical reports.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Any

from . import FIXTURE_VERSION, RUNNER_VERSION
from .cases import Suite
from .metrics import HARNESS_DEFINITIONS, breakdown, delegation_metrics, release_blockers, safety_checks
from .runner import POST_STAGE_NOT_RUN_REASON, CaseResult, RunOutput, pipeline_versions
from .shadow import ShadowRecordError, build_shadow_outcome, shadow_kpis

ROOT = Path(__file__).resolve().parents[3]
REPORT_KIND = "relayguard-development-evaluation"

NOTICE_JA = (
    "開発用評価（Builder実行）。ラベルは候補であり、正式Gold・正式release-set・Release Gate PASS・"
    "SHADOW_GATE判断のいずれでもない。Architect承認・独立QAの代替にしない。"
    "Interpretation/Decisionはfixture供給であり、実LLM・実メールの安全性の証拠ではない。"
)
LABEL_PROVENANCE_JA = (
    "期待ラベルは実装と同じBuilder（Claude Code）が仕様文から作成した。実装との一致は仕様解釈の一貫性を示すだけで、"
    "ラベルの独立な正しさ・網羅性を示さない。Architect審査と独立QAが必要。"
)

_FINGERPRINT_GLOBS: tuple[tuple[str, str], ...] = (
    ("packages/core/relayguard", "*.py"),
    ("packages/schemas/v0_5", "*.json"),
    ("packages/schemas/eval", "*.json"),
    ("packages/core/reference/iso4217", "manifest.json"),
    ("packages/evaluation/relayguard_eval", "*.py"),
)


def code_fingerprint() -> dict[str, Any]:
    """Content hash of the evaluated code, contracts and reference set (no Git in this repo)."""
    files: list[tuple[str, str]] = []
    for directory, pattern in _FINGERPRINT_GLOBS:
        for path in sorted((ROOT / directory).glob(pattern)):
            relative = path.relative_to(ROOT).as_posix()
            files.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    lines = "".join(f"{name}\t{digest}\n" for name, digest in files)
    return {"sha256": hashlib.sha256(lines.encode("utf-8")).hexdigest(), "files": dict(files)}


def _fixture_outcomes(results: list[CaseResult], observations: dict[str, Any] | None) -> dict[str, Any]:
    if observations is None:
        return {
            "status": "NOT_RUN",
            "reason_ja": "fixture runの人間介入・最終結果・自動化安全性の評価記録が供給されていない。推測で埋めない。",
            "metrics_not_run": ["human_review_rate", "safe_delegation_rate", "critical_incident_rate"],
        }
    by_case = {r.case.case_id: r for r in results}
    unknown_ids = sorted(set(observations) - set(by_case))
    if unknown_ids:
        raise ShadowRecordError(f"observations reference cases outside this run: {unknown_ids[:5]}")
    outcomes: list[dict[str, Any]] = []
    not_recordable: list[str] = []
    for case_id in sorted(observations):
        result = by_case[case_id]
        if result.shadow_result.get("status") != "assessed":
            not_recordable.append(case_id)
            continue
        observation = observations[case_id]
        if observation.get("evaluation_kind") != "fixture":
            raise ShadowRecordError("an evaluation run only accepts evaluation_kind=fixture observations")
        outcome, _ = build_shadow_outcome(result.shadow_result, observation)
        outcomes.append(outcome)
    kpis = shadow_kpis(outcomes, "fixture")
    kpis["status"] = "COUNTED"
    kpis["cases_without_observation"] = sorted(set(by_case) - set(observations))
    kpis["observations_for_rejected_cases"] = not_recordable
    return kpis


def build_report(run: RunOutput, observations: dict[str, Any] | None = None) -> dict[str, Any]:
    suite: Suite = run.suite
    results = list(run.results)
    measured = [r for r in results if r.case.in_metrics]
    excluded = [r.case.case_id for r in results if not r.case.in_metrics]
    versions = pipeline_versions()
    failures = [{"case_id": r.case.case_id, **mismatch, "versions": versions} for r in results for mismatch in r.mismatches]
    label_counts = Counter(r.case.label_status for r in results)
    report: dict[str, Any] = {
        "report_kind": REPORT_KIND,
        "notice_ja": NOTICE_JA,
        "label_provenance_ja": LABEL_PROVENANCE_JA,
        "runner_version": RUNNER_VERSION,
        "fixture_version": FIXTURE_VERSION,
        "gate": {
            "release_gate": "NOT_EVALUATED",
            "shadow_gate": "NOT_DETERMINED",
            "reasons_ja": [
                "ラベルがArchitect承認済みGoldではない（候補）",
                f"post段階はNOT_RUN: {POST_STAGE_NOT_RUN_REASON}",
                "challenge-set・独立QAは本runに含まれない",
                "Gate判断は人間が行う（自動判定で置き換えない）",
            ],
        },
        "suite": {
            "name": suite.name,
            "case_count": len(results),
            "manifest_sha256": suite.manifest_sha256,
            "label_status_counts": dict(sorted(label_counts.items())),
            "excluded_from_metrics": excluded,
            "matrix": suite.matrix() if suite.name != "sg001" else None,
            "post_verification_labels_present": sum(1 for r in results if r.case.has_post_labels),
        },
        "versions": versions,
        "code_fingerprint": code_fingerprint(),
        "harness_definitions_ja": list(HARNESS_DEFINITIONS),
        "stages": {
            "pre_generation": "RUN",
            "post_verification": "NOT_RUN",
            "final_delegation": "NOT_RUN",
        },
        "delegation_metrics": delegation_metrics(measured),
        "release_blockers": release_blockers(measured),
        "safety_checks": safety_checks(results),
        "shadow_outcomes": _fixture_outcomes(measured, observations),
        "breakdown": {
            "category": breakdown(measured, "category"),
            "variant": breakdown(measured, "variant"),
            "label_status": breakdown(results, "label_status"),
        },
        "failures": failures,
        "cases": [r.to_json() for r in results],
    }
    return report


_DIFF_FIELDS = ("status", "level", "minimum_level", "reason_codes", "error_code", "risk_factors")


def regression_diff(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Case-level differences against an earlier report of the same harness."""
    if baseline.get("report_kind") != REPORT_KIND:
        raise ValueError("baseline is not a relayguard evaluation report")
    now = {c["case_id"]: c for c in current["cases"]}
    before = {c["case_id"]: c for c in baseline["cases"]}
    changed: list[dict[str, Any]] = []
    for case_id in sorted(set(now) & set(before)):
        fields = {
            name: {"baseline": before[case_id]["actual"].get(name), "current": now[case_id]["actual"].get(name)}
            for name in _DIFF_FIELDS
            if before[case_id]["actual"].get(name) != now[case_id]["actual"].get(name)
        }
        if fields:
            changed.append({"case_id": case_id, "changes": fields})
    return {
        "baseline_suite_manifest_sha256": baseline["suite"]["manifest_sha256"],
        "current_suite_manifest_sha256": current["suite"]["manifest_sha256"],
        "same_suite": baseline["suite"]["manifest_sha256"] == current["suite"]["manifest_sha256"],
        "baseline_code_fingerprint": baseline["code_fingerprint"]["sha256"],
        "current_code_fingerprint": current["code_fingerprint"]["sha256"],
        "version_changes": {
            key: {"baseline": baseline["versions"].get(key), "current": current["versions"].get(key)}
            for key in sorted(set(current["versions"]) | set(baseline["versions"]))
            if baseline["versions"].get(key) != current["versions"].get(key)
        },
        "result_changes": changed,
        "label_changes": sorted(case_id for case_id in set(now) & set(before) if now[case_id]["expected"] != before[case_id]["expected"]),
        "input_changes": sorted(
            case_id for case_id in set(now) & set(before) if now[case_id]["input_sha256"] != before[case_id]["input_sha256"]
        ),
        "added_cases": sorted(set(now) - set(before)),
        "removed_cases": sorted(set(before) - set(now)),
        "new_under_classifications": sorted(
            case_id for case_id in set(now) & set(before) if now[case_id]["under_classified"] and not before[case_id]["under_classified"]
        ),
    }


def _fmt_rate(entry: dict[str, Any]) -> str:
    return f"{entry['value']} ({entry['numerator']}/{entry['denominator']})"


def summary_markdown(report: dict[str, Any]) -> str:
    m = report["delegation_metrics"]
    suite = report["suite"]
    lines = [
        f"# RelayGuard 開発用評価サマリ（{suite['name']}）",
        "",
        f"> {report['notice_ja']}",
        ">",
        f"> {report['label_provenance_ja']}",
        "",
        f"- Release Gate: **{report['gate']['release_gate']}** / SHADOW_GATE: **{report['gate']['shadow_gate']}**",
        f"- runner {report['runner_version']} / fixture {report['fixture_version']} / schema {report['versions']['schema_version']}"
        f" / policy {report['versions']['policy_version']} / 通貨 {report['versions']['currency_set_version']}"
        f" / model {report['versions']['model']} / prompt {report['versions']['prompt_version']}",
        f"- suite manifest `{suite['manifest_sha256']}` / code fingerprint `{report['code_fingerprint']['sha256']}`",
        f"- case数 {suite['case_count']}（指標対象 {m['n']}、指標除外 {len(suite['excluded_from_metrics'])}）"
        f" / ラベル状態 {suite['label_status_counts']}",
    ]
    if suite["matrix"] is not None:
        matrix = suite["matrix"]
        lines.append(
            f"- 20カテゴリ×5変種: 充足 {matrix['filled_cells']}/100、complete={matrix['complete']}、欠落 {len(matrix['missing_cells'])}"
        )
    lines += [
        "",
        "## 段階",
        "",
        "| 段階 | 状態 |",
        "|---|---|",
        *(f"| {name} | {state} |" for name, state in report["stages"].items()),
        "",
        "## 委任指標（pre_generation、候補ラベル比較）",
        "",
        "| 指標 | 値 |",
        "|---|---|",
        f"| 期待分布 | {m['expected_distribution']} |",
        f"| 予測分布 | {m['predicted_distribution']} |",
        f"| ラベル一致（全項目） | {_fmt_rate(m['pre_generation_label_match'])} |",
        f"| Delegation Level Accuracy | {_fmt_rate(m['delegation_level_accuracy'])} |",
        f"| False Automation Rate | {_fmt_rate(m['false_automation_rate'])}（件数 {m['false_automation_rate']['count']}） |",
        f"| False Escalation Rate | {_fmt_rate(m['false_escalation_rate'])} |",
        f"| L0/L1 precision | {_fmt_rate(m['l0_l1_precision'])} |",
        f"| L2/L3 recall | {_fmt_rate(m['l2_l3_recall'])} |",
        f"| Escalation Rate | {_fmt_rate(m['escalation_rate'])} |",
        f"| 期待外rejected | {m['unexpected_rejection_count']} |",
        f"| 過小判定 | {m['under_classified_count']} |",
        "",
        "## Release blocker（件数。PASS表示はしない）",
        "",
        "| blocker | 状態 | 件数 / 理由 |",
        "|---|---|---|",
    ]
    for name, entry in report["release_blockers"].items():
        if entry["status"] == "COUNTED":
            detail = f"{entry['count']}（scope: {entry['scope']}）"
        else:
            detail = entry["reason_ja"]
            pre = entry.get("pre_generation_under_classification")
            if pre is not None:
                detail += f"。pre段階の過小判定 {pre['count']}/{pre['cases_checked']}"
        lines.append(f"| {name} | {entry['status']} | {detail} |")
    shadow = report["shadow_outcomes"]
    lines += ["", "## Shadow記録・KPI", ""]
    if shadow["status"] == "NOT_RUN":
        lines.append(f"NOT_RUN: {shadow['reason_ja']}")
    else:
        lines.append(
            f"evaluation_kind={shadow['evaluation_kind']} N={shadow['n']} / Human Review Rate {_fmt_rate(shadow['human_review_rate'])}"
            f" / Safe Delegation Rate {_fmt_rate(shadow['safe_delegation_rate'])}"
            f" / Critical Incident Rate {_fmt_rate(shadow['critical_incident_rate'])}"
        )
    safety = report["safety_checks"]
    lines += [
        "",
        "## 決定性・外部実行",
        "",
        f"- 非決定的なcase: {safety['nondeterministic_cases'] or 'なし'}",
        f"- external_action_performed=true: {safety['external_action_performed_cases'] or 'なし'}",
        "",
        "## 不一致",
        "",
    ]
    if not report["failures"]:
        lines.append("なし")
    else:
        lines += ["| case | 段階 | 項目 | 期待 | 実測 |", "|---|---|---|---|---|"]
        lines += [f"| {f['case_id']} | {f['stage']} | {f['field']} | {f['expected']} | {f['actual']} |" for f in report["failures"]]
    lines += ["", "## ハーネス定義（仕様外の判断。要確認）", "", *(f"- {d}" for d in report["harness_definitions_ja"]), ""]
    return "\n".join(lines)
