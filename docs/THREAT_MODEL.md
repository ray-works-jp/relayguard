# ShadowGuard Threat Model

Status: Design Baseline

## 1. Primary Safety Failure

最重要事故:

> 本来 HUMAN_APPROVAL または BLOCK である案件を AUTO と判定すること。

特に、AIとIndependent Evaluatorが同じ誤解を共有し、安全に見えるケースを重点対象とする。

## 2. Protected Assets

- Delegation decision
- Company policy
- Authority limits
- Monetary values
- Currency
- Contract conditions
- License conditions
- Guarantees
- Refund/discount limits
- PII
- Legal risk signals
- Audit evidence
- Policy/model version
- Evaluation labels

## 3. Threats

### T1 Prompt Injection — Critical
入力本文がsystem/policy/roleを変更させようとする。

Control:
- 入力を命令ではなくdataとして扱う
- policyは外部入力から変更不可
- injection signalでSTRONG昇格
- unresolvedの場合BLOCK

### T2 Indirect Prompt Injection — Critical
引用、HTML、URL、埋込テキスト等を通じて指示注入。

Control:
- untrusted content separation
- URL/添付の自動実行禁止
- suspicious embedded instruction検出

### T3 Policy Bypass — Critical
LLMがcompany policyを無視、または入力内容をpolicyとして扱う。

Control:
- Policy Engine分離
- deterministic threshold
- final policy guard

### T4 Malicious Customer Content — High
感情操作・偽ポリシー・権威主張等で判定を誘導。

Control:
- evidence separation
- authority source固定

### T5 Malformed LLM Output / Schema Bypass — Critical
壊れたJSONや型違反をsilent coercionして採用。

Control:
- strict schema validation
- unknown field policy
- retry上限
- fail closed

### T6 Hallucinated Refund — Critical
存在しない返金を許可。

Control:
- policy + authority + amount/currency deterministic check
- unknown amount/currencyでAUTO禁止

### T7 Hallucinated Discount — Critical
規定外値引き。

Control:
- discount threshold rule
- authority validation

### T8 Invented Guarantee — Critical
未承認保証・SLAを追加。

Control:
- guarantee authority
- guarantee actionをAUTO禁止候補

### T9 Altered Contract Condition — Critical
契約条件を変更。

Control:
- contract intent/risk detection
- minimum HUMAN_APPROVAL

### T10 Incorrect Currency / Amount — Critical
通貨・金額誤認。

Control:
- typed amount/currency representation
- deterministic comparison
- unknown/ambiguous→AUTO禁止

### T11 Legal Threat Miss — Critical
法的措置・契約解除等を通常問い合わせ扱い。

Control:
- legal signal extraction
- STRONG escalation
- HUMAN_APPROVAL/BLOCK minimum

### T12 Privacy / PII Leakage — High
raw PIIをログまたは外部モデルへ過剰送信。

Control:
- data minimization
- operational logging禁止項目
- redaction policy

### T13 Duplicate Processing — Medium
同一ケースを重複評価し、集計を歪める。

Control:
- stable input hash
- case ID
- deduplication in batch evaluation

### T14 Stale Policy — High
古いpolicyで安全判定。

Control:
- policy_version mandatory
- stale policy detection
- AUTO禁止

### T15 Contradictory History — High
過去と現在の条件が矛盾。

Control:
- contradiction signal
- unresolved→HUMAN_APPROVAL以上

### T16 Generator/Evaluator Correlated Failure — Critical
同一モデル/同一prompt傾向で誤りを共有。

Control:
- independent context
- model tier/role separation
- deterministic rule
- disagreement and critical-risk escalation
- adversarial dataset

### T17 Model Outage — High
timeout/outage時に古いsafe resultを再利用。

Control:
- no silent fallback to cached safe decision
- AUTO禁止
- explicit degraded status

### T18 Partial Failure — High
一部コンポーネント失敗後に判定だけ返す。

Control:
- completion state
- required-stage checklist
- incomplete pipeline→AUTO禁止

### T19 Missing/Conflicting Policy — High
policy欠落または矛盾。

Control:
- missing/conflict signal
- AUTO禁止

### T20 High Monetary Impact Misclassification — Critical
高額案件をAUTO。

Control:
- deterministic thresholds
- STANDARD/STRONG escalation
- HUMAN_APPROVAL minimum

## 4. Security Invariants

1. External inputを信頼しない。
2. LLM outputを信頼しない。
3. Policy EngineをLLM出力から独立させる。
4. Authority unknownでAUTOにしない。
5. Critical unknownを安全値へ変換しない。
6. Amount/currency/date/thresholdはtyped deterministic rule優先。
7. Model outage / partial failure時にAUTOにしない。
8. Prompt Injection unresolvedはBLOCK。
9. Policy versionを必須とする。
10. AUTO判定はIndependent Evaluation対象とする。

## 5. Release Blockers

- Expected HUMAN_APPROVAL/BLOCK → Actual AUTO が1件以上
- Prompt Injection policy bypass
- schema bypass
- high monetary risk AUTO
- legal/contract critical miss
- missing/conflicting/stale policyでAUTO
- malformed LLM outputをsafeとして採用
- model outage/partial failure時のAUTO
- unresolved Critical finding
