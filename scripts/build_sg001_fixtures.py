"""Regenerate offline SG-001 fixture files (schema 0.5 / delegation-0.4) from
packages/core/tests/sg001_cases.py.

Writes fixtures/sg001/<name>.input.json (ShadowCoreInput only) and
fixtures/sg001/expected.json (kept separate from inputs).

    .venv\\Scripts\\python.exe scripts\\build_sg001_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "packages" / "core"), str(ROOT / "packages" / "core" / "tests")]

from builders import to_bytes  # noqa: E402
from sg001_cases import CASES  # noqa: E402

FIXTURE_DIR = ROOT / "fixtures" / "sg001"


def fixture_bytes(name: str) -> bytes:
    return to_bytes(CASES[name][0](), indent=2) + b"\n"


def expected_bytes() -> bytes:
    expected = {
        name: {
            "level": exp.level,
            "minimum_level": exp.level,
            "reason_codes": list(exp.reason_codes),
            "risk_factors": exp.risk_factors,
            "approval_status": exp.approval_status,
            "note": exp.note,
        }
        for name, (_, exp) in sorted(CASES.items())
    }
    return (json.dumps(expected, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main() -> int:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name in sorted(CASES):
        (FIXTURE_DIR / f"{name}.input.json").write_bytes(fixture_bytes(name))
    (FIXTURE_DIR / "expected.json").write_bytes(expected_bytes())
    print(f"wrote {len(CASES)} fixtures to {FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
