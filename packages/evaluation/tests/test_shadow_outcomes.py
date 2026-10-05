"""ShadowOutcome contract, append-only store and KPIs (SCHEMA.md §8, EVALUATION.md §13).
All outcome data here is synthetic test data, never an observation."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from eval_support import CANDIDATES, ROOT, SG001, assessed_result, observation

from relayguard_eval.cases import load_fixture_suite
from relayguard_eval.report import build_report
from relayguard_eval.runner import run_suite
from relayguard_eval.shadow import (
    ShadowRecordError,
    ShadowStore,
    build_shadow_outcome,
    shadow_kpis,
    shadow_outcome_problems,
    store_kpis,
)

L0_INPUT = CANDIDATES / "inputs" / "RG-EVAL-001.input.json"
L1_INPUT = CANDIDATES / "inputs" / "RG-EVAL-004.input.json"
L2_INPUT = CANDIDATES / "inputs" / "RG-EVAL-011.input.json"
L3_INPUT = CANDIDATES / "inputs" / "RG-EVAL-066.input.json"


def _outcome(input_path: Path, seed: str = "t", **overrides: Any) -> dict[str, Any]:
    outcome, _ = build_shadow_outcome(assessed_result(input_path, seed), observation(**overrides))
    return outcome


def test_prediction_is_copied_from_the_assessment_not_supplied() -> None:
    result = assessed_result(L2_INPUT)
    outcome, binding = build_shadow_outcome(result, observation())
    assert outcome["predicted_delegation_level"] == "L2_PRE_APPROVAL"
    assert outcome["assessment_id"] == result["assessment"]["assessment_id"]
    assert binding["decision_hash"] == result["assessment"]["binding"]["decision_hash"]
    assert binding["input_hash"] == result["input_hash"]

    with pytest.raises(ShadowRecordError, match="outside ShadowOutcome"):
        build_shadow_outcome(result, observation(predicted_delegation_level="L0_AUTO"))


def test_rejected_or_tampered_results_cannot_be_recorded() -> None:
    rejected = {"status": "rejected", "schema_version": "0.5", "failure": {}, "external_action_performed": False}
    with pytest.raises(ShadowRecordError, match="assessed"):
        build_shadow_outcome(rejected, observation())
    tampered = assessed_result(L2_INPUT)
    tampered["assessment"]["level"] = "L0_AUTO"  # below minimum, audit no longer binds it
    with pytest.raises(ShadowRecordError, match="invariants"):
        build_shadow_outcome(tampered, observation())


@pytest.mark.parametrize("missing", ["actual_human_intervention", "final_outcome", "would_have_been_safe_to_automate", "cost_currency"])
def test_observation_fields_are_never_defaulted(missing: str) -> None:
    partial = observation()
    del partial[missing]
    with pytest.raises(ShadowRecordError, match="explicit"):
        build_shadow_outcome(assessed_result(L2_INPUT), partial)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"would_have_been_safe_to_automate": True, "adjudicator_id": "qa_1"}, "unknown requires"),
        ({"final_outcome": "safe"}, "adjudicator_id"),
        ({"final_outcome": "critical_incident", "would_have_been_safe_to_automate": False}, "adjudicator_id"),
        ({"verification_cost": "1.20"}, "both null or both present"),
        ({"cost_currency": "USD"}, "both null or both present"),
        ({"verification_cost": "-1.00", "cost_currency": "USD"}, "negative"),
        ({"verification_cost": "1.20", "cost_currency": "XYZ"}, "schema"),
        ({"verification_cost": 1.2, "cost_currency": "USD"}, "schema"),
        ({"human_seconds": -5}, "schema"),
        ({"human_seconds": "30"}, "schema"),
        ({"actual_human_intervention": None}, "schema"),
        ({"evaluation_kind": "synthetic"}, "schema"),
    ],
)
def test_outcome_contract_violations(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ShadowRecordError, match=message):
        build_shadow_outcome(assessed_result(L2_INPUT), observation(**overrides))


def test_valid_settled_outcome() -> None:
    outcome = _outcome(
        L0_INPUT,
        final_outcome="safe",
        would_have_been_safe_to_automate=True,
        adjudicator_id="qa_reviewer_1",
        human_seconds=90,
        verification_cost="0.0300",
        cost_currency="USD",
    )
    assert shadow_outcome_problems(outcome) == []


def _store(tmp_path: Path) -> ShadowStore:
    return ShadowStore(tmp_path / "shadow.jsonl")


def _append(store: ShadowStore, input_path: Path, seed: str, when: datetime, **overrides: Any) -> dict[str, Any]:
    outcome, binding = build_shadow_outcome(assessed_result(input_path, seed), observation(**overrides))
    return store.append(outcome, binding, recorded_at=when)


def test_store_is_an_append_only_chain_with_revisions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    t1 = datetime(2026, 9, 1, tzinfo=UTC)
    _append(store, L2_INPUT, "x", t1)
    # Later adjudication of the same assessment is a revision.
    _append(
        store,
        L2_INPUT,
        "x",
        datetime(2026, 9, 20, tzinfo=UTC),
        final_outcome="safe",
        would_have_been_safe_to_automate=False,
        adjudicator_id="qa_1",
    )
    state = store.read()
    assert [e["sequence"] for e in state.entries] == [1, 2]
    assert len(state.latest()) == 1
    assert state.latest()[0]["outcome"]["final_outcome"] == "safe"
    assert state.first_recorded_at()[state.latest()[0]["outcome"]["assessment_id"]] == "2026-09-01T00:00:00.000Z"
    assert "Please refund" not in store.path.read_text(encoding="utf-8")


def test_revision_cannot_change_prediction_kind_or_binding(tmp_path: Path) -> None:
    store = _store(tmp_path)
    entry = _append(store, L2_INPUT, "x", datetime(2026, 9, 1, tzinfo=UTC))
    outcome = copy.deepcopy(entry["outcome"])
    outcome["evaluation_kind"] = "fixture"
    with pytest.raises(ShadowRecordError, match="evaluation_kind"):
        store.append(outcome, entry["binding"])
    outcome = copy.deepcopy(entry["outcome"])
    outcome["predicted_delegation_level"] = "L3_STOP"
    with pytest.raises(ShadowRecordError, match="predicted_delegation_level"):
        store.append(outcome, entry["binding"])
    binding = dict(entry["binding"], decision_hash="0" * 64)
    with pytest.raises(ShadowRecordError, match="binding"):
        store.append(copy.deepcopy(entry["outcome"]), binding)
    with pytest.raises(ShadowRecordError, match="belong"):
        store.append(copy.deepcopy(entry["outcome"]), dict(entry["binding"], assessment_id="other"))
    assert len(store.read().entries) == 1


@pytest.mark.parametrize("mutation", ["edit", "delete_first", "reorder"])
def test_broken_chain_fails_closed(tmp_path: Path, mutation: str) -> None:
    store = _store(tmp_path)
    _append(store, L2_INPUT, "a", datetime(2026, 9, 1, tzinfo=UTC))
    _append(store, L3_INPUT, "b", datetime(2026, 9, 2, tzinfo=UTC))
    lines = store.path.read_bytes().splitlines()
    if mutation == "edit":
        entry = json.loads(lines[0])
        entry["outcome"]["actual_human_intervention"] = False
        lines[0] = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    elif mutation == "delete_first":
        lines = lines[1:]
    else:
        lines = [lines[1], lines[0]]
    store.path.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(ShadowRecordError):
        store.read()


def test_fixture_and_observed_are_never_mixed() -> None:
    fixture = _outcome(L0_INPUT, "f", evaluation_kind="fixture")
    observed = _outcome(L2_INPUT, "o")
    with pytest.raises(ShadowRecordError, match="must not be aggregated"):
        shadow_kpis([fixture, observed], "observed")


def test_kpis_follow_section_13_definitions() -> None:
    outcomes = [
        # L0, adjudicated safe: full skip and pre-approval skip.
        _outcome(
            L0_INPUT,
            "1",
            actual_human_intervention=False,
            final_outcome="safe",
            would_have_been_safe_to_automate=True,
            adjudicator_id="qa",
            human_seconds=0,
        ),
        # L1, safe: post review counts as intervention; only pre-approval skip.
        _outcome(
            L1_INPUT,
            "2",
            final_outcome="safe",
            would_have_been_safe_to_automate=True,
            adjudicator_id="qa",
            human_seconds=120,
            verification_cost="0.10",
            cost_currency="USD",
        ),
        # L2, critical incident: never safe delegation.
        _outcome(
            L2_INPUT,
            "3",
            final_outcome="critical_incident",
            would_have_been_safe_to_automate=False,
            adjudicator_id="qa",
            verification_cost="15",
            cost_currency="JPY",
        ),
        # L3, unknown outcome: not counted as incident-free.
        _outcome(L3_INPUT, "4"),
    ]
    kpis = shadow_kpis(outcomes, "observed")
    assert kpis["n"] == 4
    assert kpis["human_review_rate"]["value"] == "0.7500"
    assert kpis["escalation_rate"]["value"] == "0.5000"
    assert kpis["critical_incident_rate"]["value"] == "0.2500"
    assert kpis["critical_incident_rate"]["unknown_outcome_count"] == 1
    assert kpis["critical_incidents_predicted_l0_l1"] == 0
    assert kpis["safe_delegation_rate"]["numerator"] == 1
    assert kpis["pre_approval_skippable_rate"]["numerator"] == 2
    assert kpis["safety_judgment"] == {"adjudicated": 3, "not_adjudicated": 1}
    costs = kpis["verification_cost_per_case"]
    assert set(costs["by_currency"]) == {"JPY", "USD"}, "currencies are never mixed"
    assert costs["missing"] == {"numerator": 2, "denominator": 4, "value": "0.5000"}
    assert kpis["human_minutes_per_case"] == {
        "value": "1.00",
        "measured_cases": 2,
        "missing": {"numerator": 2, "denominator": 4, "value": "0.5000"},
    }
    assert kpis["false_automation_rate"]["value"] == "N/A"
    assert "反実仮想" in kpis["counterfactual_notice_ja"]


def test_empty_population_is_na_everywhere() -> None:
    kpis = shadow_kpis([], "observed")
    assert kpis["n"] == 0
    for name in ("human_review_rate", "escalation_rate", "critical_incident_rate", "safe_delegation_rate"):
        assert kpis[name]["value"] == "N/A", name
    assert kpis["human_minutes_per_case"]["value"] == "N/A"


def test_store_kpis_use_latest_revision_and_period(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _append(store, L2_INPUT, "a", datetime(2026, 9, 1, tzinfo=UTC))
    _append(store, L3_INPUT, "b", datetime(2026, 10, 5, tzinfo=UTC))
    _append(store, L2_INPUT, "a", datetime(2026, 10, 9, tzinfo=UTC), final_outcome="noncritical_incident", adjudicator_id="qa")
    _append(store, L0_INPUT, "c", datetime(2026, 9, 3, tzinfo=UTC), evaluation_kind="fixture")
    state = store.read()
    september = store_kpis(state, "observed", "2026-09-01T00:00:00.000Z", "2026-10-01T00:00:00.000Z")
    assert september["n"] == 1
    assert september["final_outcome_counts"]["noncritical_incident"] == 1  # latest revision, first-recorded period
    assert store_kpis(state, "observed")["n"] == 2
    assert store_kpis(state, "fixture")["n"] == 1


def test_evaluation_run_shadow_metrics_are_not_run_without_observations() -> None:
    report = build_report(run_suite(load_fixture_suite(CANDIDATES)))
    assert report["shadow_outcomes"]["status"] == "NOT_RUN"


def test_evaluation_run_accepts_only_fixture_observations() -> None:
    run = run_suite(load_fixture_suite(CANDIDATES))
    fixture_obs = {"RG-EVAL-001": observation(evaluation_kind="fixture"), "RG-EVAL-096": observation(evaluation_kind="fixture")}
    report = build_report(run, fixture_obs)
    shadow = report["shadow_outcomes"]
    assert shadow["status"] == "COUNTED" and shadow["n"] == 1
    assert shadow["observations_for_rejected_cases"] == ["RG-EVAL-096"]
    assert len(shadow["cases_without_observation"]) == 98
    with pytest.raises(ShadowRecordError, match="fixture"):
        build_report(run, {"RG-EVAL-001": observation()})
    with pytest.raises(ShadowRecordError, match="outside this run"):
        build_report(run, {"RG-EVAL-999": observation(evaluation_kind="fixture")})


def _cli(*args: str) -> subprocess.CompletedProcess[bytes]:
    env = dict(
        os.environ,
        PYTHONPATH=os.pathsep.join([str(ROOT / "packages" / "core"), str(ROOT / "packages" / "evaluation")]),
        PYTHONIOENCODING="utf-8",
    )
    return subprocess.run([sys.executable, "-m", "relayguard_eval", *args], capture_output=True, env=env, timeout=120, check=False)


def test_cli_shadow_record_and_kpi(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    core = subprocess.run(
        [sys.executable, "-m", "relayguard", str(SG001 / "l2_refund_commitment_stated.input.json")],
        capture_output=True,
        env=dict(os.environ, PYTHONPATH=str(ROOT / "packages" / "core"), PYTHONIOENCODING="utf-8"),
        timeout=60,
        check=False,
    )
    assert core.returncode == 0
    result_path.write_bytes(core.stdout)
    obs_path = tmp_path / "obs.json"
    obs_path.write_text(json.dumps(observation()), encoding="utf-8")
    store = tmp_path / "store.jsonl"
    recorded = _cli("shadow-record", "--result", str(result_path), "--observation", str(obs_path), "--store", str(store))
    assert recorded.returncode == 0, recorded.stderr
    kpi = _cli("shadow-kpi", "--store", str(store), "--kind", "observed")
    assert kpi.returncode == 0, kpi.stderr
    assert json.loads(kpi.stdout)["n"] == 1

    bad_obs = tmp_path / "bad.json"
    bad_obs.write_text(json.dumps(observation(final_outcome="safe")), encoding="utf-8")
    assert _cli("shadow-record", "--result", str(result_path), "--observation", str(bad_obs), "--store", str(store)).returncode == 3
    store.write_bytes(store.read_bytes().replace(b"L2_PRE_APPROVAL", b"L0_AUTO"))
    assert _cli("shadow-kpi", "--store", str(store), "--kind", "observed").returncode == 3
