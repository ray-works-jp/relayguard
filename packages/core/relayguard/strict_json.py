"""Strict JSON decoding: invalid UTF-8, BOM, duplicate keys, non-finite numbers and
lone surrogates are rejected. Fractional/exponent numbers are decoded as Decimal
(never binary float); integers stay int, so no silent int/float coercion occurs."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from .errors import Rejection


class _DuplicateKey(ValueError):
    pass


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey()
        result[key] = value
    return result


def _reject_constant(_name: str) -> Any:
    raise ValueError("non-finite number")


def _contains_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def _check_strings(value: Any) -> None:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if _contains_surrogate(item):
                raise Rejection("SchemaInvalid", "入力に不正なUnicode（孤立サロゲート）が含まれています。")
        elif isinstance(item, dict):
            for key, child in item.items():
                if _contains_surrogate(key):
                    raise Rejection("SchemaInvalid", "入力に不正なUnicode（孤立サロゲート）が含まれています。")
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)


def parse_strict_json(raw: bytes) -> Any:
    if not isinstance(raw, (bytes, bytearray)):
        raise Rejection("SchemaInvalid", "入力はUTF-8のJSONバイト列である必要があります。")
    try:
        text = bytes(raw).decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise Rejection("SchemaInvalid", "入力が正しいUTF-8ではありません。") from None
    if text.startswith("﻿"):
        raise Rejection("SchemaInvalid", "入力の先頭にBOMがあります。BOMは受理しません。")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
            parse_float=Decimal,
        )
    except _DuplicateKey:
        raise Rejection("SchemaInvalid", "JSONに重複したキーがあります。") from None
    except ValueError, RecursionError:
        raise Rejection("SchemaInvalid", "JSONとして解析できません（構文不正・非有限数・過大な値を含む）。") from None
    _check_strings(value)
    return value
