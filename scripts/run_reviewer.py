#!/usr/bin/env python3
"""Start the RelayGuard local reviewer from a source checkout (no installation step).

Usage: python scripts/run_reviewer.py --operator YOUR_ID [--port 8765] [--samples DIR] [--token TOKEN]
Defaults --samples to the bundled synthetic release-set cases.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "packages" / "core"), str(_ROOT / "packages" / "ui")]

from relayguard_ui.__main__ import main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--samples" not in argv:
        argv += ["--samples", str(_ROOT / "eval" / "release-set-candidates" / "inputs")]
    raise SystemExit(main(argv))
