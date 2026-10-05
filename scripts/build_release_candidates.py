"""Regenerate the 100 release-set candidate cases (fixture_version 0.2) from
packages/evaluation/authoring/.

Writes eval/release-set-candidates/inputs/<case_id>.input.json (ShadowCoreInput bytes only)
and eval/release-set-candidates/cases/<case_id>.case.json (labels, pinned by input hash).
The labels are Builder candidates, never Architect-approved Gold.

    .venv\\Scripts\\python.exe scripts\\build_release_candidates.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "core"),
    str(ROOT / "packages" / "core" / "tests"),
    str(ROOT / "packages" / "evaluation"),
    str(ROOT / "packages" / "evaluation" / "authoring"),
]

import cat01_05  # noqa: E402, F401  (registers candidates)
import cat06_10  # noqa: E402, F401
import cat11_15  # noqa: E402, F401
import cat16_20  # noqa: E402, F401
from builders import to_bytes  # noqa: E402
from common import REGISTRY, Candidate  # noqa: E402

OUT_DIR = ROOT / "eval" / "release-set-candidates"


def input_bytes(item: Candidate) -> bytes:
    built = item.build()
    if isinstance(built, bytes):
        return built
    return to_bytes(built, indent=2) + b"\n"


def case_bytes(item: Candidate, raw_input: bytes) -> bytes:
    document = {
        "fixture_version": "0.2",
        "case_id": item.case_id,
        "title_ja": item.title_ja,
        "category": item.category,
        "variant": item.variant,
        "origin": "synthetic",
        "threats": list(item.threats),
        "input_file": f"inputs/{item.case_id}.input.json",
        "input_sha256": hashlib.sha256(raw_input).hexdigest(),
        "expected_delegation": item.expected,
        # Post-verification labels are not authored before SHADOW_GATE (stages are NOT_RUN).
        "unsafe_candidate_reply": None,
        "expected_verification": None,
        "expected_final_delegation": None,
        "release_class": item.release_class,
        "label": {"status": "builder_candidate", "basis": list(item.basis), "rationale_ja": item.rationale_ja},
    }
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def rendered() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for case_id in sorted(REGISTRY):
        item = REGISTRY[case_id]
        raw_input = input_bytes(item)
        files[f"inputs/{case_id}.input.json"] = raw_input
        files[f"cases/{case_id}.case.json"] = case_bytes(item, raw_input)
    return files


def main() -> int:
    files = rendered()
    for directory in ("inputs", "cases"):
        target = OUT_DIR / directory
        target.mkdir(parents=True, exist_ok=True)
        for stale in target.glob("*.json"):
            if f"{directory}/{stale.name}" not in files:
                stale.unlink()
    for relative, data in files.items():
        (OUT_DIR / relative).write_bytes(data)
    print(f"wrote {len(REGISTRY)} candidate cases to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
