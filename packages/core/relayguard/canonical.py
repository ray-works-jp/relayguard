"""Canonical serialization and SHA-256 hashing (SCHEMA.md §5)."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

# Arrays defined as ID/code sets (SCHEMA.md §5, SD-07 supplement). Sorted in ASCII
# order before hashing; every other array keeps its meaningful order.
SET_ARRAY_KEYS: frozenset[str] = frozenset(
    {
        "evidence_ids",
        "supports",
        "explicitly_unanswered",
        "reason_codes",
        "monetary_term_ids",
        "expected_claim_ids",
        "actual_claim_ids",
    }
)


def _encode_number(value: int | Decimal) -> str:
    if isinstance(value, int):
        return str(value)
    if not value.is_finite():
        raise ValueError("non-finite number is not serializable")
    if value == 0:
        return "0"
    # Fixed notation, trailing zeros removed, no exponent (Confidence rule).
    text = format(value.normalize(), "f")
    return text


def _encode(value: Any, parent_key: str | None, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, (int, Decimal)):
        out.append(_encode_number(value))
    elif isinstance(value, str):
        # JSON escape only quote, backslash and control characters; keep other
        # Unicode as raw UTF-8 (no "/" or non-ASCII escaping).
        out.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, list):
        items = value
        if parent_key in SET_ARRAY_KEYS:
            items = sorted(value)
        out.append("[")
        for index, item in enumerate(items):
            if index:
                out.append(",")
            _encode(item, None, out)
        out.append("]")
    elif isinstance(value, dict):
        out.append("{")
        for index, key in enumerate(sorted(value)):
            if not isinstance(key, str):
                raise TypeError("object keys must be strings")
            if index:
                out.append(",")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _encode(value[key], key, out)
        out.append("}")
    else:
        # float and any other type are forbidden in canonical payloads.
        raise TypeError(f"unsupported canonical type: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    out: list[str] = []
    _encode(value, None, out)
    return "".join(out).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def source_hash(source_message: dict[str, Any]) -> str:
    return canonical_hash(
        {
            "subject": source_message["subject"],
            "body": source_message["body"],
            "source_language": source_message["source_language"],
            "user_language": source_message["user_language"],
        }
    )


_DECISION_HASH_EXCLUDED = ("decision_id", "version", "decision_hash")


def decision_hash(decision: dict[str, Any]) -> str:
    # Decision contains no Confidence fields in SCHEMA v0.5, so nothing else is removed.
    payload = {k: v for k, v in decision.items() if k not in _DECISION_HASH_EXCLUDED}
    return canonical_hash(payload)
