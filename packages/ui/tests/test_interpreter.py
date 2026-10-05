"""Optional Claude Interpreter adapter - offline tests with a fake client (no network, no API key)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from relayguard.errors import Rejection
from relayguard_ui.app import create_app
from relayguard_ui.interpreter import MODEL, ClaudeInterpreter, default_client, link_faults, provider_message, quality_hint
from relayguard_ui.service import CaseService, CaseState

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "fixtures" / "sg001" / "l2_answer_from_source_evidence.input.json").read_text(encoding="utf-8"))
SUBJECT = FIXTURE["source_message"]["subject"]
BODY = FIXTURE["source_message"]["body"]


@dataclass
class Block:
    text: str
    type: str = "text"


@dataclass
class Response:
    content: list[Block]
    stop_reason: str = "end_turn"


@dataclass
class FakeStream:
    response: Response

    def __enter__(self) -> FakeStream:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get_final_message(self) -> Response:
        return self.response


@dataclass
class FakeMessages:
    outputs: list[Response]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def stream(self, **kwargs: Any) -> FakeStream:
        self.calls.append(kwargs)
        return FakeStream(self.outputs.pop(0))


@dataclass
class FakeBeta:
    messages: FakeMessages


@dataclass
class FakeModel:
    id: str


@dataclass
class FakeModels:
    data: list[FakeModel] = field(default_factory=lambda: [FakeModel(MODEL)])

    def list(self, **_kwargs: Any) -> FakeModels:
        return self


@dataclass
class FakeClient:
    beta: FakeBeta
    models: FakeModels = field(default_factory=FakeModels)


def fake(*texts: str, stop_reason: str = "end_turn") -> FakeClient:
    return FakeClient(FakeBeta(FakeMessages([Response([Block(t)], stop_reason) for t in texts])))


def good_output() -> str:
    interpretation = json.loads(json.dumps(FIXTURE["interpretation"]))
    interpretation["interpretation_id"] = "int_llm"
    return json.dumps(interpretation)


def test_valid_output_creates_case_requiring_human_decision() -> None:
    client = fake(good_output())
    service = CaseService("op_llm")
    record = ClaudeInterpreter(lambda: client).interpret_into_case(service, SUBJECT, BODY)
    assert record.state == CaseState.DECISION_REQUIRED
    assert record.decision is None
    call = client.beta.messages.calls[0]
    assert call["model"] == MODEL
    assert BODY in call["messages"][0]["content"]


def test_fabricated_quote_gets_one_repair_then_fails_closed() -> None:
    bad = json.loads(good_output())
    bad["state"]["evidence"][0]["quote"] = "We promise a refund of USD 900."
    client = fake(json.dumps(bad), json.dumps(bad))
    service = CaseService("op_llm")
    with pytest.raises(Rejection):
        ClaudeInterpreter(lambda: client).interpret_into_case(service, SUBJECT, BODY)
    assert len(client.beta.messages.calls) == 2
    assert service.list_cases() == []


def test_repair_attempt_can_succeed() -> None:
    client = fake("not json at all", good_output())
    record = ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_llm"), SUBJECT, BODY)
    assert record.state == CaseState.DECISION_REQUIRED
    assert "was rejected" in client.beta.messages.calls[1]["messages"][0]["content"]


def test_model_claiming_approval_is_rejected() -> None:
    fixture = json.loads((ROOT / "eval" / "release-set-candidates" / "inputs" / "RG-EVAL-011.input.json").read_text(encoding="utf-8"))
    interpretation = fixture["interpretation"]
    for claim in interpretation["state"]["requested_commitments"]:
        claim["authorization_state"] = "approved"
    client = fake(json.dumps(interpretation), json.dumps(interpretation))
    with pytest.raises(Rejection) as exc:
        ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_llm"), None, fixture["source_message"]["body"])
    assert exc.value.code == "PolicyViolation"


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refusal_or_truncation_is_provider_unavailable(stop_reason: str) -> None:
    client = fake(good_output(), stop_reason=stop_reason)
    with pytest.raises(Rejection) as exc:
        ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_llm"), SUBJECT, BODY)
    assert exc.value.code == "ProviderUnavailable"
    assert len(client.beta.messages.calls) == 1


def test_oversized_input_is_not_sent() -> None:
    client = fake(good_output())
    with pytest.raises(Rejection) as exc:
        ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_llm"), None, "x" * (64 * 1024 + 1))
    assert exc.value.code == "UnsupportedInput"
    assert client.beta.messages.calls == []


def test_ui_requires_enablement_and_consent() -> None:
    client = fake(good_output())
    service = CaseService("op_llm")
    app_off = TestClient(create_app(service, access_token="t" * 20))
    app_off.get("/login?token=" + "t" * 20)
    assert "/cases/interpret" not in app_off.get("/new").text

    web = TestClient(create_app(service, access_token="t" * 20, interpreter=ClaudeInterpreter(lambda: client)))
    web.get("/login?token=" + "t" * 20)
    html = web.get("/new").text
    csrf = html.split('name="csrf" value="', 1)[1].split('"', 1)[0]
    web.post("/cases/interpret", data={"csrf": csrf, "subject": SUBJECT, "body": BODY})
    assert client.beta.messages.calls == []
    web.post("/cases/interpret", data={"csrf": csrf, "subject": SUBJECT, "body": BODY, "consent": "1"})
    assert len(client.beta.messages.calls) == 1
    assert len(service.list_cases()) == 1


class FakeAPIError(Exception):
    """Stands in for anthropic.APIError, which carries a status_code and a message."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (FakeAPIError("x", 401), "APIキーが無効です"),
        (FakeAPIError("x", 403), "権限がありません"),
        (FakeAPIError("x", 404), "利用できません"),
        (FakeAPIError("x", 429), "レート制限"),
        (FakeAPIError("x", 503), "Anthropic側で一時的な障害"),
        (FakeAPIError("your credit balance is too low", 400), "クレジット残高が不足"),
        (FakeAPIError("boom"), "ネットワーク接続を確認"),
    ],
)
def test_provider_errors_say_what_to_fix(error: Exception, expected: str) -> None:
    assert expected in provider_message(error)


