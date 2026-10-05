"""Fixes for the 0.1.0 manual E2E observations (GPT Work ruling 2026-09-26: #1, #6, #7, #8, #9).

Display only: no check, level or state transition changes here.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from relayguard_ui.api_key import SessionKey, client_factory
from relayguard_ui.app import create_app
from relayguard_ui.interpreter import ClaudeInterpreter
from relayguard_ui.labels import STATE_NEXT_ACTIONS, STOP_AFTER_EDIT, STOP_AFTER_GENERATE, STOP_NEUTRAL
from relayguard_ui.selfcheck import CheckSetup, run_checks
from relayguard_ui.service import CaseService, CaseState
from relayguard_ui.view import next_steps, progress, reply_edited, reply_origin_event, stop_guidance

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "eval" / "release-set-candidates" / "inputs"
TOKEN = "e2e-fixes-test-token-value"
SAMPLE = "RG-EVAL-011.input.json"


def web(key: SessionKey | None = None) -> TestClient:
    key = key if key is not None else SessionKey()
    app = create_app(
        CaseService("op_e2e"),
        access_token=TOKEN,
        samples_dir=SAMPLES,
        interpreter=ClaudeInterpreter(client_factory(key)),
        api_key=key,
    )
    client = TestClient(app)
    client.get(f"/login?token={TOKEN}")
    return client


def _csrf(client: TestClient) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', client.get("/new").text)
    assert match
    return match.group(1)


def _revision(html: str) -> str:
    match = re.search(r'name="revision" value="(\d+)"', html)
    assert match
    return match.group(1)


# --- #1 the browser may offer to save the key --------------------------------------------------


def test_both_key_forms_keep_a_password_field_and_warn_about_browser_saving() -> None:
    client = web()
    for path in ("/new", "/settings"):
        html = client.get(path).text
        assert 'type="password" name="key"' in html, path
        assert "data-key-browser-note" in html and "「保存しない」を選んでください" in html, path
    for doc in ("packaging/windows/README-ja.txt", "docs/distribution/PRIVACY-ja.md"):
        assert "「保存しない」を選んでください" in (ROOT / doc).read_text(encoding="utf-8"), doc


# --- #8 / #9 self-check from the screen ---------------------------------------------------------


def test_the_screen_check_skips_the_port_and_advises_only_the_on_screen_key() -> None:
    html = web().get("/self-check").text
    assert "ポート 0" not in html
    assert "ポートの空き確認は省略しました" in html
    assert "設定する" in html and "$env:" not in html and "setx" not in html


def test_the_pre_start_check_still_probes_the_port() -> None:
    results = {r.name: r for r in run_checks(CheckSetup(root=ROOT, samples_dir=SAMPLES, port=0, live=False, key=lambda: ""))}
    assert not results["ポート"].skipped and "省略" not in results["ポート"].detail


# --- #6 next action follows the state -------------------------------------------------------------


def test_after_approval_the_next_action_follows_the_state_not_the_level() -> None:
    service = CaseService("op_e2e")
    record = service.import_shadow_input((SAMPLES / SAMPLE).read_bytes())
    service.generate(record.case_id, record.revision)
    assert record.state == CaseState.SAFE_CANDIDATE
    for state in (CaseState.FINAL_APPROVED, CaseState.COPIED):
        record.state = state
        steps = next_steps(record)
        assert steps == [STATE_NEXT_ACTIONS[str(state)]]
        assert not any("最終承認してから" in step for step in steps)
        assert progress(record).hint == STATE_NEXT_ACTIONS[str(state)]


# --- #7 stop guidance by cause, never by screen position ------------------------------------------


def test_a_stop_after_an_own_edit_says_to_undo_the_edit() -> None:
    client = web()
    client.post("/cases/import-sample", data={"csrf": _csrf(client), "name": SAMPLE})
    page = client.get("/cases/RG-EVAL-011").text
    client.post("/cases/RG-EVAL-011/generate", data={"csrf": _csrf(client), "revision": _revision(page)})
    page = client.get("/cases/RG-EVAL-011").text
    reply = re.search(r'<textarea name="reply_text"[^>]*>([^<]*)</textarea>', page)
    assert reply
    edited = reply.group(1).replace("&#39;", "'").replace("&amp;", "&") + "\nWe will also pay USD 500.\n"
    client.post("/cases/RG-EVAL-011/draft", data={"csrf": _csrf(client), "revision": _revision(page), "reply_text": edited})
    page = client.get("/cases/RG-EVAL-011").text
    assert "編集内容で再検査" in page
    assert STOP_AFTER_EDIT in page
    assert "上の「あなたの判断」" not in page


def test_the_stop_wording_depends_on_whether_the_reply_was_edited() -> None:
    service = CaseService("op_e2e")
    record = service.import_shadow_input((SAMPLES / SAMPLE).read_bytes())
    service.generate(record.case_id, record.revision)
    assert not reply_edited(record) and stop_guidance(record) == STOP_AFTER_GENERATE
    assert record.draft is not None
    service.edit_draft(record.case_id, record.revision, record.draft["reply_text"] + "\nWe will also pay USD 500.\n")
    assert record.state == CaseState.BLOCKED
    assert reply_edited(record) and stop_guidance(record) == STOP_AFTER_EDIT
    assert progress(record).hint == STOP_AFTER_EDIT
    service.generate(record.case_id, record.revision)
    assert not reply_edited(record)
    for text in (STOP_AFTER_EDIT, STOP_AFTER_GENERATE):
        assert "上の" not in text and "1. 相手の要求と、あなたの判断" in text


# --- 0.1.2: the stop wording never asserts the cause (GPT Work ruling 2026-09-26) ------------------


def _generated_sample() -> tuple[CaseService, str]:
    service = CaseService("op_e2e")
    record = service.import_shadow_input((SAMPLES / SAMPLE).read_bytes())
    service.generate(record.case_id, record.revision)
    return service, record.case_id


def test_deleting_an_approved_condition_stops_as_condition_removed_with_neutral_edit_wording() -> None:
    service, case_id = _generated_sample()
    record = service.get(case_id)
    assert record.draft is not None
    lines = record.draft["reply_text"].split("\n")
    assert any(line.startswith("- Condition:") for line in lines), "RG-EVAL-011 carries an approved condition"
    service.edit_draft(case_id, record.revision, "\n".join(line for line in lines if not line.startswith("- Condition:")))
    assert record.state == CaseState.BLOCKED
    assert record.verification is not None
    types = {finding["type"] for finding in record.verification["proposal"]["findings"]}
    assert "condition_removed" in types
    assert stop_guidance(record) == STOP_AFTER_EDIT
    for text in (STOP_AFTER_EDIT, STOP_AFTER_GENERATE, STOP_NEUTRAL):
        assert "決めていない内容が含まれています" not in text  # a missing approved line is not an addition
        assert "対応" in text


def test_an_event_that_does_not_match_the_current_draft_hash_gives_neutral_wording() -> None:
    service, case_id = _generated_sample()
    record = service.get(case_id)
    assert record.draft is not None
    service.edit_draft(case_id, record.revision, record.draft["reply_text"] + "\nWe will also pay USD 500.\n")
    assert reply_origin_event(record) == "edited"
    record.draft = {**record.draft, "draft_hash": "0" * 64}  # same id, different hash: not attributable
    assert reply_origin_event(record) == "" and not reply_edited(record)
    assert stop_guidance(record) == STOP_NEUTRAL
