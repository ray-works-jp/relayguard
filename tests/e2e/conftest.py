"""Shared fixtures and opaque-box harnesses for RelayGuard E2E tests."""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from builders import CaseBuilder, Json, text_claim
from relayguard.canonical import canonical_bytes
from relayguard.shadow_core import ShadowCoreRuntime, run_shadow_core

DEFAULT_TEST_MOMENT = datetime(2026, 9, 15, 9, 30, tzinfo=UTC)


def deterministic_runtime(seed: str = "e2e", moment: datetime | None = None) -> ShadowCoreRuntime:
    """Create a fixed, deterministic runtime for reproducible hash chains."""
    counter = itertools.count(1)
    when = moment or DEFAULT_TEST_MOMENT
    return ShadowCoreRuntime(
        clock=lambda: when,
        new_id=lambda prefix: f"{prefix}_{seed}_{next(counter):04d}",
        invocation="fixture",
    )


def invoke_cli(input_path: Path | str, *extra_args: str) -> tuple[int, str, str]:
    """Execute the RelayGuard CLI entrypoint as an opaque black-box subprocess.

    Returns (exit_code, stdout, stderr).
    """
    cmd = [sys.executable, "-m", "relayguard", str(input_path), *extra_args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_opaque(document: Any, runtime: ShadowCoreRuntime | None = None) -> Json:
    """Execute the opaque core engine via canonical bytes."""
    if isinstance(document, bytes):
        raw = document
    elif isinstance(document, str):
        raw = document.encode("utf-8")
    else:
        raw = canonical_bytes(document)
    return run_shadow_core(raw, runtime or deterministic_runtime())


def create_baseline_valid_case(case_id: str = "case_e2e_nominal_01", body: str = "Order status check") -> Json:
    """Build a baseline valid nominal case using independent builder."""
    builder = CaseBuilder(case_id, body, subject="Order inquiry")
    builder.add("sender_intent", text_claim("c_intent_01", "Order status check"), body)
    doc: Json = builder.build()
    return doc


def assert_opaque_assessed(result: Json) -> Json:
    """Assert opaque assessment response invariant."""
    assert result["status"] == "assessed", f"Expected assessed, got: {result.get('failure')}"
    assert "assessment" in result
    assert result["external_action_performed"] is False
    assert isinstance(result["audit"], list)
    assessment: Json = result["assessment"]
    return assessment


def assert_opaque_rejected(result: Json, expected_code: str | None = None) -> Json:
    """Assert opaque fail-closed rejection response invariant."""
    assert result["status"] == "rejected", f"Expected rejected, got: {result}"
    assert "assessment" not in result
    assert result["external_action_performed"] is False
    failure: Json = result["failure"]
    assert failure["retryable"] is False
    if expected_code is not None:
        assert failure["code"] == expected_code, f"Expected code {expected_code}, got {failure['code']}"
    return failure


@pytest.fixture
def sample_valid_fixture(tmp_path: Path) -> Path:
    """Provide a serialized valid fixture file for CLI black-box execution."""
    doc = create_baseline_valid_case("case_cli_fixture_01", "Hello, please confirm order #12345.")
    target = tmp_path / "valid_fixture.json"
    target.write_bytes(canonical_bytes(doc))
    return target


@pytest.fixture
def deterministic_env() -> Iterator[ShadowCoreRuntime]:
    """Provide a deterministic runtime instance."""
    yield deterministic_runtime()
