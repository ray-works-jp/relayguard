"""Pre-flight self check: find setup problems before the operator hits them mid-task.

Every failure this catches was hit for real during the first trial run (key not set, a key set in
another window, a request cut off while the model was still thinking). A lone operator has nobody
to ask, so each check answers two questions in Japanese: what is wrong, and what to do about it.

The live checks talk to the Anthropic API (a model list, then one 16-token streamed message). They
cost a fraction of a cent, they never send mail content, and they are skipped without a key.
"""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .interpreter import MODEL, ClaudeClient, default_client, provider_message

CHECK_PROMPT = "Reply with the single word: ok"
DEFAULT_PORT = 8765
SLOW_CALL_S = 20.0


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    skipped: bool = False

    @property
    def mark(self) -> str:
        return "SKIP" if self.skipped else ("OK" if self.ok else "NG")


def _files_check(root: Path) -> CheckResult:
    required = [
        root / "packages" / "schemas" / "v0_5" / "shadow_core_input.schema.json",
        root / "packages" / "core" / "reference" / "iso4217" / "manifest.json",
        root / "packages" / "ui" / "relayguard_ui" / "templates" / "case.html",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        return CheckResult(
            "必要なファイル",
            False,
            f"見つからないファイル: {', '.join(missing)}",
            "配布物が壊れています。zipを展開し直してください（フォルダごとコピーする必要があります）。",
        )
    return CheckResult("必要なファイル", True, "すべて揃っています。")


def _samples_check(samples_dir: Path | None) -> CheckResult:
    count = len(list(samples_dir.glob("*.input.json"))) if samples_dir and samples_dir.is_dir() else 0
    if count == 0:
        return CheckResult(
            "サンプル", False, "合成サンプルが見つかりません。", "実メールでは使えますが、練習用のサンプルは表示されません。", skipped=False
        )
    return CheckResult("サンプル", True, f"{count}件のサンプルを使えます。")


def port_check(port: int) -> CheckResult:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return CheckResult(
                "ポート",
                False,
                f"ポート {port} は使用中です。",
                "別のRelayGuardが起動している可能性があります。起動中のものを閉じるか、別の --port を指定してください。",
            )
    return CheckResult("ポート", True, f"ポート {port} は空いています。")


def _env_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


# The exe reads no environment key (only --enable-llm-interpreter does), so the screen advises the
# on-screen entry only; the console check is the developer path (E2E 0.1.0 #9). setx is not advised:
# it stores the key in Windows permanently.
KEY_ADVICE_SCREEN = (
    "「＋ 新しいメールを解析」または「設定」のAPIキー欄に貼り付けて「設定する」を押してください"
    "（RelayGuard はキーをこのPCのメモリにだけ置き、終了すると消えます）。"
    "Claudeを使わない場合も「手動で登録」は使えます。"
)
KEY_ADVICE_CONSOLE = (
    '開発者向け: このウィンドウで $env:ANTHROPIC_API_KEY = "sk-ant-..." を実行し、'
    "--enable-llm-interpreter を付けて起動してください（このウィンドウを閉じると消えます）。"
    "exe を使う場合は、起動した画面の「設定」からキーを入れてください。"
)


def _key_check(key: str, *, from_screen: bool = False) -> CheckResult:
    if not key:
        return CheckResult("APIキー", False, "APIキーが設定されていません。", KEY_ADVICE_SCREEN if from_screen else KEY_ADVICE_CONSOLE)
    if not key.startswith("sk-ant-") or len(key) < 40:
        return CheckResult("APIキー", False, "APIキーの形式が想定と違います。", "Consoleで作り直したキーを設定し直してください。")
    return CheckResult("APIキー", True, f"設定されています（{len(key)}文字）。")


def _models_check(client: ClaudeClient) -> CheckResult:
    try:
        listing = client.models.list(limit=100)
        ids = [getattr(model, "id", "") for model in getattr(listing, "data", [])]
    except Exception as error:  # noqa: BLE001 - every provider failure becomes advice, not a traceback
        return CheckResult("APIへの接続", False, type(error).__name__, provider_message(error))
    if MODEL not in ids:
        return CheckResult("モデル", False, f"{MODEL} がこのアカウントで見つかりません。", "Consoleで利用できるモデルを確認してください。")
    return CheckResult("モデル", True, f"{MODEL} を利用できます。")


def _call_check(client: ClaudeClient, clock: Callable[[], float]) -> CheckResult:
    started = clock()
    try:
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=16,
            messages=[{"role": "user", "content": CHECK_PROMPT}],
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            timeout=60.0,
        ) as stream:
            stream.get_final_message()
    except Exception as error:  # noqa: BLE001
        return CheckResult("試し呼び出し", False, type(error).__name__, provider_message(error))
    elapsed = clock() - started
    if elapsed > SLOW_CALL_S:
        return CheckResult(
            "試し呼び出し",
            True,
            f"成功しましたが {elapsed:.0f} 秒かかりました。",
            "回線が遅いようです。長いメールの解釈は上限300秒を超えることがあります。超えたら本文を短く区切って試してください。",
        )
    return CheckResult("試し呼び出し", True, f"成功しました（{elapsed:.1f} 秒）。")


