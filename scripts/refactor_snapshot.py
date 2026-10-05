"""Behaviour snapshot for refactoring a pure function: record real calls, replay them later.

    python scripts/refactor_snapshot.py record <corpus.pkl>   # before the refactor
    python scripts/refactor_snapshot.py replay <corpus.pkl>   # after: exit 1 on any difference

``record`` runs the whole pytest suite and scripts/fuzz_extractor.py with the target wrapped,
and keeps every distinct (input, output) pair. ``replay`` calls the current code with each
recorded input, requires an identical output (finding order and IDs included), and lists the
target's source lines the corpus never executed - a refactor there is not covered.

The corpus holds synthetic test mail text only. Keep it outside the repository (scratchpad).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import inspect
import pickle
import runpy
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import FrameType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for sub in ("packages/core", "packages/ui", "packages/evaluation"):
    sys.path.insert(0, str(ROOT / sub))

# name -> (module defining it, modules that imported it by name and must see the wrapper)
TARGETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "compute_diff": ("relayguard.diff_engine", ("relayguard.verifier",)),
    "_claim_hits": ("relayguard.delegation", ()),
}


def _record(target: str, out: Path) -> int:
    import pytest  # noqa: PLC0415 - only needed for recording

    home, users = TARGETS[target]
    original: Callable[..., Any] = getattr(importlib.import_module(home), target)
    corpus: dict[str, tuple[tuple[Any, ...], Any]] = {}

    def wrapper(*args: Any) -> Any:
        frozen = copy.deepcopy(args)
        result = original(*args)
        if isinstance(result, Iterator):  # a generator: keep the yielded items, in order
            result = list(result)
            corpus.setdefault(hashlib.sha256(pickle.dumps(frozen)).hexdigest(), (frozen, copy.deepcopy(result)))
            return iter(result)
        blob = pickle.dumps(frozen)
        corpus.setdefault(hashlib.sha256(blob).hexdigest(), (frozen, copy.deepcopy(result)))
        return result

    for name in (home, *users):
        setattr(importlib.import_module(name), target, wrapper)
    code = pytest.main(["-q", "-p", "no:cacheprovider", "-x", str(ROOT)])
    sys.argv = [str(ROOT / "scripts" / "fuzz_extractor.py")]  # the fuzz script parses its own argv
    try:
        runpy.run_path(str(ROOT / "scripts" / "fuzz_extractor.py"), run_name="__main__")
    except SystemExit as stop:
        code = code or int(stop.code or 0)
    out.write_bytes(pickle.dumps({"target": target, "calls": list(corpus.values())}))
    print(f"recorded {len(corpus)} distinct calls of {target} -> {out} (pytest/fuzz exit {code})")
    return int(code)


def _replay(out: Path) -> int:
    # Safe here: the corpus is a file this script wrote on this PC in record mode; never replay one received from elsewhere.
    data = pickle.loads(out.read_bytes())  # noqa: S301
    target: str = data["target"]
    module = importlib.import_module(TARGETS[target][0])
    function: Callable[..., Any] = getattr(module, target)
    source_file = inspect.getsourcefile(module)
    executed: set[int] = set()

    def tracer(frame: FrameType, event: str, _arg: object) -> Any:
        if frame.f_code.co_filename != source_file:
            return None
        if event == "line":
            executed.add(frame.f_lineno)
        return tracer

    mismatches = 0
    sys.settrace(tracer)
    try:
        for args, expected in data["calls"]:
            got = function(*copy.deepcopy(args))
            if (list(got) if isinstance(got, Iterator) else got) != expected:
                mismatches += 1
    finally:
        sys.settrace(None)

    lines = inspect.getsource(module).splitlines()
    code_lines = {
        i
        for i, text in enumerate(lines, start=1)
        if text.strip() and not text.strip().startswith(("#", '"', ")", "]", "}", "else:", "try:", "finally:"))
    }
    never = sorted(n for n in _body_lines(module) & code_lines if n not in executed)
    print(f"{target}: {len(data['calls'])} recorded calls, {mismatches} mismatches")
    print(f"lines inside {Path(source_file or '').name} functions never executed by the corpus: {never or 'none'}")
    return 1 if mismatches else 0


def _body_lines(module: Any) -> set[int]:
    """Lines inside the module's function bodies (definitions and signatures excluded)."""
    import ast  # noqa: PLC0415

    tree = ast.parse(inspect.getsource(module))
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for stmt in node.body:
                found.update(range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1))
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("record", "replay"))
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--target", default="compute_diff", choices=sorted(TARGETS))
    args = parser.parse_args()
    return _record(args.target, args.corpus) if args.mode == "record" else _replay(args.corpus)


if __name__ == "__main__":
    raise SystemExit(main())
