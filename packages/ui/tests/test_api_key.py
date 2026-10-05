"""An API key entered on the screen: memory only, never echoed, never logged, never a silent env fallback."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from relayguard.errors import Rejection
from relayguard_ui import api_key as api_key_module
from relayguard_ui.api_key import SessionKey, client_factory
from relayguard_ui.app import create_app
from relayguard_ui.interpreter import ClaudeInterpreter
from relayguard_ui.service import CaseService

ROOT = Path(__file__).resolve().parents[3]
TOKEN = "api-key-test-token-value"
KEY = "sk-ant-api03-" + "k" * 60
ENV_KEY = "sk-ant-api03-" + "e" * 60


def test_a_key_must_look_like_a_key_and_the_refusal_does_not_repeat_it() -> None:
    key = SessionKey()
    for junk in ("", "   ", "hello world", "https://example.com/?q=1", "sk-ant-short", "Dear team, please refund"):
        with pytest.raises(Rejection) as exc:
            key.set(junk)
        if junk.strip():
            assert junk.strip() not in exc.value.explanation_ja
    assert not key.available()


def test_set_and_clear() -> None:
    key = SessionKey()
    key.set(f"  {KEY}\n")
    assert key.value() == KEY and key.source() == "screen"
    key.clear()
    assert key.value() is None and key.source() is None


def test_an_environment_key_counts_only_when_the_operator_asked_for_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", ENV_KEY)
    assert SessionKey().value() is None
    assert SessionKey(env_allowed=True).value() == ENV_KEY
    both = SessionKey(env_allowed=True)
    both.set(KEY)
    assert both.value() == KEY and both.source() == "screen"


def test_the_client_factory_never_falls_back_to_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", ENV_KEY)
    seen: list[str | None] = []

    def fake_client(value: str | None = None) -> object:
        seen.append(value)
        return object()

    monkeypatch.setattr(api_key_module, "default_client", fake_client)
    key = SessionKey()
    build = client_factory(key)
    with pytest.raises(Rejection) as exc:
        build()
    assert exc.value.code == "ProviderUnavailable" and seen == []
    key.set(KEY)
    build()
    assert seen == [KEY]


def web(key: SessionKey) -> TestClient:
    app = create_app(CaseService("op_key"), access_token=TOKEN, interpreter=ClaudeInterpreter(client_factory(key)), api_key=key)
    client = TestClient(app)
    client.get(f"/login?token={TOKEN}")
    return client


def csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_without_a_key_the_page_asks_for_one_and_offers_no_interpret_form() -> None:
    html = web(SessionKey()).get("/new").text
    assert 'action="/settings/api-key"' in html
    assert 'type="password" name="key" autocomplete="off"' in html
    assert 'action="/cases/interpret"' not in html
    # The key-free path stays one click away.
    assert 'href="/new?mode=manual"' in html


def test_after_a_key_change_the_page_returns_only_to_one_of_two_fixed_pages() -> None:
    client = web(SessionKey())
    token = csrf(client.get("/new").text)
    for back, expected in (("new", "/new"), ("settings", "/settings"), ("https://evil.example/", "/new"), ("//evil", "/new")):
        key = SessionKey()
        client = web(key)
        token = csrf(client.get("/new").text)
        response = client.post("/settings/api-key", data={"csrf": token, "key": KEY, "consent": "1", "back": back}, follow_redirects=False)
        assert response.headers["location"] == expected, back
        cleared = client.post("/settings/api-key/clear", data={"csrf": token, "back": back}, follow_redirects=False)
        assert cleared.headers["location"] == expected, back


def test_the_settings_page_manages_the_key() -> None:
    key = SessionKey()
    client = web(key)
    html = client.get("/settings").text
    assert 'action="/settings/api-key"' in html and 'name="back" value="settings"' in html
    key.set(KEY)
    html = client.get("/settings").text
    assert 'action="/settings/api-key/clear"' in html and KEY not in html


def test_entering_a_key_turns_claude_on_and_the_key_never_comes_back_in_a_page(caplog: pytest.LogCaptureFixture) -> None:
    key = SessionKey()
    client = web(key)
    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/settings/api-key", data={"csrf": csrf(client.get("/new").text), "key": KEY, "consent": "1"}, follow_redirects=False
        )
    assert response.status_code == 303
    html = client.get("/new").text
    assert 'action="/cases/interpret"' in html
    assert "APIキー設定済み" in html
    assert KEY not in html and KEY[:20] not in html
    assert KEY not in caplog.text
    assert key.value() == KEY


def test_a_bad_key_is_refused_without_echoing_what_was_pasted() -> None:
    key = SessionKey()
    client = web(key)
    pasted = "Please-refund-my-order-R2001-immediately-thanks"
    response = client.post("/settings/api-key", data={"csrf": csrf(client.get("/new").text), "key": pasted, "consent": "1"})
    assert response.status_code == 400
    assert pasted not in response.text
    assert "sk-ant-" in response.text
    assert not key.available()


def test_the_key_form_needs_the_csrf_token() -> None:
    key = SessionKey()
    client = web(key)
    response = client.post("/settings/api-key", data={"csrf": "forged", "key": KEY, "consent": "1"})
    assert response.status_code == 400
    assert not key.available()


def test_clearing_the_key_turns_claude_off_again() -> None:
    key = SessionKey()
    key.set(KEY)
    client = web(key)
    client.post("/settings/api-key/clear", data={"csrf": csrf(client.get("/new").text)})
    assert not key.available()
    assert 'action="/cases/interpret"' not in client.get("/new").text


def test_interpret_is_refused_until_a_key_is_entered() -> None:
    client = web(SessionKey())
    response = client.post(
        "/cases/interpret", data={"csrf": csrf(client.get("/new").text), "subject": "x", "body": "Hello", "consent": "1"}
    )
    assert response.status_code == 400
    assert "APIキーを入れてください" in response.text


def test_the_default_client_hands_the_key_to_the_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakeAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class FakeModule:
        Anthropic = FakeAnthropic

    monkeypatch.setitem(__import__("sys").modules, "anthropic", FakeModule)
    from relayguard_ui.interpreter import default_client  # noqa: PLC0415

    default_client(KEY)
    assert captured["api_key"] == KEY


def test_a_key_is_not_taken_without_the_consent_to_send() -> None:
    key = SessionKey()
    client = web(key)
    response = client.post("/settings/api-key", data={"csrf": csrf(client.get("/new").text), "key": KEY})
    assert response.status_code == 400
    assert "同意" in response.text
    assert not key.available()


def test_with_an_on_screen_key_the_consent_given_at_entry_covers_each_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    key = SessionKey()
    key.set(KEY)
    calls: list[str] = []

    def fake_interpret(_self: Any, _service: Any, _subject: Any, body: str) -> Any:
        calls.append(body)
        raise Rejection("ProviderUnavailable", "stub")

    monkeypatch.setattr(ClaudeInterpreter, "interpret_into_case", fake_interpret)
    client = web(key)
    html = client.get("/new").text
    assert 'name="consent"' not in html.split('action="/cases/interpret"', 1)[1].split("</form>", 1)[0]
    client.post("/cases/interpret", data={"csrf": csrf(html), "subject": "x", "body": "Hello"})
    assert calls == ["Hello"]
