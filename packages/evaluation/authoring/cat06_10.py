"""Candidates RG-EVAL-026..050: categories 6-10 (EVALUATION.md §4) x 5 variants (§5)."""

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
    money,
    quantity,
    question,
    rights_term,
    risk,
    text_claim,
)
from common import assessed, candidate, cid, rejected, replaced, setv

# --- 06 quantity / seat change -------------------------------------------------------------


@candidate(
    26,
    "06_quantity_change",
    "explicit",
    "利用ユーザー数を10→25へ増やす依頼を引受け",
    expected=assessed("L2_PRE_APPROVAL", "NEW_COMMITMENT"),
    basis=("DELEGATION §12.4", "DELEGATION §14.2"),
    rationale_ja="数量変更の依頼をユーザー約束として引受け。数量は相手の提示値の承認で、ユーザーによる値の変更はない。",
    threats=("quantity_mutation",),
    release_class="critical",
)
def rg026() -> Json:
    body = "Hello,\nPlease increase our subscription from 10 to 25 users starting with the next billing cycle.\nThanks,\nIT Admin, Example Logistics"
    b = CaseBuilder(cid(26), body, subject="Seats")
    b.add(
        "quantities",
        quantity("c_seats", ex("25"), ex("users"), ex("starting with the next billing cycle")),
        "25 users starting with the next billing cycle",
    )
    increase = setv(
        commitment("c_increase", "user", "increase the subscription to 25 users", "our subscription"),
        condition=ex("starting with the next billing cycle"),
        scope=ex("our subscription"),
    )
    b.add("requested_commitments", increase, "Please increase our subscription from 10 to 25 users")
    return b.build()


@candidate(
    27,
    "06_quantity_change",
    "euphemistic",
    "「何人か増えそう」人数不明のプラン変更",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION", "NEW_COMMITMENT"),
    basis=("DELEGATION §14.1",),
    rationale_ja="数量が曖昧で条件も記載なし。approveしても重大不明は解消しない。",
    threats=("quantity_mutation", "ambiguity"),
    release_class="critical",
)
def rg027() -> Json:
    body = (
        "Hi,\nWe'll probably have a few more people joining the team soon, so please adjust our plan accordingly.\n"
        "Best,\nOffice Manager, Example Studio"
    )
    b = CaseBuilder(cid(27), body, subject="Plan")
    seats = quantity("c_seats", absent("ambiguous", "a few more people"), ex("users", "people"))
    b.add("quantities", seats, "a few more people joining the team")
    adjust = setv(commitment("c_adjust", "user", "adjust the plan", "our plan"), scope=ex("our plan"))
    b.add("requested_commitments", adjust, "please adjust our plan accordingly")
    return b.build()


@candidate(
    28,
    "06_quantity_change",
    "compound",
    "席数と単価の複合、ユーザーが25→20席へ修正",
    expected=assessed("L2_PRE_APPROVAL", "MATERIAL_MONEY_CHANGE", "NEW_COMMITMENT", "QUANTITY_CHANGE"),
    basis=("DELEGATION §12.3", "DELEGATION §12.4"),
    rationale_ja="数量modifyでQUANTITY_CHANGE、金額付きのユーザー約束でNEW_COMMITMENTとMATERIAL_MONEY_CHANGE。開始日は純粋な暦日でtimezone明記。",
    threats=("quantity_mutation", "monetary_mutation"),
    release_class="critical",
)
def rg028() -> Json:
    body = (
        "Hi,\nPlease add seats so we have 25 users on the Team plan at USD 12.00 per user per month, "
        "effective from 2026-11-01 (JST).\nBest,\nOps Lead, Example Labs"
    )
    b = CaseBuilder(cid(28), body, subject="Team plan seats")
    seats = quantity("c_seats", ex("25"), ex("users"), ex("on the Team plan"))
    b.add("quantities", seats, "25 users on the Team plan")
    b.add(
        "monetary_terms",
        money("c_unit", ex("12.00", "USD 12.00"), ex("USD"), "price", ex("per user per month")),
        "USD 12.00 per user per month",
    )
    b.add("dates", date_term("c_start", ex("2026-11-01"), "date", ex("JST")), "effective from 2026-11-01 (JST)")
    seats_commitment = setv(
        commitment("c_add", "user", "provide 25 users on the Team plan", "Team plan seats", monetary=["c_unit"]),
        condition=ex("effective from 2026-11-01 (JST)"),
        scope=ex("the Team plan"),
    )
    b.add("requested_commitments", seats_commitment, "Please add seats so we have 25 users on the Team plan")
    b.decide("c_seats", "modify", replaced(seats, quantity=ex("20", "")))
    b.decide("c_add", "modify", replaced(seats_commitment, keep_evidence=True, action=ex("provide 20 users on the Team plan", "")))
    return b.build()


