"""AC-2 / SCHEMA.md §11: every required field, additional property, type, enum, format,
ID, nullable and version violation is rejected without coercion (never a default level)."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from builders import Json, rehash, to_bytes
from helpers import assert_rejected, run
from sg001_cases import l0_receipt_confirmation, l2_refund_commitment, structural_coverage

Path = tuple[str | int, ...]

ENUM_KEYS = frozenset(
    {
        "status", "source_language", "user_language", "source_kind", "type", "actor",
        "authorization_state", "intensity", "decision", "kind", "schema_version",
    }
)  # fmt: skip


def _walk(value: Any, path: Path, pattern: tuple[str, ...]) -> Iterator[tuple[Path, tuple[str, ...], Any]]:
    yield path, pattern, value
    if isinstance(value, dict):
        for key, child in value.items():
            label = f"{key}:{value['kind']}" if key == "value" and "kind" in value else key
            yield from _walk(child, (*path, key), (*pattern, label))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, (*path, index), (*pattern, "*"))


def _unique_nodes(document: Json) -> list[tuple[Path, Any]]:
    """One node per structural location (array indices collapsed, replacement kinds kept)."""
    seen: set[tuple[str, ...]] = set()
    nodes: list[tuple[Path, Any]] = []
    for path, pattern, value in _walk(document, (), ()):
        if pattern not in seen:
            seen.add(pattern)
            nodes.append((path, value))
    return nodes


def _get(document: Any, path: Path) -> Any:
    for segment in path:
        document = document[segment]
    return document


def _label(path: Path) -> str:
    return "/" + "/".join(map(str, path))


BASE = structural_coverage()
NODES = _unique_nodes(BASE)
OBJECT_KEYS = [(path, key) for path, value in NODES if isinstance(value, dict) for key in value]
OBJECT_PATHS = [path for path, value in NODES if isinstance(value, dict)]
LEAF_PATHS = [path for path, _ in NODES if path]


def _wrong_type(value: Any) -> Any:
    if isinstance(value, bool):
        return "true"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str):
        return 1
    if value is None:
        return True
    if isinstance(value, list):
        return None
    return []


def test_base_document_is_valid() -> None:
    assert run(BASE)["status"] == "assessed"
    assert len(OBJECT_KEYS) > 400


@pytest.mark.parametrize(("path", "key"), OBJECT_KEYS, ids=[_label((*p, k)) for p, k in OBJECT_KEYS])
def test_missing_required_field_rejected(path: Path, key: str) -> None:
    document = copy.deepcopy(BASE)
    del _get(document, path)[key]
    assert_rejected(run(document), "SchemaInvalid")


@pytest.mark.parametrize("path", OBJECT_PATHS, ids=[_label(p) for p in OBJECT_PATHS])
def test_additional_property_rejected(path: Path) -> None:
    document = copy.deepcopy(BASE)
    _get(document, path)["expected_level"] = "L0_AUTO"
    assert_rejected(run(document), "SchemaInvalid")


@pytest.mark.parametrize("path", LEAF_PATHS, ids=[_label(p) for p in LEAF_PATHS])
def test_wrong_type_rejected_without_coercion(path: Path) -> None:
    document = copy.deepcopy(BASE)
    parent = _get(document, path[:-1])
    parent[path[-1]] = _wrong_type(parent[path[-1]])
    assert_rejected(run(document), "SchemaInvalid")


ENUM_PATHS = [p for p, v in NODES if p and p[-1] in ENUM_KEYS and isinstance(v, str)]


@pytest.mark.parametrize("path", ENUM_PATHS, ids=[_label(p) for p in ENUM_PATHS])
def test_invalid_enum_rejected(path: Path) -> None:
    document = copy.deepcopy(BASE)
    _get(document, path[:-1])[path[-1]] = "INVALID_ENUM_VALUE"
    assert_rejected(run(document), "SchemaInvalid")


def _with_leaf(path: Path, value: Any, base: Json | None = None) -> Json:
    document = copy.deepcopy(base if base is not None else BASE)
    _get(document, path[:-1])[path[-1]] = value
    return document


PRICE = ("interpretation", "state", "monetary_terms", 0)
SEATS = ("interpretation", "state", "quantities", 0)
DATE = ("interpretation", "state", "dates", 0)


@pytest.mark.parametrize(
    "bad",
    ["1,000", "1e3", "1E3", "$5", "01", "1.", ".5", " 5", "5 ", "+5", "--1", "NaN", "Infinity", "", "1" * 39, "0." + "1" * 19, "１２"],
)
def test_invalid_decimal_rejected(bad: str) -> None:
    assert_rejected(run(_with_leaf((*PRICE, "amount", "value"), bad)), "SchemaInvalid")


def test_decimal_limits_accepted_at_boundary() -> None:
    doc = _with_leaf((*SEATS, "quantity", "value"), "1" * 20 + "." + "1" * 18)
    assert run(rehash(doc))["status"] == "assessed"


def test_decimal_as_json_number_rejected() -> None:
    assert_rejected(run(_with_leaf((*PRICE, "amount", "value"), Decimal("1000.50"))), "SchemaInvalid")
    assert_rejected(run(_with_leaf((*PRICE, "amount", "value"), 1000)), "SchemaInvalid")


@pytest.mark.parametrize("bad", ["2026-02-30", "2026-2-03", "2026/02/03", "20260203", "2026-13-01", "0000-01-01", "2026-02-03T00:00:00Z"])
def test_invalid_date_rejected(bad: str) -> None:
    assert_rejected(run(_with_leaf((*DATE, "date", "value"), bad)), "SchemaInvalid")


@pytest.mark.parametrize(
    "bad",
    [
        "2026-09-15T09:00:00Z",
        "2026-09-15T09:00:00.000+09:00",
        "2026-09-15 09:00:00.000Z",
        "2026-09-15T24:00:00.000Z",
        "2026-09-15T23:59:60.000Z",
        "2026-02-29T00:00:00.000Z",
        "2026-09-15T09:00:00.0000Z",
    ],
)
def test_invalid_timestamp_rejected(bad: str) -> None:
    assert_rejected(run(_with_leaf(("approved_decision", "approved_at"), bad)), "SchemaInvalid")


@pytest.mark.parametrize("bad", ["usd", "US$", "$", "XYZ", "HRK", "XXX", "XTS", "USDT", "US"])
def test_unsupported_currency_rejected(bad: str) -> None:
    assert_rejected(run(_with_leaf((*PRICE, "currency", "value"), bad)), "SchemaInvalid")


@pytest.mark.parametrize("bad", ["", "a b", "a\n", "日本", "a" * 129, "a.b", "a/b", "a\u00a0"])
def test_invalid_id_rejected(bad: str) -> None:
    assert_rejected(run(_with_leaf(("case_id",), bad)), "SchemaInvalid")


def test_id_length_boundary_accepted() -> None:
    assert run(_with_leaf(("case_id",), "a" * 128))["status"] == "assessed"


@pytest.mark.parametrize("bad", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "0" * 63 + "\n"])
def test_invalid_hash_rejected(bad: str) -> None:
    assert_rejected(run(_with_leaf(("source_message", "content_hash"), bad)), "SchemaInvalid")


@pytest.mark.parametrize("bad", [0, -1, Decimal("1.0"), "1", True, 9007199254740992])
def test_invalid_version_rejected(bad: Any) -> None:
    assert_rejected(run(_with_leaf(("interpretation", "version"), bad)), "SchemaInvalid")


@pytest.mark.parametrize("bad", [Decimal("1.5"), Decimal("-0.1"), Decimal("0.1234"), "0.5", True])
def test_invalid_confidence_rejected(bad: Any) -> None:
    doc = _with_leaf(("interpretation", "state", "evidence", 1, "confidence"), bad)
    assert_rejected(run(doc), "SchemaInvalid")


def test_confidence_boundaries_accepted() -> None:
    for value in (0, 1, Decimal("0.001"), Decimal("0.500")):
        doc = _with_leaf(("interpretation", "state", "evidence", 1, "confidence"), value)
        assert run(doc)["status"] == "assessed"


@pytest.mark.parametrize("text", ["bad\u0000", "bad\u0007", "bad\u001b", "bad\u007f", "bad\u0085"])
def test_control_characters_in_text_rejected(text: str) -> None:
    doc = _with_leaf(("interpretation", "state", "sender_intent", 0, "text", "value"), text)
    assert_rejected(run(doc), "SchemaInvalid")


def test_newline_and_tab_allowed_in_text() -> None:
    doc = _with_leaf(("interpretation", "state", "sender_intent", 0, "text", "value"), "line1\r\n\tline2")
    assert run(doc)["status"] == "assessed"


def test_nullable_misuse_rejected() -> None:
    value_path = (*PRICE, "amount")
    explicit_null = _with_leaf(value_path, {"status": "explicit", "value": None, "raw_text": ""})
    assert_rejected(run(explicit_null), "SchemaInvalid")
    unknown_with_value = _with_leaf(value_path, {"status": "unknown", "value": "5", "raw_text": ""})
    assert_rejected(run(unknown_with_value), "SchemaInvalid")
    string_status = _with_leaf(value_path, "unknown")
    assert_rejected(run(string_status), "SchemaInvalid")
    empty_subject = _with_leaf(("source_message", "subject"), "")
    assert_rejected(run(empty_subject), "SchemaInvalid")
    null_body = _with_leaf(("source_message", "body"), None)
    assert_rejected(run(null_body), "SchemaInvalid")
    null_array = _with_leaf(("approved_decision", "human_notes"), None)
    assert_rejected(run(null_array), "SchemaInvalid")
    legal_not_required = _with_leaf(("interpretation", "state", "legal_claims", 0, "requires_human_review"), False)
    assert_rejected(run(legal_not_required), "SchemaInvalid")


def test_replacement_rules_enforced_by_schema() -> None:
    base = l2_refund_commitment()
    items = base["approved_decision"]["items"]
    modify_without_replacement = copy.deepcopy(base)
    modify_without_replacement["approved_decision"]["items"][0]["decision"] = "modify"
    assert_rejected(run(rehash(modify_without_replacement)), "SchemaInvalid")

    approve_with_replacement = copy.deepcopy(base)
    claim = base["interpretation"]["state"]["monetary_terms"][0]
    approve_with_replacement["approved_decision"]["items"][0]["replacement"] = {"kind": "MonetaryTerm", "value": claim}
    assert items[0]["decision"] == "approve"
    assert_rejected(run(rehash(approve_with_replacement)), "SchemaInvalid")

    untagged = copy.deepcopy(base)
    untagged["approved_decision"]["items"][0]["decision"] = "modify"
    untagged["approved_decision"]["items"][0]["replacement"] = claim
    assert_rejected(run(rehash(untagged)), "SchemaInvalid")


def test_duplicate_items_in_id_sets_rejected() -> None:
    doc = copy.deepcopy(BASE)
    claim = doc["interpretation"]["state"]["sender_intent"][0]
    claim["evidence_ids"] = claim["evidence_ids"] * 2
    assert_rejected(run(rehash(doc)), "SchemaInvalid")


@pytest.mark.parametrize("version", ["0.4", "0.6", "0.5 ", 0.5])
def test_unknown_schema_version_rejected(version: Any) -> None:
    value = Decimal("0.5") if version == 0.5 else version
    assert_rejected(run(_with_leaf(("schema_version",), value, l0_receipt_confirmation())), "SchemaInvalid")


def test_non_object_top_level_rejected() -> None:
    for raw in (b"[]", b"null", b'"x"', b"1", b""):
        result = run(raw)
        assert_rejected(result, "SchemaInvalid")
        assert result["failure"]["case_id"] is None


def test_raw_bytes_roundtrip_of_builder_is_exact() -> None:
    raw = to_bytes(BASE)
    assert b"0.95" in raw and b"@@RG_DECIMAL@@" not in raw
