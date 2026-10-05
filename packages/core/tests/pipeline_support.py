"""Shared helpers for post-SHADOW_GATE pipeline tests (Generator -> Extractor -> Verifier -> Final Approval).

Synthetic offline fixtures only. Pre-generation assessment always comes from the real
Shadow Core so the downstream stages are exercised against production Domain output.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from builders import Json, to_bytes
from helpers import fixed_runtime

from relayguard.final_approval import ApprovalRuntime
from relayguard.generator import GeneratorRuntime, compute_draft_hash, draft_binding, generate_draft
from relayguard.integrity import DomainContext, validate_domain
from relayguard.reply_extractor import ReplyExtractorRuntime, extract_reply
from relayguard.shadow_core import run_shadow_core
from relayguard.strict_json import parse_strict_json
from relayguard.verifier import VerifierRuntime, verify_draft

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_FILES: list[Path] = sorted((ROOT / "eval" / "release-set-candidates" / "inputs").glob("*.input.json")) + sorted(
    (ROOT / "fixtures" / "sg001").glob("*.input.json")
)


def ids(seed: str) -> Any:
    counter = itertools.count(1)
    return lambda prefix: f"{prefix}_{seed}{next(counter)}"


def runtimes(seed: str = "t") -> tuple[GeneratorRuntime, ReplyExtractorRuntime, VerifierRuntime, ApprovalRuntime]:
    new_id = ids(seed)
    moment = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)
    return (
        GeneratorRuntime(new_id=new_id),
        ReplyExtractorRuntime(new_id=new_id),
        VerifierRuntime(new_id=new_id),
        ApprovalRuntime(clock=lambda: moment, new_id=new_id),
    )


def assess(raw: bytes) -> tuple[DomainContext, Json]:
    result = run_shadow_core(raw, fixed_runtime())
    assert result["status"] == "assessed", result.get("failure")
    return validate_domain(parse_strict_json(raw)), result["assessment"]


def assess_document(document: Json) -> tuple[DomainContext, Json]:
    return assess(to_bytes(document))


def generate(ctx: DomainContext, pre: Json, seed: str = "t") -> Json:
    return generate_draft(ctx, pre, runtime=runtimes(seed)[0])


def verify_text(ctx: DomainContext, pre: Json, draft: Json, seed: str = "v") -> tuple[Json, Json, Json]:
    """Extract + verify a draft. Returns (extraction, verification, post_assessment)."""
    _, extractor_rt, verifier_rt, _ = runtimes(seed)
    extraction = extract_reply(draft["reply_text"], draft_binding(draft), runtime=extractor_rt)
    verification, post = verify_draft(ctx, pre, draft, extraction, runtime=verifier_rt)
    return extraction, verification, post


def finding_types(verification: Json) -> set[str]:
    return {finding["type"] for finding in verification["proposal"]["findings"]}


def extraction_for(text: str, draft_id: str = "draft_x") -> Json:
    binding = {
        "decision": {
            "case_id": "case_x",
            "source_hash": "0" * 64,
            "interpretation_id": "int_x",
            "interpretation_version": 1,
            "decision_id": "dec_x",
            "decision_version": 1,
            "decision_hash": "1" * 64,
            "policy_version": "delegation-0.4",
        },
        "draft_id": draft_id,
        "draft_hash": compute_draft_hash(text),
    }
    return extract_reply(text, binding, runtime=ReplyExtractorRuntime(new_id=ids("x")))