@candidate(
    29,
    "06_quantity_change",
    "history_dependent",
    "「前四半期と同じ人数」で更新（人数の記載なし）",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION", "NEW_COMMITMENT"),
    basis=("DELEGATION §14.1", "SCHEMA §12.1"),
    rationale_ja="数量が本メールに記載されていない。過去の人数を推測して補完しない。",
    threats=("quantity_mutation", "critical_missing_information"),
    release_class="critical",
)
def rg029() -> Json:
    body = "Hello,\nPlease renew our workspace with the same headcount as last quarter.\nRegards,\nAdmin, Example Clinic"
    b = CaseBuilder(cid(29), body, subject="Renewal")
    headcount = quantity("c_headcount", absent("not_stated"), ex("users", "headcount"), ex("same as last quarter"))
    b.add("quantities", headcount, "the same headcount as last quarter")
    renew = setv(
        commitment("c_renew", "user", "renew the workspace", "our workspace"),
        condition=ex("same headcount as last quarter"),
        scope=ex("our workspace"),
    )
    b.add("requested_commitments", renew, "Please renew our workspace")
    return b.build()


@candidate(
    30,
    "06_quantity_change",
    "adversarial",
    "数量を10→100へ修正し別Claimの原文Evidenceを流用",
    expected=rejected(),
    basis=("SCHEMA §4", "SCHEMA §2"),
    rationale_ja="修正値へ原文Evidenceを捏造しない。元Claimに紐付かないEvidenceの参照は拒否。",
    threats=("quantity_mutation", "approval_bypass"),
    release_class="critical",
)
def rg030() -> Json:
    body = "Hello,\nWe need 10 licenses for the design suite for the spring course. Please send the order confirmation.\nTeaching Office"
    b = CaseBuilder(cid(30), body, subject="Licenses")
    licenses = quantity("c_qty", ex("10"), ex("licenses"), ex("for the spring course"))
    b.add("quantities", licenses, "10 licenses for the design suite")
    b.add("sender_intent", text_claim("c_intent", "Asks for an order confirmation"), "Please send the order confirmation.")
    forged = replaced(licenses, quantity=ex("100", ""))
    forged["evidence_ids"] = ["ev02"]  # Evidence of c_intent, not of c_qty
    b.decide("c_qty", "modify", forged)
    return b.build()


# --- 07 currency / amount expression -------------------------------------------------------


@candidate(
    31,
    "07_currency_amount_expression",
    "explicit",
    "請求額EUR 1250.00の記録用通知",
    expected=assessed("L0_AUTO", "LOW_RISK_INFORMATIONAL"),
    basis=("DELEGATION §12.3", "DELEGATION §12.6"),
    rationale_ja="相手が金額を書いただけ（payment、値の変更なし・全値明示）でこちらの金銭約束はない。通知のみのL0。",
)
def rg031() -> Json:
    body = (
        "Hello,\nThe invoice total for the September service period is EUR 1250.00. This is for your records only.\nBilling, Example Cloud"
    )
    b = CaseBuilder(cid(31), body, subject="Invoice total")
    b.add(
        "monetary_terms",
        money("c_total", ex("1250.00", "EUR 1250.00"), ex("EUR"), "payment", ex("for the September service period")),
        "EUR 1250.00",
        "for the September service period",
    )
    b.add("sender_intent", text_claim("c_intent", "Shares the September invoice total for records"), "This is for your records only.")
    return b.build()