def test_missing_api_key_names_the_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(Rejection) as exc:
        default_client()
    assert exc.value.code == "ProviderUnavailable"
    assert "ANTHROPIC_API_KEY" in exc.value.explanation_ja


def test_failed_interpretation_keeps_the_pasted_mail_on_screen() -> None:
    def boom() -> Any:
        raise Rejection("ProviderUnavailable", "クレジット残高が不足しています。")

    service = CaseService("op_llm")
    web = TestClient(create_app(service, access_token="t" * 20, interpreter=ClaudeInterpreter(boom)))
    web.get("/login?token=" + "t" * 20)
    csrf = web.get("/new").text.split('name="csrf" value="', 1)[1].split('"', 1)[0]
    response = web.post("/cases/interpret", data={"csrf": csrf, "subject": SUBJECT, "body": BODY, "consent": "1"})
    assert response.status_code == 400
    assert "クレジット残高が不足しています。" in response.text
    assert BODY.splitlines()[0] in response.text
    assert service.list_cases() == []


def test_each_attempt_gets_the_remaining_budget_and_streams() -> None:
    """D-2 and D-7(b): the 300 s total budget is the hard limit; an attempt is not cut off at a fixed 60 s."""
    client = fake(good_output())
    clock = iter([0.0, 5.0, 5.0, 5.0])
    ClaudeInterpreter(lambda: client, lambda: next(clock)).interpret_into_case(CaseService("op_llm"), SUBJECT, BODY)
    call = client.beta.messages.calls[0]
    assert call["timeout"] == pytest.approx(295.0)
    assert call["model"] == MODEL


def test_the_budget_stops_a_second_attempt() -> None:
    bad = json.dumps({"interpretation_id": "int_llm"})
    client = fake(bad, good_output())
    clock = iter([0.0, 1.0, 999.0])
    with pytest.raises(Rejection) as caught:
        ClaudeInterpreter(lambda: client, lambda: next(clock)).interpret_into_case(CaseService("op_llm"), SUBJECT, BODY)
    assert caught.value.code == "ProviderUnavailable"
    assert len(client.beta.messages.calls) == 1


# --- Output that passes the schema but read nothing off the mail (quality_hint) ---------------
#
# These are the faults observed on a real refund mail: the amount was left "unknown" although the
# sender wrote "USD 2,340", the term was typed "other", the sign-off was filed as a question, and
# every quote was a whole paragraph. All four are schema-valid, so the repair attempt never fired.


def _document(**state: Any) -> str:
    base: dict[str, Any] = {"evidence": [], "monetary_terms": [], "questions": []}
    return json.dumps({"state": base | state})