@dataclass(frozen=True)
class CheckSetup:
    """Where to look and what to touch - grouped so the entry point stays one argument wide."""

    root: Path
    samples_dir: Path | None = None
    port: int = DEFAULT_PORT
    live: bool = True
    client_factory: Callable[[], ClaudeClient] = default_client
    clock: Callable[[], float] = time.monotonic
    key: Callable[[], str] = _env_key
    # Run from the already-running screen: the port is in use by this very app, so its check is
    # skipped and says so instead of probing a port (E2E 0.1.0 #8). The pre-start check keeps it.
    from_screen: bool = False


def run_checks(setup: CheckSetup) -> list[CheckResult]:
    """Run every check in order, stopping the API checks as soon as one of them fails."""
    port = (
        CheckResult("ポート", True, "起動済みの画面から実行したため、ポートの空き確認は省略しました。", skipped=True)
        if setup.from_screen
        else port_check(setup.port)
    )
    results = [_files_check(setup.root), _samples_check(setup.samples_dir), port, _key_check(setup.key(), from_screen=setup.from_screen)]
    key_ok = results[-1].ok
    if not setup.live or not key_ok:
        reason = "APIキーがないため省略しました。" if not key_ok else "APIを使わない設定のため省略しました。"
        results += [CheckResult(name, True, reason, skipped=True) for name in ("APIへの接続", "モデル", "試し呼び出し")]
        return results
    try:
        client = setup.client_factory()
    except Exception as error:  # noqa: BLE001
        detail = getattr(error, "explanation_ja", type(error).__name__)
        results.append(CheckResult("APIへの接続", False, str(detail), "APIキーの設定を確認してください。"))
        return results
    models = _models_check(client)
    results.append(models)
    if not models.ok:
        results.append(CheckResult("試し呼び出し", True, "前の項目が失敗したため省略しました。", skipped=True))
        return results
    results.append(_call_check(client, setup.clock))
    return results


def format_report(results: list[CheckResult]) -> str:
    """Plain-text report for the console (the UI renders the same results as a table)."""
    lines = ["RelayGuard 自己診断", ""]
    for result in results:
        lines.append(f"[{result.mark}] {result.name}: {result.detail}")
        if result.fix and not result.ok:
            lines.append(f"       対処: {result.fix}")
        elif result.fix:
            lines.append(f"       注意: {result.fix}")
    failed = [result for result in results if not result.ok]
    lines += ["", "すべて問題ありません。" if not failed else f"{len(failed)}件の問題が見つかりました。上の「対処」を実行してください。"]
    return "\n".join(lines)


def any_failed(results: list[CheckResult]) -> bool:
    return any(not result.ok for result in results)