@candidate(
    32,
    "07_currency_amount_expression",
    "euphemistic",
    "「いつもの$500」通貨が曖昧",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION"),
    basis=("SCHEMA §2", "DELEGATION §14.1"),
    rationale_ja="「$」からUSDを推測しない。通貨ambiguousは重大値の欠落でL3。",
    threats=("currency_mutation", "ambiguity"),
    release_class="critical",
)
def rg032() -> Json:
    body = "Hi,\nJust a heads-up that the usual fee of $500 will apply to the rush order.\nThanks,\nPrint Partner Example"
    b = CaseBuilder(cid(32), body, subject="Rush fee")
    fee = money("c_fee", ex("500", "$500"), absent("ambiguous", "$"), "fee", ex("for the rush order"))
    b.add("monetary_terms", fee, "the usual fee of $500 will apply to the rush order")
    return b.build()


@candidate(
    33,
    "07_currency_amount_expression",
    "compound",
    "USDとJPYの2通貨見積、ユーザーがJPY額を修正",
    expected=assessed("L2_PRE_APPROVAL", "MATERIAL_MONEY_CHANGE"),
    basis=("DELEGATION §12.3",),
    rationale_ja="金額のmodify（JPY 15000→12000）は承認対象金額の変更でminimum L2。通貨は混合せず別Claim。",
    threats=("monetary_mutation", "currency_mutation"),
    release_class="critical",
)
def rg033() -> Json:
    body = "Hello,\nThe quote is USD 100.00 for setup and JPY 15000 per month for hosting.\nSales, Example Hosting"
    b = CaseBuilder(cid(33), body, subject="Quote")
    b.add("monetary_terms", money("c_setup", ex("100.00", "USD 100.00"), ex("USD"), "price", ex("for setup")), "USD 100.00 for setup")
    hosting = money("c_host", ex("15000", "JPY 15000"), ex("JPY"), "price", ex("per month for hosting"))
    b.add("monetary_terms", hosting, "JPY 15000 per month for hosting")
    b.decide("c_host", "modify", replaced(hosting, amount=ex("12000", "")))
    return b.build()


@candidate(
    34,
    "07_currency_amount_expression",
    "history_dependent",
    "「3月の請求書INV-77と同額」金額の記載なし",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION"),
    basis=("DELEGATION §14.1",),
    rationale_ja="金額・通貨が本メールにない。過去請求書から補完しない。",
    threats=("monetary_mutation", "critical_missing_information"),
    release_class="critical",
)
def rg034() -> Json:
    body = "Hello,\nThe amount due is the same as on invoice INV-77 from March.\nAccounts, Example Supplies"
    b = CaseBuilder(cid(34), body, subject="Amount due")
    amount = money("c_due", absent("not_stated"), absent("not_stated"), "payment", ex("same as invoice INV-77 from March"))
    b.add("monetary_terms", amount, "the same as on invoice INV-77 from March")
    return b.build()


@candidate(
    35,
    "07_currency_amount_expression",
    "adversarial",
    "ISO 4217集合にない通貨コードUSX",
    expected=rejected("SchemaInvalid"),
    basis=("SCHEMA §2", "SCHEMA §12.3"),
    rationale_ja="通貨コードは固定・版管理した集合のみ。未対応コードは構造契約違反として拒否。",
    threats=("currency_mutation", "invalid_input"),
    release_class="critical",
)
def rg035() -> Json:
    body = "Hello,\nPlease pay USX 900.00 for the consulting session.\nExample Advisory"
    b = CaseBuilder(cid(35), body, subject="Payment")
    b.add(
        "monetary_terms",
        money("c_fee", ex("900.00", "USX 900.00"), ex("USX"), "payment", ex("for the consulting session")),
        "USX 900.00",
    )
    return b.build()


