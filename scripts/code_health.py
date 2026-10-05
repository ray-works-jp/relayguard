"""Cheap refactoring triage: find hotspots without reading the code.

Prints a short report (standard library only, no LLM): largest files, longest and most
branchy functions, and function bodies duplicated across files. Read only what it lists.

    python scripts/code_health.py [--top 15]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".venv", "build", "dist", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", "node_modules"}
BRANCHES = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.BoolOp, ast.IfExp, ast.comprehension, ast.Match)


def sources() -> list[Path]:
    return [p for p in ROOT.rglob("*.py") if not SKIP & set(p.relative_to(ROOT).parts)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--tests", action="store_true", help="include tests")
    top = parser.parse_args()
    files = [p for p in sources() if top.tests or "tests" not in p.parts]

    sizes: list[tuple[int, str]] = []
    funcs: list[tuple[int, int, str]] = []
    bodies: dict[str, list[str]] = defaultdict(list)
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        sizes.append((text.count("\n") + 1, rel))
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                branches = sum(isinstance(n, BRANCHES) for n in ast.walk(node))
                where = f"{rel}:{node.lineno} {node.name}"
                funcs.append((length, branches, where))
                if length >= 6:
                    body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
                    bodies[hashlib.sha256(body.encode()).hexdigest()].append(where)

    print(f"# files={len(files)} lines={sum(s for s, _ in sizes)} functions={len(funcs)}\n")
    print("## largest files")
    for n, rel in sorted(sizes, reverse=True)[: top.top]:
        print(f"{n:6}  {rel}")
    print("\n## longest functions (lines, branches)")
    for length, branches, where in sorted(funcs, reverse=True)[: top.top]:
        print(f"{length:4} {branches:3}  {where}")
    print("\n## most branchy functions (branches, lines)")
    for length, branches, where in sorted(funcs, key=lambda f: (f[1], f[0]), reverse=True)[: top.top]:
        print(f"{branches:4} {length:4}  {where}")
    dupes = [w for w in bodies.values() if len(w) > 1]
    print(f"\n## identical function bodies ({len(dupes)} groups)")
    for group in dupes[: top.top]:
        print("  " + " == ".join(group))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
