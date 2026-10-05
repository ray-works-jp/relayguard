"""CLI: python -m relayguard <shadow_core_input.json>

Prints the ShadowCoreResult JSON. Exit code 0 = assessed, 1 = rejected, 2 = usage error.
No network access and no external action.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .shadow_core import run_shadow_core


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: python -m relayguard <shadow_core_input.json>\n")
        return 2
    try:
        raw = Path(argv[0]).read_bytes()
    except OSError:
        sys.stderr.write("error: input file cannot be read\n")
        return 2
    result = run_shadow_core(raw)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0 if result["status"] == "assessed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