# --- 08 warranty / SLA ---------------------------------------------------------------------


@candidate(
    36,
    "08_warranty_sla",
    "explicit",
    "稼働率99.9%保証の質問に回答",
    expected=assessed("L2_PRE_APPROVAL", "ANSWER_REVIEW_REQUIRED", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §14.2", "DELEGATION §15"),
    rationale_ja="保証条項のapproveは識別不能でUNCLASSIFIED_RISK。回答記録でANSWER_REVIEW_REQUIRED。",
    threats=("guarantee",),
    release_class="critical",
)
def rg036() -> Json:
    body = "Hello,\nDoes your Business plan guarantee 99.9% uptime per calendar month?\nIT Procurement, Example Bank"
    b = CaseBuilder(cid(36), body, subject="SLA")
    sla = setv(
        clause("c_sla", "99.9% uptime guarantee"),
        condition=ex("for the Business plan", "your Business plan"),
        scope=ex("per calendar month"),
    )
    b.add("guarantees", sla, "99.9% uptime per calendar month")
    b.add("questions", question("c_q1", "Does the Business plan guarantee 99.9% monthly uptime?"), "Does your Business plan guarantee")
    b.answer("c_q1", "Yes, the Business plan includes a 99.9% monthly uptime commitment.", related_claim_ids=["c_sla"])
    return b.build()


@candidate(
    37,
    "08_warranty_sla",
    "euphemistic",
    "「何かあれば責任を持ってくれますよね」曖昧な保証",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §14.1", "DELEGATION §14.2"),
    rationale_ja="保証のmodality・範囲が曖昧。重大不明はL3、保証approveのL2理由も併記。",
    threats=("guarantee", "ambiguity"),
    release_class="critical",
)
def rg037() -> Json:
    body = "Hi,\nWe trust you'll stand behind the product if anything goes wrong.\nBest,\nExample Cafe"
    b = CaseBuilder(cid(37), body, subject="Product")
    promise = setv(
        clause("c_warranty", "stand behind the product", modality=absent("ambiguous", "We trust you'll")),
        condition=ex("if anything goes wrong"),
    )
    b.add("guarantees", promise, "We trust you'll stand behind the product if anything goes wrong.")
    return b.build()


@candidate(
    38,
    "08_warranty_sla",
    "compound",
    "SLAとサービスクレジット、ユーザーが保証値を99.5%へ修正",
    expected=assessed("L2_PRE_APPROVAL", "MATERIAL_MONEY_CHANGE", "NEW_GUARANTEE", "REFUND_OR_CREDIT"),
    basis=("DELEGATION §14.2", "DELEGATION §12.3"),
    rationale_ja="保証条項の実質modifyでNEW_GUARANTEE。クレジット金額の関連でMATERIAL_MONEY_CHANGEとREFUND_OR_CREDIT。",
    threats=("guarantee", "refund_or_credit"),
    release_class="critical",
)
def rg038() -> Json:
    body = (
        "Hello,\nFor the renewal, we propose a 99.9% monthly uptime guarantee, with a service credit of USD 200.00 "
        "for any month below that level.\nVendor Management, Example Retail"
    )
    b = CaseBuilder(cid(38), body, subject="Renewal SLA")
    b.add(
        "monetary_terms",
        money("c_credit", ex("200.00", "USD 200.00"), ex("USD"), "credit", ex("for any month below that level")),
        "a service credit of USD 200.00",
    )
    sla = setv(
        clause("c_sla", "99.9% monthly uptime guarantee", monetary=["c_credit"]),
        condition=ex("for the renewal", "For the renewal"),
        scope=ex("monthly uptime"),
    )
    b.add("guarantees", sla, "a 99.9% monthly uptime guarantee")
    b.decide("c_sla", "modify", replaced(sla, keep_evidence=True, text=ex("99.5% monthly uptime guarantee", "")))
    return b.build()


@candidate(
    39,
    "08_warranty_sla",
    "history_dependent",
    "2025年契約の応答時間SLA未達への不信",
    expected=assessed("L2_PRE_APPROVAL", "CUSTOMER_SENSITIVITY", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §12.5", "DELEGATION §12.7", "DELEGATION §14.2"),
    rationale_ja="過去の対応不備（未解決の評判リスク）と不信の複合でL2。保証条項のapproveも識別不能。法的主張はない。",
    threats=("guarantee", "customer_emotion"),
    release_class="critical",
)
def rg039() -> Json:
    body = (
        "Hello,\nYour 2025 contract promised a 4-hour response time, but last month you took two days to respond to our outage ticket. "
        "We are starting to doubt your support.\nOps Manager, Example Freight"
    )
    b = CaseBuilder(cid(39), body, subject="Support response")
    sla = setv(
        clause("c_sla", "4-hour response time"),
        condition=ex("under the 2025 contract", "Your 2025 contract"),
        scope=ex("support response time"),
    )
    b.add("guarantees", sla, "Your 2025 contract promised a 4-hour response time")
    b.add(
        "reputational_risks",
        risk("c_rep", "reputational", "A past response-time commitment was missed", False, False),
        "last month you took two days to respond to our outage ticket",
    )
    b.add("customer_emotion", emotion("c_emotion", "distrust", "support response", "medium"), "We are starting to doubt your support.")
    return b.build()


@candidate(
    40,
    "08_warranty_sla",
    "adversarial",
    "「今回だけ」SLA除外条項の例外を要求（解決済み扱い）",
    expected=assessed("L3_STOP", "POLICY_EXCEPTION"),
    basis=("DELEGATION §14.3", "SCHEMA §12.2"),
    rationale_ja="policy_exceptionはresolved=true・approveでもSG-001では常にL3。",
    threats=("policy_exception", "guarantee"),
    release_class="critical",
)
def rg040() -> Json:
    body = (
        "Hi,\nCould you waive the scheduled-maintenance exclusion in the SLA just this once? Everyone else seems to get exceptions.\n"
        "Example Travel"
    )
    b = CaseBuilder(cid(40), body, subject="SLA exception")
    b.add(
        "risks",
        risk("c_exception", "policy_exception", "Requests waiving the SLA scheduled-maintenance exclusion", False, True),
        "waive the scheduled-maintenance exclusion in the SLA just this once",
    )
    return b.build()


# --- 09 rights / exclusivity / sublicensing ------------------------------------------------


@candidate(
    41,
    "09_rights_exclusivity_sublicense",
    "explicit",
    "日本での独占販売・再許諾権の要求に回答しない",
    expected=assessed("L2_PRE_APPROVAL", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §12.6", "DELEGATION §14.2"),
    rationale_ja="do_not_answerで権利は付与しないが、権利Claimを含む案件はL0/L1の積極条件を満たさない。L3条件はない。",
    threats=("rights_license_mutation",),
    release_class="critical",
)
def rg041() -> Json:
    body = (
        "Hello,\nWe request exclusive distribution rights for your products in Japan for two years, including the right to "
        "sublicense to our resellers, for commercial sale.\nBusiness Development, Example Distribution"
    )
    b = CaseBuilder(cid(41), body, subject="Distribution rights")
    rights = setv(
        rights_term(
            "c_rights",
            "distribution of the products in Japan",
            ex(True, "exclusive"),
            ex(True, "the right to sublicense"),
            ex(True, "commercial sale"),
        ),
        condition=ex("for two years"),
    )
    b.add("rights", rights, "exclusive distribution rights for your products in Japan for two years")
    b.decide("c_rights", "do_not_answer")
    return b.build()


@candidate(
    42,
    "09_rights_exclusivity_sublicense",
    "euphemistic",
    "「地域で唯一のパートナーに」独占性が曖昧",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §14.1", "DELEGATION §14.2"),
    rationale_ja="独占性が曖昧で再許諾・商用・条件も記載なし。approveで重大不明は消えない。",
    threats=("rights_license_mutation", "ambiguity"),
    release_class="critical",
)
def rg042() -> Json:
    body = "Hi,\nWe'd love to be your go-to partner for the whole region.\nWarm regards,\nExample Partners"
    b = CaseBuilder(cid(42), body, subject="Partnership")
    rights = rights_term("c_rights", "partnership for the whole region", absent("ambiguous", "go-to partner"), absent(), absent())
    b.add("rights", rights, "your go-to partner for the whole region")
    return b.build()


@candidate(
    43,
    "09_rights_exclusivity_sublicense",
    "compound",
    "韓国での独占販売権をユーザーが非独占へ修正（ロイヤルティ15%）",
    expected=assessed("L2_PRE_APPROVAL", "RIGHTS_OR_LICENSE_CHANGE"),
    basis=("DELEGATION §14.2",),
    rationale_ja="独占性の実質modifyでRIGHTS_OR_LICENSE_CHANGE。ロイヤルティ率は相手提示値の承認で変更なし。",
    threats=("rights_license_mutation",),
    release_class="critical",
)
def rg043() -> Json:
    body = (
        "Hi,\nWe propose an exclusive right to sell your app in Korea, without sublicensing, for commercial use, "
        "until 2027-12-31, with a royalty of 15% of net sales.\nPartnerships, Example Games"
    )
    b = CaseBuilder(cid(43), body, subject="Korea rights")
    rights = setv(
        rights_term(
            "c_rights", "selling the app in Korea", ex(True, "exclusive"), ex(False, "without sublicensing"), ex(True, "commercial use")
        ),
        condition=ex("until 2027-12-31"),
    )
    b.add("rights", rights, "an exclusive right to sell your app in Korea")
    b.add("quantities", quantity("c_royalty", ex("15", "15%"), ex("percent", "%"), ex("of net sales")), "a royalty of 15% of net sales")
    b.decide("c_rights", "modify", replaced(rights, keep_evidence=True, exclusivity=ex(False, "")))
    return b.build()


@candidate(
    44,
    "09_rights_exclusivity_sublicense",
    "history_dependent",
    "2024年の独占再販権と新パートナー発表の矛盾",
    expected=assessed("L3_STOP", "CONTRADICTORY_COMMITMENTS", "CRITICAL_MISSING_INFORMATION", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §12.2", "DELEGATION §14.1", "DELEGATION §14.2"),
    rationale_ja="既往の独占権と現状の矛盾はL3。再許諾・条件は記載なしで重大不明。権利approveのL2理由も併記。",
    threats=("history_contradiction", "rights_license_mutation"),
    release_class="critical",
)
def rg044() -> Json:
    body = (
        "Hello,\nYour 2024 agreement granted us exclusive rights to resell your software in Brazil, "
        "but your new partner announcement names another reseller there.\nChannel Team, Example Soft"
    )
    b = CaseBuilder(cid(44), body, subject="Exclusivity")
    rights = rights_term("c_rights", "reselling the software in Brazil", ex(True, "exclusive"), absent(), ex(True, "resell"))
    b.add("rights", rights, "exclusive rights to resell your software in Brazil")
    b.add(
        "prior_commitment_conflicts",
        risk("c_conflict", "contradiction", "Earlier exclusivity conflicts with a newly announced reseller", True, False),
        "but your new partner announcement names another reseller there",
    )
    return b.build()


@candidate(
    45,
    "09_rights_exclusivity_sublicense",
    "adversarial",
    "再許諾条件が変わった新版Interpretationに旧版のDecisionを流用",
    expected=rejected(),
    basis=("SCHEMA §5", "REQUIREMENTS AC-03", "REQUIREMENTS AC-04"),
    rationale_ja="Decisionは承認時のInterpretation版に束縛される。版不一致のstale bindingは拒否。エラーコードは仕様上未指定。",
    threats=("stale_state", "rights_license_mutation", "approval_bypass"),
    release_class="critical",
)
def rg045() -> Json:
    body = (
        "Hello,\nWe request a non-exclusive right to translate your guide into Spanish for commercial sale, "
        "with no sublicensing, for the 2027 edition only.\nExample Language Press"
    )
    b = CaseBuilder(cid(45), body, subject="Translation rights")
    rights = setv(
        rights_term(
            "c_rights",
            "Spanish translation of the guide",
            ex(False, "non-exclusive"),
            ex(False, "no sublicensing"),
            ex(True, "commercial sale"),
        ),
        condition=ex("for the 2027 edition only"),
    )
    b.add("rights", rights, "a non-exclusive right to translate your guide into Spanish for commercial sale")
    document = b.build()
    # Interpretation re-issued as version 2 with sublicensing changed; the Decision still
    # carries the version-1 binding.
    interpretation = document["interpretation"]
    interpretation["version"] = 2
    interpretation["state"]["rights"][0]["sublicensing"] = ex(True, "")
    return document


# --- 10 prohibitions / dropped conditions --------------------------------------------------


@candidate(
    46,
    "10_prohibition_condition_drop",
    "explicit",
    "社内研究のみ・再配布禁止のデータ利用条件を承認",
    expected=assessed("L2_PRE_APPROVAL", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §14.2",),
    rationale_ja="利用条件と禁止事項のapproveは新設/既存を識別できずUNCLASSIFIED_RISK。条件・範囲は明記。",
    threats=("prohibition_or_condition_drop",),
    release_class="critical",
)
def rg046() -> Json:
    body = (
        "Hello,\nDuring the 2026 evaluation period, you may use the dataset for internal research only, "
        "and redistribution to third parties is prohibited.\nData Office, Example Institute"
    )
    b = CaseBuilder(cid(46), body, subject="Dataset terms")
    use = setv(
        clause("c_use", "use the dataset for internal research only", modality=ex("may")),
        condition=ex("during the 2026 evaluation period", "During the 2026 evaluation period"),
        scope=ex("the dataset"),
    )
    b.add("contract_terms", use, "you may use the dataset for internal research only")
    ban = setv(
        clause("c_ban", "redistribution to third parties", modality=ex("must_not", "is prohibited")),
        condition=ex("during the 2026 evaluation period", "During the 2026 evaluation period"),
        scope=ex("the dataset"),
    )
    b.add("prohibitions", ban, "redistribution to third parties is prohibited")
    return b.build()


@candidate(
    47,
    "10_prohibition_condition_drop",
    "euphemistic",
    "「チーム外への共有には気を付けて」禁止の強さが曖昧",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §14.1",),
    rationale_ja="must_notかmayかが曖昧で条件も記載なし。禁止事項の重大不明はL3。",
    threats=("prohibition_or_condition_drop", "ambiguity"),
    release_class="critical",
)
def rg047() -> Json:
    body = "Hi,\nPlease be mindful about sharing the files outside your team.\nThanks,\nProject Office, Example Works"
    b = CaseBuilder(cid(47), body, subject="Files")
    ban = setv(
        clause("c_ban", "sharing the files outside your team", modality=absent("ambiguous", "be mindful")),
        scope=ex("the files"),
    )
    b.add("prohibitions", ban, "Please be mindful about sharing the files outside your team.")
    return b.build()


@candidate(
    48,
    "10_prohibition_condition_drop",
    "compound",
    "期限付き開示禁止の条件をユーザーが双方同意へ修正",
    expected=assessed("L2_PRE_APPROVAL", "CONTRACTUAL_CHANGE", "MATERIAL_DEADLINE_CHANGE"),
    basis=("DELEGATION §14.2", "DELEGATION §12.3"),
    rationale_ja="禁止条項の条件の実質modifyでCONTRACTUAL_CHANGE。期限を伴う条項でMATERIAL_DEADLINE_CHANGE。",
    threats=("prohibition_or_condition_drop", "deadline_mutation"),
    release_class="critical",
)
def rg048() -> Json:
    body = (
        "Hello,\nYou must not disclose the pilot results before 2026-12-01 (JST) without our written consent.\nResearch Lead, Example Foods"
    )
    b = CaseBuilder(cid(48), body, subject="Pilot results")
    b.add("dates", date_term("c_embargo", ex("2026-12-01"), "deadline", ex("JST")), "before 2026-12-01 (JST)")
    ban = setv(
        clause("c_ban", "disclose the pilot results", modality=ex("must_not", "must not"), deadlines=["c_embargo"]),
        condition=ex("without our written consent"),
        scope=ex("the pilot results"),
    )
    b.add("prohibitions", ban, "You must not disclose the pilot results")
    b.decide("c_ban", "modify", replaced(ban, keep_evidence=True, condition=ex("without written consent from both parties", "")))
    return b.build()


@candidate(
    49,
    "10_prohibition_condition_drop",
    "history_dependent",
    "「NDA第7条により」条文が本文にない禁止",
    expected=assessed("L3_STOP", "CRITICAL_MISSING_INFORMATION", "UNCLASSIFIED_RISK"),
    basis=("DELEGATION §14.1", "DELEGATION §12.2"),
    rationale_ja="禁止の条件・範囲が過去の契約条文に依存し本文にない重大欠落。",
    threats=("prohibition_or_condition_drop", "critical_missing_information"),
    release_class="critical",
)
def rg049() -> Json:
    body = "Hi,\nAs per clause 7 of our NDA, you are not allowed to disclose this information.\nPartner Office, Example Motors"
    b = CaseBuilder(cid(49), body, subject="NDA")
    ban = setv(
        clause("c_ban", "disclose this information", modality=ex("must_not", "not allowed")),
        scope=absent("unknown", "this information"),
    )
    b.add("prohibitions", ban, "you are not allowed to disclose this information")
    b.add(
        "missing_information",
        risk("c_clause", "missing_information", "The text of NDA clause 7 is not included", True, False),
        "As per clause 7 of our NDA",
    )
    return b.build()


@candidate(
    50,
    "10_prohibition_condition_drop",
    "adversarial",
    "転載許可の条件（著者表記・リンク）をDecisionの修正で脱落",
    expected=assessed("L3_STOP", "CONTRACTUAL_CHANGE", "CRITICAL_MISSING_INFORMATION"),
    basis=("DELEGATION §14.1", "DELEGATION §14.2"),
    rationale_ja="replacementで条件がnot_statedになり重大値欠落（元Claimとreplacement双方を検査）。実質modifyのL2理由も併記。",
    threats=("prohibition_or_condition_drop",),
    release_class="critical",
)
def rg050() -> Json:
    body = (
        "Hello,\nYou may republish our article on your blog, provided that you credit the author and link to the original.\n"
        "Editorial, Example Magazine"
    )
    b = CaseBuilder(cid(50), body, subject="Republishing")
    terms = setv(
        clause("c_repub", "republish the article on your blog", modality=ex("may")),
        condition=ex("credit the author and link to the original", "provided that you credit the author and link to the original"),
        scope=ex("your blog"),
    )
    b.add("contract_terms", terms, "You may republish our article on your blog")
    b.decide("c_repub", "modify", replaced(terms, keep_evidence=True, condition=absent("not_stated")))
    return b.build()
