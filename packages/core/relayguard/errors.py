"""Failure taxonomy (SCHEMA.md §9, IMPLEMENTATION.md §12)."""

from __future__ import annotations

from typing import Literal

ErrorCode = Literal[
    "SafetyBlock",
    "SchemaInvalid",
    "StaleState",
    "ProviderUnavailable",
    "UnsupportedInput",
    "InjectionSuspected",
    "PolicyViolation",
    "InternalIntegrityError",
    "DelegationConflict",
]


class Rejection(Exception):
    """Fail-closed rejection. explanation_ja must never contain raw input values."""

    def __init__(self, code: ErrorCode, explanation_ja: str) -> None:
        super().__init__(code)
        self.code: ErrorCode = code
        self.explanation_ja = explanation_ja
