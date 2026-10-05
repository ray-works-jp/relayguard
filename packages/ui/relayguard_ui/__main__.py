"""Start the local reviewer: python -m relayguard_ui --operator <id> [--port 8765] [--samples DIR]

Binds to 127.0.0.1 only. Prints a one-time login URL containing a random access token.
"""

from __future__ import annotations

import argparse
import logging
import re
import secrets
import sys
from pathlib import Path

from .api_key import SessionKey, client_factory
from .app import create_app
from .interpreter import ClaudeInterpreter
from .selfcheck import CheckSetup, any_failed, format_report, port_check, run_checks
from .service import CaseService

_OPERATOR_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="relayguard_ui", description="RelayGuard local reviewer (no e-mail sending).")
    parser.add_argument("--operator", required=True, help="approver ID recorded in Decision / Final Approval (A-Z a-z 0-9 _ -)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--samples", type=Path, default=None, help="directory of *.input.json synthetic cases")
    parser.add_argument(
        "--enable-llm-interpreter",
        action="store_true",
        help="also accept ANTHROPIC_API_KEY from the environment (a key can always be entered on the screen instead)",
    )
    parser.add_argument("--token", default=None, help="fixed access token (default: random per start)")
    parser.add_argument("--self-check", action="store_true", help="check the setup (files, port, API key, a live API call) and exit")
    args = parser.parse_args(argv)
    if not _OPERATOR_RE.fullmatch(args.operator):
        parser.error("--operator must match [A-Za-z0-9_-]{1,64}")

    if args.self_check:
        setup = CheckSetup(root=Path(__file__).resolve().parents[2].parent, samples_dir=args.samples, port=args.port)
        results = run_checks(setup)
        sys.stdout.write(format_report(results) + "\n")
        return 1 if any_failed(results) else 0

    import uvicorn  # noqa: PLC0415 - server dependency is only needed when actually serving

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    token = args.token or secrets.token_urlsafe(24)
    if len(token) < 16:
        parser.error("--token must be at least 16 characters")
    port = port_check(args.port)
    if not port.ok:
        # uvicorn would print an English socket error after the login URL was already shown. A fixed
        # --port is never auto-moved here, so do not reuse the exe's "auto-select" hint (ruling P-6).
        sys.stderr.write(
            f"error: {port.detail} 指定したポートは使用中で、起動していません。"
            "使用中のRelayGuardを閉じるか、別の --port を指定して起動してください。\n"
        )
        return 2
    # Claude stays off until a key is entered on the screen; the environment key counts only with the
    # flag, so a variable left over from another tool does not switch it on (B9 as revised 2026-09-23).
    key = SessionKey(env_allowed=args.enable_llm_interpreter)
    interpreter = ClaudeInterpreter(client_factory(key))
    app = create_app(CaseService(args.operator), access_token=token, samples_dir=args.samples, interpreter=interpreter, api_key=key)
    sys.stdout.write(
        f"\nRelayGuard Reviewer: http://127.0.0.1:{args.port}/login?token={token}\n(ローカル専用・メール送信機能はありません)\n\n"
    )
    sys.stdout.flush()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
