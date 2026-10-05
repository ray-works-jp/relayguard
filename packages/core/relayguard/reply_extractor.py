"""Decision-blind Reply Extractor (IMPLEMENTATION.md §5.6, SCHEMA.md §6).

Input: ``final_reply_text`` and its DraftBinding only. The Approved Decision, the Generator
proposal / represented_state and any rationale are never inputs, so extraction cannot be
biased toward "what was approved".

Output: ReplyExtraction whose StructuredState lists every critical token and clause found in
the reply. Every Evidence is ``source_kind=reply`` bound to draft_id / draft_hash, and its
quote is the full line the claim came from (an exact substring of the reply).

Fail-closed extraction rules (English reply, deterministic):
- Money is explicit only as ISO code + amount (``USD 49.00`` / ``49.00 USD``). Symbols and
  currency words (``$``, ``yen``, ``円``) give currency=ambiguous: ``$`` is never read as USD.
- Dates are explicit only when year/month/day are all present and real. Partial or numeric
  slash dates are ambiguous.
- Percentages and number+unit are QuantityTerms.
- Any other digit run that is not part of a letter-prefixed identifier (``R-2001``, ``#12``)
  becomes an unresolved critical Risk. Spelled-out amounts next to money/unit words likewise.
- Keyword classes (guarantee, refund/credit, discount/waiver, cancellation, license/rights,
  prohibition, legal) and first-person commitment sentences become typed claims.
- Reply-derived commitments are never ``approved``: the extractor has no authority.
Recall over precision: an over-extracted claim blocks a draft; a missed one could pass it.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .canonical import sha256_hex
from .claims import CLAIM_ARRAYS
from .currency import SUPPORTED_CURRENCIES
from .errors import Rejection
from .schema_validation import validate_draft_binding, validate_reply_extraction

EXTRACTOR_VERSION = "rg-reply-extractor-det-1"

_NUMBER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
_NUM_END = r"(?![0-9A-Za-z])(?!\.[0-9])(?!,[0-9])"
_NUM_START = r"(?<![0-9A-Za-z.,])"

_CODE_FIRST = re.compile(rf"(?<![A-Za-z])(?P<code>[A-Z]{{3}})\s?(?P<amount>{_NUMBER}){_NUM_END}")
_CODE_LAST = re.compile(rf"{_NUM_START}(?P<amount>{_NUMBER})\s?(?P<code>[A-Z]{{3}})(?![A-Za-z])")
_SYMBOL_FIRST = re.compile(rf"(?P<symbol>US\$|A\$|C\$|HK\$|S\$|NZ\$|R\$|[$€£¥￥₩₹₽₺₫฿₱])\s?(?P<amount>{_NUMBER}){_NUM_END}")
_WORD_LAST = re.compile(
    rf"{_NUM_START}(?P<amount>{_NUMBER})\s?(?P<word>dollars?|euros?|pounds?|yen|yuan|won|rupees?|francs?|円|ドル|ユーロ)(?![A-Za-z])",
    re.IGNORECASE,
)
_PERCENT = re.compile(rf"{_NUM_START}(?P<amount>{_NUMBER})\s?(?P<unit>%|percent\b|per cent\b|パーセント)", re.IGNORECASE)
_UNIT_WORDS = (
    r"business days?|calendar days?|working days?|days?|weeks?|months?|years?|hours?|minutes?|"
    r"units?|pcs|pieces?|items?|boxes|box|cartons?|pallets?|sets?|licen[cs]es?|seats?|users?|copies|copy|kg|g|lbs?|tons?|m|cm|mm"
)
_QUANTITY = re.compile(rf"{_NUM_START}(?P<amount>{_NUMBER})\s?(?P<unit>{_UNIT_WORDS})(?![A-Za-z])", re.IGNORECASE)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO_DATE = re.compile(r"(?<![0-9])(?P<y>[0-9]{4})-(?P<m>[0-9]{1,2})-(?P<d>[0-9]{1,2})(?![0-9])")
_JA_DATE = re.compile(r"(?:(?P<y>[0-9]{4})年)?(?P<m>[0-9]{1,2})月(?P<d>[0-9]{1,2})日")
_MDY_DATE = re.compile(
    rf"\b(?P<month>{_MONTH_RE})\.?\s+(?P<d>[0-9]{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y>[0-9]{{4}}))?(?![0-9])", re.IGNORECASE
)
_DMY_DATE = re.compile(
    rf"(?<![0-9])(?P<d>[0-9]{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<month>{_MONTH_RE})\b\.?(?:,?\s+(?P<y>[0-9]{{4}}))?", re.IGNORECASE
)
_SLASH_DATE = re.compile(r"(?<![0-9/.])(?:[0-9]{1,4}/[0-9]{1,2}(?:/[0-9]{1,4})?|[0-9]{1,4}\.[0-9]{1,2}\.[0-9]{1,4})(?![0-9/]|\.[0-9])")
_TIMEZONE = re.compile(r"\(timezone:\s*(?P<tz>[^)]+)\)|\b(?P<abbr>UTC|GMT|JST|KST|CET|CEST|BST|EST|EDT|CST|CDT|MST|MDT|PST|PDT|AEST|IST)\b")
_DEADLINE_CUE = re.compile(r"\b(by|before|no later than|deadline|due|until|within)\b", re.IGNORECASE)
_RELATIVE_DATE = re.compile(
    r"\b(today|tomorrow|tonight|yesterday|next\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"this\s+(?:week|month|friday|weekend)|end of (?:the )?(?:day|week|month|quarter|year)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|asap|as soon as possible|immediately|right away|shortly)\b",
    re.IGNORECASE,
)
_NUMBER_WORDS = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|sixty|"
    r"seventy|eighty|ninety|hundred|thousand|million|billion|dozen|half|double|triple|twice)\b"
    r"(?=(?:[\s-]+\w+){0,3}?[\s-]+"
    r"(?:dollars?|euros?|pounds?|yen|percent|per cent|%|days?|weeks?|months?|years?|units?|pieces?|times|licen[cs]es?)\b)",
    re.IGNORECASE,
)
_DIGITS = re.compile(r"[0-9０-９]+")
_IDENTIFIER = re.compile(r"(?<![\w#-])[A-Za-z#][A-Za-z#_-]*[0-9][A-Za-z0-9_/-]*")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+")
# Links written so they do not look like links to a scanner but still tell a reader where to go.
_DEFANGED_URL = re.compile(
    r"h[a-z]{1,3}ps?\s*:\s*//\S+"
    r"|[A-Za-z0-9-]+\s*(?:\[\s*(?:\.|dot)\s*\]|\(\s*(?:\.|dot)\s*\))\s*[A-Za-z0-9-]+\S*"
    r"|\b[A-Za-z0-9-]{2,}\.[A-Za-z]{2,}/\S*",
    re.IGNORECASE,
)
_OBFUSCATED_EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]+\s*(?:\(at\)|\[at\]|\{at\}|\bat\b)\s*"
    r"(?:[A-Za-z0-9-]+(?:\s*(?:\(dot\)|\[dot\]|\{dot\}|\bdot\b)\s*[A-Za-z0-9-]+)+"
    r"|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)",
    re.IGNORECASE,
)
_INVISIBLE = re.compile(r"[\u00ad\u200b-\u200f\u2060\u2066-\u2069\ufeff]")
_SPACED_LETTERS = re.compile(r"(?:(?<![A-Za-z0-9])|(?<=\s))(?:[A-Za-z0-9][ .\-_]){3,}[A-Za-z0-9](?![A-Za-z0-9])")
# Lookalike letters that carry the same meaning to a reader but defeat an ASCII pattern.
_CONFUSABLES = str.maketrans(
    {
        "\u0261": "g", "\u0131": "i", "\u04cf": "l", "\u01c0": "l", "\u2113": "l",
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0445": "x", "\u0443": "y",
        "\u0410": "A", "\u0415": "E", "\u041e": "O", "\u0420": "P", "\u0421": "C", "\u0425": "X",
        "\u0405": "S", "\u0455": "s", "\u0406": "I", "\u0456": "i", "\u0408": "J", "\u0458": "j",
        "\u0555": "O", "\u0585": "o", "\u0578": "n", "\u03bf": "o", "\u039f": "O", "\u0391": "A", "\u0392": "B",
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
        "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u2009": " ",
    }
)  # fmt: skip


def deobfuscate(text: str) -> str:
    """Fold what a reader sees through: full-width forms, invisible characters, lookalike letters.

    Scanning only - every Evidence quote stays the original line, so the operator sees exactly
    what is in the reply.
    """
    return unicodedata.normalize("NFKC", _INVISIBLE.sub("", text)).translate(_CONFUSABLES)


def _despaced(text: str) -> str:
    """Join letter-by-letter spellings ("g-u-a-r-a-n-t-e-e" -> "guarantee") so they scan like the word."""
    return _SPACED_LETTERS.sub(lambda match: re.sub(r"[ .\-_]", "", match.group(0)), text)


def scan_forms(text: str) -> tuple[str, ...]:
    """The text plus the folded variants a keyword scan must also see."""
    folded = deobfuscate(text)
    return tuple(sorted({text, folded, _despaced(folded)}))


_FIRST_PERSON = re.compile(r"\b(we|i|us|our team|our company)\b|\b(we|i)'(ll|d|m|re|ve)\b", re.IGNORECASE)
_MODAL = re.compile(
    r"\b(will|shall|can|could|may|might|must|would|going to|intend to|plan to|promise|commit|undertake|agree|"
    r"ensure|arrange|offer|provide|send|ship|deliver|issue|pay|refund|replace|waive|extend|cancel)\b|'ll\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(not|cannot|can't|won't|will not|unable|never|no longer)\b", re.IGNORECASE)

KEYWORD_CLASSES: dict[str, re.Pattern[str]] = {
    "guarantees": re.compile(r"guarant|warrant|assur|ensure|promis|certain|definitely|100\s?%", re.IGNORECASE),
    "refund_terms": re.compile(
        r"refund|reimburs|compensat|money back|chargeback|store credit|\bcredit(?:s|ed)?\b|返金|補償", re.IGNORECASE
    ),
    "contract_terms": re.compile(
        r"discount|waiv|free of charge|complimentary|no charge|no cost|at no extra|price (?:change|increase|reduction)|"
        r"contract|agreement|terms and conditions|penalt|liabilit|indemn|invoice amount|割引|無償|契約",
        re.IGNORECASE,
    ),
    "cancellation_terms": re.compile(r"cancel|terminat|解約|キャンセル", re.IGNORECASE),
    "license_terms": re.compile(
        r"licen[cs]|sublicen|exclusiv|royalt|copyright|intellectual property|commercial use|ライセンス|著作権", re.IGNORECASE
    ),
    "prohibitions": re.compile(r"prohibit|forbid|not allowed|not permitted|must not|禁止", re.IGNORECASE),
}
_LEGAL = re.compile(
    r"\blaw\s?suit|\blegal action|\blitigation|\battorney|\blawyer|\bcourt\b|\bsue\b|\bsettlement|訴訟|弁護士", re.IGNORECASE
)
_INJECTION = re.compile(
    r"ignore (?:all |the )?(?:previous|prior|above) instructions|system prompt|developer message|jailbreak|"
    r"you are now|disregard (?:the )?(?:rules|policy)|<\s*/?\s*(?:script|system)\b",
    re.IGNORECASE,
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass(frozen=True)
class ReplyExtractorRuntime:
    new_id: Callable[[str], str] = field(default=_new_id)


def _explicit(value: Any, raw_text: str) -> dict[str, Any]:
    return {"status": "explicit", "value": value, "raw_text": raw_text}


def _absent(status: str, raw_text: str = "") -> dict[str, Any]:
    return {"status": status, "value": None, "raw_text": raw_text}


def normalize_decimal(text: str) -> str | None:
    """Digits with optional valid thousands separators -> SCHEMA Decimal string, else None."""
    cleaned = text.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0:
        return None
    return cleaned


def _real_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


@dataclass
class _Line:
    text: str
    covered: list[tuple[int, int]] = field(default_factory=list)

    def free(self, start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in self.covered)

    def cover(self, start: int, end: int) -> None:
        self.covered.append((start, end))


class _Builder:
    def __init__(self, reply_text: str, draft_id: str, draft_hash: str) -> None:
        self.reply_text = reply_text
        self.draft_id = draft_id
        self.draft_hash = draft_hash
        self.arrays: dict[str, list[dict[str, Any]]] = {name: [] for name in CLAIM_ARRAYS}
        self.evidence: list[dict[str, Any]] = []
        self._evidence_by_quote: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def _claim_id(self, prefix: str) -> str:
        self._seq += 1
        return f"rx_{prefix}_{self._seq:04d}"

    def add(self, array: str, prefix: str, quote: str, body: dict[str, Any]) -> None:
        if quote not in self.reply_text:
            raise Rejection("InternalIntegrityError", "抽出Evidenceが返信本文の部分文字列ではありません。")
        claim_id = self._claim_id(prefix)
        evidence = self._evidence_by_quote.get(quote)
        if evidence is None:
            evidence = {
                "evidence_id": f"rx_ev_{len(self.evidence) + 1:04d}",
                "source_kind": "reply",
                "source_id": self.draft_id,
                "source_hash": self.draft_hash,
                "quote": quote,
                "supports": [],
                "confidence": None,
            }
            self.evidence.append(evidence)
            self._evidence_by_quote[quote] = evidence
        evidence["supports"].append(claim_id)
        self.arrays[array].append({"id": claim_id, "evidence_ids": [evidence["evidence_id"]], **body})

    def risk(self, array: str, quote: str, rtype: str, description: str, raw: str) -> None:
        self.add(
            array,
            "risk",
            quote,
            {"type": rtype, "description": _explicit(description, raw), "affects_critical": True, "resolved": False},
        )


def split_lines(reply_text: str) -> list[str]:
    return [line.strip() for line in reply_text.splitlines() if line.strip()]


def _sentences(line: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(line) if s.strip()]


def _money(builder: _Builder, line: _Line, quote: str) -> None:
    text = line.text
    specs: list[tuple[re.Pattern[str], str]] = [
        (_CODE_FIRST, "code"),
        (_CODE_LAST, "code"),
        (_SYMBOL_FIRST, "symbol"),
        (_WORD_LAST, "word"),
    ]
    for pattern, kind in specs:
        for match in pattern.finditer(text):
            if not line.free(match.start(), match.end()):
                continue
            amount = normalize_decimal(match.group("amount"))
            if kind == "code":
                code = match.group("code")
                if code not in SUPPORTED_CURRENCIES:
                    continue
                currency = _explicit(code, code)
            else:
                currency = _absent("ambiguous", match.group(kind))
            line.cover(match.start(), match.end())
            builder.add(
                "monetary_terms",
                "money",
                quote,
                {
                    "amount": _explicit(amount, match.group("amount"))
                    if amount is not None
                    else _absent("ambiguous", match.group("amount")),
                    "currency": currency,
                    "type": _money_type(quote),
                    "condition": _absent("not_stated"),
                },
            )


def _money_type(line: str) -> str:
    lower = line.lower()
    for keywords, mtype in (
        (("refund", "reimburs", "money back"), "refund"),
        (("discount",), "discount"),
        (("credit",), "credit"),
        (("fee", "charge", "penalt"), "fee"),
        (("price", "cost"), "price"),
        (("pay",), "payment"),
    ):
        if any(k in lower for k in keywords):
            return mtype
    return "other"


def _timezone(text: str, end: int) -> dict[str, Any]:
    match = _TIMEZONE.search(text, end, min(len(text), end + 40))
    if match is None:
        return _absent("not_stated")
    value = (match.group("tz") or match.group("abbr")).strip()
    return _explicit(value, match.group(0))


def _dates(builder: _Builder, line: _Line, quote: str) -> None:
    text = line.text
    for pattern in (_ISO_DATE, _JA_DATE, _MDY_DATE, _DMY_DATE):
        for match in pattern.finditer(text):
            if not line.free(match.start(), match.end()):
                continue
            line.cover(match.start(), match.end())
            groups = match.groupdict()
            month = int(groups["m"]) if groups.get("m") else _MONTHS[groups["month"].lower().rstrip(".")]
            iso = _real_date(int(groups["y"]), month, int(groups["d"])) if groups.get("y") else None
            date_value = _explicit(iso, match.group(0)) if iso else _absent("ambiguous", match.group(0))
            cue = _DEADLINE_CUE.search(text[: match.start()]) or text[: match.start()].strip().lower().endswith("deadline:")
            builder.add(
                "dates",
                "date",
                quote,
                {"type": "deadline" if cue else "date", "date": date_value, "timezone": _timezone(text, match.end())},
            )
    for match in _SLASH_DATE.finditer(text):
        if line.free(match.start(), match.end()):
            line.cover(match.start(), match.end())
            builder.add(
                "dates", "date", quote, {"type": "date", "date": _absent("ambiguous", match.group(0)), "timezone": _absent("not_stated")}
            )
    for match in _RELATIVE_DATE.finditer(text):
        builder.add(
            "dates", "date", quote, {"type": "date", "date": _absent("ambiguous", match.group(0)), "timezone": _absent("not_stated")}
        )


def _quantities(builder: _Builder, line: _Line, quote: str) -> None:
    for pattern in (_PERCENT, _QUANTITY):
        for match in pattern.finditer(line.text):
            if not line.free(match.start(), match.end()):
                continue
            line.cover(match.start(), match.end())
            amount = normalize_decimal(match.group("amount"))
            unit = match.group("unit").lower()
            unit = "percent" if unit in ("%", "percent", "per cent", "パーセント") else unit
            builder.add(
                "quantities",
                "qty",
                quote,
                {
                    "quantity": _explicit(amount, match.group("amount"))
                    if amount is not None
                    else _absent("ambiguous", match.group("amount")),
                    "unit": _explicit(unit, match.group("unit")),
                    "condition": _absent("not_stated"),
                },
            )


def _residual_numbers(builder: _Builder, line: _Line, quote: str) -> None:
    text = line.text
    seen_email = False
    for match in _EMAIL.finditer(text):
        seen_email = True
        line.cover(match.start(), match.end())
        builder.add("personal_data", "pii", quote, {"text": _explicit(match.group(0), match.group(0))})
    if not seen_email:
        for match in _OBFUSCATED_EMAIL.finditer(deobfuscate(text)):
            builder.add("personal_data", "pii", quote, {"text": _explicit(match.group(0), match.group(0))})
    seen_url = False
    for match in _URL.finditer(text):
        seen_url = True
        line.cover(match.start(), match.end())
        builder.risk("risks", quote, "other", "reply_link", match.group(0))
    if not seen_url:
        for match in _DEFANGED_URL.finditer(deobfuscate(text)):
            builder.risk("risks", quote, "other", "reply_link", match.group(0))
    for match in _IDENTIFIER.finditer(text):
        if not line.free(match.start(), match.end()):
            continue
        prefix = re.match(r"[A-Za-z]+", match.group(0).lstrip("#"))
        if prefix and prefix.group(0).upper()[:3] in SUPPORTED_CURRENCIES and len(prefix.group(0)) == 3:
            continue  # "USD5k"-like token: left to the residual digit rule below
        line.cover(match.start(), match.end())
    for match in _DIGITS.finditer(text):
        if line.free(match.start(), match.end()):
            line.cover(match.start(), match.end())
            builder.risk("risks", quote, "other", "unclassified_number", match.group(0))
    for match in _NUMBER_WORDS.finditer(text):
        builder.risk("risks", quote, "other", "spelled_out_number", match.group(0))


def _clauses(builder: _Builder, quote: str) -> None:
    for sentence in _sentences(quote):
        negated = any(_NEGATION.search(form) for form in scan_forms(sentence))
        forms = scan_forms(sentence)
        for array, pattern in KEYWORD_CLASSES.items():
            if not any(pattern.search(form) for form in forms):
                continue
            if array == "license_terms":
                lower = sentence.lower()
                builder.add(
                    array,
                    "rights",
                    quote,
                    {
                        "scope": _explicit(sentence, sentence),
                        "exclusivity": _explicit("exclusiv" in lower and "non-exclusiv" not in lower, sentence),
                        "sublicensing": _explicit("sublicen" in lower, sentence),
                        "commercial_use": _explicit("commercial use" in lower, sentence),
                        "condition": _absent("not_stated"),
                    },
                )
                continue
            builder.add(
                array,
                "clause",
                quote,
                {
                    "text": _explicit(sentence, sentence),
                    "modality": _explicit("must_not" if negated or array == "prohibitions" else "will", sentence),
                    "condition": _absent("not_stated"),
                    "scope": _absent("not_stated"),
                    "monetary_term_ids": [],
                    "deadline_ids": [],
                    "commitment_ids": [],
                },
            )
        if _FIRST_PERSON.search(sentence) and _MODAL.search(sentence):
            builder.add(
                "commitments",
                "commit",
                quote,
                {
                    "actor": "user",
                    "action": _explicit(sentence, sentence),
                    "object": _absent("not_stated"),
                    "modality": _explicit("must_not" if negated else "will", sentence),
                    "condition": _absent("not_stated"),
                    "scope": _absent("not_stated"),
                    "deadline_id": None,
                    "monetary_term_ids": [],
                    "authorization_state": "not_approved",
                },
            )
        elif re.search(r"\b(you|your)\b", sentence, re.IGNORECASE) and re.search(r"\b(will|must|shall)\b", sentence, re.IGNORECASE):
            builder.add(
                "requested_commitments",
                "ask",
                quote,
                {
                    "actor": "counterparty",
                    "action": _explicit(sentence, sentence),
                    "object": _absent("not_stated"),
                    "modality": _explicit("must_not" if negated else "will", sentence),
                    "condition": _absent("not_stated"),
                    "scope": _absent("not_stated"),
                    "deadline_id": None,
                    "monetary_term_ids": [],
                    "authorization_state": "not_approved",
                },
            )
        if sentence.rstrip().endswith("?"):
            builder.add("questions", "q", quote, {"text": _explicit(sentence, sentence), "required_answer": False})
        if _LEGAL.search(sentence):
            builder.add(
                "legal_claims",
                "legal",
                quote,
                {"claim_type": _explicit("legal_reference_in_reply", sentence), "requires_human_review": True},
            )
        if _INJECTION.search(sentence):
            builder.risk("prompt_injection_risks", quote, "injection", "instruction_like_text_in_reply", sentence)


def _iter_lines(reply_text: str) -> Iterator[_Line]:
    for raw in reply_text.splitlines():
        if raw.strip():
            yield _Line(raw.strip())


def extract_reply(
    final_reply_text: str,
    binding: dict[str, Any],
    *,
    runtime: ReplyExtractorRuntime | None = None,
) -> dict[str, Any]:
    """Return a schema-valid ReplyExtraction. Raises Rejection on binding mismatch."""
    runtime = runtime or ReplyExtractorRuntime()
    if not isinstance(final_reply_text, str) or not final_reply_text.strip():
        raise Rejection("UnsupportedInput", "返信本文が空です。")
    validate_draft_binding(binding)
    if binding["draft_hash"] != sha256_hex(final_reply_text.encode("utf-8")):
        raise Rejection("StaleState", "DraftBindingのdraft_hashが返信本文と一致しません。")

    builder = _Builder(final_reply_text, binding["draft_id"], binding["draft_hash"])
    for line in _iter_lines(final_reply_text):
        quote = line.text
        _money(builder, line, quote)
        _dates(builder, line, quote)
        _quantities(builder, line, quote)
        _residual_numbers(builder, line, quote)
        _clauses(builder, quote)

    state: dict[str, Any] = {name: builder.arrays[name] for name in CLAIM_ARRAYS}
    state["human_review_required"] = True
    state["confidence"] = None
    state["evidence"] = builder.evidence
    extraction = {"extraction_id": runtime.new_id("rx"), "binding": binding, "state": state}
    validate_reply_extraction(extraction)
    return extraction
