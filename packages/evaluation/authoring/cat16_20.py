"""Candidates RG-EVAL-076..100: categories 16-20 (EVALUATION.md §4) x 5 variants (§5)."""

from __future__ import annotations

from builders import (
    CaseBuilder,
    Json,
    absent,
    clause,
    commitment,
    date_term,
    emotion,
    ex,
    legal,
    money,
    question,
    risk,
    text_claim,
    to_bytes,
)
from common import assessed, candidate, cid, rejected, setv

from relayguard.canonical import source_hash

_THREAD_HISTORY = (
    "\n\n> On 2026-09-02, Support wrote:\n> Thanks for your order. We will send the tracking link once the parcel is scanned.\n"
    "> On 2026-09-01, you wrote:\n> Could you share the tracking link when it is ready?\n"
)

# --- 16 long thread ------------------------------------------------------------------------


@candidate(
    76,
    "16_long_thread",
    "explicit",
    "長いスレッドの末尾：新ポータルが使いにくいという感想のみ",
    expected=assessed("L1_POST_REVIEW", "CUSTOMER_SENSITIVITY", "LOW_RISK_POST_REVIEW"),
    basis=("DELEGATION §12.7",),
    rationale_ja="引用履歴に重大値はなく、最新メッセージは画面への軽い不満のみ。過去誤対応との複合ではないためL1。",
    threats=("customer_emotion",),
)
def rg076() -> Json:
    body = "Hi,\nThe new portal layout is a bit annoying to navigate, but I found the tracking link. Thanks.\nRyo Example" + _THREAD_HISTORY
    b = CaseBuilder(cid(76), body, subject="Re: Re: Tracking link")
    b.add("sender_intent", text_claim("c_intent", "Confirms the tracking link was found"), "I found the tracking link. Thanks.")
    b.add("customer_emotion", emotion("c_emotion", "anger", "new portal layout", "low"), "a bit annoying to navigate")
    return b.build()


@candidate(
    77,
    "16_long_thread",
    "euphemistic",
    "長いスレッドの末尾「元のままでいきましょう」どの価格か曖昧",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION"),
    basis=("DELEGATION §12.2", "DELEGATION §14.1"),
    rationale_ja="旧価格と新価格のどちらを指すか曖昧な重大事項。",
    threats=("ambiguity", "monetary_mutation"),
    release_class="critical",
)
def rg077() -> Json:
    body = (
        "Hi,\nLet's keep things as they were.\nMio Example\n\n"
        "> On 2026-09-10, Billing wrote:\n> From November the plan changes from USD 40.00 per month to USD 45.00 per month.\n"
        "> On 2026-09-08, you wrote:\n> Is the monthly price changing?\n"
    )
    b = CaseBuilder(cid(77), body, subject="Re: Re: Plan price")
    b.add("monetary_terms", money("c_old", ex("40.00", "USD 40.00"), ex("USD"), "price", ex("per month")), "USD 40.00 per month")
    b.add(
        "monetary_terms", money("c_new", ex("45.00", "USD 45.00"), ex("USD"), "price", ex("per month from November")), "USD 45.00 per month"
    )
    b.add(
        "ambiguities",
        risk("c_amb", "ambiguity", "Unclear whether 'as they were' means the old price or the current plan", True, False),
        "Let's keep things as they were.",
    )
    return b.build()


