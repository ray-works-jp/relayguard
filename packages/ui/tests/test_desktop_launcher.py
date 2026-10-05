"""Double-click launcher helpers (scripts/relayguard_desktop.py): safe defaults, no surprises."""

from __future__ import annotations

import socket
from pathlib import Path

import relayguard_desktop as desktop

ROOT = Path(__file__).resolve().parents[3]


def test_operator_id_is_sanitized_to_the_cli_pattern() -> None:
    assert desktop.operator_id("山田 太郎") == "operator"
    assert desktop.operator_id("taro.yamada") == "taro_yamada"
    assert desktop.operator_id(None) == "operator"
    assert len(desktop.operator_id("x" * 200)) == 64


def test_build_argv_fills_defaults_but_never_overrides_the_user() -> None:
    argv = desktop.build_argv([], ROOT, user="hp", port=8800, token="t" * 32)
    assert argv == [
        "--operator",
        "hp",
        "--samples",
        str(ROOT / "eval" / "release-set-candidates" / "inputs"),
        "--port",
        "8800",
        "--token",
        "t" * 32,
    ]
    assert "--enable-llm-interpreter" not in argv

    custom = desktop.build_argv(["--operator", "boss", "--enable-llm-interpreter"], ROOT, user="hp", port=8800, token="t" * 32)
    assert custom[:3] == ["--operator", "boss", "--enable-llm-interpreter"]
    assert custom.count("--operator") == 1


def test_free_port_skips_a_port_in_use() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        assert desktop.free_port(taken, 5) != taken


def test_source_checkout_resolves_bundled_samples() -> None:
    assert desktop.bundle_root() == ROOT
    assert (desktop.samples_dir(ROOT) / "RG-EVAL-011.input.json").is_file()
