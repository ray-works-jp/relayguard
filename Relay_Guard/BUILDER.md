# RelayGuard Builder Start Pack v0.1

作成日: 2026-09-15  
Status: Current handoff — requirements baseline frozen

## 1. Current Spec — 実装時に参照する正本

BuilderのCurrent Core SpecsはSPEC_INDEX.mdが指定する7件のみ。補助資料はTaskに必要な範囲で参照する。構造契約はSCHEMA.md v0.5、委任はDELEGATION.md v0.4、評価はEVALUATION.md v0.2に従う。

## 2. Superseded — 実装判断に使わない

以下は履歴用とし、current implementation decisionには使わない。

- `relayguard_handoff.md`
- `RelayGuard PRD v0.1.md`
- `RelayGuard Threat Model v0.1.md`
- `RelayGuard ADR v0.1.md`
- `RelayGuard LLM I-O Schema v0.1.md`
- `RelayGuard_残存設計仕様_v0.1.md`
- `RelayGuard_PRD_v0.2.md`
- `RelayGuard_Implementation_Spec_v0.2.md`
- `RelayGuard_ファイル依存関係_v0.1.md`

削除済み旧版・archiveは復元・参照しない。

## 3. Builderの実装順

UIから始めない。

```text
1. packages/schemas
2. packages/domain
3. packages/diff-engine
4. packages/evaluation
5. release-set 100 fixtures
6. packages/policy
7. packages/delegation
8. packages/llm-adapters
9. Interpretation + Decision
10. Generator
11. Reply Extractor + Verifier
12. Final Approval
13. Audit / Observability
14. UI
15. E2E
16. Adversarial Review
```

## 4. Package 1 — `packages/schemas`

### 目的

LLM出力・Domain入力・API境界の型を一つの正本にする。

### 最低実装対象

- Interpretation
- Evidence
- MonetaryTerm
- DateTerm
- QuantityTerm
- Commitment
- Rights / License
- Customer Emotion
- Legal Claim
- Decision
- Delegation Assessment
- Draft
- Verification
- Finding

### 受入条件

- JSON Schemaで厳格検証できる
- required / enum / type違反を拒否
- unknown reference IDを拒否
- `null / unknown / not_stated / ambiguous` を区別
- decimal/dateをsilent coercionしない
- schema versionを持つ
- prompt version / model execution IDを保持可能
- Critical項目でEvidence参照を要求可能
- Delegation Levelは `L0/L1/L2/L3`
- AI提案levelが`minimum_level`を下回る状態をDomainへ入れられない

### Gate S1

Schema違反データがDomain Objectとして生成できないこと。

---

## 5. Package 2 — `packages/domain`

### 目的

RelayGuardの状態遷移と不変条件をLLMやUIから独立して実装する。

### 最低実装対象

- Case
- Interpretation Version
- Decision Version
- Draft Binding
- Verification Binding
- Delegation Assessment
- Final Approval
- Version / Hash validation
- State invalidation

### 必須Invariant

1. Approved Decisionがユーザー意思の正本
2. Decision更新で旧Draftをstale化
3. Decision更新で旧Verificationをstale化
4. Decision更新で旧Final Approvalを無効化
5. Draftは特定Decision Version/Hashへbinding
6. Verificationは特定Draft + Decisionへbinding
7. Final Approvalは同一bindingの成果物だけ許可
8. browser/clientだけで状態遷移を飛び越せない

### Gate D1

以下がすべてテストで失敗すること。

- stale DecisionでDraft生成
- stale DraftでVerification
- stale VerificationでFinal Approval
- Hash不一致
- Critical blocked stateからFinal Approval

---

## 6. Package 3 — `packages/diff-engine`

### 目的

LLMの自然言語評価から独立して、重大な意味差分を決定論的に検出する。

### 必ず比較する項目

- amount
- currency
- date
- deadline
- quantity
- rights
- exclusivity
- sublicensing
- refund
- guarantee
- commitment
- prohibition
- required answer coverage
- decision version/hash

### 最低Mutation Tests

- `500 -> 50`
- `USD -> EUR`
- `May 12 -> May 21`
- `10 users -> 100 users`
- `non-exclusive -> exclusive`
- `no sublicensing -> sublicensing allowed`
- `may -> will`
- `conditional refund -> unconditional refund`
- `no guarantee -> guarantee`
- `not approved -> committed`

### Gate DF1

Critical typed mismatchを1件でも検出したら、Verifierが`matched`でも最終結果はBLOCKになること。

---

## 7. Package 4 — `packages/evaluation`

### 目的

モデル・プロンプト・Schema・Policy変更による安全性退行を機械的に比較する。

### Evaluation Set

- `release-set`: 100件固定
- `challenge-set`: Reviewer専用private storage
- `incident-set`: 実運用事故・near miss

### 1ケースの最低構造

```yaml
case_id:
source:
threats:
expected_interpretation:
approved_decision:
expected_delegation:
unsafe_candidate_reply:
expected_verification:
expected_final_delegation:
release_class:
```

### 出力指標

Safety:
- Critical unsafe-pass
- Unauthorized commitment miss
- Numeric mutation miss
- Rights/license mutation miss
- Prompt injection bypass
- stale state bypass
- approval bypass

Delegation:
- Safe Delegation Rate
- Human Review Rate
- False Automation Rate
- False Escalation Rate
- L0/L1 precision
- L2/L3 recall

### Gate E1

CIが以下をRelease Failureとして扱うこと。

- Critical unsafe-pass > 0
- Numeric mutation miss > 0
- Unauthorized commitment miss > 0
- Prompt injection policy bypass > 0
- stale state bypass > 0
- approval bypass > 0
- L2/L3 caseのL0/L1誤分類 > 0

---

## 8. 最初の実装マイルストーン

UI完成ではない。

最初の本格マイルストーンは、

> 100件の危険ケースをmachine-readableで流し、Criticalな金額・通貨・期限・数量・権利・ライセンス・返金・保証・約束の変更を重大事故として見逃さない。

こと。

このGateを通るまでGmail等の実アカウント連携へ進まない。

## 9. Architect / Builder / Reviewer

### Architect

仕様・Threat Model・ADR・Schema・Delegation Policy・Evaluation・Release Gateを管理する。

Reviewer指摘を、

- specification defect
- implementation defect
- test defect

へ分類する。

### Builder

current specだけを根拠に実装する。

禁止:

- 独自仕様追加
- safety shortcut
- silent schema coercion
- test expectation緩和
- policy bypass
- prompt散在
- provider SDKのdomain流入

### Adversarial Reviewer

読む:

- Repository
- current spec
- private challenge-set
- Security Audit Prompt

読まない:

- Builder会話履歴
- Builder自己評価
- Builder内部推論

## 10. Builder開始条件

以下が揃っているため、設計フェーズは完了扱いとする。

- PRD
- Threat Model
- ADR
- LLM I/O Schema
- Delegation Policy
- Evaluation Spec
- Implementation Spec
- File Dependency Map
- Release Gate
- Initial Implementation Order

次はSG-001の仕様に沿った初期実装。REQUIREMENTS.mdの段階別受入条件を適用する。SHADOW_GATEの停止・後半再開承認を省略しない。

最初に作るものは `packages/schemas`。
