"""Authoring helpers for the 100 release-set candidate cases (fixture_version 0.2).

Every case is synthetic (no real people, companies or mail). Labels are Builder candidates
derived from the DELEGATION.md v0.4 rule text (§§12, 14, 15) and SCHEMA.md v0.5, written
before running the implementation; they are not Architect-approved Gold.

A case function returns either a ShadowCoreInput document or raw bytes (for inputs that
cannot be represented as a well-formed document, such as duplicate JSON keys).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from builders import Json

LEVELS = ("L0_AUTO", "L1_POST_REVIEW", "L2_PRE_APPROVAL", "L3_STOP")


@dataclass(frozen=True)
class Candidate:
    case_id: str
    category: str
    variant: str
    title_ja: str
    threats: tuple[str, ...]
    release_class: str
    expected: dict[str, Any]
    basis: tuple[str, ...]
    rationale_ja: str
    build: Callable[[], Json | bytes]


REGISTRY: dict[str, Candidate] = {}


def assessed(level: str, *reason_codes: str) -> dict[str, Any]:
    """Pre-generation expectation. Without a model proposal the level equals the minimum."""
    if level not in LEVELS or not reason_codes:
        raise ValueError("assessed() needs a level and at least one reason code")
    return {
        "outcome": "assessed",
        "level": level,
        "minimum_level": level,
        "reason_codes": sorted(set(reason_codes)),
        "error_code": None,
    }


def rejected(error_code: str | None = None) -> dict[str, Any]:
    """error_code=None when the Current spec requires rejection without naming the code."""
    return {"outcome": "rejected", "level": None, "minimum_level": None, "reason_codes": None, "error_code": error_code}


def candidate(
    number: int,
    category: str,
    variant: str,
    title_ja: str,
    *,
    expected: dict[str, Any],
    basis: tuple[str, ...],
    rationale_ja: str,
    threats: tuple[str, ...] = (),
    release_class: str = "standard",
) -> Callable[[Callable[[], Json | bytes]], Callable[[], Json | bytes]]:
    case_id = f"RG-EVAL-{number:03d}"

    def register(build: Callable[[], Json | bytes]) -> Callable[[], Json | bytes]:
        if case_id in REGISTRY:
            raise ValueError(f"duplicate candidate {case_id}")
        REGISTRY[case_id] = Candidate(
            case_id=case_id,
            category=category,
            variant=variant,
            title_ja=title_ja,
            threats=threats,
            release_class=release_class,
            expected=expected,
            basis=basis,
            rationale_ja=rationale_ja,
            build=build,
        )
        return build

    return register


def cid(number: int) -> str:
    return f"RG-EVAL-{number:03d}"


def setv(claim: Json, **fields: object) -> Json:
    claim = copy.deepcopy(claim)
    claim.update(fields)
    return claim


def replaced(claim: Json, *, keep_evidence: bool = False, **fields: object) -> Json:
    """User replacement for modify: same id, only the changed fields, no fabricated Evidence."""
    value = setv(claim, **fields)
    if not keep_evidence:
        value["evidence_ids"] = []
    return value
