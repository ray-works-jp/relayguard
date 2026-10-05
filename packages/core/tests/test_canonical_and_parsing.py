"""Canonical serialization / hash vectors (SCHEMA.md §5) and strict JSON decoding."""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from relayguard.canonical import canonical_bytes, canonical_hash, decision_hash, source_hash
from relayguard.errors import Rejection
from relayguard.strict_json import parse_strict_json


def test_source_hash_matches_independent_byte_vector() -> None:
    source = {
        "message_id": "m1",
        "subject": None,
        "body": 'Price "5/7" é\n\\ 日本',
        "source_language": "en",
        "user_language": "ja",
        "content_hash": "ignored",
    }
    expected_bytes = '{"body":"Price \\"5/7\\" é\\n\\\\ 日本","source_language":"en","subject":null,"user_language":"ja"}'.encode()
    assert source_hash(source) == hashlib.sha256(expected_bytes).hexdigest()


def test_body_is_not_trimmed_or_normalized() -> None:
    base = {"subject": "s", "body": "A", "source_language": "en", "user_language": "ja"}
    variants = [dict(base, body=b) for b in ("A", "A ", " A", "A\n", "\u0041\u030a", "\u00c5")]
    hashes = {source_hash(v) for v in variants}
    assert len(hashes) == len(variants)


def test_set_arrays_are_sorted_other_arrays_keep_order() -> None:
    a = {"evidence_ids": ["b", "a"], "items": ["b", "a"]}
    b = {"evidence_ids": ["a", "b"], "items": ["b", "a"]}
    c = {"evidence_ids": ["a", "b"], "items": ["a", "b"]}
    assert canonical_hash(a) == canonical_hash(b)
    assert canonical_hash(b) != canonical_hash(c)


def test_confidence_fixed_notation_and_float_forbidden() -> None:
    assert canonical_bytes({"c": Decimal("0.500")}) == b'{"c":0.5}'
    assert canonical_bytes({"c": Decimal("1.0")}) == b'{"c":1}'
    assert canonical_bytes({"c": Decimal("0E-3")}) == b'{"c":0}'
    assert canonical_bytes({"c": Decimal("1E-1")}) == b'{"c":0.1}'
    with pytest.raises(TypeError):
        canonical_bytes({"c": 0.5})


def test_decision_hash_excludes_only_id_version_and_hash() -> None:
    decision = {"decision_id": "d1", "version": 1, "decision_hash": "x", "approved_by": "u1", "items": []}
    same = dict(decision, decision_id="d2", version=7, decision_hash="y")
    changed = dict(decision, approved_by="u2")
    assert decision_hash(decision) == decision_hash(same)
    assert decision_hash(decision) != decision_hash(changed)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":-Infinity}',
        b"\xef\xbb\xbf{}",
        b'{"a":"\xff"}',
        b'{"a":"\\ud800"}',
        b'{"\\udc00":1}',
        b"{'a':1}",
        b'{"a":1,}',
        b"[" * 100000 + b"]" * 100000,
        b'{"a":' + b"9" * 5000 + b"}",
    ],
    ids=lambda raw: repr(raw[:24]),
)
def test_strict_parser_rejects(raw: bytes) -> None:
    with pytest.raises(Rejection) as info:
        parse_strict_json(raw)
    assert info.value.code == "SchemaInvalid"


def test_strict_parser_keeps_int_and_decimal_distinct() -> None:
    value = parse_strict_json(b'{"i":1,"f":1.0,"e":1e-1}')
    assert value["i"] == 1 and type(value["i"]) is int
    assert isinstance(value["f"], Decimal) and isinstance(value["e"], Decimal)


def test_strict_parser_rejects_non_bytes() -> None:
    with pytest.raises(Rejection):
        parse_strict_json("{}")  # type: ignore[arg-type]
