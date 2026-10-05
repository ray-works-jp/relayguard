from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

from builders import Json, to_bytes

from relayguard.shadow_core import ShadowCoreRuntime, run_shadow_core


def fixed_runtime(seed: str = "a", moment: datetime | None = None) -> ShadowCoreRuntime:
    counter = itertools.count(1)
    when = moment or datetime(2026, 9, 15, 9, 30, tzinfo=UTC)
    return ShadowCoreRuntime(clock=lambda: when, new_id=lambda prefix: f"{prefix}_{seed}{next(counter)}")


def run(document: Any, runtime: ShadowCoreRuntime | None = None) -> Json:
    raw = document if isinstance(document, bytes) else to_bytes(document)
    return run_shadow_core(raw, runtime or fixed_runtime())


def assert_rejected(result: Json, code: str | None = None) -> None:
    assert result["status"] == "rejected", result
    assert "assessment" not in result
    assert result["external_action_performed"] is False
    assert result["failure"]["retryable"] is False
    if code is not None:
        assert result["failure"]["code"] == code, result["failure"]


def assert_assessed(result: Json) -> Json:
    assert result["status"] == "assessed", result.get("failure")
    assessment: Json = result["assessment"]
    return assessment
