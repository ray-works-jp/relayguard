"""Synthetic counterparty mail generator (scripts/make_counterparty_mail.py).

Two things must hold. The output has to survive the same .eml reader the operator uses, and a
generated mail must never be able to pass as one that actually arrived - it is not pilot data
(REQUIREMENTS.md §3 SC-01 needs a counterparty with its own interests) and not evaluation data.
No test here calls the API.
"""

from __future__ import annotations

from email import message_from_bytes, policy
from email.message import EmailMessage
from typing import Any

import make_counterparty_mail as gen
import pytest

from relayguard.errors import Rejection
from relayguard_ui.eml import parse_eml

MAIL = gen.Generated(
    scenario="refund",
    subject="Refund for order 4471",
    body="Hi,\n\nThe unit arrived damaged. Please refund $49.00 this week.\n\nThanks,\nYuki Example",
)


def test_generated_mail_reads_back_through_the_operators_own_eml_reader() -> None:
    content = parse_eml(gen.to_eml(MAIL, 1))
    assert content.subject == MAIL.subject
    assert "arrived damaged" in content.body
    assert content.attachments == ()
    assert not content.is_long


def test_a_generated_mail_is_marked_as_synthetic_in_its_headers() -> None:
    message: EmailMessage = message_from_bytes(gen.to_eml(MAIL, 3), policy=policy.default)
    assert message["X-RelayGuard-Synthetic"] == "true"
    assert message["X-RelayGuard-Scenario"] == "refund"
    # example.invalid can never resolve, so nothing here can be sent by accident (RFC 6761).
    assert "example.invalid" in str(message["From"])


def test_the_subject_line_is_split_off_the_model_output() -> None:
    subject, body = gen._split("Subject: Late delivery\n\nHello,\n\nWhere is order 12?\n")
    assert subject == "Late delivery"
    assert body.startswith("Hello,")


def test_a_fenced_reply_is_still_read() -> None:
    subject, _body = gen._split("```\nSubject: Seat count\n\nCan we add five seats?\n```")
    assert subject == "Seat count"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Here is the e-mail you asked for.\n\nHello,", "Subject: 行がありません"),
        ("Subject:   \n\nbody", "件名または本文が空です"),
        ("Subject: Only a subject\n\n   ", "件名または本文が空です"),
    ],
)
def test_output_that_is_not_an_email_is_rejected(text: str, message: str) -> None:
    with pytest.raises(Rejection) as caught:
        gen._split(text)
    assert message in caught.value.explanation_ja


def test_every_scenario_has_a_prompt() -> None:
    assert len(gen.SCENARIOS) == 10
    assert all(value.strip() for value in gen.SCENARIOS.values())


def test_the_generator_refuses_to_write_into_evaluation_data(capsys: pytest.CaptureFixture[str]) -> None:
    """Mixing synthetic mail into eval/ or fixtures/ would corrupt the pinned suites."""
    for target in ("eval/release-set-candidates/inputs", "fixtures/sg001"):
        with pytest.raises(SystemExit):
            gen.main(["--count", "1", "--out", target])
        assert "評価データと混同" in capsys.readouterr().err


def test_a_missing_api_key_is_explained_rather_than_raised(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert gen.main(["--count", "1"]) == 1
    assert "APIキーが設定されていません" in capsys.readouterr().err


def test_a_provider_failure_becomes_advice_not_a_traceback() -> None:
    class Broken:
        def __getattr__(self, _name: str) -> Any:
            raise RuntimeError("connection reset")

    with pytest.raises(Rejection) as caught:
        gen.generate(Broken(), "refund")
    assert caught.value.code == "ProviderUnavailable"