def _value(status: str, value: Any = None, raw: str = "") -> dict[str, Any]:
    return {"status": status, "value": value, "raw_text": raw}


def _evidence(evidence_id: str, quote: str) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "quote": quote, "supports": []}


def _read_badly() -> str:
    """Schema-valid and integrity-clean, but the question is the paragraph instead of the question."""
    document = json.loads(good_output())
    document["state"]["questions"][0]["text"]["value"] = "We were charged twice for our annual renewal. " * 6
    return json.dumps(document)


def test_an_amount_left_unread_although_its_own_evidence_states_one_is_sent_back() -> None:
    text = _document(
        evidence=[_evidence("e1", "Please refund USD 2,340 to the original card.")],
        monetary_terms=[{"id": "c_m1", "evidence_ids": ["e1"], "type": "refund", "amount": _value("unknown", raw="USD 2,340")}],
    )
    hint = quality_hint(text)
    assert hint is not None
    assert "c_m1" in hint and "explicit amount" in hint


def test_an_amount_the_mail_never_states_is_left_alone() -> None:
    text = _document(
        evidence=[_evidence("e1", "Please refund the duplicate charge.")],
        monetary_terms=[{"id": "c_m1", "evidence_ids": ["e1"], "type": "refund", "amount": _value("not_stated")}],
    )
    assert quality_hint(text) is None


def test_a_document_number_is_not_an_amount() -> None:
    text = _document(
        evidence=[_evidence("e1", "invoice 20431 for the same amount hit the card two days later")],
        monetary_terms=[
            {"id": "c_m1", "evidence_ids": ["e1"], "type": "payment", "amount": _value("ambiguous", raw="for the same amount")}
        ],
    )
    assert quality_hint(text) is None


def test_other_is_sent_back_when_the_evidence_is_about_a_refund() -> None:
    text = _document(
        evidence=[_evidence("e1", "We would like a refund.")],
        monetary_terms=[{"id": "c_m2", "evidence_ids": ["e1"], "type": "other", "amount": _value("not_stated")}],
    )
    hint = quality_hint(text)
    assert hint is not None and "c_m2" in hint


def test_a_sign_off_filed_as_a_question_is_sent_back() -> None:
    text = _document(questions=[{"id": "c_q1", "evidence_ids": [], "text": _value("explicit", "Thanks, Dana Whitlock Office Manager")}])
    hint = quality_hint(text)
    assert hint is not None and "sign-off" in hint


def test_a_paragraph_pasted_into_a_question_is_sent_back() -> None:
    text = _document(questions=[{"id": "c_q2", "evidence_ids": [], "text": _value("explicit", "We were charged twice. " * 12)}])
    hint = quality_hint(text)
    assert hint is not None and "c_q2" in hint


def test_a_whole_paragraph_quoted_as_evidence_is_sent_back() -> None:
    hint = quality_hint(_document(evidence=[_evidence("e1", "x" * 241)]))
    assert hint is not None and "shortest exact substring" in hint


def test_a_real_question_and_a_short_quote_pass() -> None:
    text = _document(
        evidence=[_evidence("e1", "Can you confirm by Friday?")],
        questions=[{"id": "c_q1", "evidence_ids": ["e1"], "text": _value("explicit", "Can you confirm by Friday?")}],
    )
    assert quality_hint(text) is None


def test_output_that_is_not_json_is_left_to_schema_validation() -> None:
    assert quality_hint("not json at all") is None
    assert quality_hint("[]") is None


def test_the_fixture_interpretation_is_not_flagged() -> None:
    """The check must not fire on output that is already good, or every case costs two calls."""
    assert quality_hint(good_output()) is None


def test_a_badly_read_output_costs_one_repair_and_the_hint_says_why() -> None:
    client = fake(_read_badly(), good_output())
    record = ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_llm"), SUBJECT, BODY)
    assert record.state == CaseState.DECISION_REQUIRED
    assert len(client.beta.messages.calls) == 2
    assert "is a paragraph" in client.beta.messages.calls[1]["messages"][0]["content"]


def test_a_repair_that_comes_back_invalid_fails_closed_without_reusing_the_first() -> None:
    """IMPLEMENTATION.md §5.2 fails closed after the one repair; §23 forbids reusing an earlier result.

    The first output here is schema-valid - only quality_hint rejected it - so reusing it would be
    tempting and is exactly what the spec prohibits.
    """
    service = CaseService("op_llm")
    client = fake(_read_badly(), "not json at all")
    with pytest.raises(Rejection):
        ClaudeInterpreter(lambda: client).interpret_into_case(service, SUBJECT, BODY)
    assert len(client.beta.messages.calls) == 2
    assert service.list_cases() == []


