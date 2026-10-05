"""Japanese display labels (IMPLEMENTATION.md §11: never claim "safe"; show reasons with levels)."""

from __future__ import annotations

LEVEL_LABELS: dict[str, str] = {
    "L0_AUTO": "AIに任せられる候補（いまは自動では送りません）",
    "L1_POST_REVIEW": "AI＋事後確認の候補（いまは自動では送りません）",
    "L2_PRE_APPROVAL": "送る前にあなたの承認が必要",
    "L3_STOP": "AIでは扱えません（手動で対応）",
}

# Short form for the case list, where the full label does not fit in a column.
LEVEL_SHORT: dict[str, str] = {
    "L0_AUTO": "AI候補",
    "L1_POST_REVIEW": "AI＋事後確認",
    "L2_PRE_APPROVAL": "承認が必要",
    "L3_STOP": "AI停止・手動対応",
}

STATE_LABELS: dict[str, str] = {
    "INPUT_READY": "取り込み済み",
    "DECISION_REQUIRED": "判断待ち",
    "DELEGATION_ASSESSED": "返信案の作成待ち",
    "SAFE_CANDIDATE": "検査済み・承認待ち",
    "BLOCKED": "検査で停止（修正が必要）",
    "FINAL_APPROVED": "承認済み・コピー待ち",
    "COPIED": "コピー済み",
    "STOPPED": "手動で対応",
}

REASON_LABELS: dict[str, str] = {
    "LEGAL_CLAIM": "法的主張がある",
    "UNRESOLVED_PROMPT_INJECTION": "未解決のプロンプトインジェクションの疑い",
    "CRITICAL_MISSING_INFORMATION": "重大な値が不明・曖昧",
    "ATTACHMENT_REQUIRED_MISSING": "必要な添付が未確認",
    "CONTRADICTORY_COMMITMENTS": "約束が矛盾している",
    "CRITICAL_DIFF": "返信とDecisionに重大な差異",
    "REFUND_OR_CREDIT": "返金・クレジット",
    "CONTRACTUAL_CHANGE": "契約条件の変更",
    "RIGHTS_OR_LICENSE_CHANGE": "権利・ライセンスの変更",
    "NEW_GUARANTEE": "新しい保証",
    "MATERIAL_MONEY_CHANGE": "金額・通貨の新設/変更",
    "MATERIAL_DEADLINE_CHANGE": "期限の新設/変更",
    "QUANTITY_CHANGE": "数量の新設/変更",
    "PERSONAL_DATA_DISCLOSURE": "個人情報の開示",
    "NEW_COMMITMENT": "新しい約束",
    "POLICY_EXCEPTION": "ポリシー例外",
    "CUSTOMER_SENSITIVITY": "顧客感情への配慮が必要",
    "LOW_RISK_INFORMATIONAL": "既知情報の回答・受領確認のみ",
    "LOW_RISK_POST_REVIEW": "文体・感情配慮のみ",
    "UNCLASSIFIED_RISK": "分類できないリスク",
    "ANSWER_REVIEW_REQUIRED": "回答内容の確認が必要",
    "INVALID_INPUT": "入力不正",
    "INCOMPLETE_PIPELINE": "検査が完了していない",
    "STALE_STATE": "古い状態",
    "VERIFIER_BLOCK": "検査による停止",
}

FINDING_LABELS: dict[str, str] = {
    "amount_changed": "金額の差異",
    "currency_changed": "通貨の差異・不確定",
    "date_changed": "日付・期限の差異・不確定",
    "quantity_changed": "数量の差異",
    "right_changed": "権利の差異",
    "license_changed": "ライセンスの追加・差異",
    "guarantee_added": "保証の追加",
    "refund_added": "返金・補償の追加",
    "commitment_added": "約束の追加",
    "prohibition_removed": "禁止事項の削除",
    "required_answer_missing": "必要な回答の欠落",
    "condition_removed": "条件の欠落",
    "ambiguity_resolved_without_authority": "権限なしの曖昧さ解消",
    "attachment_dependency": "添付依存",
    "prompt_injection_risk": "プロンプトインジェクションの疑い",
    "unsupported_claim": "承認されていない記述",
    "state_mismatch": "承認内容の欠落・改変",
    "customer_emotion_missed": "感情への配慮不足",
    "legal_claim_detected": "法的表現",
    "delegation_level_too_low": "委任レベルが低すぎる",
}

