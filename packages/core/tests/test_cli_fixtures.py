"""Committed offline fixture files stay in sync with the builder and run through the CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sg001_cases import CASES

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "fixtures" / "sg001"
sys.path.insert(0, str(ROOT / "scripts"))

import build_sg001_fixtures  # noqa: E402


def _cli(path: Path) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "packages" / "core"), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-m", "relayguard", str(path)], capture_output=True, env=env, timeout=60, check=False)


@pytest.mark.parametrize("name", sorted(CASES))
def test_fixture_file_is_up_to_date(name: str) -> None:
    path = FIXTURE_DIR / f"{name}.input.json"
    assert path.read_bytes() == build_sg001_fixtures.fixture_bytes(name), "run scripts/build_sg001_fixtures.py"


def test_expected_file_is_up_to_date_and_separate() -> None:
    assert (FIXTURE_DIR / "expected.json").read_bytes() == build_sg001_fixtures.expected_bytes()
    for name in CASES:
        assert b"expected" not in (FIXTURE_DIR / f"{name}.input.json").read_bytes()


@pytest.mark.parametrize("name", sorted(CASES))
def test_cli_assesses_fixture(name: str) -> None:
    expected = json.loads((FIXTURE_DIR / "expected.json").read_text(encoding="utf-8"))[name]
    completed = _cli(FIXTURE_DIR / f"{name}.input.json")
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.decode("utf-8"))
    assert result["status"] == "assessed"
    assert result["assessment"]["level"] == expected["level"]
    assert result["assessment"]["reason_codes"] == expected["reason_codes"]
    assert result["external_action_performed"] is False


def test_cli_rejects_invalid_input(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_bytes(b'{"schema_version":"0.3","case_id":"x","case_id":"y"}')
    completed = _cli(bad)
    assert completed.returncode == 1
    result = json.loads(completed.stdout.decode("utf-8"))
    assert result["status"] == "rejected"
    assert result["failure"]["code"] == "SchemaInvalid"


def test_cli_usage_errors(tmp_path: Path) -> None:
    assert _cli(tmp_path / "missing.json").returncode == 2