def test_the_output_budget_leaves_room_for_thinking_on_a_long_mail() -> None:
    """16000 tokens truncated a 571-word mail once thinking was counted; Opus 5 allows 128K."""
    from relayguard_ui.interpreter import MAX_OUTPUT_TOKENS  # noqa: PLC0415

    client = fake(good_output())
    ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_llm"), SUBJECT, BODY)
    assert client.beta.messages.calls[0]["max_tokens"] == MAX_OUTPUT_TOKENS
    assert 32000 <= MAX_OUTPUT_TOKENS <= 128000


def test_effort_is_pinned_to_the_measured_setting() -> None:
    """Default effort took 236.9 s on a long mail; medium read best of three in 124.7 s (2026-09-23)."""
    from relayguard_ui.interpreter import EFFORT  # noqa: PLC0415

    client = fake(good_output())
    ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_llm"), SUBJECT, BODY)
    assert client.beta.messages.calls[0]["output_config"] == {"effort": EFFORT} == {"effort": "medium"}


def test_the_total_budget_is_the_d7_trial_limit_and_still_fails_closed() -> None:
    """D-7(b): 300 s total, one repair at most, fail closed past it, no reuse of a failed attempt."""
    from relayguard_ui.interpreter import TOTAL_BUDGET_S  # noqa: PLC0415

    assert TOTAL_BUDGET_S == 300.0
    bad = json.dumps({"interpretation_id": "int_llm"})
    client = fake(bad, good_output())
    clock = iter([0.0, 1.0, 301.0])
    service = CaseService("op_llm")
    with pytest.raises(Rejection) as caught:
        ClaudeInterpreter(lambda: client, lambda: next(clock)).interpret_into_case(service, SUBJECT, BODY)
    assert caught.value.code == "ProviderUnavailable" and "300秒" in caught.value.explanation_ja
    assert len(client.beta.messages.calls) == 1
    assert service.list_cases() == []


# Ruling R-4 (2026-09-23): links are never repaired by the program - the repair hint only names them.


def _first_link(document: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    evidence = document["state"]["evidence"][0]
    return evidence["supports"][0], evidence


def test_link_faults_is_silent_on_consistent_output() -> None:
    assert link_faults(good_output()) is None


def test_link_faults_names_every_one_sided_and_dangling_link() -> None:
    document = json.loads(good_output())
    claim_id, evidence = _first_link(document)
    evidence["supports"].append("c_ghost")
    for items in document["state"].values():
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("id") == claim_id:
                item["evidence_ids"].append("e_missing")
    hint = link_faults(json.dumps(document))
    assert hint is not None
    assert f"claim {claim_id} cites evidence e_missing, which does not exist" in hint
    assert f"evidence {evidence['evidence_id']} supports c_ghost, which is not a claim id" in hint


def test_a_link_mismatch_repair_names_the_ids_and_the_links_are_not_fixed_for_the_model() -> None:
    document = json.loads(good_output())
    claim_id, evidence = _first_link(document)
    evidence["supports"].remove(claim_id)
    bad = json.dumps(document)
    client = fake(bad, bad)
    service = CaseService("op_llm")
    with pytest.raises(Rejection) as exc:
        ClaudeInterpreter(lambda: client).interpret_into_case(service, SUBJECT, BODY)
    assert exc.value.code == "InternalIntegrityError"
    assert service.list_cases() == []
    repair = client.beta.messages.calls[1]["messages"][0]["content"]
    assert f"supports omits {claim_id}" in repair
    assert "do not add a link only to satisfy the check" in repair


def test_the_link_hint_stays_out_of_the_log(caplog: pytest.LogCaptureFixture) -> None:
    document = json.loads(good_output())
    claim_id, evidence = _first_link(document)
    evidence["supports"].remove(claim_id)
    client = fake(json.dumps(document), good_output())
    with caplog.at_level("INFO"):
        ClaudeInterpreter(lambda: client).interpret_into_case(CaseService("op_llm"), SUBJECT, BODY)
    assert "InternalIntegrityError" in caplog.text
    assert claim_id not in caplog.text
