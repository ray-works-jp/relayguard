#!/usr/bin/env python3
"""Double-click launcher for the packaged RelayGuard reviewer (also runs from a source checkout).

- No arguments needed: the operator ID comes from the Windows user name (sanitized), the port is
  the first free one from 8765, and the samples are the bundled synthetic cases.
- Opens the one-time login URL in the default browser. Server stays on 127.0.0.1; no e-mail sending.
- Extra arguments are passed through to relayguard_ui (e.g. --enable-llm-interpreter, --operator).

Packaged layout (see packaging/windows/relayguard.spec): the verified source trees are shipped as
plain files under <bundle>/packages/{core,ui,schemas} so their paths and SHA-256 match the checkout.
"""

from __future__ import annotations

import getpass
import os
import re
import secrets
import socket
import sys
import threading
import webbrowser
from pathlib import Path

DEFAULT_PORT = 8765
PORT_ATTEMPTS = 20
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def bundle_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def samples_dir(root: Path) -> Path:
    bundled = root / "samples"
    return bundled if bundled.is_dir() else root / "eval" / "release-set-candidates" / "inputs"


def operator_id(raw: str | None) -> str:
    cleaned = _UNSAFE.sub("_", raw or "").strip("_")[:64]
    return cleaned or "operator"


def free_port(start: int = DEFAULT_PORT, attempts: int = PORT_ATTEMPTS) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(f"空いているポートが見つかりません（{start}〜{start + attempts - 1}）。他のRelayGuardを閉じてから再実行してください。")


def build_argv(extra: list[str], root: Path, *, user: str | None, port: int, token: str) -> list[str]:
    argv = list(extra)
    if "--operator" not in argv:
        argv += ["--operator", operator_id(user)]
    if "--samples" not in argv:
        argv += ["--samples", str(samples_dir(root))]
    if "--port" not in argv:
        argv += ["--port", str(port)]
    if "--token" not in argv:
        argv += ["--token", token]
    return argv


def _option(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def _current_user() -> str | None:
    try:
        return getpass.getuser()
    except OSError:
        return os.environ.get("USERNAME")


def main(extra: list[str]) -> int:
    root = bundle_root()
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(root / "packages" / "core"), str(root / "packages" / "ui")]
    from relayguard_ui.__main__ import main as serve  # noqa: PLC0415 - import after sys.path setup

    port = int(extra[extra.index("--port") + 1]) if "--port" in extra else free_port()
    argv = build_argv(extra, root, user=_current_user(), port=port, token=secrets.token_urlsafe(24))
    url = f"http://127.0.0.1:{_option(argv, '--port')}/login?token={_option(argv, '--token')}"
    sys.stdout.write("RelayGuard を起動しています。ブラウザが開かない場合は下のURLを開いてください。\n")
    sys.stdout.write("この黒い画面を閉じると終了します（案件はメモリ上のみで、終了時に消えます）。\n")
    if not os.environ.get("RELAYGUARD_NO_BROWSER"):
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    return serve(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
