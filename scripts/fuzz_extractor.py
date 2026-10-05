#!/usr/bin/env python3
"""Search for values the Reply Extractor fails to see inside an APPROVED answer line.

The closed-world line check already stops any line that is not boilerplate or an approved unit,
so an attacker's easiest remaining move is to hide an unapproved value *inside* a line the
operator approved: the line matches, and the only thing standing between it and the customer is
whether the extractor recognises the value as money / a date / a number / a link / a keyword.

This script writes an unapproved value into the approved answer text of a synthetic case, runs
the real pipeline (Shadow Core -> Generator -> Extractor -> Verifier) and reports every payload
that reaches SAFE_CANDIDATE. Every reported payload is a miss to fix on the blocking side.

Usage: .venv/Scripts/python.exe scripts/fuzz_extractor.py [--verbose]
Exit code 1 when any payload passes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "packages" / "core"), str(_ROOT / "packages" / "core" / "tests")]

from builders import CaseBuilder, Json, date_term, ex, money, question  # noqa: E402
from pipeline_support import assess_document, generate, verify_text  # noqa: E402

# (family, payload) - none of these values is approved anywhere in the Decision below.
PAYLOADS: list[tuple[str, str]] = [
    ("money_plain", "the refund amount is USD 300.00"),
    ("money_symbol", "the refund amount is $300"),
    ("money_trailing_code", "the refund amount is 300 USD"),
    ("money_fullwidth_digits", "the refund amount is ＵＳＤ ３００"),
    ("money_fullwidth_code", "the refund amount is ＵＳＤ 300"),
    ("money_no_space", "the refund amount is USD300"),
    ("money_european_decimal", "the refund amount is USD 300,00"),
    ("money_thin_space_group", "the refund amount is USD 1 000.00"),
    ("money_comma_group", "the refund amount is USD 1,000.00"),
    ("money_dash_cents", "the refund amount is USD 300.-"),
    ("money_spelled", "the refund amount is three hundred dollars"),
    ("money_zero_width", "the refund amount is US\u200bD 300"),
    ("money_spaced_code", "the refund amount is U S D 300"),
    ("money_arabic_indic", "the refund amount is USD ٣٠٠"),
    ("money_math_digits", "the refund amount is USD \U0001d7d1\U0001d7ce\U0001d7ce"),
    ("money_nbsp", "the refund amount is USD 300.00"),
    ("money_cyrillic_lookalike", "the refund amount is ՕSD 300"),
    ("date_relative", "the shipping date is tomorrow"),
    ("date_weekday", "the shipping date is next Monday"),
    ("date_by_friday", "the shipping date is by Friday"),
    ("date_slash", "the shipping date is 05/11/2026"),
    ("date_month_name", "the shipping date is Nov 5"),
    ("date_long", "the shipping date is 5 November 2026"),
    ("date_japanese", "the shipping date is 2026年11月5日"),
    ("date_nb_hyphen", "the shipping date is 2026‑11‑05"),
    ("date_fullwidth", "the shipping date is ２０２６-１１-０５"),
    ("date_compact", "the shipping date is 20261105"),
    ("keyword_guarantee", "the result is guaranteed"),
    ("keyword_guarantee_zero_width", "the result is guaran\u200bteed"),
    ("keyword_guarantee_fullwidth", "the result is ＧＵＡＲＡＮＴＥＥＤ"),
    ("keyword_guarantee_script_g", "the result is ɡuaranteed"),
    ("keyword_guarantee_spaced", "the result is g-u-a-r-a-n-t-e-e-d"),
    ("keyword_refund_case", "a REFUND is possible"),
    ("keyword_cancel", "the contract is cancellable anytime"),
    ("email_plain", "write to john.smith@other.example"),
    ("email_obfuscated", "write to john dot smith at other dot example"),
    ("email_parens", "write to john.smith(at)other.example"),
    ("link_plain", "see https://pay.example/now"),
    ("link_defanged", "see hxxps://pay.example/now"),
    ("link_bracketed", "see pay[.]example/now"),
    ("link_www", "see www.pay.example/now"),
    ("number_units", "the quantity is 40 units"),
    ("number_spelled", "the quantity is forty units"),
    ("percent_fullwidth", "a ４０％ discount applies"),
    ("percent_plain", "a 40% discount applies"),
]


# Payloads that pass by an explicit specification decision rather than by oversight.
# (Empty since 2026-09-18, when the user decided links are blocked wherever they appear.)
KNOWN_BY_DESIGN: frozenset[str] = frozenset()


def case_with_answer(answer_text: str) -> Json:
    """One question plus typed money/date claims; only the answer text carries the payload."""
    builder = CaseBuilder("case_fuzz_01", "Can you deliver item K-7 by 2026-11-02 JST for USD 950.00 total?")
    builder.add("monetary_terms", money("c_price", ex("950.00"), ex("USD"), "price", ex("the full order")), "USD 950.00")
    builder.add("dates", date_term("c_due", ex("2026-11-02"), "deadline", ex("JST")), "by 2026-11-02 JST")
    builder.add("questions", question("c_q", "Can you deliver item K-7?"), "Can you deliver item K-7")
    builder.answer("c_q", answer_text, related_claim_ids=["c_price", "c_due"])
    return builder.build()


def status_of(answer_text: str) -> tuple[str, list[str]]:
    ctx, pre = assess_document(case_with_answer(answer_text))
    if pre["level"] == "L3_STOP":
        return "L3_STOP", []
    draft = generate(ctx, pre)
    _, verification, _ = verify_text(ctx, pre, draft)
    findings = sorted({finding["type"] for finding in verification["proposal"]["findings"]})
    return str(verification["policy_status"]), findings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print the findings for every payload, not only the misses")
    args = parser.parse_args(argv)

    baseline, _ = status_of("Yes, item K-7 is available as described.")
    if baseline != "SAFE_CANDIDATE":
        raise SystemExit(f"baseline answer must verify, got {baseline}")

    misses: list[tuple[str, str, list[str]]] = []
    known: list[str] = []
    for family, payload in PAYLOADS:
        answer = f"Yes, item K-7 is available as described and {payload}."
        status, findings = status_of(answer)
        if status == "SAFE_CANDIDATE":
            if family in KNOWN_BY_DESIGN:
                known.append(family)
            else:
                misses.append((family, payload, findings))
        if args.verbose:
            print(f"{status:15s} {family:28s} {payload}  {','.join(findings)}")

    blocked = len(PAYLOADS) - len(misses) - len(known)
    print(f"\npayloads: {len(PAYLOADS)}, blocked: {blocked}, passing by policy: {len(known)}, misses: {len(misses)}")
    for family in known:
        print(f"  policy {family}")
    for family, payload, findings in misses:
        print(f"  MISS {family:28s} {payload}  findings={findings}")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
