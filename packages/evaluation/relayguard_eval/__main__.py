"""CLI for the offline evaluation harness. No network, no external action.

    python -m relayguard_eval run --suite release-set-candidates --out eval/runs/latest
    python -m relayguard_eval run --suite sg001 --out eval/runs/sg001 [--baseline old/report.json]
    python -m relayguard_eval shadow-record --result result.json --observation obs.json --store store.jsonl
    python -m relayguard_eval shadow-kpi --store store.jsonl --kind observed [--from TS] [--to TS]

Exit codes: 0 = run completed (mismatches are reported, not hidden), 2 = usage / input error,
3 = the suite or store cannot be evaluated as a whole (fail closed).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from relayguard.strict_json import parse_strict_json

from .cases import SuiteError, load_fixture_suite, load_sg001_suite
from .report import ROOT, build_report, regression_diff, summary_markdown
from .runner import dumps_report, run_suite
from .shadow import ShadowRecordError, ShadowStore, build_shadow_outcome, store_kpis

SUITES = {
    "release-set-candidates": lambda: load_fixture_suite(ROOT / "eval" / "release-set-candidates"),
    "sg001": lambda: load_sg001_suite(ROOT / "fixtures" / "sg001"),
}


def _read_json(path: Path) -> Any:
    return parse_strict_json(path.read_bytes())


def _run(args: argparse.Namespace) -> int:
    try:
        suite = SUITES[args.suite]()
    except SuiteError as error:
        sys.stderr.write(f"suite error: {error}\n")
        return 3
    observations = _read_json(Path(args.observations)) if args.observations else None
    try:
        report = build_report(run_suite(suite), observations)
    except ShadowRecordError as error:
        sys.stderr.write(f"observation error: {error}\n")
        return 3
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_bytes(dumps_report(report))
    (out / "summary.md").write_bytes(summary_markdown(report).encode("utf-8"))
    if args.baseline:
        diff = regression_diff(report, _read_json(Path(args.baseline)))
        (out / "regression_diff.json").write_bytes(dumps_report(diff))
    metrics = report["delegation_metrics"]
    sys.stdout.write(
        f"{suite.name}: {report['suite']['case_count']} cases, label match "
        f"{metrics['pre_generation_label_match']['numerator']}/{metrics['pre_generation_label_match']['denominator']}, "
        f"release_gate={report['gate']['release_gate']} -> {out}\n"
    )
    return 0


def _shadow_record(args: argparse.Namespace) -> int:
    try:
        outcome, binding = build_shadow_outcome(_read_json(Path(args.result)), _read_json(Path(args.observation)))
        entry = ShadowStore(Path(args.store)).append(outcome, binding)
    except ShadowRecordError as error:
        sys.stderr.write(f"shadow record rejected: {error}\n")
        return 3
    sys.stdout.write(f"recorded sequence {entry['sequence']} for {outcome['assessment_id']}\n")
    return 0


def _shadow_kpi(args: argparse.Namespace) -> int:
    try:
        state = ShadowStore(Path(args.store)).read()
        kpis = store_kpis(state, args.kind, args.period_from, args.period_to)
    except ShadowRecordError as error:
        sys.stderr.write(f"shadow store error: {error}\n")
        return 3
    sys.stdout.write(dumps_report(kpis).decode("utf-8"))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="relayguard_eval")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--suite", choices=sorted(SUITES), required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--baseline")
    run.add_argument("--observations", help="case_id -> fixture observation (human-adjudicated)")
    record = commands.add_parser("shadow-record")
    record.add_argument("--result", required=True)
    record.add_argument("--observation", required=True)
    record.add_argument("--store", required=True)
    kpi = commands.add_parser("shadow-kpi")
    kpi.add_argument("--store", required=True)
    kpi.add_argument("--kind", choices=["fixture", "observed"], required=True)
    kpi.add_argument("--from", dest="period_from")
    kpi.add_argument("--to", dest="period_to")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    try:
        handler = {"run": _run, "shadow-record": _shadow_record, "shadow-kpi": _shadow_kpi}[args.command]
        return handler(args)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"input error: {type(error).__name__}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
