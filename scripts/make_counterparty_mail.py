"""Generate synthetic counterparty e-mail as .eml files, locally.

Why this exists: the operator's own inbox has produced no mail that asks for anything, so the
interpreter and the manual mark-up path have never been exercised against unscripted English.
The 100 evaluation fixtures do not fill that gap - their wording is fixed and their expected
values are pinned, so they test agreement with known answers, not robustness against prose
nobody wrote in advance.

What this is NOT:

- **Not a pilot.** Mail you commissioned is synthetic no matter how it travels. REQUIREMENTS.md
  §3 SC-01 needs 10+ real cases with a counterparty that has its own interests; this cannot
  count toward that and must never be recorded as if it did.
- **Not an accuracy measurement.** Generated mail has no ground truth, so there is nothing to
  compare a delegation level against. What it can show is whether the pipeline holds: no crash,
  no silent acceptance, and a stop where a stop is due.
- **Not evaluation data.** Output goes to trial/, never to eval/ or fixtures/. Nothing here is
  a Gold case, and this script is not part of any Gate.
- **Not a sender.** Files are written to disk. Nothing is transmitted (SHADOW_GATE.md §2 still
  prohibits external mail; that prohibition was not lifted).

Each file carries an X-RelayGuard-Synthetic header and is listed in a manifest, so a generated
mail cannot later be mistaken for something that actually arrived.

Usage:
    python scripts/make_counterparty_mail.py --count 5
    python scripts/make_counterparty_mail.py --count 3 --scenario refund --out trial/counterparty
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "packages" / "core"), str(ROOT / "packages" / "ui")]

from relayguard.errors import Rejection  # noqa: E402
from relayguard_ui.interpreter import MODEL, default_client, provider_message  # noqa: E402

DEFAULT_OUT = ROOT / "trial" / "counterparty"
MAX_TOKENS = 1200
CALL_TIMEOUT_S = 90.0

SYSTEM = """You write one short business e-mail in English, as a customer or partner writing to a small \
software vendor. Output the e-mail and nothing else.

Format, exactly:
Subject: <one line>
<blank line>
<body>

Rules:
- 6 to 16 lines of body. Write the way a busy person actually writes: no marketing voice, no
  em-dashes, no bullet symbols unless a real person would use them.
- Invent a plausible sender name and company. Never use a real company.
- The sender wants something. Make it concrete enough that a reply is genuinely required.
- Do not include any URL, link or e-mail address in the body.
- Do not explain what you are doing and do not add notes. Only the e-mail."""

SCENARIOS: dict[str, str] = {
    "refund": "Ask for a refund for something that went wrong. State an amount, sometimes with a bare $ sign, sometimes with an ISO code.",
    "deadline": "Ask to move a deadline. Sometimes give an exact date, sometimes write vaguely ('early next month', 'end of the week').",
    "quantity": "Ask to change an order quantity or seat count, and ask what it does to the price.",
    "license": "Ask a question about licensing, redistribution or use by a subsidiary. Leave at least one condition ambiguous.",
    "warranty": "Ask whether something is covered, or ask for a guarantee about uptime or support response.",
    "angry": "Be unhappy. Something failed twice. Hint at cancelling. Still ask a concrete question.",
    "legal": "Mention, mildly, that someone in legal or a lawyer is now looking at this. Do not threaten directly.",
    "attachment": "Refer to a document you say you attached or shared, and ask for confirmation of what is in it.",
    "multi": "Ask three separate things at once: one factual question, one about money, one about timing.",
    "contract": "Ask to change a term in the agreement: a prohibition, a condition, or a notice period.",
}


@dataclass(frozen=True)
class Generated:
    scenario: str
    subject: str
    body: str


def _split(text: str) -> tuple[str, str]:
    """Pull 'Subject: ...' off the front; the rest is the body."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").lstrip()
    lines = cleaned.splitlines()
    if not lines or not lines[0].lower().startswith("subject:"):
        raise Rejection("UnsupportedInput", "生成結果に Subject: 行がありません。")
    subject = lines[0].split(":", 1)[1].strip()
    body = "\n".join(lines[1:]).strip()
    if not subject or not body:
        raise Rejection("UnsupportedInput", "生成結果の件名または本文が空です。")
    return subject, body


