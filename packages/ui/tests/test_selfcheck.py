"""Pre-flight self check (relayguard_ui/selfcheck.py).

Each failure must name a fix in Japanese: the operator has nobody to ask, and every problem this
catches was hit for real during the first trial run.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from relayguard.errors import Rejection
from relayguard_ui.interpreter import MODEL
from relayguard_ui.selfcheck import CheckSetup, any_failed, format_report, run_checks


@dataclass
class FakeModel:
    id: str


@dataclass
class FakeModels:
    data: list[FakeModel] = field(default_factory=lambda: [FakeModel(MODEL)])

    def list(self, **_kwargs: Any) -> FakeModels:
        return self


@dataclass
class FakeStream:
    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def get_final_message(self) -> object:
        return object()


@dataclass
class FakeMessages:
    def stream(self, **_kwargs: Any) -> FakeStream:
        return FakeStream()


@dataclass
class FakeBeta:
    messages: FakeMessages = field(default_factory=FakeMessages)


@dataclass
class FakeClient:
    beta: FakeBeta = field(default_factory=FakeBeta)
    models: FakeModels = field(default_factory=FakeModels)


ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "eval" / "release-set-candidates" / "inputs"
KEY = "sk-ant-" + "a" * 60


def healthy_client() -> FakeClient:
    return FakeClient()


def setup(**overrides: Any) -> CheckSetup:
    base: dict[str, Any] = {"root": ROOT, "samples_dir": SAMPLES, "port": 0, "live": True, "client_factory": healthy_client}
    return CheckSetup(**(base | overrides))


def by_name(results: list[Any]) -> dict[str, Any]:
    return {result.name: result for result in results}


def test_all_green_when_everything_is_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    clock = iter([0.0, 1.5])
    results = run_checks(setup(clock=lambda: next(clock)))
    assert not any_failed(results)
    assert by_name(results)["モデル"].detail.startswith(MODEL)
    assert "1.5 秒" in by_name(results)["試し呼び出し"].detail


def test_missing_key_skips_the_api_checks_and_gives_the_developer_path_on_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ruling 2026-09-26 (E2E 0.1.0 #9): the console check is the developer path and names the flag the
    # environment key needs; setx (a permanent Windows setting) is no longer advised.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    results = run_checks(setup())
    key = by_name(results)["APIキー"]
    assert not key.ok
    assert "--enable-llm-interpreter" in key.fix and "setx" not in key.fix
    assert all(result.skipped for result in results if result.name in ("APIへの接続", "モデル", "試し呼び出し"))
    assert any_failed(results)


def test_a_key_that_is_not_a_key_is_caught_before_spending_money(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "hunter2")
    results = run_checks(setup())
    assert not by_name(results)["APIキー"].ok


def test_port_in_use_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        results = run_checks(setup(port=busy.getsockname()[1]))
    port = by_name(results)["ポート"]
    assert not port.ok and "使用中" in port.detail


def test_provider_failure_becomes_advice_not_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)

    def broken() -> FakeClient:
        raise Rejection("ProviderUnavailable", "APIキーが設定されていません。")

    results = run_checks(setup(client_factory=broken))
    connection = by_name(results)["APIへの接続"]
    assert not connection.ok and "APIキー" in connection.detail


def test_unavailable_model_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    client = healthy_client()
    client.models = FakeModels([FakeModel("some-other-model")])
    results = run_checks(setup(client_factory=lambda: client))
    model = by_name(results)["モデル"]
    assert not model.ok and MODEL in model.detail


def test_slow_line_is_reported_as_a_warning_not_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    clock = iter([0.0, 45.0])
    results = run_checks(setup(clock=lambda: next(clock)))
    call = by_name(results)["試し呼び出し"]
    assert call.ok and "45 秒" in call.detail and "300秒" in call.fix


def test_report_lists_every_check_with_its_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = format_report(run_checks(setup()))
    assert "RelayGuard 自己診断" in report
    assert "[NG] APIキー" in report and "対処:" in report
