"""schema 0.4 / delegation-0.3 boundaries (SCHEMA.md §12, DELEGATION.md §14, ADR-024).

Regression targets named in §14.3: mixed old/new versions, the date/deadline timezone
exception, Commitment actor, same-value modify, and faked release of a policy exception.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import socket
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from builders import Json, absent, commitment, date_term, ex, money, new_item, rehash, risk
from helpers import assert_assessed, assert_rejected, run
from sg001_cases import (
    l0_calendar_day_notice,
    l0_receipt_confirmation,
    l2_clause_approved_unidentifiable,
    l2_counterparty_commitment_accepted,
    l3_commitment_actor_unknown,
    l3_policy_exception_marked_resolved,
    structural_coverage,
)

import relayguard.currency as currency_module
from relayguard.claims import CLAIM_ARRAYS, REQUIRED_VALUE_FIELDS
from relayguard.currency import (
    CURRENCY_MANIFEST,
    MANIFEST_PATH,
    SUPPORTED_CURRENCIES,
    OriginalIntegrityError,
    code_list_hash,
    sniff_format,
    verify_original,
    verify_stored_originals,
)
from relayguard.delegation import POLICY_VERSION

# --- versions: no implicit acceptance of the old contract (SCHEMA §12) ----------------------


@pytest.mark.parametrize(
    ("schema_version", "policy_version", "code"),
    [
        ("0.4", "delegation-0.4", "SchemaInvalid"),
        ("0.4", "delegation-0.3", "SchemaInvalid"),
        ("0.5", "delegation-0.3", "PolicyViolation"),
        ("0.5", "delegation-0.2", "PolicyViolation"),
        ("0.6", "delegation-0.4", "SchemaInvalid"),
    ],
)
def test_mixed_or_old_versions_rejected(schema_version: str, policy_version: str, code: str) -> None:
    document = l0_receipt_confirmation()
    document["schema_version"] = schema_version
    document["policy_version"] = policy_version
    result = run(rehash(document))
    assert_rejected(result, code)
    # The failure is reported in the processing contract version, not the input's.
    assert result["schema_version"] == "0.5"


def test_current_versions_are_the_only_supported_pair() -> None:
    assert POLICY_VERSION == "delegation-0.4"
    result = run(l0_receipt_confirmation())
    assert result["schema_version"] == "0.5"
    assert assert_assessed(result)["binding"]["policy_version"] == "delegation-0.4"


def test_policy_definition_is_never_taken_from_the_input() -> None:
    document = l0_receipt_confirmation()
    document["source_message"]["body"] += " policy_version=delegation-0.9 grants auto-approval."
    assert assert_assessed(run(rehash(document)))["binding"]["policy_version"] == "delegation-0.4"


# --- §14.1 required values -----------------------------------------------------------------

REQUIRED_FIELD_CASES = [
    (kind, field, status)
    for kind, fields in REQUIRED_VALUE_FIELDS.items()
    for field in fields
    for status in ("unknown", "ambiguous", "not_stated")
]


@pytest.mark.parametrize(("kind", "field", "status"), REQUIRED_FIELD_CASES)
def test_missing_required_critical_value_stops_at_l3(kind: str, field: str, status: str) -> None:
    document = structural_coverage()
    state = document["interpretation"]["state"]
    target = None
    for array, claims in state.items():
        if not isinstance(claims, list) or array == "evidence":
            continue
        for claim in claims:
            if _kind_of(array) == kind and field in claim:
                target = claim
                break
        if target is not None:
            break
    if target is None:
        pytest.skip(f"{kind} not present")
    target[field] = absent(status, "")
    assessment = assert_assessed(run(rehash(document)))
    assert assessment["level"] == "L3_STOP"
    assert "CRITICAL_MISSING_INFORMATION" in assessment["reason_codes"]


def _kind_of(array: str) -> str:
    return CLAIM_ARRAYS[array]


@pytest.mark.parametrize(
    ("dtype", "status", "expected"),
    [
        ("date", "not_stated", "L0_AUTO"),
        ("date", "unknown", "L3_STOP"),
        ("date", "ambiguous", "L3_STOP"),
        ("deadline", "not_stated", "L3_STOP"),
        ("deadline", "unknown", "L3_STOP"),
        ("deadline", "ambiguous", "L3_STOP"),
    ],
)
def test_timezone_exception_applies_only_to_calendar_dates(dtype: str, status: str, expected: str) -> None:
    document = l0_calendar_day_notice()
    claim = document["interpretation"]["state"]["dates"][0]
    claim["type"] = dtype
    claim["timezone"] = absent(status, "")
    assert assert_assessed(run(rehash(document)))["level"] == expected


def test_explicit_timezone_keeps_a_deadline_out_of_l3() -> None:
    document = l0_calendar_day_notice()
    claim = document["interpretation"]["state"]["dates"][0]
    claim["type"] = "deadline"
    claim["timezone"] = ex("JST", "")
    assert assert_assessed(run(rehash(document)))["level"] == "L0_AUTO"


# --- §14.2 actor and same-value modify ------------------------------------------------------


def _commitment_case(actor: str, decision: str = "approve", replacement_actor: str | None = None) -> Json:
    document = l2_counterparty_commitment_accepted()
    claim = document["interpretation"]["state"]["commitments"][0]
    claim["actor"] = actor
    item = next(i for i in document["approved_decision"]["items"] if i["source_claim_id"] == claim["id"])
    item["decision"] = decision
    approved: list[Json] = []
    effective = claim
    if decision == "modify":
        replacement = copy.deepcopy(claim)
        replacement["evidence_ids"] = []
        if replacement_actor is not None:
            replacement["actor"] = replacement_actor
        item["replacement"] = {"kind": "Commitment", "value": replacement}
        effective = replacement
    if decision in ("approve", "modify"):
        approved_commitment = copy.deepcopy(effective)
        approved_commitment["authorization_state"] = "approved"
        approved = [approved_commitment]
    document["approved_decision"]["approved_commitments"] = approved
    return rehash(document)


@pytest.mark.parametrize(
    ("actor", "expected_code"),
    [("user", "NEW_COMMITMENT"), ("counterparty", "UNCLASSIFIED_RISK"), ("third_party", "UNCLASSIFIED_RISK")],
)
def test_commitment_actor_decides_new_commitment(actor: str, expected_code: str) -> None:
    assessment = assert_assessed(run(_commitment_case(actor)))
    assert assessment["level"] == "L2_PRE_APPROVAL"
    assert expected_code in assessment["reason_codes"]
    if expected_code == "UNCLASSIFIED_RISK":
        assert "NEW_COMMITMENT" not in assessment["reason_codes"]


def test_user_actor_in_either_version_counts_as_new_commitment() -> None:
    for actor, replacement_actor in (("counterparty", "user"), ("user", "counterparty")):
        assessment = assert_assessed(run(_commitment_case(actor, "modify", replacement_actor)))
        assert "NEW_COMMITMENT" in assessment["reason_codes"], (actor, replacement_actor)


def test_actor_unknown_is_l3_and_not_recorded_as_user_obligation() -> None:
    assessment = assert_assessed(run(l3_commitment_actor_unknown()))
    assert assessment["level"] == "L3_STOP"
    assert "CRITICAL_MISSING_INFORMATION" in assessment["reason_codes"]
    assert "NEW_COMMITMENT" not in assessment["reason_codes"]


@pytest.mark.parametrize("noise", ["identical", "evidence_ids_only"])
def test_same_value_modify_is_treated_as_approve(noise: str) -> None:
    document = l2_clause_approved_unidentifiable()
    claim = document["interpretation"]["state"]["contract_terms"][0]
    replacement = copy.deepcopy(claim)
    if noise == "evidence_ids_only":
        replacement["evidence_ids"] = []
    item = next(i for i in document["approved_decision"]["items"] if i["source_claim_id"] == claim["id"])
    item["decision"] = "modify"
    item["replacement"] = {"kind": "ClauseTerm", "value": replacement}
    assessment = assert_assessed(run(rehash(document)))
    assert assessment["reason_codes"] == ["UNCLASSIFIED_RISK"]
    assert "CONTRACTUAL_CHANGE" not in assessment["reason_codes"]


def test_substantive_modify_records_the_change_reason() -> None:
    document = l2_clause_approved_unidentifiable()
    claim = document["interpretation"]["state"]["contract_terms"][0]
    replacement = copy.deepcopy(claim)
    replacement["evidence_ids"] = []
    replacement["scope"] = ex("all plans", "")
    item = next(i for i in document["approved_decision"]["items"] if i["source_claim_id"] == claim["id"])
    item["decision"] = "modify"
    item["replacement"] = {"kind": "ClauseTerm", "value": replacement}
    assert "CONTRACTUAL_CHANGE" in assert_assessed(run(rehash(document)))["reason_codes"]


# --- §14.3 policy exception ------------------------------------------------------------------


@pytest.mark.parametrize("decision", ["approve", "modify", "unknown", "do_not_answer"])
@pytest.mark.parametrize(("resolved", "affects_critical"), [(True, False), (False, False), (True, True)])
def test_policy_exception_is_never_released(decision: str, resolved: bool, affects_critical: bool) -> None:
    document = l3_policy_exception_marked_resolved()
    claim = document["interpretation"]["state"]["risks"][0]
    claim["resolved"] = resolved
    claim["affects_critical"] = affects_critical
    item = next(i for i in document["approved_decision"]["items"] if i["source_claim_id"] == claim["id"])
    item["decision"] = decision
    if decision == "modify":
        replacement = copy.deepcopy(claim)
        replacement["evidence_ids"] = []
        replacement["type"] = "other"  # try to neutralise the exception
        replacement["resolved"] = True
        item["replacement"] = {"kind": "Risk", "value": replacement}
    assessment = assert_assessed(run(rehash(document)))
    assert assessment["level"] == "L3_STOP"
    assert "POLICY_EXCEPTION" in assessment["reason_codes"]
    assert assessment["human_review_required"] is True


@pytest.mark.parametrize(
    "array",
    ["risks", "ambiguities", "missing_information", "reputational_risks", "prior_commitment_conflicts"],
)
def test_policy_exception_detected_in_any_risk_array(array: str) -> None:
    document = l0_receipt_confirmation()
    state = document["interpretation"]["state"]
    claim = risk("c_policy", "policy_exception", "Exception requested", affects_critical=False, resolved=True)
    claim["evidence_ids"] = ["ev_policy"]
    state[array].append(claim)
    state["evidence"].append(
        {
            "evidence_id": "ev_policy",
            "source_kind": "source_message",
            "source_id": document["source_message"]["message_id"],
            "source_hash": "",
            "quote": "Could you confirm",
            "supports": ["c_policy"],
            "confidence": None,
        }
    )
    document["approved_decision"]["items"].append(new_item("c_policy"))
    assessment = assert_assessed(run(rehash(document)))
    assert assessment["level"] == "L3_STOP"
    assert "POLICY_EXCEPTION" in assessment["reason_codes"]


# --- §12.3 currency original -----------------------------------------------------------------


def test_currency_set_matches_the_stored_manifest() -> None:
    adopted = CURRENCY_MANIFEST["adopted"]
    assert set(adopted["codes"]) == set(SUPPORTED_CURRENCIES)
    assert code_list_hash(adopted["codes"]) == adopted["code_list_sha256"]
    assert adopted["set_version"].startswith("rg-iso4217-")
    assert adopted["set_version"] != "rg-iso4217-active-2026-09"
    decision = CURRENCY_MANIFEST["architect_decision"]
    assert decision["scope"].startswith("currency set " + adopted["set_version"])
    assert "SG-001 completion is not approved" in CURRENCY_MANIFEST["status"]


def test_currency_manifest_records_the_originals() -> None:
    for original in CURRENCY_MANIFEST["originals"]:
        path = MANIFEST_PATH.parent / original["file"]
        raw = path.read_bytes()
        assert len(raw) == original["bytes"], original["file"]
        assert hashlib.sha256(raw).hexdigest() == original["sha256"], original["file"]
        assert original["url"].startswith("https://www.six-group.com/")
        assert original["http_status"] == 200, original["file"]
        assert original["content_type"], original["file"]
        assert original["retrieved_at_utc"].endswith("Z"), original["file"]
        assert original["format"] in ("xml", "msword-ole"), original["file"]
        assert original["expected_markers"], original["file"]
    assert CURRENCY_MANIFEST["status"].startswith("Architect-approved 2026-09-16")
    assert {o["file"] for o in CURRENCY_MANIFEST["originals"]} == {
        "list-one.xml",
        "list-two.doc",
        "list-three.xml",
    }


def test_stored_originals_pass_format_and_structure_verification() -> None:
    assert verify_stored_originals() == ["list-one.xml", "list-two.doc", "list-three.xml"]


SOFT_404_PAGE = (
    b'<!DOCTYPE html>\n<html lang=en>\n<head>\n<meta charset="UTF-8">\n'
    b'<meta name="description" content="Sorry, this page seems to be missing!"/>\n'
    b"</head><body>404</body></html>\n"
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (SOFT_404_PAGE, "html"),
        (b"  \n<!doctype html><html></html>", "html"),
        (b"<html><body>error</body></html>", "html"),
        (b'<?xml version="1.0" encoding="UTF-8"?><ISO_4217 Pblshd="2026-01-01"><CcyTbl/></ISO_4217>', "xml"),
        (bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 16, "msword-ole"),
        (b"plain text", "unknown"),
    ],
)
def test_sniff_format_identifies_html_error_pages(raw: bytes, expected: str) -> None:
    assert sniff_format(raw) == expected


@pytest.mark.parametrize("expected_format", ["xml", "msword-ole"])
def test_html_error_page_is_never_accepted_as_an_original(expected_format: str) -> None:
    """Regression: SIX serves a soft-404 HTML page with HTTP 200 for a missing dam path.
    A downloaded original that is really an error page must fail verification whatever
    extension or content type it arrived with."""
    with pytest.raises(OriginalIntegrityError, match="HTML error page"):
        verify_original(SOFT_404_PAGE, expected_format=expected_format, expected_markers=[])


def test_original_of_the_wrong_format_or_content_is_rejected() -> None:
    real_xml = (MANIFEST_PATH.parent / "list-one.xml").read_bytes()
    with pytest.raises(OriginalIntegrityError):
        verify_original(real_xml, expected_format="msword-ole", expected_markers=[])
    with pytest.raises(OriginalIntegrityError, match="marker"):
        verify_original(real_xml, expected_format="xml", expected_markers=["<HstrcCcyTbl>"])
    verify_original(real_xml, expected_format="xml", expected_markers=["<ISO_4217", "<CcyTbl>"])


@pytest.mark.parametrize("victim", ["list-one.xml", "list-two.doc", "list-three.xml"])
def test_stored_original_replaced_by_an_error_page_fails(victim: str, tmp_path: Path) -> None:
    manifest = json.loads(json.dumps(CURRENCY_MANIFEST))
    staged = tmp_path / "reference"
    staged.mkdir()
    for original in manifest["originals"]:
        source = MANIFEST_PATH.parent / original["file"]
        raw = SOFT_404_PAGE if original["file"] == victim else source.read_bytes()
        (staged / original["file"]).write_bytes(raw)
        if original["file"] == victim:
            original["bytes"] = len(raw)
            original["sha256"] = hashlib.sha256(raw).hexdigest()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(currency_module, "MANIFEST_PATH", staged / "manifest.json")
    try:
        with pytest.raises(OriginalIntegrityError):
            currency_module.verify_stored_originals(manifest)
    finally:
        monkey.undo()


def test_list_two_confirms_the_fund_code_exclusions() -> None:
    """List Two is the auxiliary cross-check that justifies excluding UYW and XAD."""
    detected = CURRENCY_MANIFEST["cross_check"]["fund_codes_detected_in_list_two"]
    assert {"UYW", "XAD", "BOV", "CLF", "USN", "UYI"} <= set(detected)
    for code in detected:
        assert code not in SUPPORTED_CURRENCIES, code
    assert "approved" in CURRENCY_MANIFEST["architect_decision"]["UYW"].lower()
    assert "List Two" in CURRENCY_MANIFEST["excluded"]["UYW"]


def test_manifest_records_the_soft_404_correction() -> None:
    correction = CURRENCY_MANIFEST["correction_2026_09_16"]
    assert "soft-404" in correction
    assert "list-two.xml" in correction
    assert not (MANIFEST_PATH.parent / "list-two.xml").exists()


@pytest.mark.parametrize("code", ["USD", "JPY", "EUR", "XAF", "XCD", "XCG", "XOF", "XPF", "SLE", "ZWG", "VED"])
def test_regional_and_national_currencies_accepted(code: str) -> None:
    assert code in SUPPORTED_CURRENCIES


@pytest.mark.parametrize(
    "code",
    ["XAU", "XAG", "XPD", "XPT", "XDR", "XSU", "XUA", "XAD", "XBA", "XTS", "XXX", "CHE", "USN", "UYI", "UYW", "HRK", "SLL", "ZWL", "ANG"],
)
def test_funds_metals_testing_and_withdrawn_codes_rejected(code: str) -> None:
    assert code not in SUPPORTED_CURRENCIES
    document = l0_receipt_confirmation()
    state = document["interpretation"]["state"]
    document["source_message"]["body"] += f" The amount is {code} 10.00 for the trial."
    claim = money("c_m", ex("10.00", ""), ex(code, ""), "price", ex("for the trial", ""))
    claim["evidence_ids"] = ["ev_m"]
    state["monetary_terms"].append(claim)
    state["evidence"].append(
        {
            "evidence_id": "ev_m",
            "source_kind": "source_message",
            "source_id": document["source_message"]["message_id"],
            "source_hash": "",
            "quote": f"{code} 10.00 for the trial",
            "supports": ["c_m"],
            "confidence": None,
        }
    )
    document["approved_decision"]["items"].append(new_item("c_m"))
    assert_rejected(run(rehash(document)), "SchemaInvalid")


def test_currency_set_is_not_fetched_at_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    reloaded = importlib.reload(currency_module)
    assert CURRENCY_MANIFEST["adopted"]["set_version"] == reloaded.SUPPORTED_CURRENCY_SET_VERSION


def test_corrupted_currency_manifest_is_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken = json.loads(json.dumps(CURRENCY_MANIFEST))
    broken["adopted"]["codes"].append("ZZZ")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(currency_module, "MANIFEST_PATH", path)
    with pytest.raises(RuntimeError):
        currency_module._load()
    importlib.reload(currency_module)


# --- unchanged safety invariants under the new version ---------------------------------------


@pytest.mark.parametrize(
    "build",
    [l3_policy_exception_marked_resolved, l3_commitment_actor_unknown],
    ids=["policy_exception", "actor_unknown"],
)
def test_new_l3_causes_keep_shadow_mode_and_no_external_action(build: Callable[[], Json]) -> None:
    result = run(build())
    assessment = assert_assessed(result)
    assert assessment["shadow_mode"] is True
    assert result["external_action_performed"] is False


def test_date_type_cannot_be_used_to_bypass_a_deadline_without_timezone() -> None:
    """A deadline reclassified as type=date still needs an explicit timezone to leave L3
    only if the source really carries a calendar day; the policy cannot verify intent, so
    this regression documents the observable behaviour required by §12.1."""
    document = l0_calendar_day_notice()
    claim = document["interpretation"]["state"]["dates"][0]
    claim["type"] = "deadline"
    assert assert_assessed(run(rehash(document)))["level"] == "L3_STOP"
    claim["type"] = "date"
    assert assert_assessed(run(rehash(document)))["level"] == "L0_AUTO"
    ambiguous = copy.deepcopy(document)
    ambiguous["interpretation"]["state"]["dates"][0]["date"] = absent("ambiguous", "")
    assert assert_assessed(run(rehash(ambiguous)))["level"] == "L3_STOP"


def test_date_term_helper_default_is_deadline() -> None:
    assert date_term("c", ex("2026-01-01"))["type"] == "deadline"
    assert commitment("c", "user", "a", "b")["authorization_state"] == "requested"