SEVERITY_LABELS: dict[str, str] = {"critical": "重大", "high": "高", "medium": "中", "low": "低"}

ARRAY_LABELS: dict[str, str] = {
    "sender_intent": "相手の意図",
    "requests": "依頼",
    "questions": "質問",
    "monetary_terms": "金額",
    "dates": "日付・期限",
    "quantities": "数量",
    "contract_terms": "契約条件",
    "prohibitions": "禁止事項",
    "guarantees": "保証",
    "refund_terms": "返金条件",
    "cancellation_terms": "解約条件",
    "license_terms": "ライセンス",
    "rights": "権利",
    "requested_commitments": "求められている約束",
    "commitments": "約束",
    "personal_data": "個人情報",
    "customer_emotion": "顧客感情",
    "legal_claims": "法的主張",
    "reputational_risks": "評判リスク",
    "prior_commitment_conflicts": "過去の約束との矛盾",
    "risks": "リスク",
    "ambiguities": "曖昧さ",
    "missing_information": "不足情報",
    "attachment_dependencies": "添付依存",
    "prompt_injection_risks": "インジェクションの疑い",
    "recommended_actions": "推奨対応",
}

DECISION_LABELS: dict[str, str] = {"approve": "承認する", "unknown": "保留（不明）", "do_not_answer": "回答しない"}

# What the operator should actually do next. Findings say what is wrong; these say what to do,
# because the target user has no colleague to ask (README: 限界 / handoff §4.1).
NEXT_ACTIONS: dict[str, str] = {
    "amount_changed": "その金額をDecisionで承認するか、返信から金額を外してください。承認できない金額は送れません。",
    "currency_changed": "通貨をISOコード（USD/EUR/JPY等）で承認し直してください。「$」だけでは通貨を特定できません。",
    "date_changed": "日付を年月日とタイムゾーンまで決めて承認してください。「tomorrow」「next week」のような書き方は送れません。",
    "quantity_changed": "その数量をDecisionの承認済み項目として追加してください。",
    "right_changed": "権利の範囲をDecisionで承認し直してください。",
    "license_changed": "ライセンスに関する記述は、承認済みのライセンス項目がない限り送れません。文を外してください。",
    "guarantee_added": "保証の表現（guarantee / ensure / 100% など）を外すか、保証内容をDecisionで承認してください。",
    "refund_added": "返金・クレジットの記述を外すか、金額と条件をDecisionで承認してください。",
    "commitment_added": "新しい約束を書かないでください。約束する場合は、Decisionで承認してから作り直してください。",
    "prohibition_removed": "「しない」と承認した内容が返信から消えています。元の否定表現を戻してください。",
    "required_answer_missing": "回答が必要な質問に、英語の回答文を入力してください。",
    "condition_removed": "承認済みの条件（〜の場合に限る等）が返信から抜けています。条件を戻してください。",
    "ambiguity_resolved_without_authority": "曖昧なままの項目を、あなたが値を決めて承認するか、回答しない扱いにしてください。",
    "attachment_dependency": "添付の内容に依存する返信です。添付を自分で確認し、メールは手動で書いてください。",
    "prompt_injection_risk": "相手のメールにAIへの指示文が含まれています。AIで返信せず、手動で対応してください。",
    "unsupported_claim": "承認していない記述（数値・リンク等）が含まれています。その部分を外してください。",
    "state_mismatch": "承認した内容が返信から欠けているか、書き換えられています。返信案を作り直してください。",
    "customer_emotion_missed": "相手が強い不満を示しています。お詫びの一文を入れるか、このまま進めるかを選んでください（停止はしません）。",
    "legal_claim_detected": "法的措置に関する表現があります。AIで返信せず、必要なら専門家に相談してください。",
    "delegation_level_too_low": "判定レベルが内容に対して低すぎます。Decisionを見直してください。",
}

