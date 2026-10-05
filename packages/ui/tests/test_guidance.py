"""The Japanese "what to do now" guidance (labels.NEXT_ACTIONS, view.next_steps).

The target operator has nobody to ask, so a stop has to say what to do about it - without ever
claiming the reply is safe, and without deciding anything on the operator's behalf.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from relayguard_ui.app import create_app
from relayguard_ui.labels import DATE_TYPE_LABELS, FINDING_LABELS, LEVEL_LABELS, MONEY_TYPE_LABELS, NEXT_ACTIONS
from relayguard_ui.service import CaseService
from relayguard_ui.view import next_steps, nothing_is_requested

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "packages" / "schemas" / "v0_5" / "draft.schema.json"

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "eval" / "release-set-candidates" / "inputs"
TOKEN = "guidance-test-token-value"


def web() -> TestClient:
    client = TestClient(create_app(CaseService("op_test"), access_token=TOKEN, samples_dir=SAMPLES))
    assert client.get(f"/login?token={TOKEN}", follow_redirects=False).status_code == 303
    return client


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match
    return match.group(1)


def revision_of(html: str) -> str:
    match = re.search(r'name="revision" value="([0-9]+)"', html)
    assert match
    return match.group(1)


def open_case(client: TestClient, name: str) -> str:
    page = client.get("/new").text
    response = client.post("/cases/import-sample", data={"csrf": csrf_of(page), "name": name}, follow_redirects=False)
    # Samples that are rejected on purpose render the settings page with the reason instead of a redirect.
    return str(response.headers.get("location", "/-")).rsplit("/", 1)[1]


def test_every_finding_type_has_a_next_action() -> None:
    assert set(FINDING_LABELS) == set(NEXT_ACTIONS)
    assert all(text.endswith("。") for text in NEXT_ACTIONS.values())


def test_blocked_case_shows_what_to_do_and_never_claims_safety() -> None:
    client = web()
    service_case = open_case(client, "RG-EVAL-002.input.json")
    html = client.get(f"/cases/{service_case}").text
    client.post(f"/cases/{service_case}/generate", data={"csrf": csrf_of(html), "revision": revision_of(html)})
    html = client.get(f"/cases/{service_case}").text
    tampered = re.search(r'name="reply_text"[^>]*>(.*?)</textarea>', html, re.S)
    assert tampered
    broken = tampered.group(1).replace("Thank you for your message.", "Thank you for your message.\nWe guarantee a refund of USD 300.00.")
    client.post(
        f"/cases/{service_case}/draft",
        data={"csrf": csrf_of(html), "revision": revision_of(html), "reply_text": broken},
    )
    blocked = client.get(f"/cases/{service_case}").text
    assert "次にやること" in blocked
    assert NEXT_ACTIONS["unsupported_claim"] in blocked or NEXT_ACTIONS["guarantee_added"] in blocked
    assert "安全" not in blocked.split("次にやること")[1].split("</section>")[0]


def test_safe_candidate_tells_the_operator_to_approve_and_copy() -> None:
    client = web()
    case_id = open_case(client, "RG-EVAL-002.input.json")
    html = client.get(f"/cases/{case_id}").text
    client.post(f"/cases/{case_id}/generate", data={"csrf": csrf_of(html), "revision": revision_of(html)})
    page = client.get(f"/cases/{case_id}").text
    assert "最終承認してからコピー" in page


def test_l3_case_says_to_handle_it_by_hand() -> None:
    client = web()
    pages = (client.get(f"/cases/{open_case(client, name)}").text for name in sorted(p.name for p in SAMPLES.glob("*.input.json")))
    l3_page = next((page for page in pages if LEVEL_LABELS["L3_STOP"] in page), None)
    assert l3_page is not None, "no L3 sample found"
    assert "手動で返信するか、返信しないかを決めてください" in l3_page


def test_note_appears_only_when_the_mail_asks_for_nothing() -> None:
    service = CaseService("op_test")
    record = service.import_shadow_input((SAMPLES / "RG-EVAL-002.input.json").read_bytes())
    assert not nothing_is_requested(record)
    assert next_steps(record) == []

    empty = record.interpretation["state"]
    for array in ("questions", "requests", "requested_commitments", "monetary_terms", "dates", "quantities"):
        empty[array] = []
    assert nothing_is_requested(record)


def test_a_finding_names_the_claim_it_is_about() -> None:
    """Three questions with no answer produce three identical lines; only the claim id tells them apart."""
    from relayguard_ui.view import finding_rows  # noqa: PLC0415 - local to keep the module's imports as they were

    service = CaseService("op_test")
    record = service.import_shadow_input((SAMPLES / "RG-EVAL-051.input.json").read_bytes())
    service.generate(record.case_id, record.revision)
    rows = [row for row in finding_rows(service.get(record.case_id)) if row.claim_ids]
    for row in rows:
        assert all(cid.startswith("c") for cid in row.claim_ids)


def test_the_everyday_pages_carry_no_developer_vocabulary() -> None:
    """REQUIREMENTS §11: the operator has to understand the screen, not the schema."""
    from relayguard_ui.interpreter import ClaudeInterpreter  # noqa: PLC0415

    client = TestClient(create_app(CaseService("op_test"), access_token=TOKEN, samples_dir=SAMPLES, interpreter=ClaudeInterpreter()))
    client.get(f"/login?token={TOKEN}")
    for path in ("/", "/new", "/new?mode=manual"):
        html = client.get(path).text
        for word in ("JSON", "schema", "SCHEMA", "Interpretation", "ShadowCore", "Evidence"):
            assert word not in html, (path, word)
    settings = client.get("/settings").text
    assert "開発者向け" in settings and 'action="/cases/import-json"' in settings and 'action="/cases/import-interpretation"' in settings


def test_a_claim_reads_as_one_japanese_line_before_any_typed_field() -> None:
    from relayguard_ui.view import claim_rows  # noqa: PLC0415

    service = CaseService("op_test")
    record = service.import_shadow_input((SAMPLES / "RG-EVAL-011.input.json").read_bytes())
    rows = {row.array: row for row in claim_rows(record)}
    assert rows["monetary_terms"].headline == "49.00 USD（返金）"
    # The schema's own field names must not be what the operator reads first.
    assert all(name not in ("action", "object", "modality") for name, _shown, _flag in rows["monetary_terms"].fields)


def test_an_unstated_value_says_so_in_the_headline() -> None:
    from relayguard_ui.view import _headline  # noqa: PLC0415

    body = {"amount": {"status": "explicit", "value": "500"}, "currency": {"status": "ambiguous", "value": None}, "type": "price"}
    assert _headline("MonetaryTerm", body) == "500 ［曖昧］（価格）"


def test_the_decision_sheet_has_three_columns_not_four() -> None:
    """区分 moved onto the content line: same information, one less column to read across."""
    client = web()
    response = client.post(
        "/cases/import-sample",
        data={"csrf": csrf_of(client.get("/new").text), "name": "RG-EVAL-011.input.json"},
        follow_redirects=False,
    )
    html = client.get(str(response.headers["location"])).text
    assert "<th>相手が言っていること</th><th>原文の根拠</th><th>判断</th>" in html
    assert "<th>区分</th>" not in html
    # The kind is still shown, now as a tag in front of the readable line.
    assert '<span class="tag">金額</span>49.00 USD（返金）' in html


def test_the_type_labels_cover_exactly_the_schema_enums() -> None:
    """A label map that drifts from the schema either shows a blank type or advertises one that cannot occur."""
    defs = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]
    assert set(MONEY_TYPE_LABELS) == set(defs["MonetaryTerm"]["properties"]["type"]["enum"])
    assert set(DATE_TYPE_LABELS) == set(defs["DateTerm"]["properties"]["type"]["enum"])
