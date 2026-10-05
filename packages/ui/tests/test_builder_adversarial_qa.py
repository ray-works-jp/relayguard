"""Builder adversarial QA, 2026-09-23 (handoff/BUILDER_ADVERSARIAL_QA_2026-09-23.md).

Evidence level 2 only. The same Claude that built RelayGuard wrote these attacks, so they share
its blind spots; they are NOT independent QA (level 4) and must never be recorded as such.

Each test is an attack that the existing suite did not already make, grouped by the numbered
focus items of handoff/ANTIGRAVITY_QA_REQUEST_2026-09-20.md §2. A test that passes means the
attack failed.
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relayguard.errors import Rejection
from relayguard.reply_extractor import extract_reply, split_lines
from relayguard_ui.app import create_app
from relayguard_ui.interpreter import quality_hint
from relayguard_ui.service import CaseService, CaseState, ServiceRuntime

ROOT = Path(__file__).resolve().parents[3]
INPUTS = ROOT / "eval" / "release-set-candidates" / "inputs"
ALL_INPUTS = sorted(INPUTS.glob("*.input.json"))
RANK = {"L0_AUTO": 0, "L1_POST_REVIEW": 1, "L2_PRE_APPROVAL": 2, "L3_STOP": 3}
TOKEN = "adversarial-qa-token"
MARKER = "QA-PII-MARKER-7f3a"


def _case(number: str, service: CaseService | None = None) -> tuple[CaseService, str]:
    service = service or CaseService("op_qa")
    record = service.import_shadow_input((INPUTS / f"RG-EVAL-{number}.input.json").read_bytes())
    return service, record.case_id


def _drafted(number: str) -> tuple[CaseService, str]:
    service, case_id = _case(number)
    service.generate(case_id, service.get(case_id).revision)
    return service, case_id


def _edit(service: CaseService, case_id: str, text: str) -> CaseState:
    service.edit_draft(case_id, service.get(case_id).revision, text)
    return service.get(case_id).state


def _approved(number: str = "011") -> tuple[CaseService, str]:
    service, case_id = _drafted(number)
    assert service.get(case_id).state == CaseState.SAFE_CANDIDATE
    service.final_approve(case_id, service.get(case_id).revision)
    return service, case_id


# RG-EVAL-011: L2, an approved USD 49.00 refund; the generated draft passes every check.
BASE = (
    "Hello,\n\nThank you for your message.\n\nWe will: refund USD 49.00\n- Regarding: order R-2001\n"
    "- Scope: to the original payment method\n- Condition: the kettle arrived damaged\n"
    "- Amount: USD 49.00 (refund), condition: for the damaged kettle in order R-2001\n\nBest regards,\n"
)


def test_the_base_draft_really_is_the_generated_one() -> None:
    """Every attack below edits BASE; if generation drifts, the attacks would test nothing."""
    service, case_id = _drafted("011")
    assert service.get(case_id).draft["reply_text"] == BASE  # type: ignore[index]
    assert _edit(service, case_id, BASE) == CaseState.SAFE_CANDIDATE


# ----- 1. dangerous low assessment / 9. no draft under L3_STOP --------------------------------


@pytest.mark.parametrize("path", ALL_INPUTS, ids=lambda p: p.name[:11])
def test_no_case_ever_gets_a_lower_level_after_generation_or_a_draft_under_l3(path: Path) -> None:
    service = CaseService("op_qa")
    try:
        record = service.import_shadow_input(path.read_bytes())
    except Rejection:
        return  # rejected inputs never reach generation; Gate A pins which ones
    case_id, pre = record.case_id, record.pre_assessment["level"]  # type: ignore[index]
    if pre == "L3_STOP":
        for attempt in (
            lambda: service.generate(case_id, service.get(case_id).revision),
            lambda: service.edit_draft(case_id, service.get(case_id).revision, BASE),
            lambda: service.final_approve(case_id, service.get(case_id).revision),
            lambda: service.mark_copied(case_id, service.get(case_id).revision),
            lambda: service.copy_text(case_id),
        ):
            with pytest.raises(Rejection):
                attempt()
        assert service.get(case_id).draft is None
        return
    service.generate(case_id, service.get(case_id).revision)
    after = service.get(case_id)
    assert RANK[after.post_assessment["level"]] >= RANK[pre]  # type: ignore[index]


def test_an_l3_case_serves_no_reply_over_http() -> None:
    service, case_id = _case("032")  # L3: CRITICAL_MISSING_INFORMATION
    client = TestClient(create_app(service, access_token=TOKEN))
    client.get(f"/login?token={TOKEN}")
    assert client.get(f"/cases/{case_id}/approved.txt").status_code == 409
    assert "Best regards" not in client.get(f"/cases/{case_id}").text


# ----- 2. approval forgery --------------------------------------------------------------------


def test_nothing_can_be_copied_before_final_approval_even_at_l0() -> None:
    service, case_id = _drafted("001")
    assert service.get(case_id).state == CaseState.SAFE_CANDIDATE
    with pytest.raises(Rejection):
        service.copy_text(case_id)
    with pytest.raises(Rejection):
        service.mark_copied(case_id, service.get(case_id).revision)


def test_a_blocked_draft_cannot_be_final_approved() -> None:
    service, case_id = _drafted("011")
    assert _edit(service, case_id, BASE + "We will also cover shipping.\n") == CaseState.BLOCKED
    with pytest.raises(Rejection):
        service.final_approve(case_id, service.get(case_id).revision)


def test_a_tampered_audit_chain_stops_final_approval_and_copy() -> None:
    service, case_id = _drafted("011")
    service.get(case_id).audit[0]["entity_hash"] = "0" * 64
    with pytest.raises(Rejection) as caught:
        service.final_approve(case_id, service.get(case_id).revision)
    assert caught.value.code == "InternalIntegrityError"


def test_copy_hands_out_exactly_the_text_that_was_approved() -> None:
    """QA-02 (fixed): in-memory tampering after approval. Defence in depth; not reachable from the UI."""
    service, case_id = _approved()
    service.get(case_id).draft["reply_text"] = BASE + "We will also refund USD 5,000.\n"  # type: ignore[index]
    with pytest.raises(Rejection):
        service.copy_text(case_id)


# ----- 3. binding -----------------------------------------------------------------------------


def test_every_state_change_refuses_a_stale_revision() -> None:
    service, case_id = _drafted("011")
    stale = service.get(case_id).revision - 1
    attempts: list[Callable[[], object]] = [
        lambda: service.generate(case_id, stale),
        lambda: service.edit_draft(case_id, stale, BASE),
        lambda: service.final_approve(case_id, stale),
        lambda: service.submit_decision(case_id, stale, {}, {}),
    ]
    for attempt in attempts:
        with pytest.raises(Rejection) as caught:
            attempt()
        assert caught.value.code == "StaleState"


def test_the_same_form_submitted_twice_only_counts_once() -> None:
    service, case_id = _drafted("011")
    revision = service.get(case_id).revision
    service.final_approve(case_id, revision)
    with pytest.raises(Rejection) as caught:
        service.final_approve(case_id, revision)
    assert caught.value.code == "StaleState"


def test_an_edit_after_final_approval_voids_the_approval() -> None:
    service, case_id = _approved()
    _edit(service, case_id, BASE)
    assert service.get(case_id).approval is None
    with pytest.raises(Rejection):
        service.copy_text(case_id)


def test_a_new_decision_after_final_approval_voids_the_draft_and_the_approval() -> None:
    service, case_id = _approved()
    service.submit_decision(case_id, service.get(case_id).revision, {}, {})
    record = service.get(case_id)
    assert record.draft is None and record.approval is None
    with pytest.raises(Rejection):
        service.copy_text(case_id)


# ----- 4. policy exceptions (links, ADR-027) / 7. closed-world evasion ------------------------

EVASIONS = {
    "new line": BASE + "We will also waive next year's fee.\n",
    "appended to an approved line": BASE.replace("refund USD 49.00\n", "refund USD 49.00 and a USD 500 credit\n", 1),
    "changed amount": BASE.replace("refund USD 49.00\n", "refund USD 94.00\n", 1),
    "fullwidth digit": BASE.replace("refund USD 49.00\n", "refund USD 4９.00\n", 1),
    "cyrillic a in boilerplate": BASE.replace("Thank you for your message.", "Thаnk you for your message.", 1),
    "lower-cased boilerplate": BASE.replace("Thank you for your message.", "thank you for your message.", 1),
    "zero-width space inside": BASE.replace("Thank you for your message.", "Thank you for your\u200b message.", 1),
    "right-to-left override": BASE.replace("Thank you for your message.", "\u202eThank you for your message.", 1),
    "hidden after U+2028": BASE.replace("Thank you for your message.", "Thank you for your message.\u2028We guarantee 100% uptime.", 1),
    "hidden after U+001C": BASE.replace("Thank you for your message.", "Thank you for your message.\x1cWe guarantee 100% uptime.", 1),
    "hidden after bare CR": BASE.replace("Hello,", "Hello,\rWe will refund USD 500.", 1),
    "hidden after NEL": BASE.replace("Hello,", "Hello,\x85We will refund USD 500.", 1),
    "tab-joined claim": BASE.replace("Best regards,", "Best regards,\tWe accept liability.", 1),
    "https link": BASE + "https://example.com/refund\n",
    "www link": BASE + "www.example.com\n",
    "defanged link": BASE + "example[.]com/pay\n",
    "mailto": BASE + "mailto:billing@example.com\n",
    "link inside approved line": BASE.replace("refund USD 49.00\n", "refund USD 49.00 https://example.com\n", 1),
}


@pytest.mark.parametrize("text", EVASIONS.values(), ids=EVASIONS.keys())
def test_no_unapproved_content_survives_the_closed_world_check(text: str) -> None:
    """Either the edit is refused outright (the verified draft stays as it was) or it is BLOCKED."""
    service, case_id = _drafted("011")
    try:
        state = _edit(service, case_id, text)
    except Rejection:
        assert service.get(case_id).draft["reply_text"] == BASE  # type: ignore[index]
        return
    assert state == CaseState.BLOCKED
    with pytest.raises(Rejection):
        service.final_approve(case_id, service.get(case_id).revision)


def test_the_line_splitter_hides_nothing_between_check_and_copy() -> None:
    """Whatever splitlines() cuts on, every piece is checked, and the copied string is the checked one."""
    hidden = "Thank you for your message.\u2029We will refund USD 500."
    assert split_lines(hidden) == ["Thank you for your message.", "We will refund USD 500."]


# ----- 5. question/answer contract ------------------------------------------------------------


def test_an_approved_answer_cannot_be_dropped_or_rewritten() -> None:
    from test_reply_origin import ANSWER, approved_case  # noqa: PLC0415 - reuse its full manual flow

    service, _client, case_id = approved_case()
    draft = service.get(case_id).draft["reply_text"]  # type: ignore[index]
    assert ANSWER in draft
    assert _edit(service, case_id, draft.replace(ANSWER, "")) == CaseState.BLOCKED
    assert _edit(service, case_id, draft.replace(ANSWER, "Yes, that is not correct.")) == CaseState.BLOCKED
    assert _edit(service, case_id, draft) == CaseState.SAFE_CANDIDATE


def test_approving_a_question_without_an_answer_does_not_produce_a_passing_reply() -> None:
    from test_reply_origin import approved_case  # noqa: PLC0415

    service, _client, case_id = approved_case()
    question_id = service.get(case_id).interpretation["state"]["questions"][0]["id"]
    try:
        service.submit_decision(case_id, service.get(case_id).revision, {question_id: "approve"}, {})
    except Rejection:
        return  # refused at the Decision: the contract holds
    try:
        service.generate(case_id, service.get(case_id).revision)
    except Rejection:
        return
    assert service.get(case_id).state != CaseState.SAFE_CANDIDATE


# ----- 6. PII ---------------------------------------------------------------------------------


def test_no_body_subject_or_answer_text_reaches_logs_or_the_audit_chain(caplog: pytest.LogCaptureFixture) -> None:
    from test_reply_origin import approved_case, csrf_of  # noqa: PLC0415

    caplog.set_level(logging.DEBUG)
    service, client, case_id = approved_case()
    record = service.get(case_id)
    question_id = record.interpretation["state"]["questions"][0]["id"]
    html = client.get(f"/cases/{case_id}").text
    client.post(
        f"/cases/{case_id}/decision",
        data={
            "csrf": csrf_of(html),
            "revision": str(record.revision),
            f"choice__{question_id}": "approve",
            f"answer__{question_id}": MARKER,
        },
    )
    client.post(f"/cases/{case_id}/draft", data={"csrf": csrf_of(html), "revision": "0", "reply_text": MARKER})  # stale on purpose
    client.post(f"/cases/{case_id}/draft", data={"csrf": "wrong", "revision": "0", "reply_text": MARKER})
    assert MARKER not in caplog.text
    assert "kettle" not in caplog.text.lower()
    assert MARKER not in client.get(f"/cases/{case_id}/audit.json").text


# ----- 8. decision-blind extraction -----------------------------------------------------------


def test_the_extractor_cannot_see_the_decision() -> None:
    assert list(inspect.signature(extract_reply).parameters)[:2] == ["final_reply_text", "binding"]
    source = (ROOT / "packages" / "core" / "relayguard" / "reply_extractor.py").read_text(encoding="utf-8")
    imported = {node.module for node in ast.walk(ast.parse(source)) if isinstance(node, ast.ImportFrom) and node.module and node.level == 1}
    assert imported <= {"canonical", "claims", "currency", "errors", "schema_validation"}
    service, case_id = _drafted("011")
    binding = service.get(case_id).extraction["binding"]  # type: ignore[index]
    # Identifiers, hashes and versions only - nothing the Decision says (choices, answers, notes).
    assert all(isinstance(value, str | int) for value in binding["decision"].values())
    assert not {"items", "question_answers", "notes", "answers", "choices"} & set(binding["decision"])


def test_the_same_reply_extracts_the_same_under_different_decisions() -> None:
    """Bound to two unrelated Decisions (an L2 refund and an L0 no-op), the same text reads the same."""
    refund, refund_id = _drafted("011")
    noop, noop_id = _drafted("001")
    own = refund.get(refund_id).extraction["binding"]  # type: ignore[index]
    # Same draft (the hash must match BASE, or the extractor refuses), a different Decision bound to it.
    foreign = own | {"decision": noop.get(noop_id).extraction["binding"]["decision"]}  # type: ignore[index]
    bindings = [own, foreign]
    assert bindings[0]["decision"] != bindings[1]["decision"]

    def claims(binding: dict[str, object]) -> list[object]:
        state = extract_reply(BASE, binding)["state"]
        return [
            (key, sorted(json.dumps(c.get("quote", c), sort_keys=True) for c in value))
            for key, value in sorted(state.items())
            if isinstance(value, list)
        ]

    assert claims(bindings[0]) == claims(bindings[1])


# ----- 10. UI boundaries ----------------------------------------------------------------------


def _client(service: CaseService) -> TestClient:
    client = TestClient(create_app(service, access_token=TOKEN))
    client.get(f"/login?token={TOKEN}")
    return client


POSTS = ["/cases/import-sample", "/cases/import-json", "/cases/import-manual", "/cases/interpret", "/cases/read-eml"]


@pytest.mark.parametrize("path", ["/", "/self-check", "/cases/x", "/cases/x/audit.json", "/cases/x/approved.txt", *POSTS])
def test_nothing_is_reachable_without_the_session_cookie(path: str) -> None:
    client = TestClient(create_app(CaseService("op_qa"), access_token=TOKEN))
    response = client.post(path) if path in POSTS else client.get(path)
    assert response.status_code == 401


def test_a_foreign_host_header_is_refused_even_with_a_valid_session() -> None:
    client = _client(CaseService("op_qa"))
    assert client.get("/", headers={"host": "attacker.example"}).status_code == 403


def test_the_session_cookie_is_httponly_and_samesite_strict() -> None:
    client = TestClient(create_app(CaseService("op_qa"), access_token=TOKEN))
    cookie = client.get(f"/login?token={TOKEN}", follow_redirects=False).headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


@pytest.mark.parametrize("route", ["decision", "generate", "draft", "final-approval", "copied", "delete"])
def test_a_wrong_csrf_token_changes_nothing(route: str) -> None:
    service, case_id = _drafted("011")
    before = service.get(case_id).revision
    _client(service).post(
        f"/cases/{case_id}/{route}", data={"csrf": "forged", "revision": str(before), "reply_text": "x"}, follow_redirects=False
    )
    assert service.get(case_id).revision == before  # delete included: the case still exists


@pytest.mark.parametrize("name", ["..%2Fapp.py", "../app.py", "app.css%00.py", "%2e%2e%2fservice.py"])
def test_static_files_do_not_traverse(name: str) -> None:
    assert _client(CaseService("op_qa")).get(f"/static/{name}").status_code == 404


def test_an_expired_case_cannot_be_opened_or_approved_by_its_direct_url() -> None:
    """QA-01 (fixed): 24-hour retention must hold on every path, not only on the case list."""
    now = [datetime(2026, 9, 23, tzinfo=UTC)]
    service = CaseService("op_qa", ServiceRuntime(clock=lambda: now[0]))
    _service, case_id = _case("011", service)
    service.generate(case_id, service.get(case_id).revision)
    now[0] += timedelta(hours=25)
    with pytest.raises(Rejection):
        service.final_approve(case_id, service.get(case_id).revision)


# ----- 11. interpreter adapter ----------------------------------------------------------------


def test_no_consent_means_the_interpreter_is_never_called() -> None:
    calls: list[str] = []

    class Spy:
        def interpret_into_case(self, *_args: object) -> None:
            calls.append("called")

    service = CaseService("op_qa")
    client = TestClient(create_app(service, access_token=TOKEN, interpreter=Spy()))  # type: ignore[arg-type]
    client.get(f"/login?token={TOKEN}")
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/new").text).group(1)  # type: ignore[union-attr]
    for consent in ("", "0", "true", "yes", "on"):
        client.post("/cases/interpret", data={"csrf": csrf, "body": MARKER, "consent": consent})
    assert calls == []


@pytest.mark.parametrize(
    "text",
    ["", "null", "[]", "{}", '{"state": 1}', '{"state": {"evidence": "x", "monetary_terms": {}, "questions": [1, null]}}', "{" * 5000],
)
def test_quality_hint_never_raises_and_only_ever_advises(text: str) -> None:
    assert quality_hint(text) is None or isinstance(quality_hint(text), str)


def test_quality_hint_is_used_only_as_a_repair_hint() -> None:
    source = (ROOT / "packages" / "ui" / "relayguard_ui" / "interpreter.py").read_text(encoding="utf-8")
    uses = [line.strip() for line in source.splitlines() if "quality_hint(" in line and not line.lstrip().startswith("def ")]
    assert uses == ["fault = quality_hint(text)"]


# ----- 12. no external sending ----------------------------------------------------------------

NETWORK_MODULES = {"smtplib", "imaplib", "poplib", "ftplib", "socket", "http.client", "urllib.request", "requests", "httpx", "aiohttp"}


def test_no_product_module_can_send_anything() -> None:
    product = [*(ROOT / "packages" / "core" / "relayguard").glob("*.py"), *(ROOT / "packages" / "ui" / "relayguard_ui").glob("*.py")]
    found: dict[str, set[str]] = {}
    for path in product:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
        hits = {name for name in names if name in NETWORK_MODULES or name.split(".")[0] in {"smtplib", "requests", "httpx"}}
        if "anthropic" in names:
            hits.add("anthropic")
        if hits:
            found[path.name] = hits
    # interpreter: the consented Claude call. selfcheck: binds 127.0.0.1 to see if the port is free.
    assert found == {"interpreter.py": {"anthropic"}, "selfcheck.py": {"socket"}}
    selfcheck = (ROOT / "packages" / "ui" / "relayguard_ui" / "selfcheck.py").read_text(encoding="utf-8")
    assert ".connect(" not in selfcheck and ".send" not in selfcheck


def test_the_generated_reply_has_no_address_to_send_to() -> None:
    service, case_id = _approved()
    text = service.copy_text(case_id)
    assert "@" not in text and "To:" not in text
    assert json.dumps(service.get(case_id).approval).count("send") == 0
