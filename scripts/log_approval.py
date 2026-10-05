"""Record the operator's own approvals of AI-agent work - D-5(d-2), provisional.

Why this exists: SC-01 is stuck because the operator's inbox produces no English mail that needs a
reply. The operator does, however, approve AI-agent work every day - relaying rulings between
agents, accepting results, granting operations. D-5(d-2) (human decision, 2026-09-22) measures that
in parallel with the mail product, without touching the product.

What one record holds: which agent, what kind of approval, what the human actually did, whether
the check could have been skipped, the minutes it took, and an optional reference to what was
approved (a file name, a hash, a handoff document). Metadata only - no agent output, no prompt, no
mail body, no secret. The reference points at the approved thing; it never copies it.

What this is NOT:

- **Not SC-01-equivalent evidence on its own.** The Architect ruling of 2026-09-23 (D-5 ratified
  as d-2) requires (1) a record that lets the approved thing and the human's action be matched up
  later, (2) an assessment independent of the operator's own "could it be skipped", and (3) the
  full count including dangerous and undecidable cases, over 10+ real cases. This tool supplies
  (1) only when a reference is given, never (2), and (3) only if every approval gets logged.
  The ruling does not fix the record format, and using this one must not harden it into the spec.
- **Not a predictor.** No delegation level is predicted here; only what the human actually did.
  The question it can answer is how many checks were skippable - the baseline a delegation layer
  would have to beat.
- **Not independent.** The operator judges "could it have been skipped" themself, often right
  away. Read the rate as a self-report.

Usage:
    python scripts/log_approval.py              # asks four numbered questions
    python scripts/log_approval.py --summary
    python scripts/log_approval.py --agent "GPT Work" --kind relay --did none --safe yes --minutes 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = ROOT / "trial" / "agent-approvals" / "approvals.jsonl"
SCHEMA = "rg-agent-approval-0.1"
MAX_AGENT = 40
MAX_NOTE = 200
MAX_REF = 200
MAX_MINUTES = 600
MAX_TRIES = 3

AGENTS = ("GPT Work", "Claude Code", "Antigravity")
KINDS: dict[str, str] = {
    "relay": "裁定・報告の中継",
    "result": "作業結果の承認",
    "plan": "計画・方針の承認",
    "permission": "操作の許可",
    "other": "その他",
}
ACTIONS: dict[str, str] = {
    "none": "そのまま通した",
    "edited": "直してから通した",
    "asked": "質問・差し戻した",
    "rejected": "止めた",
}
SAFE: dict[str, str] = {
    "yes": "確認を省いても問題なかった",
    "no": "確認が必要だった",
    "unknown": "わからない",
}


class Refused(Exception):
    """Input that cannot be recorded, with the reason in Japanese."""


def _choose(ask: Callable[[str], str], title: str, options: dict[str, str]) -> str:
    keys = list(options)
    lines = [title] + [f"  {n}. {options[key]}" for n, key in enumerate(keys, 1)]
    for _ in range(MAX_TRIES):
        answer = ask("\n".join(lines) + "\n番号: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(keys):
            return keys[int(answer) - 1]
    raise Refused("番号が選ばれなかったので記録しませんでした。")


def _interactive(ask: Callable[[str], str]) -> dict[str, Any]:
    agent_options = {name: name for name in AGENTS} | {"(other)": "その他（名前を入力）"}
    agent = _choose(ask, "1. どのエージェントの作業ですか", agent_options)
    if agent == "(other)":
        agent = ask("名前: ").strip()
    kind = _choose(ask, "2. 何を承認しましたか", KINDS)
    action = _choose(ask, "3. あなたは何をしましたか", ACTIONS)
    safe = _choose(ask, "4. 振り返って、あなたの確認は省けましたか", SAFE)
    minutes = ask("かかった分数（空欄で省略）: ").strip()
    ref = ask("承認したものの参照（ファイル名・hash・依頼書名。空欄で省略。中身は貼らない）: ").strip()
    note = ask("メモ（1行・空欄で省略。本文や秘密は書かない）: ").strip()
    return {
        "agent": agent,
        "kind": kind,
        "action": action,
        "safe": safe,
        "minutes": minutes or None,
        "ref": ref or None,
        "note": note or None,
    }


def make_record(answers: dict[str, Any]) -> dict[str, Any]:
    """Validate one set of answers (keys: agent, kind, action, safe, minutes, ref, note) into a record."""
    agent = str(answers["agent"]).strip()
    kind, action, safe = answers["kind"], answers["action"], answers["safe"]
    minutes, ref, note = answers.get("minutes"), answers.get("ref"), answers.get("note")
    if not agent or len(agent) > MAX_AGENT:
        raise Refused(f"エージェント名は1〜{MAX_AGENT}文字にしてください。")
    for value, options, label in ((kind, KINDS, "kind"), (action, ACTIONS, "did"), (safe, SAFE, "safe")):
        if value not in options:
            raise Refused(f"{label} は {' / '.join(options)} のいずれかです。")
    spent: int | None = None
    if minutes is not None and str(minutes).strip():
        text = str(minutes).strip()
        if not text.isdigit() or int(text) > MAX_MINUTES:
            raise Refused(f"分数は0〜{MAX_MINUTES}の整数にしてください。")
        spent = int(text)
    for value, limit, label in ((ref, MAX_REF, "参照"), (note, MAX_NOTE, "メモ")):
        if value is not None and ("\n" in value or "\r" in value or len(value) > limit):
            raise Refused(f"{label}は改行なしの{limit}文字以内にしてください。")
    ref, note = ref or None, note or None
    return {
        "schema": SCHEMA,
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "agent": agent,
        "kind": kind,
        "action": action,
        "safe_to_skip": safe,
        "minutes": spent,
        "ref": ref,
        "note": note,
    }


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rate(numerator: int, denominator: int) -> str:
    return "N/A（分母0）" if denominator == 0 else f"{numerator / denominator:.0%}（{numerator}/{denominator}）"


def summarize(records: list[dict[str, Any]]) -> str:
    if not records:
        return "記録はまだありません。"
    safe = Counter(r["safe_to_skip"] for r in records)
    actions = Counter(r["action"] for r in records)
    agents = Counter(r["agent"] for r in records)
    timed = [r["minutes"] for r in records if r["minutes"] is not None]
    judged = safe["yes"] + safe["no"]
    referenced = sum(1 for r in records if r.get("ref"))
    lines = [
        f"記録件数: {len(records)}（{records[0]['at'][:10]} 〜 {records[-1]['at'][:10]}）",
        f"確認を省けた率: {_rate(safe['yes'], judged)}  ※「わからない」{safe['unknown']}件は分母に含めない",
        f"あなたが手を入れた率: {_rate(len(records) - actions['none'], len(records))}",
        "対応の内訳: " + " / ".join(f"{ACTIONS[k]} {actions[k]}" for k in ACTIONS),
        "エージェント別: " + " / ".join(f"{name} {count}" for name, count in agents.most_common()),
        f"かかった時間: 合計{sum(timed)}分（{len(records) - len(timed)}件は未記入）",
        f"後から照合できる件数（参照あり）: {referenced}/{len(records)}",
        "",
        "D-5(d-2) の実測（基礎資料）です。省けたかどうかはあなた自身の判定で、独立判定ではありません。",
        "SC-01 相当には、照合できる記録・独立した評価・危険/判断不能を含む全件の内訳が必要です（2026-09-23 裁定）。",
        "この集計だけでは SC-01 相当とは判定されません。",
    ]
    return "\n".join(lines)


def main(argv: list[str], ask: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(prog="log_approval", description="AIエージェントの作業をあなたが承認した記録を1件追加する（暫定）。")
    parser.add_argument("--summary", action="store_true", help="集計を表示する")
    parser.add_argument("--agent")
    parser.add_argument("--kind", choices=list(KINDS))
    parser.add_argument("--did", choices=list(ACTIONS))
    parser.add_argument("--safe", choices=list(SAFE))
    parser.add_argument("--minutes")
    parser.add_argument("--ref", help="承認したものの参照（ファイル名・hash・依頼書名）。中身は書かない")
    parser.add_argument("--note")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if "eval" in args.file.parts or "fixtures" in args.file.parts:
        parser.error("記録を eval/ や fixtures/ へ書き出さないでください（評価データと混同されます）。")

    if args.summary:
        sys.stdout.write(summarize(read_records(args.file)) + "\n")
        return 0
    try:
        if args.agent is None:
            answers = _interactive(ask)
        elif None in (args.kind, args.did, args.safe):
            raise Refused("--agent を使うときは --kind --did --safe も指定してください。")
        else:
            answers = {
                "agent": args.agent,
                "kind": args.kind,
                "action": args.did,
                "safe": args.safe,
                "minutes": args.minutes,
                "ref": args.ref,
                "note": args.note,
            }
        record = make_record(answers)
    except (Refused, EOFError, KeyboardInterrupt) as stop:
        sys.stderr.write(f"{stop}\n" if isinstance(stop, Refused) else "中断しました。記録していません。\n")
        return 1

    args.file.parent.mkdir(parents=True, exist_ok=True)
    with args.file.open("a", encoding="utf-8") as out:
        out.write(json.dumps(record, ensure_ascii=False) + "\n")
    count = len(read_records(args.file))
    sys.stdout.write(f"記録しました（{count}件目）: {record['agent']} / {KINDS[record['kind']]} / {ACTIONS[record['action']]}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
