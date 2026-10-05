"""Adversarial Reply Extractor / Evidence integrity tests.

Ported from the pre-2026-09-17 adversarial suite (currency & amount parsing, dates, verbatim
quote integrity, substring edge cases, context isolation). Private helper tests
(``_format_decimal`` / ``_ExtractionContext``) became public-contract tests: tampered
Evidence is now rejected by the Verifier binding check, which is where it matters.
"""

from __future__ import annotations

import copy
import unicodedata
from typing import Any

import pytest
from builders import CaseBuilder, Json, question
from pipeline_support import assess_document, extraction_for, generate, runtimes

from relayguard.errors import Rejection
from relayguard.generator import draft_binding
from relayguard.reply_extractor import extract_reply, normalize_decimal
from relayguard.schema_validation import validate_reply_extraction
from relayguard.verifier import verify_draft


def simple_case() -> tuple[Any, Json, Json, Json]:
    b = CaseBuilder("case_adv_01", "Did the catalogue arrive?")
    b.add("questions", question("c_q1", "Did the catalogue arrive?"), "Did the catalogue arrive?")
    b.answer("c_q1", "Yes, the catalogue arrived.")
    ctx, pre = assess_document(b.build())
    draft = generate(ctx, pre)
    extraction = extract_reply(draft["reply_text"], draft_binding(draft), runtime=runtimes()[1])
    return ctx, pre, draft, extraction


class TestCurrencyAndAmountParsing:
    def test_high_decimal_precision_18_places(self) -> None:
        money = extraction_for("Total USD 1.123456789012345678.\n")["state"]["monetary_terms"]
        assert money[0]["amount"]["value"] == "1.123456789012345678"

    def test_zero_amount(self) -> None:
        money = extraction_for("Fee JPY 0 applies.\n")["state"]["monetary_terms"]
        assert money[0]["amount"]["value"] == "0"

    def test_normalize_decimal_rejects_negative_and_non_numeric(self) -> None:
        assert normalize_decimal("-5") is None
        assert normalize_decimal("abc") is None
        assert normalize_decimal("1,234.5") == "1234.5"

    def test_unsupported_iso_like_code_is_not_money_but_still_flagged(self) -> None:
        state = extraction_for("Pay XYZ 100 now.\n")["state"]
        assert state["monetary_terms"] == []
        assert any(r["description"]["value"] == "unclassified_number" for r in state["risks"])

    def test_every_supported_symbol_is_ambiguous(self) -> None:
        for symbol in ("$", "€", "£", "¥", "￥", "₩", "₹", "A$", "C$", "HK$"):
            money = extraction_for(f"Price {symbol}3000.\n")["state"]["monetary_terms"]
            assert money[0]["currency"]["status"] == "ambiguous", symbol
            assert money[0]["amount"]["value"] == "3000", symbol


class TestDatesAndDeadlines:
    def test_valid_leap_year_iso_date(self) -> None:
        assert extraction_for("On 2028-02-29.\n")["state"]["dates"][0]["date"]["value"] == "2028-02-29"

    def test_invalid_dates_never_become_explicit(self) -> None:
        for expr in ("2026-02-29", "2026-04-31", "2026-00-10"):
            dates = extraction_for(f"On {expr}.\n")["state"]["dates"]
            assert dates[0]["date"]["status"] == "ambiguous", expr

    def test_deadline_cues(self) -> None:
        for cue in ("by", "before", "no later than", "due", "until"):
            assert extraction_for(f"Ship {cue} 2026-10-01.\n")["state"]["dates"][0]["type"] == "deadline", cue

    def test_textual_dates_with_ordinal_and_comma(self) -> None:
        for expr in ("October 1st, 2026", "Oct. 1 2026", "1st of October 2026", "2026年10月1日"):
            assert extraction_for(f"On {expr}.\n")["state"]["dates"][0]["date"]["value"] == "2026-10-01", expr


