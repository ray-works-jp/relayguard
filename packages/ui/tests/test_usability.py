"""The screens tell a first-time operator where they are and what to press next.

Display only: every check here reads pages and view models. Nothing about the decision, the
checks or the delegation level changes, and the pages still never say the reply is safe.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from relayguard_ui.api_key import SessionKey, client_factory
from relayguard_ui.app import create_app
from relayguard_ui.interpreter import ClaudeInterpreter
from relayguard_ui.service import CaseService, CaseState
from relayguard_ui.view import STEP_LABELS, progress

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "eval" / "release-set-candidates" / "inputs"
STATIC = ROOT / "packages" / "ui" / "relayguard_ui" / "static"
TOKEN = "usability-test-token-value"
KEY = "sk-ant-api03-" + "u" * 60
PLAIN_EML = b"From: a@example.com\nSubject: Refund\nContent-Type: text/plain\n\nPlease refund USD 49.00.\n"


def web(*, llm: bool = False, samples: bool = True, key: SessionKey | None = None) -> TestClient:
    interpreter = ClaudeInterpreter(client_factory(key)) if key is not None else ClaudeInterpreter() if llm else None
    app = create_app(
        CaseService("op_usability"),
        access_token=TOKEN,
        samples_dir=SAMPLES if samples else None,
        interpreter=interpreter,
        api_key=key,
    )
    client = TestClient(app)
    client.get(f"/login?token={TOKEN}")
    return client


def _csrf(client: TestClient) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', client.get("/new").text)
    assert match
    return match.group(1)


# --- home ---------------------------------------------------------------------------------------


def test_home_leads_with_the_new_mail_button_and_an_empty_state() -> None:
    html = web().get("/").text
    assert 'class="cta" href="/new"' in html
    assert "案件はまだありません" in html
    for label in ("メールを追加", "解析", "確認・承認"):
        assert label in html
    assert 'name="name" value="RG-EVAL-011.input.json"' in html
    assert "サンプル案件を開いて試す" not in web(samples=False).get("/").text


def test_the_case_list_uses_plain_words_and_still_says_cases_vanish() -> None:
    client = web()
    client.post("/cases/import-sample", data={"csrf": _csrf(client), "name": "RG-EVAL-011.input.json"})
    html = client.get("/").text
    assert "任せられる範囲" in html and "承認が必要" in html
    visible = re.sub(r"<[^>]+>", " ", html)
    assert "L2" not in visible and "事前判定" not in visible
    assert "閉じると" in html and "消えます" in html


def test_the_sample_button_opens_a_case() -> None:
    client = web()
    response = client.post("/cases/import-sample", data={"csrf": _csrf(client), "name": "RG-EVAL-011.input.json"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/cases/RG-EVAL-011"


def test_the_navigation_marks_the_current_page() -> None:
    client = web(llm=True)
    for path, label in (("/", "案件"), ("/new", "新しいメール"), ("/settings", "設定")):
        html = client.get(path).text
        assert re.search(rf'href="{path}" aria-current="page">{label}<', html), path


# --- /new -------------------------------------------------------------------------------------


def test_new_opens_on_automatic_and_offers_the_key_right_there() -> None:
    html = web(key=SessionKey()).get("/new").text
    assert re.search(r'href="/new" aria-current="page">自動解析', html)
    assert 'action="/settings/api-key"' in html and 'name="back" value="new"' in html
    assert 'action="/cases/import-manual"' not in html


def test_with_a_key_the_automatic_tab_is_one_paste_box_and_one_button() -> None:
    key = SessionKey()
    key.set(KEY)
    html = web(key=key).get("/new").text
    assert "APIキー設定済み" in html and 'action="/settings/api-key"' not in html
    form = html.split('action="/cases/interpret"', 1)[1].split("</form>", 1)[0]
    assert form.count("<textarea") == 1 and "解析する" in form
    assert re.search(r'action="/cases/interpret" data-busy="[^"]*最大5分', html)


def test_an_unknown_mode_falls_back_to_the_automatic_tab() -> None:
    html = web(llm=True).get("/new?mode=../../settings").text
    assert re.search(r'href="/new" aria-current="page">', html)


def test_without_an_interpreter_new_opens_on_the_manual_tab() -> None:
    html = web().get("/new").text
    assert re.search(r'href="/new\?mode=manual" aria-current="page">', html)
    assert 'action="/cases/import-manual"' in html


def test_the_manual_tab_builds_cards_from_a_template_with_the_existing_field_names() -> None:
    html = web(llm=True).get("/new?mode=manual").text
    assert "選択した部分を引用として追加" in html and "＋ 項目を追加" in html
    # No pre-rendered "unused" rows: cards come from the template, numbered by app.js.
    assert 'name="kind_1"' not in html and "（使わない）" not in html
    template = html.split("<template data-item-template>", 1)[1].split("</template>", 1)[0]
    for field in ("kind", "quote", "text", "amount", "currency", "money_type", "date", "timezone", "date_type"):
        assert f'data-field="{field}"' in template
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "field.name = `${field.dataset.field}_${n}`" in script
    assert "MAX_ITEMS = 6" in script


def test_reading_an_eml_fills_the_same_tab_and_creates_nothing() -> None:
    calls: list[str] = []

    class Spy(ClaudeInterpreter):
        def interpret_into_case(self, *args: object, **kwargs: object) -> object:  # type: ignore[override]
            calls.append("called")
            raise AssertionError("reading a file must not interpret it")

    for mode, tab in (
        ("auto", 'href="/new" aria-current="page"'),
        ("manual", 'href="/new?mode=manual" aria-current="page"'),
        ("x", 'href="/new" aria-current="page"'),
    ):
        app = create_app(CaseService("op_usability"), access_token=TOKEN, interpreter=Spy())
        client = TestClient(app)
        client.get(f"/login?token={TOKEN}")
        response = client.post(
            "/cases/read-eml", data={"csrf": _csrf(client), "mode": mode}, files={"file": ("mail.eml", PLAIN_EML, "message/rfc822")}
        )
        assert response.status_code == 200
        assert tab in response.text, mode
        assert "Please refund USD 49.00." in response.text
        assert "ファイルから読み込みました" in response.text
        assert "案件はまだありません" in client.get("/").text
        bad = client.post("/cases/read-eml", data={"csrf": _csrf(client), "mode": mode}, files={"file": ("x.eml", b"", "message/rfc822")})
        assert bad.status_code == 400 and tab in bad.text and 'role="alert"' in bad.text
    assert calls == []


# --- settings and case page ---------------------------------------------------------------------


def test_settings_holds_the_self_check_and_the_developer_tools() -> None:
    html = web(llm=True).get("/settings").text
    assert 'href="/self-check"' in html
    assert "サンプル案件を開く" in html and "JSONから案件を作成" in html
    assert 'href="/self-check"' not in web(llm=True).get("/").text


def test_the_case_page_marks_the_current_step_for_screen_readers() -> None:
    client = web()
    client.post("/cases/import-sample", data={"csrf": _csrf(client), "name": "RG-EVAL-011.input.json"})
    html = client.get("/cases/RG-EVAL-011").text
    assert html.count('aria-current="step"') == 1
    assert "いまやること:" in html
    assert "（いまここ）" in html
    assert 'data-busy="返信案を作って検査しています' in html


def test_both_themes_declare_their_own_color_scheme() -> None:
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    light, dark = css.split("@media (prefers-color-scheme: dark)", 1)
    assert "color-scheme: light;" in light
    assert "color-scheme: dark;" in dark.split("}", 2)[0] + dark.split("}", 2)[1]
    assert "light dark" not in css
    for selector in (
        'input[type="text"]',
        'input[type="password"]',
        'input[type="file"]',
        'input[type="search"]',
        "::file-selector-button",
        ":-webkit-autofill",
    ):
        assert selector in css


def test_progress_follows_the_state_and_never_skips_a_stop() -> None:
    service = CaseService("op_usability")
    record = service.import_shadow_input((SAMPLES / "RG-EVAL-011.input.json").read_bytes())
    expected = {
        CaseState.DELEGATION_ASSESSED: ["done", "done", "current", "todo"],
        CaseState.BLOCKED: ["done", "done", "stopped", "todo"],
        CaseState.STOPPED: ["done", "done", "stopped", "todo"],
        CaseState.SAFE_CANDIDATE: ["done", "done", "done", "current"],
        CaseState.FINAL_APPROVED: ["done", "done", "done", "current"],
        CaseState.COPIED: ["done", "done", "done", "done"],
    }
    for state, marks in expected.items():
        record.state = state
        shown = progress(record)
        assert [label for label, _ in shown.statuses] == list(STEP_LABELS)
        assert [mark for _, mark in shown.statuses] == marks, state
        assert shown.hint
        assert "安全です" not in shown.hint


def test_a_user_case_waiting_for_the_decision_says_which_button_to_press() -> None:
    service = CaseService("op_usability")
    record = service.import_shadow_input((SAMPLES / "RG-EVAL-011.input.json").read_bytes())
    record.state, record.origin = CaseState.DECISION_REQUIRED, "user"
    shown = progress(record)
    assert [mark for _, mark in shown.statuses] == ["done", "current", "todo", "todo"]
    assert "この判断で確定する" in shown.hint