LEVEL_NEXT_ACTIONS: dict[str, str] = {
    "L3_STOP": "この案件はAIで返信を作れません。原文を自分で読み、手動で返信するか、返信しないかを決めてください。",
    "L2_PRE_APPROVAL": "内容を確認し、問題がなければ最終承認してからコピーしてください。",
    "L1_POST_REVIEW": "内容を確認し、問題がなければ最終承認してからコピーしてください。",
    "L0_AUTO": "内容を確認し、問題がなければ最終承認してからコピーしてください。",
}

# After the final approval the next action follows the case state, not the level (E2E 0.1.0 #6).
STATE_NEXT_ACTIONS: dict[str, str] = {
    "FINAL_APPROVED": "本文をコピーし、ご自身のメールソフトに貼り付けて送ってください。",
    "COPIED": "コピー済みです。送信はご自身のメールソフトで行ってください。",
}

# A stop names what to fix by section title, never by screen position (E2E 0.1.0 #7). Whether the
# reply is the operator's edit is shown only as context: the cause is always the findings below,
# which may be something added or something approved that went missing (ruling 2026-09-26, 0.1.2).
STOP_AFTER_EDIT = (
    "検査で停止しました。あなたが編集した返信本文と、下の指摘・それぞれの「対応」を確認してください。"
    "必要な内容を戻し（または不要な記述を外し）、「編集内容で再検査」を押すか、「英語の返信案を作って検査する」で作り直してください。"
    "内容そのものを変える場合は、「1. 相手の要求と、あなたの判断」を見直してください。"
)
STOP_AFTER_GENERATE = (
    "検査で停止しました。まず下の指摘と、それぞれの「対応」を確認してください。"
    "対応に沿って直してから、「英語の返信案を作って検査する」で作り直してください。"
    "内容そのものを変える場合は、「1. 相手の要求と、あなたの判断」を見直してください。"
)
STOP_NEUTRAL = "検査で停止しました。下の指摘と、それぞれの「対応」を確認し、対応に沿って直してから再検査してください。"


NO_REQUEST_NOTE = (
    "このメールには、質問・依頼・金額・期限・求められている約束が1つも見つかりません。"
    "お知らせや宣伝のメールで、返信が不要な可能性があります。返信するかどうかはあなたが決めてください。"
)


# Typed field names as a person reads them. The schema's own names (action, object, modality...)
# are contract vocabulary, not Japanese a lone operator can act on (REQUIREMENTS.md §11:
# 重大判断・Critical findingは日本語のみで理解可能とする).
FIELD_LABELS: dict[str, str] = {
    "text": "内容",
    "action": "してほしいこと",
    "object": "対象",
    "amount": "金額",
    "currency": "通貨",
    "date": "日付",
    "timezone": "タイムゾーン",
    "quantity": "数量",
    "unit": "単位",
    "scope": "範囲",
    "exclusivity": "独占性",
    "sublicensing": "再許諾",
    "commercial_use": "商用利用",
    "modality": "強さ",
    "condition": "条件",
    "claim_type": "種類",
    "description": "説明",
    "target": "対象",
    "type": "区分",
    "actor": "主体",
    "intensity": "強さ",
    "required_answer": "回答が必要",
    "affects_critical": "重要項目に影響",
    "resolved": "解消済み",
    "authorization_state": "承認状態",
}

MONEY_TYPE_LABELS: dict[str, str] = {
    "refund": "返金", "price": "価格", "discount": "値引き", "credit": "クレジット",
    "payment": "支払", "fee": "手数料", "other": "その他",
}  # fmt: skip

DATE_TYPE_LABELS: dict[str, str] = {"deadline": "期限", "date": "日付"}

VALUE_STATUS_LABELS: dict[str, str] = {"unknown": "不明", "not_stated": "記載なし", "ambiguous": "曖昧"}
