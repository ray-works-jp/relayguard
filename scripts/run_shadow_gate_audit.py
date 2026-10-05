#!/usr/bin/env python3
"""RelayGuard SHADOW_GATE Mechanical Verification & Audit Script.

Executes all gate criteria deterministically to issue a formal SHADOW_GATE audit certificate.
Criteria:
1. Static lint and formatting check (ruff)
2. Strict type check (mypy)
3. Unit, integration, and adversarial regression test suite (pytest; core + evaluation suites only - the UI suite is run separately)
4. SG-001 Gold dataset integrity & 100% agreement
5. 100-case official release-set offline run (zero Dangerous AUTO, zero PII leak, zero drift)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# Ensure paths are set for internal evaluation imports
sys.path.insert(0, str(ROOT / "packages" / "core"))
sys.path.insert(0, str(ROOT / "packages" / "evaluation"))

from relayguard_eval.cases import load_fixture_suite  # noqa: E402


def compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_command(cmd: list[str], description: str) -> tuple[bool, str]:
    print(f"[*] Running: {description} ...", end=" ", flush=True)
    start = time.monotonic()
    env = dict(os.environ)
    pp = [
        str(ROOT / "packages" / "core"),
        str(ROOT / "packages" / "evaluation"),
        str(ROOT / "packages" / "core" / "tests"),
        str(ROOT / "packages" / "evaluation" / "tests"),
    ]
    if "PYTHONPATH" in env:
        pp.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pp)

    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed = time.monotonic() - start
    if proc.returncode == 0:
        print(f"[PASS] ({elapsed:.1f}s)")
        return True, proc.stdout
    else:
        print(f"[FAIL] ({elapsed:.1f}s)")
        print(proc.stdout)
        print(proc.stderr)
        return False, proc.stdout + "\n" + proc.stderr


def main() -> int:
    print("=" * 80)
    print("  RelayGuard SHADOW_GATE Mechanical Audit Execution")
    print(f"  Target Repository Root: {ROOT}")
    print("=" * 80)
    print()

    report: dict[str, Any] = {
        "gate": "SHADOW_GATE",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "criteria": {},
        "hashes": {},
        "decision": "BLOCKED",
    }

    # 1. Spec & Manifest Hash Verifications
    print("[1] Verifying Core Specs & Manifest Hashes...")
    specs = {
        "ADR-026": ROOT / "Relay_Guard" / "ADR-026_SHADOW_GATE_DECISIONS.md",
        "SCHEMA_v05": ROOT / "Relay_Guard" / "SCHEMA.md",
        "DELEGATION_v04": ROOT / "Relay_Guard" / "DELEGATION.md",
        "SG001_expected": ROOT / "fixtures" / "sg001" / "expected.json",
    }
    all_specs_exist = True
    for name, path in specs.items():
        if not path.exists():
            print(f"  [!] Missing required spec: {path}")
            all_specs_exist = False
        else:
            h = compute_sha256(path)
            report["hashes"][name] = h
            print(f"  - {name:20s}: {h}")

    if not all_specs_exist:
        report["decision"] = "FAILED (Missing Specs)"
        return 1

    # Verify expected.json hash matches ADR-026 accepted hash
    expected_sg001_hash = "3a9f01866181c227bfdffffead3062de9ad496cb19848cf5ab42234b089bdec6"
    actual_sg001_hash = report["hashes"]["SG001_expected"]
    if actual_sg001_hash != expected_sg001_hash:
        print(f"  [!] SG-001 expected.json hash mismatch! Expected {expected_sg001_hash}, got {actual_sg001_hash}")
        report["decision"] = "FAILED (SG001 Hash Mismatch)"
        return 1
    print("  [OK] SG-001 Gold expected.json matches ADR-026 specification hash.")

    # Load candidates suite and verify manifest hash
    suite_candidates = load_fixture_suite(ROOT / "eval" / "release-set-candidates")
    expected_candidate_manifest = "2929f19ea47c5c7061bd0ff31ebbdd3b676b3a28ed8fb76fd649c3a6fd9808bc"
    actual_candidate_manifest = suite_candidates.manifest_sha256
    report["hashes"]["candidates_manifest"] = actual_candidate_manifest
    if actual_candidate_manifest != expected_candidate_manifest:
        print(f"  [!] Candidates suite manifest mismatch! Expected {expected_candidate_manifest}, got {actual_candidate_manifest}")
        report["decision"] = "FAILED (Candidate Manifest Mismatch)"
        return 1
    print(f"  - candidates_manifest : {actual_candidate_manifest}")
    print("  [OK] 100-case release-set candidate manifest matches ADR-026 specification hash.")
    print()

    # 2. Ruff Lint & Format
    ok_ruff_check, _ = run_command([PYTHON, "-m", "ruff", "check", "."], "Ruff Linter")
    ok_ruff_fmt, _ = run_command([PYTHON, "-m", "ruff", "format", "--check", "."], "Ruff Formatter")
    report["criteria"]["ruff_check"] = ok_ruff_check
    report["criteria"]["ruff_format"] = ok_ruff_fmt

    # 3. Mypy Strict Type Check
    ok_mypy, _ = run_command([PYTHON, "-m", "mypy", "--config-file", "pyproject.toml"], "Mypy Strict Type Check")
    report["criteria"]["mypy_strict"] = ok_mypy

    # 4. Pytest Full Regression & Adversarial Suite
    ok_pytest, _ = run_command([PYTHON, "-m", "pytest", "-q"], "Pytest Full Suite (including Adversarial QA)")
    report["criteria"]["pytest_full"] = ok_pytest

    # 5. SG-001 Runner Execution
    sg001_cmd = [
        PYTHON,
        "-m",
        "relayguard_eval",
        "run",
        "--suite",
        "sg001",
        "--out",
        str(ROOT / "eval" / "runs" / "sg001_audit"),
    ]
    ok_sg001, _ = run_command(sg001_cmd, "SG-001 Evaluation Run")
    report["criteria"]["sg001_run"] = ok_sg001

    # 6. 100-Case Release-Set Candidates Runner Execution
    relset_cmd = [
        PYTHON,
        "-m",
        "relayguard_eval",
        "run",
        "--suite",
        "release-set-candidates",
        "--out",
        str(ROOT / "eval" / "runs" / "release_set_audit"),
    ]
    ok_relset, _ = run_command(relset_cmd, "100-Case Release-Set Run")
    report["criteria"]["release_set_run"] = ok_relset

    # Verify Release-Set report metrics
    rel_report_path = ROOT / "eval" / "runs" / "release_set_audit" / "report.json"
    if rel_report_path.exists():
        rel_data = json.loads(rel_report_path.read_text(encoding="utf-8"))
        del_metrics = rel_data.get("delegation_metrics", {})
        blockers = rel_data.get("release_blockers", {})
        safety = rel_data.get("safety_checks", {})

        delegation_acc_val = del_metrics.get("delegation_level_accuracy", {}).get("value")
        false_auto_count = del_metrics.get("false_automation_rate", {}).get("count", 999)
        under_class_count = del_metrics.get("under_classified_count", 999)
        pii_leak_count = blockers.get("raw_pii_operational_log_leak", {}).get("count", 999)
        drift_cases = safety.get("nondeterministic_cases", [])
        drift_count = len(drift_cases) if isinstance(drift_cases, list) else 999
        ext_cases = safety.get("external_action_performed_cases", [])
        external_action_count = len(ext_cases) if isinstance(ext_cases, list) else 999

        report["metrics"] = {
            "delegation_accuracy": delegation_acc_val,
            "false_automation_count": false_auto_count,
            "under_classified_count": under_class_count,
            "pii_leak_count": pii_leak_count,
            "determinism_violations": drift_count,
            "external_action_performed": external_action_count,
        }
        print(f"  - 100-case Agreement Accuracy : {delegation_acc_val}")
        print(f"  - Dangerous False Automations : {false_auto_count} (Target: 0)")
        print(f"  - Under-Classified Cases      : {under_class_count} (Target: 0)")
        print(f"  - Raw PII Leak Incidents      : {pii_leak_count} (Target: 0)")
        print(f"  - Determinism Violations      : {drift_count} (Target: 0)")
        print(f"  - External Action Performed   : {external_action_count} (Target: 0)")

        gate_passed = (
            ok_ruff_check
            and ok_ruff_fmt
            and ok_mypy
            and ok_pytest
            and ok_sg001
            and ok_relset
            and delegation_acc_val == "1.0000"
            and false_auto_count == 0
            and under_class_count == 0
            and pii_leak_count == 0
            and drift_count == 0
            and external_action_count == 0
        )
    else:
        gate_passed = False

    gate_a = gate_passed
    report["gates"] = {"A_shadow_core": gate_a}

    # Gate B and Gate C were added by Architect ruling D-4 (2026-09-20). The hard stop was
    # ratified conditionally (docs/SHADOW_GATE.md §5): "formal gate passed" may only be shown
    # when all three gates pass, so a green Shadow Core alone is no longer sufficient.
    print()
    print("[B] Reply Extractor adversarial fuzz (ruling D-4)...")
    gate_b, _ = run_command([PYTHON, str(ROOT / "scripts" / "fuzz_extractor.py")], "Reply Extractor Fuzz")
    report["gates"]["B_reply_extractor_fuzz"] = gate_b

    print()
    print("[C] UI contract and display tests (ruling D-4)...")
    gate_c, _ = run_command([PYTHON, "-m", "pytest", "-q", str(ROOT / "packages" / "ui" / "tests")], "UI Test Suite")
    report["gates"]["C_ui"] = gate_c

    all_gates = gate_a and gate_b and gate_c
    # Evidence level per the delegation instruction: 1 implemented / 2 builder-verified /
    # 3 architect-approved / 4 independent QA / 5 release. This script can only ever reach 2.
    report["evidence_level"] = "2_BUILDER_VERIFIED"
    report["not_established"] = ["3_ARCHITECT_VERIFIED", "4_INDEPENDENT_QA", "5_RELEASE_APPROVED"]
    print()
    print("=" * 80)
    print(f"  Gate A (Shadow Core)          : {'PASS' if gate_a else 'FAIL'}")
    print(f"  Gate B (Reply Extractor Fuzz) : {'PASS' if gate_b else 'FAIL'}")
    print(f"  Gate C (UI)                   : {'PASS' if gate_c else 'FAIL'}")
    if all_gates:
        report["decision"] = "PASSED (All 3 Gates - ruling D-1 conditions met)"
        print()
        print("  *** FORMAL STATUS: PASSED (3/3 gates) ***")
        print("  Hard stop released per docs/SHADOW_GATE.md §5 (conditional ratification D-1).")
        print("  NOT a release approval: real-LLM evaluation, pilot and independent QA are NOT_RUN.")
        print("  External mail / external Action remain prohibited (SHADOW_GATE §2).")
        print("  Evidence level: BUILDER_VERIFIED (2 of 5). NOT Architect-verified, NOT independent QA.")
    else:
        report["decision"] = "BLOCKED"
        print()
        print("  *** FORMAL STATUS: BLOCKED ***")
    print("=" * 80)
    gate_passed = all_gates

    # Save audit report
    out_dir = ROOT / "eval" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / "SHADOW_GATE_AUDIT_REPORT.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Audit certificate saved to: {report_file}")

    return 0 if gate_passed else 1


if __name__ == "__main__":
    sys.exit(main())
