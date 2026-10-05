"""Marking a mail up by hand instead of calling the LLM (no API key, nothing leaves the machine).

The manual path must not be a back door: the same Evidence rule applies (quotes must be in the
mail), blank values stay "unknown" rather than being guessed, and the Decision is still human.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from relayguard.errors import Rejection
from relayguard_ui.app import create_app
from relayguard_ui.manual_interpretation import ManualEntry, build_interpretation, entries_from_form
from relayguard_ui.service import CaseService, CaseState

TOKEN = "manual-test-token-value"
SUBJECT = "Refund for order 4471"
BODY = "Hello,\n\nThe kettle arrived damaged. Can you confirm a refund of USD 49.00 by 2026-10-01 JST?\n\nRegards,\nCustomer\n"


def web() -> TestClient:
    client = TestClient(create_app(CaseService("op_manual"), access_token=TOKEN))
    assert client.get(f"/login?token={TOKEN}", follow_redirects=False).status_code == 303
    return client


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_entries_become_claims_with_evidence_from_the_mail() -> None:
    entries = [
        ManualEntry(kind="question", quote="Can you confirm a refund of USD 49.00", text="Can you confirm the refund?"),
        ManualEntry(kind="money", quote="USD 49.00", amount="49.00", currency="usd", money_type="refund"),
        ManualEntry(kind="date", quote="by 2026-10-01 JST", date="2026-10-01", timezone="JST"),
    ]
    state = build_interpretation(SUBJECT, BODY, entries)["state"]
    assert state["questions"][0]["required_answer"] is True
    assert state["monetary_terms"][0]["amount"] == {"status": "explicit", "value": "49.00", "raw_text": "USD 49.00"}
    assert state["monetary_terms"][0]["currency"]["value"] == "USD"
    assert state["dates"][0]["date"]["value"] == "2026-10-01"
    assert [evidence["quote"] for evidence in state["evidence"]] == [entry.quote for entry in entries]
    assert all(evidence["quote"] in f"{SUBJECT}\n{BODY}" for evidence in state["evidence"])


def test_blank_value_stays_unknown_and_is_never_guessed() -> None:
    state = build_interpretation(SUBJECT, BODY, [ManualEntry(kind="money", quote="USD 49.00", amount="49.00")])["state"]
    assert state["monetary_terms"][0]["currency"] == {"status": "unknown", "value": None, "raw_text": "USD 49.00"}


def test_a_commitment_from_the_mail_is_requested_never_approved() -> None:
    state = build_interpretation(SUBJECT, BODY, [ManualEntry(kind="commitment", quote="confirm a refund", text="confirm the refund")])[
        "state"
    ]
    assert state["requested_commitments"][0]["authorization_state"] == "requested"


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([], "登録する項目が1つもありません"),
        ([ManualEntry(kind="money", quote="   ")], "原文の引用が空です"),
        ([ManualEntry(kind="money", quote="USD 99.00")], "見つかりません"),
        ([ManualEntry(kind="bogus", quote="USD 49.00")], "種類が不正です"),
        ([ManualEntry(kind="money", quote="USD 49.00", money_type="bribe")], "種別が不正です"),
    ],
)
def test_invalid_entries_are_rejected(entries: list[ManualEntry], message: str) -> None:
    with pytest.raises(Rejection) as caught:
        build_interpretation(SUBJECT, BODY, entries)
    assert message in caught.value.explanation_ja


def test_form_rows_are_read_and_blank_rows_skipped() -> None:
    form = {
        "kind_1": "question", "quote_1": "Can you confirm a refund", "text_1": "Can you confirm?",
        "kind_2": "none", "quote_2": "ignored",
        "kind_3": "money", "quote_3": "USD 49.00", "amount_3": "49.00", "currency_3": "USD", "money_type_3": "refund",
    }  # fmt: skip
    entries = entries_from_form(form)
    assert [entry.kind for entry in entries] == ["question", "money"]
    assert entries[1].amount == "49.00"


def test_route_creates_a_case_awaiting_the_human_decision() -> None:
    client = web()
    page = client.get("/new").text
    assert "自分で読み取って登録する" in page
    response = client.post(
        "/cases/import-manual",
        data={
            "csrf": csrf_of(page),
            "subject": SUBJECT,
            "body": BODY,
            "kind_1": "question",
            "quote_1": "Can you confirm a refund of USD 49.00",
            "text_1": "Can you confirm the refund?",
            "kind_2": "money",
            "quote_2": "USD 49.00",
            "amount_2": "49.00",
            "currency_2": "USD",
            "money_type_2": "refund",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    case_page = client.get(response.headers["location"]).text
    assert "判断待ち" in case_page
    assert "Can you confirm the refund?" in case_page


def test_route_keeps_the_mail_on_screen_when_a_quote_is_wrong() -> None:
    client = web()
    page = client.get("/new").text
    response = client.post(
        "/cases/import-manual",
        data={"csrf": csrf_of(page), "subject": SUBJECT, "body": BODY, "kind_1": "money", "quote_1": "USD 99.00", "amount_1": "99.00"},
    )
    assert response.status_code == 400
    assert "見つかりません" in response.text
    assert "The kettle arrived damaged." in response.text


def test_manual_case_reaches_a_verified_reply() -> None:
    """End to end without any API key: mark up -> approve -> generate -> verify."""
    service = CaseService("op_manual")
    client = TestClient(create_app(service, access_token=TOKEN))
    client.get(f"/login?token={TOKEN}")
    page = client.get("/new").text
    response = client.post(
        "/cases/import-manual",
        data={
            "csrf": csrf_of(page),
            "subject": SUBJECT,
            "body": BODY,
            "kind_1": "question",
            "quote_1": "Can you confirm a refund of USD 49.00",
            "text_1": "Can you confirm the refund?",
        },
        follow_redirects=False,
    )
    case_id = str(response.headers["location"]).rsplit("/", 1)[1]
    html = client.get(f"/cases/{case_id}").text
    record = service.get(case_id)
    question_id = record.interpretation["state"]["questions"][0]["id"]
    client.post(
        f"/cases/{case_id}/decision",
        data={
            "csrf": csrf_of(html),
            "revision": str(record.revision),
            f"choice__{question_id}": "approve",
            f"answer__{question_id}": "Yes, the refund is confirmed.",
        },
    )
    html = client.get(f"/cases/{case_id}").text
    client.post(f"/cases/{case_id}/generate", data={"csrf": csrf_of(html), "revision": str(record.revision)})
    assert record.state in (CaseState.SAFE_CANDIDATE, CaseState.BLOCKED)
    assert record.draft is not None
    assert "Yes, the refund is confirmed." in record.draft["reply_text"]
