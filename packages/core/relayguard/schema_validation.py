"""Executable JSON Schema validation for SCHEMA.md v0.5 contracts.

Differences from a stock Draft 2020-12 validator (all stricter):
- ``pattern`` uses full-match semantics (no trailing-newline ``$`` loophole).
- ``integer`` accepts only int (not bool, not Decimal/float such as 1.0).
- ``number`` accepts only int (not bool) and Decimal produced by strict_json.
- rg-* formats are asserted.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections.abc import Iterator
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, validators
from jsonschema.exceptions import ValidationError

from .currency import SUPPORTED_CURRENCIES
from .errors import Rejection

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "v0_5"

_DECIMAL_RE = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIMESTAMP_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")
_CURRENCY_RE = re.compile(r"[A-Z]{3}")
_SAFE_PATH_SEGMENT = re.compile(r"[a-z_]{1,64}")


def _is_int(_checker: Any, instance: Any) -> bool:
    return isinstance(instance, int) and not isinstance(instance, bool)


def _is_number(_checker: Any, instance: Any) -> bool:
    if isinstance(instance, bool):
        return False
    if isinstance(instance, int):
        return True
    return isinstance(instance, Decimal) and instance.is_finite()


def _full_match_pattern(validator: Any, pattern: str, instance: Any, _schema: Any) -> Iterator[ValidationError]:
    if not validator.is_type(instance, "string"):
        return
    if re.fullmatch(pattern, instance) is None:
        yield ValidationError("pattern mismatch")


_FORMAT_CHECKER = FormatChecker(formats=())


def _check_decimal(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    match = _DECIMAL_RE.fullmatch(instance)
    if match is None:
        return False
    digits = instance.lstrip("-").replace(".", "")
    fraction = match.group(2)
    fraction_digits = len(fraction) - 1 if fraction else 0
    return len(digits) <= 38 and fraction_digits <= 18


def _check_date(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    if _DATE_RE.fullmatch(instance) is None:
        return False
    try:
        _dt.date.fromisoformat(instance)
    except ValueError:
        return False
    return True


def _check_timestamp(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    if _TIMESTAMP_RE.fullmatch(instance) is None:
        return False
    try:
        _dt.datetime.strptime(instance, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def _check_currency(instance: object) -> bool:
    if not isinstance(instance, str):
        return True
    return _CURRENCY_RE.fullmatch(instance) is not None and instance in SUPPORTED_CURRENCIES


def _check_confidence(instance: object) -> bool:
    if isinstance(instance, bool) or not isinstance(instance, (int, Decimal)):
        return True
    value = Decimal(instance)
    if not value.is_finite():
        return False
    exponent = value.normalize().as_tuple().exponent
    return isinstance(exponent, int) and exponent >= -3


for _name, _check in (
    ("rg-decimal", _check_decimal),
    ("rg-date", _check_date),
    ("rg-timestamp", _check_timestamp),
    ("rg-currency", _check_currency),
    ("rg-confidence", _check_confidence),
):
    _FORMAT_CHECKER.checks(_name)(_check)

_TYPE_CHECKER = Draft202012Validator.TYPE_CHECKER.redefine_many({"integer": _is_int, "number": _is_number})

StrictValidator = validators.extend(
    Draft202012Validator,
    validators={"pattern": _full_match_pattern},
    type_checker=_TYPE_CHECKER,
)


@cache
def load_strict_validator(path: Path) -> Any:
    """Strict validator (full-match patterns, strict int/Decimal, rg-* formats) for any
    schema file, so other RelayGuard contracts share exactly the same type rules."""
    with path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    StrictValidator.check_schema(schema)
    return StrictValidator(schema, format_checker=_FORMAT_CHECKER)


def _validator(name: str) -> Any:
    return load_strict_validator(SCHEMA_DIR / name)


def safe_error_locations(validator: Any, instance: Any) -> list[str]:
    """Error locations without values (values may carry PII)."""
    return [_safe_location(e) for e in validator.iter_errors(instance)]


def _safe_location(error: ValidationError) -> str:
    # Only schema-known lowercase property names and indices are shown; values and
    # unexpected keys (which may carry PII) are never echoed.
    parts: list[str] = []
    for segment in error.absolute_path:
        if isinstance(segment, int):
            parts.append(str(segment))
        elif isinstance(segment, str) and _SAFE_PATH_SEGMENT.fullmatch(segment):
            parts.append(segment)
        else:
            parts.append("*")
    return "/" + "/".join(parts)


def _first_error(validator: Any, instance: Any) -> ValidationError | None:
    # Iteration order is deterministic for a given instance; stop at the first error.
    error: ValidationError | None = next(iter(validator.iter_errors(instance)), None)
    return error


def validate_shadow_core_input(instance: Any) -> None:
    error = _first_error(_validator("shadow_core_input.schema.json"), instance)
    if error is not None:
        raise Rejection(
            "SchemaInvalid",
            f"入力がShadowCoreInput構造契約（schema 0.5）に適合しません。場所: {_safe_location(error)}",
        )


def shadow_core_result_errors(instance: Any) -> list[str]:
    return [_safe_location(e) for e in _validator("shadow_core_result.schema.json").iter_errors(instance)]


@cache
def _draft_subschema_validator(def_name: str) -> Any:
    schema = json.loads((SCHEMA_DIR / "draft.schema.json").read_text(encoding="utf-8"))
    sub = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{def_name}",
    }
    StrictValidator.check_schema(sub)
    return StrictValidator(sub, format_checker=_FORMAT_CHECKER)


def validate_draft(instance: Any) -> None:
    error = _first_error(_validator("draft.schema.json"), instance)
    if error is not None:
        raise Rejection(
            "SchemaInvalid",
            f"Draft構造契約（schema 0.5）に適合しません。場所: {_safe_location(error)}",
        )


def validate_draft_proposal(instance: Any) -> None:
    error = _first_error(_draft_subschema_validator("DraftProposal"), instance)
    if error is not None:
        raise Rejection(
            "SchemaInvalid",
            f"DraftProposal構造契約（schema 0.5）に適合しません。場所: {_safe_location(error)}",
        )


def validate_draft_binding(instance: Any) -> None:
    error = _first_error(_draft_subschema_validator("DraftBinding"), instance)
    if error is not None:
        raise Rejection(
            "SchemaInvalid",
            f"DraftBinding構造契約（schema 0.5）に適合しません。場所: {_safe_location(error)}",
        )


def validate_reply_extraction(instance: Any) -> None:
    error = _first_error(_draft_subschema_validator("ReplyExtraction"), instance)
    if error is not None:
        raise Rejection(
            "SchemaInvalid",
            f"ReplyExtraction構造契約（schema 0.5）に適合しません。場所: {_safe_location(error)}",
        )


@cache
def _verification_subschema_validator(def_name: str) -> Any:
    schema = json.loads((SCHEMA_DIR / "verification.schema.json").read_text(encoding="utf-8"))
    sub = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{def_name}"}
    StrictValidator.check_schema(sub)
    return StrictValidator(sub, format_checker=_FORMAT_CHECKER)


def validate_verification_contract(def_name: str, instance: Any) -> None:
    """Validate Verification / DiffResult / Finding / DelegationAssessment / FinalApproval."""
    error = _first_error(_verification_subschema_validator(def_name), instance)
    if error is not None:
        raise Rejection(
            "InternalIntegrityError",
            f"{def_name}構造契約（schema 0.5）に適合しません。場所: {_safe_location(error)}",
        )