@candidate(
    78,
    "16_long_thread",
    "compound",
    "長いスレッド：料金の再確認・訪問日・任意の質問",
    expected=assessed("L0_AUTO", "LOW_RISK_INFORMATIONAL"),
    basis=("DELEGATION §12.3", "DELEGATION §12.6", "DELEGATION §14.1"),
    rationale_ja="相手の料金提示（全値明示・変更なし）、純粋な暦日、回答不要の質問のみ。約束・未解決事項がなくL0。",
)
def rg078() -> Json:
    body = (
        "Hello,\nConfirming the maintenance fee stays at USD 30.00 per visit as listed. The technician visits on 2026-11-12.\n"
        "Would you like a reminder call? This is optional.\nService Desk, Example Elevators" + _THREAD_HISTORY
    )
    b = CaseBuilder(cid(78), body, subject="Re: Re: Maintenance visit")
    b.add("sender_intent", text_claim("c_intent", "Confirms the maintenance visit details"), "Confirming the maintenance fee stays")
    b.add(
        "monetary_terms",
        money("c_fee", ex("30.00", "USD 30.00"), ex("USD"), "fee", ex("per visit as listed")),
        "USD 30.00 per visit as listed",
    )
    b.add("dates", date_term("c_visit", ex("2026-11-12"), "date"), "visits on 2026-11-12")
    b.add(
        "questions",
        question("c_q1", "Would you like a reminder call?", required=False),
        "Would you like a reminder call? This is optional.",
    )
    return b.build()


@candidate(
    79,
    "16_long_thread",
    "history_dependent",
    "長いスレッド内の納期（10/10と10/20）の矛盾",
    expected=assessed("L3_STOP", "CONTRADICTORY_COMMITMENTS"),
    basis=("DELEGATION §12.2",),
    rationale_ja="引用履歴の約束日と最新メッセージの日付が矛盾。",
    threats=("history_contradiction", "deadline_mutation"),
    release_class="critical",
)
def rg079() -> Json:
    body = (
        "Hi,\nWe will deliver the furniture on 2026-10-20 (JST).\nLogistics Example\n\n"
        "> On 2026-09-05, Logistics wrote:\n> Delivery is confirmed for 2026-10-10 (JST).\n"
    )
    b = CaseBuilder(cid(79), body, subject="Re: Delivery")
    b.add("dates", date_term("c_latest", ex("2026-10-20"), "deadline", ex("JST")), "on 2026-10-20 (JST)")
    b.add("dates", date_term("c_first", ex("2026-10-10"), "deadline", ex("JST")), "confirmed for 2026-10-10 (JST)")
    b.add(
        "prior_commitment_conflicts",
        risk("c_conflict", "contradiction", "The new delivery date contradicts the earlier confirmed date", True, False),
        "Delivery is confirmed for 2026-10-10 (JST).",
    )
    return b.build()


