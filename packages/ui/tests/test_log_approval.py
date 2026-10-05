"""Approval recorder for D-5(d-2) (scripts/log_approval.py) - provisional, metadata only.

What must hold: a record carries metadata and nothing else, bad input is refused with a reason
rather than written, the summary never divides by zero or hides "unknown", and nothing lands in
the evaluation data.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import log_approval as rec
import pytest


def _answers(*values: str) -> Iterator[str]:
    yield from values


def _asker(*values: str) -> Callable[[str], str]:
    stream = _answers(*values)
    return lambda _prompt: next(stream)


def _record(
    agent: str, kind: str, action: str, safe: str, minutes: str | None = None, note: str | None = None, ref: str | None = None
) -> dict[str, Any]:
    return rec.make_record({"agent": agent, "kind": kind, "action": action, "safe": safe, "minutes": minutes, "note": note, "ref": ref})


def test_numbered_answers_become_one_metadata_record(tmp_path: Path) -> None:
    target = tmp_path / "approvals.jsonl"
    # agent 1 = GPT Work, kind 1 = relay, did 1 = none, safe 1 = yes, 3 minutes, no reference, no note
    assert rec.main(["--file", str(target)], ask=_asker("1", "1", "1", "1", "3", "", "")) == 0
    [record] = rec.read_records(target)
    assert record == record | {"schema": rec.SCHEMA, "agent": "GPT Work", "kind": "relay", "action": "none"}
    assert record["safe_to_skip"] == "yes" and record["minutes"] == 3 and record["note"] is None and record["ref"] is None
    assert set(record) == {"schema", "at", "agent", "kind", "action", "safe_to_skip", "minutes", "ref", "note"}


def test_a_reference_to_the_approved_thing_is_kept_so_it_can_be_matched_later(tmp_path: Path) -> None:
    """Ruling 2026-09-23 (1): the approved thing and the human's action must be matchable later."""
    target = tmp_path / "approvals.jsonl"
    ref = "handoff/GPT_WORK_DECISION_REQUEST_2026-09-20_2.md"
    assert rec.main(["--file", str(target)], ask=_asker("1", "1", "1", "1", "", ref, "")) == 0
    assert rec.read_records(target)[0]["ref"] == ref


def test_an_agent_not_on_the_list_can_be_named(tmp_path: Path) -> None:
    target = tmp_path / "approvals.jsonl"
    assert rec.main(["--file", str(target)], ask=_asker("4", "Gemini", "2", "2", "3", "", "", "")) == 0
    assert rec.read_records(target)[0]["agent"] == "Gemini"


def test_three_wrong_numbers_record_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "approvals.jsonl"
    assert rec.main(["--file", str(target)], ask=_asker("9", "x", "")) == 1
    assert not target.exists()
    assert "記録しませんでした" in capsys.readouterr().err


def test_closing_the_prompt_records_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def closed(_prompt: str) -> str:
        raise EOFError

    target = tmp_path / "approvals.jsonl"
    assert rec.main(["--file", str(target)], ask=closed) == 1
    assert not target.exists()
    assert "記録していません" in capsys.readouterr().err


def test_flags_work_without_questions(tmp_path: Path) -> None:
    target = tmp_path / "approvals.jsonl"
    argv = ["--file", str(target), "--agent", "Claude Code", "--kind", "result", "--did", "edited", "--safe", "no"]
    assert rec.main(argv, ask=_asker()) == 0
    assert rec.read_records(target)[0]["action"] == "edited"


def test_partial_flags_are_refused(tmp_path: Path) -> None:
    assert rec.main(["--file", str(tmp_path / "a.jsonl"), "--agent", "Claude Code"], ask=_asker()) == 1


@pytest.mark.parametrize(
    ("minutes", "note"),
    [("-1", None), ("601", None), ("three", None), (None, "two\nlines"), (None, "x" * 201)],
)
def test_bad_values_are_refused(minutes: str | None, note: str | None) -> None:
    with pytest.raises(rec.Refused):
        _record("Claude Code", "result", "none", "yes", minutes, note)


@pytest.mark.parametrize("ref", ["pasted\nagent output", "x" * 201])
def test_a_reference_that_looks_like_pasted_content_is_refused(ref: str) -> None:
    """A reference points at the approved thing; a multi-line or long value is content, not a pointer."""
    with pytest.raises(rec.Refused):
        _record("Claude Code", "result", "none", "yes", ref=ref)


def test_records_append_rather_than_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "approvals.jsonl"
    for _ in range(3):
        rec.main(["--file", str(target), "--agent", "GPT Work", "--kind", "relay", "--did", "none", "--safe", "yes"], ask=_asker())
    assert len(rec.read_records(target)) == 3
    assert all(json.loads(line) for line in target.read_text(encoding="utf-8").splitlines())


def test_the_summary_keeps_unknown_out_of_the_denominator() -> None:
    records = [
        _record("GPT Work", "relay", "none", "yes", "2", ref="handoff/a.md"),
        _record("GPT Work", "relay", "none", "yes", None),
        _record("Claude Code", "result", "edited", "no", "10"),
        _record("Antigravity", "plan", "asked", "unknown", "5"),
    ]
    text = rec.summarize(records)
    assert "確認を省けた率: 67%（2/3）" in text
    assert "「わからない」1件" in text
    assert "あなたが手を入れた率: 50%（2/4）" in text
    assert "合計17分（1件は未記入）" in text
    assert "後から照合できる件数（参照あり）: 1/4" in text
    assert "独立判定ではありません" in text
    assert "この集計だけでは SC-01 相当とは判定されません" in text


def test_a_summary_with_nothing_judged_says_not_applicable() -> None:
    text = rec.summarize([_record("GPT Work", "relay", "none", "unknown", None)])
    assert "N/A（分母0）" in text


def test_an_empty_log_is_said_plainly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert rec.main(["--file", str(tmp_path / "none.jsonl"), "--summary"]) == 0
    assert "記録はまだありません" in capsys.readouterr().out


def test_the_recorder_refuses_to_write_into_evaluation_data(capsys: pytest.CaptureFixture[str]) -> None:
    for target in ("eval/approvals.jsonl", "fixtures/approvals.jsonl"):
        with pytest.raises(SystemExit):
            rec.main(["--file", target, "--summary"])
        assert "評価データと混同" in capsys.readouterr().err
