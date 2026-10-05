"""Per-line provenance of the reply draft (view.reply_origin_lines).

The product's whole claim is that a reply is never wholly the machine's and never wholly the
operator's. This makes that split visible: each line is generator boilerplate, the operator's own
answer text, an approved commitment the machine only worded - or nothing at all, which is exactly
the case the closed-world check stops. Display only: it must not change any verdict.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from relayguard.generator import BOILERPLATE_LINES
from relayguard_ui.app import create_app
from relayguard_ui.service import CaseService, CaseState
from relayguard_ui.view import ORIGIN_LABELS, reply_origin_lines, reply_origin_summary

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "eval" / "release-set-candidates" / "inputs"
TOKEN = "origin-test-token-value"
SUBJECT = "Damaged kettle"
BODY = "Hello,\n\nThe kettle in order R-2001 arrived damaged. Can you confirm a refund of USD 49.00?\n\nRegards,\nCustomer\n"
ANSWER = "Yes, that is correct."


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match
    return match.group(1)


def approved_case() -> tuple[CaseService, TestClient, str]:
    """A manual case taken as far as a generated, verified draft (no API key needed)."""
    service = CaseService("op_origin")
    client = TestClient(create_app(service, access_token=TOKEN, samples_dir=SAMPLES))
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
            f"answer__{question_id}": ANSWER,
        },
    )
    html = client.get(f"/cases/{case_id}").text
    client.post(f"/cases/{case_id}/generate", data={"csrf": csrf_of(html), "revision": str(service.get(case_id).revision)})
    return service, client, case_id


def test_no_draft_means_nothing_to_show() -> None:
    service = CaseService("op_origin")
    record = service.import_shadow_input((SAMPLES / "RG-EVAL-011.input.json").read_bytes())
    assert reply_origin_lines(record) == []
    assert reply_origin_summary(record) == []


def test_every_line_of_a_passing_draft_has_a_known_origin() -> None:
    service, _client, case_id = approved_case()
    record = service.get(case_id)
    assert record.state == CaseState.SAFE_CANDIDATE
    lines = [line for line in reply_origin_lines(record) if line.origin != "blank"]
    assert lines
    assert all(line.origin in ("boilerplate", "answer", "commitment") for line in lines)


def test_the_operators_own_sentence_is_marked_as_theirs() -> None:
    service, _client, case_id = approved_case()
    mine = [line for line in reply_origin_lines(service.get(case_id)) if line.origin == "answer"]
    assert [line.text for line in mine] == [ANSWER]
    assert mine[0].source_id.startswith("c_")


def test_boilerplate_is_marked_as_the_machines() -> None:
    service, _client, case_id = approved_case()
    fixed = [line for line in reply_origin_lines(service.get(case_id)) if line.origin == "boilerplate"]
    assert fixed
    assert all(line.text in BOILERPLATE_LINES for line in fixed)
    assert all(line.source_id == "" for line in fixed)


def test_blank_lines_are_kept_so_the_display_matches_the_reply() -> None:
    service, _client, case_id = approved_case()
    record = service.get(case_id)
    assert record.draft is not None
    shown = [line.text for line in reply_origin_lines(record)]
    assert shown == [raw.strip() for raw in str(record.draft["reply_text"]).splitlines()]


def test_a_line_belonging_to_nothing_is_called_out() -> None:
    """The sentence an operator adds by hand is the one case that must not look approved."""
    service, client, case_id = approved_case()
    record = service.get(case_id)
    assert record.draft is not None
    html = client.get(f"/cases/{case_id}").text
    tampered = str(record.draft["reply_text"]) + "\nWe will also pay EUR 20.00.\n"
    client.post(
        f"/cases/{case_id}/draft",
        data={"csrf": csrf_of(html), "revision": str(record.revision), "reply_text": tampered},
    )
    orphans = [line for line in reply_origin_lines(service.get(case_id)) if line.origin == "unknown"]
    assert [line.text for line in orphans] == ["We will also pay EUR 20.00."]


def test_summary_counts_the_lines_by_origin() -> None:
    service, _client, case_id = approved_case()
    record = service.get(case_id)
    summary = reply_origin_summary(record)
    assert sum(count for _origin, _label, count in summary) == len([line for line in reply_origin_lines(record) if line.text])
    assert dict((origin, label) for origin, label, _count in summary).items() <= ORIGIN_LABELS.items()


def test_the_case_page_shows_the_split() -> None:
    _service, client, case_id = approved_case()
    html = client.get(f"/cases/{case_id}").text
    assert "行ごとの由来" in html
    assert ORIGIN_LABELS["answer"] in html and ORIGIN_LABELS["boilerplate"] in html
    assert "機械の決まり文句" in html


def test_the_panel_says_in_one_sentence_what_the_split_means() -> None:
    _service, client, case_id = approved_case()
    html = client.get(f"/cases/{case_id}").text
    assert "あなたが入力した英文そのまま" in html
    assert "機械が組み立てた行" in html