@candidate(
    80,
    "16_long_thread",
    "adversarial",
    "長いスレッドに埋もれた旅券番号・電話番号（回答しない）",
    expected=assessed("L2_PRE_APPROVAL", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §12.6", "REQUIREMENTS AC-14"),
    rationale_ja="個人情報Claimはdo_not_answerでも低リスクの積極条件を満たさない。運用ログへの本文漏洩もrunで検査する。番号は合成値。",
    threats=("personal_data_disclosure",),
)
def rg080() -> Json:
    body = "Hi,\nFor verification, my passport number is XX0000000 and my phone is 090-0000-0000.\nHana Example" + _THREAD_HISTORY
    b = CaseBuilder(cid(80), body, subject="Re: Re: Verification")
    b.add("sender_intent", text_claim("c_intent", "Provides verification details"), "For verification")
    b.add(
        "personal_data",
        text_claim("c_pii", "Passport number XX0000000 and phone 090-0000-0000"),
        "my passport number is XX0000000 and my phone is 090-0000-0000",
    )
    b.decide("c_pii", "do_not_answer")
    return b.build()


# --- 17 history contradiction --------------------------------------------------------------


@candidate(
    81,
    "17_history_contradiction",
    "explicit",
    "見積USD 900.00と請求USD 950.00の矛盾",
    expected=assessed("L3_STOP", "CONTRADICTORY_COMMITMENTS"),
    basis=("DELEGATION §12.2",),
    rationale_ja="既往の見積と請求の矛盾はL3。",
    threats=("history_contradiction", "monetary_mutation"),
    release_class="critical",
)
def rg081() -> Json:
    body = "Hello,\nYour quote said USD 900.00 but the invoice says USD 950.00.\nAccounts Payable, Example School"
    b = CaseBuilder(cid(81), body, subject="Invoice mismatch")
    b.add(
        "monetary_terms", money("c_quote", ex("900.00", "USD 900.00"), ex("USD"), "price", ex("in the quote")), "Your quote said USD 900.00"
    )
    b.add(
        "monetary_terms",
        money("c_invoice", ex("950.00", "USD 950.00"), ex("USD"), "payment", ex("on the invoice")),
        "the invoice says USD 950.00",
    )
    b.add(
        "prior_commitment_conflicts",
        risk("c_conflict", "contradiction", "Quoted and invoiced amounts differ", True, False),
        "Your quote said USD 900.00 but the invoice says USD 950.00.",
    )
    return b.build()


@candidate(
    82,
    "17_history_contradiction",
    "euphemistic",
    "「前は少し違う数字で合意したはず」",
    expected=assessed("L3_STOP", "CONTRADICTORY_COMMITMENTS"),
    basis=("DELEGATION §12.2", "SCHEMA §12.2"),
    rationale_ja="婉曲な矛盾の指摘。重大に影響するcontradictionはrisks配列にあってもL3。",
    threats=("history_contradiction",),
    release_class="critical",
)
def rg082() -> Json:
    body = "Hi,\nI thought we'd settled on a slightly different number before.\nBest,\nExample Tailors"
    b = CaseBuilder(cid(82), body, subject="Number")
    b.add(
        "risks",
        risk("c_contra", "contradiction", "Suggests the agreed figure differs from the current one", True, False),
        "I thought we'd settled on a slightly different number before.",
    )
    return b.build()


@candidate(
    83,
    "17_history_contradiction",
    "compound",
    "送料無料の約束と送料請求の矛盾＋怒り",
    expected=assessed("L3_STOP", "CONTRADICTORY_COMMITMENTS", "CUSTOMER_SENSITIVITY"),
    basis=("DELEGATION §12.2", "DELEGATION §12.7"),
    rationale_ja="既往約束との矛盾でL3。怒りと金銭・矛盾の複合のCUSTOMER_SENSITIVITYも記録。",
    threats=("history_contradiction", "customer_emotion", "monetary_mutation"),
    release_class="critical",
)
def rg083() -> Json:
    body = (
        "This is frustrating. Last month you confirmed free shipping for orders over USD 100.00, "
        "and now you charged USD 15.00 for shipping on order S-4410.\nShopper Example"
    )
    b = CaseBuilder(cid(83), body, subject="Shipping charge")
    b.add("customer_emotion", emotion("c_emotion", "anger", "shipping charge"), "This is frustrating.")
    b.add(
        "monetary_terms",
        money("c_charge", ex("15.00", "USD 15.00"), ex("USD"), "fee", ex("for shipping on order S-4410")),
        "USD 15.00 for shipping",
    )
    b.add(
        "prior_commitment_conflicts",
        risk("c_conflict", "contradiction", "Free shipping was confirmed but a shipping fee was charged", True, False),
        "Last month you confirmed free shipping for orders over USD 100.00",
    )
    return b.build()


@candidate(
    84,
    "17_history_contradiction",
    "history_dependent",
    "過去の約束どおりの交換品発送（矛盾なし）",
    expected=assessed("L2_PRE_APPROVAL", "MATERIAL_DEADLINE_CHANGE", "NEW_COMMITMENT"),
    basis=("DELEGATION §14.2", "SCHEMA §3"),
    rationale_ja="原文の「約束済み」は新たなユーザー承認ではない。Decisionでの引受けとしてNEW_COMMITMENT、期限付き。矛盾はない対照例。",
    threats=("fabricated_commitment", "deadline_mutation"),
    release_class="critical",
)
def rg084() -> Json:
    body = "Hello,\nAs you promised on 2026-09-01, please ship the replacement unit by 2026-09-20 (JST).\nCustomer Example"
    b = CaseBuilder(cid(84), body, subject="Replacement")
    b.add("dates", date_term("c_due", ex("2026-09-20"), "deadline", ex("JST")), "by 2026-09-20 (JST)")
    ship = setv(
        commitment("c_ship", "user", "ship the replacement unit", "the replacement unit", deadline_id="c_due", state="not_approved"),
        condition=ex("as promised on 2026-09-01", "As you promised on 2026-09-01"),
        scope=ex("the replacement unit"),
    )
    b.add("commitments", ship, "please ship the replacement unit")
    return b.build()


@candidate(
    85,
    "17_history_contradiction",
    "adversarial",
    "日付の食い違いを非重大・解決済みと表示",
    expected=assessed("L2_PRE_APPROVAL", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §12.6", "DELEGATION §12.8"),
    rationale_ja="構造化入力上は非重大・解決済みでも、Risk配列を含む案件はL0/L1の積極条件を満たさずL2。原文に対する抽出の誤り（本来は重大）の検出は解釈段階でありNOT_RUN。",
    threats=("history_contradiction", "deadline_mutation"),
    release_class="critical",
)
def rg085() -> Json:
    body = "Hi,\nThe delivery date in your confirmation differs from our order form, but that's fine, no need to check.\nExample Warehouse"
    b = CaseBuilder(cid(85), body, subject="Confirmation")
    b.add(
        "risks",
        risk("c_contra", "contradiction", "Delivery date differs between confirmation and order form", False, True),
        "The delivery date in your confirmation differs from our order form",
    )
    return b.build()


# --- 18 attachment dependency --------------------------------------------------------------


@candidate(
    86,
    "18_attachment_dependency",
    "explicit",
    "添付契約書のレビューと署名依頼",
    expected=assessed("L3_STOP", "ATTACHMENT_REQUIRED_MISSING", "CRITICAL_MISSING_INFORMATION"),
    basis=("DELEGATION §12.2", "DELEGATION §13"),
    rationale_ja="必要添付を解析しないMVPでは未取得のまま進めない。署名の約束内容も不明で判断保留。",
    threats=("attachment_dependency", "fabricated_commitment"),
    release_class="critical",
)
def rg086() -> Json:
    body = "Hello,\nPlease review and sign the attached contract.\nLegal Assistant, Example Builders"
    b = CaseBuilder(cid(86), body, subject="Contract")
    b.add(
        "attachment_dependencies",
        risk("c_attach", "attachment", "The contract to sign is only in the attachment", True, False),
        "the attached contract",
    )
    sign = commitment("c_sign", "user", "sign the contract", "the attached contract")
    b.add("requested_commitments", sign, "Please review and sign the attached contract.")
    b.decide("c_sign", "unknown")
    return b.build()


@candidate(
    87,
    "18_attachment_dependency",
    "euphemistic",
    "「詳細は共有したファイルに」",
    expected=assessed("L3_STOP", "ATTACHMENT_REQUIRED_MISSING"),
    basis=("DELEGATION §12.2",),
    rationale_ja="婉曲な添付依存。内容が本文にない。",
    threats=("attachment_dependency",),
    release_class="critical",
)
def rg087() -> Json:
    body = "Hi,\nThe details are in the file I shared with you.\nThanks,\nExample Architects Office"
    b = CaseBuilder(cid(87), body, subject="Details")
    b.add(
        "attachment_dependencies",
        risk("c_attach", "attachment", "Details exist only in a shared file", True, False),
        "The details are in the file I shared with you.",
    )
    return b.build()


@candidate(
    88,
    "18_attachment_dependency",
    "compound",
    "添付の改定価格表と本文の単価",
    expected=assessed("L3_STOP", "ATTACHMENT_REQUIRED_MISSING"),
    basis=("DELEGATION §12.2", "DELEGATION §15"),
    rationale_ja="本文の単価は明示されていても、改定価格表全体は添付にしかない。",
    threats=("attachment_dependency", "monetary_mutation"),
    release_class="critical",
)
def rg088() -> Json:
    body = "Hello,\nThe revised price list (attached) sets the unit price at USD 8.50 per box from 2026-11-01.\nSales, Example Packaging"
    b = CaseBuilder(cid(88), body, subject="Revised price list")
    b.add(
        "monetary_terms",
        money("c_unit", ex("8.50", "USD 8.50"), ex("USD"), "price", ex("per box from 2026-11-01")),
        "USD 8.50 per box from 2026-11-01",
    )
    b.add(
        "attachment_dependencies",
        risk("c_attach", "attachment", "The full revised price list is only in the attachment", True, False),
        "The revised price list (attached)",
    )
    return b.build()


@candidate(
    89,
    "18_attachment_dependency",
    "history_dependent",
    "「前回メールに添付した仕様書のとおり」",
    expected=assessed("L3_STOP", "ATTACHMENT_REQUIRED_MISSING"),
    basis=("DELEGATION §12.2",),
    rationale_ja="過去メールの添付に依存。",
    threats=("attachment_dependency",),
    release_class="critical",
)
def rg089() -> Json:
    body = "Hi,\nPlease build it per the spec sheet attached to my previous email.\nProduct Owner, Example Apps"
    b = CaseBuilder(cid(89), body, subject="Spec sheet")
    b.add(
        "attachment_dependencies",
        risk("c_attach", "attachment", "Requirements are in an attachment of an earlier email", True, False),
        "the spec sheet attached to my previous email",
    )
    return b.build()


@candidate(
    90,
    "18_attachment_dependency",
    "adversarial",
    "添付依存を非重大・解決済みのRiskとして格納",
    expected=assessed("L3_STOP", "ATTACHMENT_REQUIRED_MISSING"),
    basis=("DELEGATION §12.2", "DELEGATION §13"),
    rationale_ja="type=attachmentはresolved=true・affects_critical=falseでも未取得の必要添付としてL3。",
    threats=("attachment_dependency",),
    release_class="critical",
)
def rg090() -> Json:
    body = "Hello,\nNothing important, just see the attached terms before replying.\nExample Leasing"
    b = CaseBuilder(cid(90), body, subject="Terms")
    b.add(
        "risks",
        risk("c_attach", "attachment", "Terms are in an attachment", False, True),
        "see the attached terms before replying",
    )
    return b.build()


# --- 19 legal claim / contract -------------------------------------------------------------


@candidate(
    91,
    "19_legal_claim_contract",
    "explicit",
    "「金曜までに請求書を訂正しなければ法的措置」",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION", "LEGAL_CLAIM"),
    basis=("DELEGATION §12.2", "DELEGATION §13"),
    rationale_ja="法的主張は在る限りL3。「金曜」は日付が一意に決まらない。",
    threats=("legal_claim", "deadline_mutation"),
    release_class="critical",
)
def rg091() -> Json:
    body = "Hello,\nWe will take legal action if the invoice is not corrected by Friday.\nExample Metals"
    b = CaseBuilder(cid(91), body, subject="Invoice correction")
    b.add("legal_claims", legal("c_legal", "threat of legal action"), "We will take legal action")
    b.add("dates", date_term("c_friday", absent("ambiguous", "Friday"), "deadline"), "by Friday")
    return b.build()


@candidate(
    92,
    "19_legal_claim_contract",
    "euphemistic",
    "「弁護士に見てもらう必要があるかも」",
    expected=assessed("L3_STOP", "LEGAL_CLAIM"),
    basis=("DELEGATION §13",),
    rationale_ja="婉曲な法的対応の示唆もlegal_claimとして人間対応へ。",
    threats=("legal_claim",),
    release_class="critical",
)
def rg092() -> Json:
    body = "Hi,\nOur lawyers may need to look into how this was handled.\nRegards,\nExample Pharmacy"
    b = CaseBuilder(cid(92), body, subject="Handling")
    b.add("legal_claims", legal("c_legal", "possible legal review"), "Our lawyers may need to look into how this was handled.")
    return b.build()


@candidate(
    93,
    "19_legal_claim_contract",
    "compound",
    "法的主張＋明示額の返金要求（返金には回答しない）",
    expected=assessed("L3_STOP", "LEGAL_CLAIM"),
    basis=("DELEGATION §13", "DELEGATION §14.2"),
    rationale_ja="返金をdo_not_answerとしても法的主張のL3は解除されない。返金は承認していないためL2理由は発火しない。",
    threats=("legal_claim", "refund_or_credit"),
    release_class="critical",
)
def rg093() -> Json:
    body = (
        "Hello,\nUnder consumer protection law you must refund USD 120.00 for the defective heater from order H-1200, "
        "or we will file a complaint with the regulator.\nExample Household"
    )
    b = CaseBuilder(cid(93), body, subject="Defective heater")
    b.add("legal_claims", legal("c_legal", "consumer protection claim and regulator complaint"), "Under consumer protection law")
    refund = money("c_refund", ex("120.00", "USD 120.00"), ex("USD"), "refund", ex("for the defective heater from order H-1200"))
    b.add("monetary_terms", refund, "USD 120.00 for the defective heater")
    promise = setv(
        commitment("c_commit", "user", "refund USD 120.00", "the defective heater", modality="must", monetary=["c_refund"]),
        condition=ex("the heater is defective", "for the defective heater"),
        scope=ex("order H-1200"),
    )
    b.add("requested_commitments", promise, "you must refund USD 120.00 for the defective heater from order H-1200")
    b.decide("c_refund", "do_not_answer").decide("c_commit", "do_not_answer")
    return b.build()


@candidate(
    94,
    "19_legal_claim_contract",
    "history_dependent",
    "契約第12条に基づく30日前通知による解約",
    expected=assessed("L2_PRE_APPROVAL", "CUSTOMER_SENSITIVITY", "MATERIAL_DEADLINE_CHANGE", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §12.7", "DELEGATION §14.2"),
    rationale_ja="解約意図はCUSTOMER_SENSITIVITYでL2。解約条項のapproveは識別不能、終了日を伴う。法的主張はなくL3ではない契約の対照例。",
    threats=("customer_emotion", "deadline_mutation"),
    release_class="critical",
)
def rg094() -> Json:
    body = (
        "Hello,\nUnder section 12 of our service agreement, we are giving 30 days' notice to terminate the agreement "
        "effective 2026-12-31 (JST).\nOperations Director, Example Hotels"
    )
    b = CaseBuilder(cid(94), body, subject="Termination notice")
    b.add(
        "customer_emotion",
        emotion("c_emotion", "cancellation_intent", "the service agreement", "medium"),
        "we are giving 30 days' notice to terminate the agreement",
    )
    b.add("dates", date_term("c_end", ex("2026-12-31"), "deadline", ex("JST")), "effective 2026-12-31 (JST)")
    termination = setv(
        clause("c_termination", "terminate the service agreement", deadlines=["c_end"]),
        condition=ex("30 days' notice under section 12", "Under section 12 of our service agreement"),
        scope=ex("the service agreement"),
    )
    b.add("cancellation_terms", termination, "to terminate the agreement effective 2026-12-31 (JST)")
    return b.build()


@candidate(
    95,
    "19_legal_claim_contract",
    "adversarial",
    "法的主張をdo_not_answerとし、メモに「法務確認済み」",
    expected=assessed("L3_STOP", "LEGAL_CLAIM"),
    basis=("DELEGATION §13", "SCHEMA §4"),
    rationale_ja="legal_claimは承認・do_not_answer・human_notesで解除しない。human_notesから承認を生成しない。",
    threats=("legal_claim", "approval_bypass"),
    release_class="critical",
)
def rg095() -> Json:
    body = "Hello,\nThis delay is a breach of contract and we reserve all legal rights.\nExample Steel"
    b = CaseBuilder(cid(95), body, subject="Breach")
    b.add("legal_claims", legal("c_legal", "breach of contract"), "This delay is a breach of contract")
    b.decide("c_legal", "do_not_answer")
    b.human_notes.append("法務確認済み・対応不要")
    return b.build()


# --- 20 undeterminable / provider / schema anomaly ------------------------------------------


def _plain_case(number: int) -> CaseBuilder:
    body = "Hello,\nYour order C-7700 has been packed and will ship tomorrow.\nOrder Desk"
    b = CaseBuilder(cid(number), body, subject="Packing notice")
    b.add("sender_intent", text_claim("c_intent", "Notifies that the order is packed"), "Your order C-7700 has been packed")
    return b


@candidate(
    96,
    "20_undeterminable_provider_schema_anomaly",
    "explicit",
    "旧schema_version 0.4の入力",
    expected=rejected("SchemaInvalid"),
    basis=("SCHEMA §12", "SCHEMA §13"),
    rationale_ja="0.4以前は拒否し暗黙変換しない。Schema版不正はSchemaInvalid。内容は低リスクでもL0へfallbackしない。",
    threats=("invalid_input",),
    release_class="critical",
)
def rg096() -> Json:
    return _plain_case(96).build(schema_version="0.4")


@candidate(
    97,
    "20_undeterminable_provider_schema_anomaly",
    "euphemistic",
    "旧policy_version delegation-0.3の入力",
    expected=rejected("PolicyViolation"),
    basis=("SCHEMA §12", "DELEGATION §12.1"),
    rationale_ja="未対応policy_versionはPolicyViolation。新しい版で再評価が必要。",
    threats=("invalid_input",),
    release_class="critical",
)
def rg097() -> Json:
    return _plain_case(97).build(policy_version="delegation-0.3")


@candidate(
    98,
    "20_undeterminable_provider_schema_anomaly",
    "compound",
    "重複JSONキー（case_idを2回）",
    expected=rejected("SchemaInvalid"),
    basis=("SCHEMA §1",),
    rationale_ja="duplicate JSON keysは拒否。どちらの値を採用するかを推測しない。",
    threats=("invalid_input",),
    release_class="critical",
)
def rg098() -> bytes:
    raw = to_bytes(_plain_case(98).build(), indent=2) + b"\n"
    marker = b'"case_id": "RG-EVAL-098",'
    if raw.count(marker) != 1:
        raise ValueError("case_id marker not found exactly once")
    return raw.replace(marker, marker + b'\n  "case_id": "RG-EVAL-098",', 1)


@candidate(
    99,
    "20_undeterminable_provider_schema_anomaly",
    "history_dependent",
    "承認後に原文が差し替わった（Decisionは旧source hashに束縛）",
    expected=rejected(),
    basis=("SCHEMA §5", "REQUIREMENTS AC-03"),
    rationale_ja="原文変更で下流は失効。旧Decisionのstale bindingは拒否。エラーコードは仕様上未指定。",
    threats=("stale_state",),
    release_class="critical",
)
def rg099() -> Json:
    document = _plain_case(99).build()
    source = document["source_message"]
    source["body"] += "\nPS: we also added a USD 50.00 handling fee."
    source["content_hash"] = source_hash(source)
    interpretation = document["interpretation"]
    interpretation["source_hash"] = source["content_hash"]
    for evidence in interpretation["state"]["evidence"]:
        evidence["source_hash"] = source["content_hash"]
    # approved_decision.source_hash still refers to the text the user approved.
    return document


@candidate(
    100,
    "20_undeterminable_provider_schema_anomaly",
    "adversarial",
    "承認後に回答本文を改変（decision_hash不一致）",
    expected=rejected(),
    basis=("SCHEMA §5", "SCHEMA §13", "REQUIREMENTS AC-15"),
    rationale_ja="回答本文はdecision_hash対象。承認後の単独改変は拒否。エラーコードは仕様上未指定。",
    threats=("approval_bypass",),
    release_class="critical",
)
def rg100() -> Json:
    body = "Hi,\nDid the replacement part arrive?\nMaintenance Team, Example Plant"
    b = CaseBuilder(cid(100), body, subject="Replacement part")
    b.add("questions", question("c_q1", "Did the replacement part arrive?"), "Did the replacement part arrive?")
    b.answer("c_q1", "Yes, it arrived this morning.")
    document = b.build()
    document["approved_decision"]["question_answers"][0]["answer_text"] = "Yes, and we accept the USD 500.00 surcharge."
    return document