class TestVerbatimQuoteIntegrityAtVerifier:
    def test_tampered_quote_character_is_rejected(self) -> None:
        ctx, pre, draft, extraction = simple_case()
        tampered = copy.deepcopy(extraction)
        tampered["state"]["evidence"].append(
            {
                "evidence_id": "rx_ev_9999",
                "source_kind": "reply",
                "source_id": draft["draft_id"],
                "source_hash": draft["draft_hash"],
                "quote": "Yes, the catalogue arrivéd.",
                "supports": [],
                "confidence": None,
            }
        )
        with pytest.raises(Rejection) as exc:
            verify_draft(ctx, pre, draft, tampered, runtime=runtimes()[2])
        assert exc.value.code == "InternalIntegrityError"

    @pytest.mark.parametrize("mutation", ["case", "whitespace", "source_id", "source_hash", "source_kind"])
    def test_evidence_mutations_are_rejected(self, mutation: str) -> None:
        ctx, pre, draft, extraction = simple_case()
        tampered = copy.deepcopy(extraction)
        evidence = tampered["state"]["evidence"][0] if tampered["state"]["evidence"] else None
        if evidence is None:
            tampered["state"]["evidence"].append(
                {"evidence_id": "rx_ev_1", "source_kind": "reply", "source_id": draft["draft_id"], "source_hash": draft["draft_hash"],
                 "quote": "Hello,", "supports": [], "confidence": None}
            )  # fmt: skip
            evidence = tampered["state"]["evidence"][0]
        if mutation == "case":
            evidence["quote"] = evidence["quote"].upper() + "X"
        elif mutation == "whitespace":
            evidence["quote"] = "  " + evidence["quote"] + "  \t"
        elif mutation == "source_id":
            evidence["source_id"] = "draft_other"
        elif mutation == "source_hash":
            evidence["source_hash"] = "a" * 64
        else:
            evidence["source_kind"] = "source_message"
        with pytest.raises(Rejection):
            verify_draft(ctx, pre, draft, tampered, runtime=runtimes()[2])

    def test_extraction_from_another_draft_is_stale(self) -> None:
        ctx, pre, draft, _ = simple_case()
        other = extraction_for(draft["reply_text"], draft_id="draft_other")
        with pytest.raises(Rejection) as exc:
            verify_draft(ctx, pre, draft, other, runtime=runtimes()[2])
        assert exc.value.code == "StaleState"


class TestQuotationSubstringEdgeCases:
    def test_empty_quote_is_rejected_by_schema(self) -> None:
        extraction = extraction_for("Hello,\nYes, 2026-10-01.\n")
        extraction["state"]["evidence"][0]["quote"] = ""
        with pytest.raises(Rejection):
            validate_reply_extraction(extraction)

    def test_nfc_and_nfd_are_different_bytes(self) -> None:
        nfc = unicodedata.normalize("NFC", "Café USD 1.00.\n")
        nfd = unicodedata.normalize("NFD", nfc)
        a, b = extraction_for(nfc), extraction_for(nfd)
        assert a["binding"]["draft_hash"] != b["binding"]["draft_hash"]
        assert all(ev["quote"] in nfd for ev in b["state"]["evidence"])

    def test_japanese_punctuation_and_emoji(self) -> None:
        text = "【重要】返金はJPY 5,000です🙏。\n"
        ext = extraction_for(text)
        assert ext["state"]["monetary_terms"][0]["amount"]["value"] == "5000"
        assert all(ev["quote"] in text for ev in ext["state"]["evidence"])


class TestContextIsolationStress:
    def test_input_objects_are_not_mutated(self) -> None:
        ctx, pre, draft, extraction = simple_case()
        before = (copy.deepcopy(pre), copy.deepcopy(draft), copy.deepcopy(extraction))
        verify_draft(ctx, pre, draft, extraction, runtime=runtimes()[2])
        assert (pre, draft, extraction) == before

    def test_same_text_same_extraction_content(self) -> None:
        first = extraction_for("We will ship USD 10.00 by 2026-10-01.\n")
        second = extraction_for("We will ship USD 10.00 by 2026-10-01.\n")
        assert first["state"] == second["state"]


class TestObfuscatedTextIsStillSeen:
    """Full-width, invisible, lookalike and letter-spaced spellings must scan like the plain word.

    Found by scripts/fuzz_extractor.py: these forms read normally to the customer but used to
    slip past the ASCII keyword and e-mail patterns inside an approved answer line.
    """

    @staticmethod
    def clause_texts(text: str) -> str:
        extraction = extraction_for(text)
        arrays = ("guarantees", "refund_terms", "contract_terms", "cancellation_terms", "license_terms", "prohibitions")
        return " ".join(str(claim) for array in arrays for claim in extraction["state"][array])

    @pytest.mark.parametrize(
        "text",
        [
            "The result is guaranteed.\n",
            "The result is ＧＵＡＲＡＮＴＥＥＤ.\n",
            "The result is guaran\u200bteed.\n",
            "The result is \u0261uaranteed.\n",
            "The result is g-u-a-r-a-n-t-e-e-d.\n",
            "A \uff32efund is possible.\n",
        ],
    )
    def test_obfuscated_keyword_is_recorded(self, text: str) -> None:
        assert self.clause_texts(text)

    def test_evidence_quotes_stay_the_original_line(self) -> None:
        text = "The result is guaran\u200bteed.\n"
        extraction = extraction_for(text)
        assert all(evidence["quote"] in text for evidence in extraction["state"]["evidence"])

    @pytest.mark.parametrize(
        "text",
        [
            "Write to john.smith@other.example.\n",
            "Write to john dot smith at other dot example.\n",
            "Write to john.smith(at)other.example.\n",
            "Write to john.smith [at] other [dot] example.\n",
        ],
    )
    def test_third_party_address_is_recorded_as_personal_data(self, text: str) -> None:
        assert extraction_for(text)["state"]["personal_data"]

    def test_plain_english_is_not_flagged_as_an_address(self) -> None:
        extraction = extraction_for("We looked at the order and the label is correct.\n")
        assert extraction["state"]["personal_data"] == []
