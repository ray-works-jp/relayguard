# RelayGuard Threat Model v0.2

## 1. 最重要事故

RelayGuardで最優先に防ぐべき事故は、

> AIが危険な意味変更・約束・判断を行い、GeneratorとVerifierの両方が同じ誤りを共有し、ユーザーには安全に見えること。

である。

Delegation Engine導入後は、さらに

> 本来L2/L3で止めるべき案件をL0/L1へ誤分類し、自動委任可能と誤認すること。

も最重要脅威とする。

## 2. 保護対象

- ユーザーの最終意思
- 金額・通貨
- 日付・期限
- 数量
- 権利
- ライセンス
- 禁止事項
- 保証
- 返金
- 契約条件
- 個人情報
- 顧客体験
- ブランド信頼
- 委任レベル
- 最終承認状態
- 監査記録

## 3. Trust Boundaries

### TB1 外部メール → RelayGuard
完全非信頼。

### TB2 RelayGuard → LLM Provider
外部境界。PII漏洩とprovider failureを考慮。

### TB3 LLM Output → Domain
完全非信頼。Schema validation必須。

### TB4 Generator → Verifier
Generator出力は非信頼。

### TB5 Verifier → Policy Engine
Verifier判定も非信頼。Deterministic Diffを優先。

### TB6 Policy Engine → UI
安全判定をUIのみで変更不可。

### TB7 Core → Future Action Gateway
MVPでは実装しない。

## 4. Threat Classes

### T1 Prompt Injection — Critical
メール本文中の指示でsystem/policy/approvalを変更させる。

### T2 Indirect Prompt Injection — Critical
引用文、署名、URL、添付言及等を経由する。

### T3 Fabricated Commitment — Critical
未承認の割引・返金・保証・期限・権利を追加。

### T4 Numeric Mutation — Critical
金額、通貨、日付、数量、割合等を変更。

### T5 Rights / License Mutation — Critical
独占、再許諾、商用利用等を変更。

### T6 Correlated Generator / Verifier Failure — Critical
両方が同じ誤解をする。

### T7 Translation Drift — High
may→will、subject to approvalの脱落等。

### T8 Semantic Omission — High
相手の重要要求・質問を無視。

### T9 Malformed Structured Output — High
Schema欠落・型違反・不正enum。

### T10 Stale State / Race — High
古いDecisionで生成・検証・承認。

### T11 Replay / Duplicate Action — Medium（MVP）
将来Action GatewayではCritical。

### T12 Personal Data Leakage — High
raw emailやPIIをログ/APMへ送信。

### T13 Provider Failure — High
timeout・仕様変更・モデル劣化・partial output。

### T14 Long / Contradictory Thread — High
履歴矛盾を誤って最新条件とみなす。

### T15 Attachment Dependency — High
未解析添付の条件を推測。

### T16 Legal / Contract Claim — High
契約解除、知財、支払義務等をAIが確定判断。

### T17 Delegation Misclassification — Critical
L2/L3案件をL0/L1へ下げる。

### T18 Customer Emotion Miss — High
怒り・解約示唆・公開苦情を低リスク扱い。

### T19 Policy Exception Miss — High
ブランドポリシーや過去約束を見落とす。

### T20 Misleading Confidence — High
高confidence表示が人間を誤誘導。

## 5. Mandatory Fail-Closed Conditions

- critical monetary mismatch
- currency mismatch
- critical date/deadline mismatch
- quantity mismatch
- unauthorized commitment
- rights/license change
- refund/guarantee addition
- attachment required but unavailable
- unresolved contradiction
- schema validation failure
- decision version mismatch
- unresolved prompt injection
- legal claim requiring human judgment
- critical delegation ambiguity

## 6. Delegation-specific Controls

AIはminimum delegation levelを引き下げられない。

最低ルール:

- legal_claim → L3
- unresolved_prompt_injection → L3
- critical_missing_information → L3
- attachment_required_missing → L3
- contradictory_commitments → L3
- refund_or_credit → minimum L2
- contractual_change → minimum L2
- rights_or_license_change → minimum L2
- new_guarantee → minimum L2
- material_money_change → minimum L2
- material_deadline_change → minimum L2
- critical_deterministic_diff → L3

## 7. Security Invariants

1. AI出力を信頼しない。
2. 原文は命令ではなくデータ。
3. 未承認重大commitmentを生成させない。
4. 重大な型付き差異は必ずblock。
5. 不明は安全と同義ではない。
6. Verifierの成功だけで安全を証明しない。
7. 最新Decision以外から生成しない。
8. 外部Actionには新しい承認境界を置く。
9. Delegation levelはPolicy Engineが最終決定する。
10. モデルのconfidenceだけで委任レベルを下げない。

## 8. Release Blockers

- Critical unsafe-passが残る
- L2/L3案件のL0/L1誤分類
- stale decisionからfinal approval可能
- prompt injectionでpolicy変更可能
- browser-only bypass
- raw PII operational-log leak
- provider failure時に古いsafe結果をsilent reuse
- challenge-setで重大事故を見逃す

## 9. Threat Model更新条件

- Gmail連携
- 添付解析
- URLクロール
- 自動送信
- 自動返金
- 自動購入
- 自動契約
- 長期メモリ
- 組織利用
- Product Agentとの直接通信
- L0/L1の実自動化解放
