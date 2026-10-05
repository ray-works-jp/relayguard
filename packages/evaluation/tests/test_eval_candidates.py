"""The committed 100 candidate cases: in sync with authoring, complete matrix, contract-valid,
labels kept separate from ShadowCoreInput, and never self-approved."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import build_release_candidates
import pytest
from eval_support import CANDIDATES

from relayguard_eval.cases import CATEGORIES, VARIANTS, load_fixture_suite
from relayguard_eval.runner import run_suite


def test_committed_files_match_authoring_source() -> None:
    rendered = build_release_candidates.rendered()
    on_disk = {
        f"{directory}/{path.name}": path.read_bytes()
        for directory in ("inputs", "cases")
        for path in (CANDIDATES / directory).glob("*.json")
    }
    assert set(on_disk) == set(rendered), "run scripts/build_release_candidates.py"
    for name, data in rendered.items():
        assert on_disk[name] == data, f"{name} is stale; run scripts/build_release_candidates.py"


def test_suite_is_a_complete_20_by_5_matrix() -> None:
    suite = load_fixture_suite(CANDIDATES)
    matrix = suite.matrix()
    assert len(suite.cases) == 100
    assert matrix["complete"], matrix
    assert Counter(c.category for c in suite.cases) == dict.fromkeys(CATEGORIES, 5)
    assert Counter(c.variant for c in suite.cases) == dict.fromkeys(VARIANTS, 20)


def test_labels_are_builder_candidates_with_a_spec_basis() -> None:
    for path in sorted((CANDIDATES / "cases").glob("*.case.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        assert case["label"]["status"] == "builder_candidate", path.name
        assert case["origin"] == "synthetic", path.name
        assert all(any(doc in basis for doc in ("DELEGATION", "SCHEMA", "REQUIREMENTS")) for basis in case["label"]["basis"]), path.name
        # Post-verification labels are not authored before SHADOW_GATE.
        assert case["unsafe_candidate_reply"] is None and case["expected_verification"] is None, path.name


@pytest.mark.parametrize("path", sorted((CANDIDATES / "inputs").glob("*.input.json")), ids=lambda p: Path(p).name)
def test_inputs_carry_no_expected_values(path: Path) -> None:
    raw = path.read_bytes()
    assert b"expected" not in raw
    assert b"builder_candidate" not in raw
    assert b"approval_status" not in raw


def test_the_set_is_not_all_block() -> None:
    """EVALUATION.md §13: low-risk positive controls are included; not every case is a block."""
    suite = load_fixture_suite(CANDIDATES)
    levels = Counter(c.expected.level if c.expected.outcome == "assessed" else "rejected" for c in suite.cases)
    assert levels["L0_AUTO"] >= 3
    assert levels["L1_POST_REVIEW"] >= 2
    assert levels["L2_PRE_APPROVAL"] >= 20
    assert levels["rejected"] >= 5


def test_current_implementation_matches_every_candidate_label() -> None:
    """Regression gate for the Builder: a change to the policy must not silently change a
    candidate result. This is label agreement, not proof that the labels are right."""
    run = run_suite(load_fixture_suite(CANDIDATES))
    mismatched = {r.case.case_id: r.mismatches for r in run.results if r.mismatches}
    assert not mismatched
    assert all(r.deterministic for r in run.results)
    assert not any(r.pii_log_leak for r in run.results)
    assert not any(r.external_action_performed for r in run.results)