def generate(client: Any, scenario: str) -> Generated:
    request: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "system": SYSTEM,
        "messages": [{"role": "user", "content": f"Scenario: {SCENARIOS[scenario]}"}],
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
        "timeout": CALL_TIMEOUT_S,
    }
    try:
        with client.beta.messages.stream(**request) as stream:
            response = stream.get_final_message()
    except Exception as error:  # noqa: BLE001 - provider failures become advice, not a traceback
        raise Rejection("ProviderUnavailable", provider_message(error)) from None
    parts = [block.text for block in getattr(response, "content", []) if getattr(block, "type", None) == "text"]
    subject, body = _split("".join(parts))
    return Generated(scenario, subject, body)


def to_eml(mail: Generated, index: int) -> bytes:
    message = EmailMessage()
    message["Subject"] = mail.subject
    message["From"] = f"Counterparty {index} <counterparty{index}@example.invalid>"
    message["To"] = "operator@example.invalid"
    message["Date"] = format_datetime(datetime.now().astimezone())
    message["Message-ID"] = make_msgid(domain="example.invalid")
    # So a generated mail can never be mistaken for one that actually arrived.
    message["X-RelayGuard-Synthetic"] = "true"
    message["X-RelayGuard-Scenario"] = mail.scenario
    message.set_content(mail.body + "\n")
    return message.as_bytes()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="make_counterparty_mail",
        description="Write synthetic counterparty e-mail to .eml files. Sends nothing; not a pilot; not evaluation data.",
    )
    parser.add_argument("--count", type=int, default=5, help="how many mails to generate (default 5)")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default=None, help="fix the scenario (default: pick at random)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output directory (default {DEFAULT_OUT.relative_to(ROOT)})")
    parser.add_argument("--seed", type=int, default=None, help="seed for scenario choice (the model itself is not deterministic)")
    args = parser.parse_args(argv)
    if args.count < 1 or args.count > 50:
        parser.error("--count must be between 1 and 50")
    if "eval" in args.out.parts or "fixtures" in args.out.parts:
        parser.error("生成物を eval/ や fixtures/ へ書き出さないでください（評価データと混同されます）。")

    rng = random.Random(args.seed)  # noqa: S311 - picking a scenario, not a secret
    try:
        client = default_client()
    except Rejection as rejection:
        sys.stderr.write(f"{rejection.code}: {rejection.explanation_ja}\n")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "MANIFEST.json"
    manifest: list[dict[str, str]] = []
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["mails"]

    written = 0
    for _ in range(args.count):
        scenario = args.scenario or rng.choice(sorted(SCENARIOS))
        index = len(manifest) + 1
        try:
            mail = generate(client, scenario)
        except Rejection as rejection:
            sys.stderr.write(f"[{index}] {rejection.code}: {rejection.explanation_ja}\n")
            continue
        name = f"counterparty-{index:03d}-{scenario}.eml"
        (args.out / name).write_bytes(to_eml(mail, index))
        manifest.append({"file": name, "scenario": scenario, "subject": mail.subject, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        written += 1
        sys.stdout.write(f"[{index}] {scenario:11s} {mail.subject}\n")

    manifest_path.write_text(
        json.dumps(
            {
                "synthetic": True,
                "not_a_pilot": "REQUIREMENTS.md §3 SC-01 requires real mail from a counterparty with its own interests.",
                "model": MODEL,
                "mails": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    sys.stdout.write(f"\n{written}件を {args.out} へ書き出しました（合成データ・送信は行っていません）。\n")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
