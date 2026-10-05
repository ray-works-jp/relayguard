"""Local reviewer UI + application service (IMPLEMENTATION.md §9-11, §23-24).

End-to-end over HTTP with synthetic fixtures only: import -> Decision -> pre assessment ->
generate -> verify -> Final Approval -> copy, plus the guards around each step.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from relayguard.audit import verify_chain
from relayguard.errors import Rejection
from relayguard_ui.app import create_app
from relayguard_ui.service import CaseRecord, CaseService, CaseState

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = ROOT / "eval" / "release-set-candidates" / "inputs"
SG001 = ROOT / "fixtures" / "sg001"
TOKEN = "test-token-value"


def client_for(service: CaseService, samples: Path | None = SAMPLES) -> TestClient:
    client = TestClient(create_app(service, access_token=TOKEN, samples_dir=samples))
    response = client.get(f"/login?token={TOKEN}", follow_redirects=False)
    assert response.status_code == 303
    return client


def csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "csrf token missing"
    return match.group(1)


def revision_of(html: str) -> int:
    match = re.search(r'name="revision" value="([0-9]+)"', html)
    assert match
    return int(match.group(1))


def state(record: CaseRecord) -> CaseState:
    return record.state


def reply(record: CaseRecord) -> str:
    assert record.draft is not None
    return str(record.draft["reply_text"])


def raw_interpretation(fixture: dict[str, Any]) -> bytes:
    return json.dumps(fixture["interpretation"]).encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_login_is_required_and_host_is_checked() -> None:
    service = CaseService("op_test")
    client = TestClient(create_app(service, access_token=TOKEN, samples_dir=SAMPLES))
    assert client.get("/new").status_code == 401
    assert client.get("/login?token=wrong").status_code == 401
    assert client.get(f"/login?token={TOKEN}", headers={"host": "evil.example"}).status_code == 403
    logged_in = client_for(service)
    assert logged_in.get("/new").status_code == 200
    assert logged_in.get("/", headers={"host": "attacker.example:8765"}).status_code == 403
    response = logged_in.get("/new")
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_fixture_flow_to_copy_and_audit_chain() -> None:
    service = CaseService("op_test")
    client = client_for(service)
    page = client.get("/new").text
    response = client.post("/cases/import-sample", data={"csrf": csrf_of(page), "name": "RG-EVAL-002.input.json"}, follow_redirects=False)
    case_url = response.headers["location"]
    case_id = case_url.rsplit("/", 1)[1]
    record = service.get(case_id)
    assert state(record) == CaseState.DELEGATION_ASSESSED

    html = client.get(case_url).text
    assert client.get(f"/cases/{case_id}/approved.txt").status_code == 409
    client.post(f"/cases/{case_id}/generate", data={"csrf": csrf_of(html), "revision": str(revision_of(html))})
    assert state(record) == CaseState.SAFE_CANDIDATE
    html = client.get(case_url).text
    assert "検査済み: あなたが決めていない内容は見つかりませんでした" in html

    client.post(f"/cases/{case_id}/final-approval", data={"csrf": csrf_of(html), "revision": str(record.revision)})
    assert state(record) == CaseState.FINAL_APPROVED
    assert record.approval is not None and record.approval["approved_by"] == "op_test"
    text = client.get(f"/cases/{case_id}/approved.txt")
    assert text.status_code == 200 and text.text == reply(record)

    client.post(f"/cases/{case_id}/copied", data={"csrf": csrf_of(html), "revision": str(record.revision)})
    assert state(record) == CaseState.COPIED
    audit = client.get(f"/cases/{case_id}/audit.json").json()["events"]
    assert verify_chain(case_id, audit)
    assert [e["event_type"] for e in audit][-3:] == [
        "delegation.post_verification_assessed",
        "final_approval.recorded",
        "reply.copied_by_operator",
    ]
    assert all(
        set(e)
        == {
            "event_id",
            "case_id",
            "actor_type",
            "actor_id",
            "event_type",
            "entity_id",
            "entity_hash",
            "previous_hash",
            "event_hash",
            "created_at",
        }
        for e in audit
    )


def test_user_decision_flow_from_interpretation() -> None:
    fixture = read_json(SG001 / "l2_answer_from_source_evidence.input.json")
    service = CaseService("op_user")
    client = client_for(service)
    page = client.get("/new").text
    response = client.post(
        "/cases/import-interpretation",
        data={
            "csrf": csrf_of(page),
            "subject": fixture["source_message"]["subject"],
            "body": fixture["source_message"]["body"],
            "interpretation": json.dumps(fixture["interpretation"]),
        },
        follow_redirects=False,
    )
    case_id = response.headers["location"].rsplit("/", 1)[1]
    record = service.get(case_id)
    assert state(record) == CaseState.DECISION_REQUIRED
    html = client.get(f"/cases/{case_id}").text
    client.post(
        f"/cases/{case_id}/decision",
        data={
            "csrf": csrf_of(html),
            "revision": str(revision_of(html)),
            "choice__c_intent": "approve",
            "choice__c_q1": "approve",
            "answer__c_q1": "invoices@example.com is correct.",
            "related__c_q1": "c_intent",
        },
    )
    assert record.last_error is None, record.last_error
    assert record.decision is not None and record.decision["approved_by"] == "op_user"
    assert state(record) == CaseState.DELEGATION_ASSESSED
    audit_actors = {(e["event_type"], e["actor_type"]) for e in record.audit}
    assert ("decision.approved", "user") in audit_actors

    html = client.get(f"/cases/{case_id}").text
    client.post(f"/cases/{case_id}/generate", data={"csrf": csrf_of(html), "revision": str(record.revision)})
    assert state(record) == CaseState.SAFE_CANDIDATE, record.verification
    assert "invoices@example.com is correct." in reply(record)


def test_unselected_claims_default_to_unknown_not_approve() -> None:
    fixture = read_json(SG001 / "l2_answer_from_source_evidence.input.json")
    service = CaseService("op_user")
    record = service.import_interpretation(
        fixture["source_message"]["subject"], fixture["source_message"]["body"], raw_interpretation(fixture)
    )
    service.submit_decision(record.case_id, record.revision, {}, {})
    assert record.decision is not None
    assert {item["decision"] for item in record.decision["items"]} == {"unknown"}
    assert record.decision["approved_commitments"] == []


def test_interpretation_with_fabricated_evidence_is_rejected() -> None:
    fixture = read_json(SG001 / "l2_answer_from_source_evidence.input.json")
    interpretation = copy.deepcopy(fixture["interpretation"])
    interpretation["state"]["evidence"][0]["quote"] = "We promise a full refund."
    service = CaseService("op_user")
    with pytest.raises(Rejection):
        service.import_interpretation(None, fixture["source_message"]["body"], json.dumps(interpretation).encode())
    assert service.list_cases() == []


def test_interpretation_claiming_approval_is_rejected() -> None:
    fixture = read_json(ROOT / "eval" / "release-set-candidates" / "inputs" / "RG-EVAL-011.input.json")
    interpretation = copy.deepcopy(fixture["interpretation"])
    for array in ("requested_commitments", "commitments"):
        for claim in interpretation["state"][array]:
            claim["authorization_state"] = "approved"
    with pytest.raises(Rejection) as exc:
        CaseService("op_user").import_interpretation(None, fixture["source_message"]["body"], json.dumps(interpretation).encode())
    assert exc.value.code == "PolicyViolation"


def _safe_case(service: CaseService) -> str:
    record = service.import_shadow_input((SAMPLES / "RG-EVAL-002.input.json").read_bytes())
    service.generate(record.case_id, record.revision)
    assert state(record) == CaseState.SAFE_CANDIDATE
    return record.case_id


def test_tampered_edit_blocks_and_cannot_be_approved() -> None:
    service = CaseService("op_test")
    case_id = _safe_case(service)
    record = service.get(case_id)
    tampered = reply(record).replace("Thank you for your message.", "Thank you for your message.\nWe will refund USD 300.00 today.")
    service.edit_draft(case_id, record.revision, tampered)
    assert state(record) == CaseState.BLOCKED
    assert record.post_assessment is not None and record.post_assessment["level"] == "L3_STOP"
    with pytest.raises(Rejection):
        service.final_approve(case_id, record.revision)
    with pytest.raises(Rejection):
        service.copy_text(case_id)


def test_edit_after_approval_voids_approval() -> None:
    service = CaseService("op_test")
    case_id = _safe_case(service)
    record = service.get(case_id)
    service.final_approve(case_id, record.revision)
    service.edit_draft(case_id, record.revision, reply(record) + "\n")
    assert record.approval is None
    assert state(record) == CaseState.SAFE_CANDIDATE
    with pytest.raises(Rejection):
        service.copy_text(case_id)


def test_stale_revision_is_rejected() -> None:
    service = CaseService("op_test")
    case_id = _safe_case(service)
    record = service.get(case_id)
    old = record.revision
    service.edit_draft(case_id, old, reply(record) + "\n")
    with pytest.raises(Rejection) as exc:
        service.final_approve(case_id, old)
    assert exc.value.code == "StaleState"


def test_concurrent_approvals_only_one_succeeds() -> None:
    service = CaseService("op_test")
    case_id = _safe_case(service)
    revision = service.get(case_id).revision
    outcomes: list[str] = []

    def attempt() -> None:
        try:
            service.final_approve(case_id, revision)
            outcomes.append("ok")
        except Rejection as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 1
    assert set(outcomes) - {"ok"} == {"StaleState"}


def test_l3_case_cannot_generate_or_approve() -> None:
    service = CaseService("op_test")
    l3 = next(p for p in sorted(SAMPLES.glob("*.input.json")) if _pre_level(service, p) == "L3_STOP")
    record = next(c for c in service.list_cases() if c.source["message_id"] == read_json(l3)["source_message"]["message_id"])
    assert state(record) == CaseState.STOPPED
    with pytest.raises(Rejection) as exc:
        service.generate(record.case_id, record.revision)
    assert exc.value.code == "SafetyBlock"
    with pytest.raises(Rejection):
        service.final_approve(record.case_id, record.revision)


def _pre_level(service: CaseService, path: Path) -> str | None:
    try:
        record = service.import_shadow_input(path.read_bytes())
    except Rejection:
        return None
    return record.pre_assessment["level"] if record.pre_assessment else None


def test_csrf_is_enforced() -> None:
    service = CaseService("op_test")
    client = client_for(service)
    client.post("/cases/import-sample", data={"csrf": "forged", "name": "RG-EVAL-002.input.json"})
    assert service.list_cases() == []


def test_operational_logs_never_contain_raw_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    fixture = read_json(SG001 / "l2_answer_from_source_evidence.input.json")
    service = CaseService("op_user")
    record = service.import_interpretation(
        fixture["source_message"]["subject"], fixture["source_message"]["body"], raw_interpretation(fixture)
    )
    answer = "invoices@example.com is correct."
    service.submit_decision(
        record.case_id,
        record.revision,
        {"c_intent": "approve", "c_q1": "approve"},
        {"c_q1": {"answer_text": answer, "related_claim_ids": ["c_intent"]}},
    )
    service.generate(record.case_id, record.revision)
    service.edit_draft(record.case_id, record.revision, reply(record) + "Call me at jane.roe@example.org\n")
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert logs, "expected operational log records"
    for secret in ("invoices@example.com", "jane.roe@example.org", "Which mailbox", fixture["source_message"]["body"][:30], "is correct"):
        assert secret not in logs
