"""Error-handling audit 2026-09-23: every failure path ends in a Rejection or a Japanese page, never a traceback.

Found by type-mutating a valid Interpretation 2,224 ways: 35 raised AttributeError/TypeError out of
import_interpretation, which turned an LLM output with a null ``state`` into a server error - no repair
attempt, and the pasted mail gone.
"""

from __future__ import annotations

import copy
import json
import logging
import socket
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from relayguard.errors import Rejection
from relayguard_ui import __main__ as entry
from relayguard_ui import eml
from relayguard_ui.app import create_app
from relayguard_ui.interpreter import ClaudeInterpreter
from relayguard_ui.service import CaseService, CaseState

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "fixtures" / "sg001" / "l2_answer_from_source_evidence.input.json").read_text(encoding="utf-8"))
BODY = FIXTURE["source_message"]["body"]
TOKEN = "t" * 20


def _mutated(path: tuple[Any, ...], value: Any) -> bytes:
    document = copy.deepcopy(FIXTURE["interpretation"])
    node = document
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return json.dumps(document).encode("utf-8")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("state",), None),
        (("state",), []),
        (("state", "evidence"), None),
        (("state", "questions", 0, "id"), []),
        (("state", "sender_intent", 0, "id"), {}),
    ],
)
def test_wrong_types_in_an_interpretation_are_a_rejection_and_store_nothing(path: tuple[Any, ...], value: Any) -> None:
    service = CaseService("op_err")
    with pytest.raises(Rejection) as exc:
        service.import_interpretation("s", BODY, _mutated(path, value))
    assert exc.value.code == "SchemaInvalid"
    assert service.list_cases() == []


class _Stream:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome

    def __enter__(self) -> _Stream:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get_final_message(self) -> Any:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _Client:
    def __init__(self, *outcomes: Any) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0
        self.beta = self
        self.models = self

    @property
    def messages(self) -> _Client:
        return self

    def stream(self, **_request: Any) -> _Stream:
        self.calls += 1
        return _Stream(self._outcomes.pop(0))


def _reply(text: str) -> Any:
    block = type("Block", (), {"type": "text", "text": text})()
    return type("Response", (), {"content": [block], "stop_reason": "end_turn"})()


def test_a_null_state_from_the_model_gets_the_repair_attempt() -> None:
    good = json.loads(json.dumps(FIXTURE["interpretation"]))
    client = _Client(_reply(_mutated(("state",), None).decode()), _reply(json.dumps(good)))
    record = ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_err"), None, BODY)  # type: ignore[arg-type,return-value]
    assert record.state == CaseState.DECISION_REQUIRED
    assert client.calls == 2


def test_an_unexpected_sdk_error_is_provider_unavailable_and_logs_the_type_only(caplog: pytest.LogCaptureFixture) -> None:
    client = _Client(RuntimeError("secret mail text"))
    with caplog.at_level(logging.WARNING), pytest.raises(Rejection) as exc:
        ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_err"), None, BODY)  # type: ignore[arg-type,return-value]
    assert exc.value.code == "ProviderUnavailable"
    assert "RuntimeError" in caplog.text
    assert "secret mail text" not in caplog.text


def test_a_parser_crash_on_a_hostile_eml_is_unsupported_input(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise IndexError("header parser bug")

    monkeypatch.setattr(eml, "message_from_bytes", explode)
    with pytest.raises(Rejection) as exc:
        eml.parse_eml(b"Subject: x\n\nbody")
    assert exc.value.code == "UnsupportedInput"


def _web(service: CaseService) -> TestClient:
    web = TestClient(create_app(service, access_token=TOKEN), raise_server_exceptions=False)
    web.get(f"/login?token={TOKEN}")
    return web


def test_a_crashing_route_answers_in_japanese_without_the_exception_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    service = CaseService("op_err")

    def crash() -> Any:
        raise RuntimeError("secret mail text")

    monkeypatch.setattr(service, "list_cases", crash)
    with caplog.at_level(logging.ERROR):
        response = _web(service).get("/")
    assert response.status_code == 500
    # P-6: a crash can follow a state change, so the page must not claim nothing was approved/copied.
    assert "操作結果を確認できません" in response.text
    assert "行われていません" not in response.text
    assert "secret mail text" not in response.text + caplog.text
    assert "RuntimeError" in caplog.text
    assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")


def test_a_missing_form_field_is_a_japanese_400_not_a_json_dump() -> None:
    response = _web(CaseService("op_err")).post("/cases/missing/generate", data={"csrf": "x"})
    assert response.status_code == 400
    assert "入力を受け付けられませんでした" in response.text
    assert "detail" not in response.text


def test_an_unknown_page_is_a_japanese_404() -> None:
    response = _web(CaseService("op_err")).get("/no-such-page")
    assert response.status_code == 404
    assert "見つかりません" in response.text


def test_a_wrong_method_is_a_japanese_405() -> None:
    response = _web(CaseService("op_err")).put("/")
    assert response.status_code == 405
    assert "この操作方法は使えません" in response.text


def test_a_busy_port_stops_before_the_login_url_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        port = busy.getsockname()[1]
        assert entry.main(["--operator", "op_err", "--port", str(port)]) == 2
    out = capsys.readouterr()
    assert "login?token" not in out.out
    assert f"ポート {port} は使用中です" in out.err
    assert "別の --port" in out.err
    assert "自動で空きポート" not in out.err
