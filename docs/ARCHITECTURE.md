# ShadowGuard Architecture

Status: Design Baseline

## 1. Architecture Style

MVPはModular Monolithを採用する。

理由:

- Coreの評価精度を先に検証したい
- モジュール境界は必要だが独立デプロイは不要
- Microservicesによる運用コストを避ける
- 100ケース評価とRegressionを高速に回したい

将来、負荷・組織分離・セキュリティ境界に明確な必要性が出た場合のみ分割する。

## 2. Core Components

### Input Normalization
責務:
- JSON Schema validation
- encoding / whitespace normalization
- stable case ID
- unsupported field rejection
- size / shape validation

LLMを使用しない。

### Intent Extraction
責務:
- customer request / question / desired outcome抽出
- refund / discount / cancel / contract / license / legal / privacy等のintent signal抽出
- ambiguity / unknown抽出

原則CHEAPから開始し、必要時のみ昇格。

### Risk Evaluation
責務:
- monetary
- legal
- contract
- license
- privacy
- security
- customer sentiment
- reputational
- ambiguity
- contradictory history
- prompt injection
を評価する。

数値・閾値は決定論的コード優先。

### Policy Engine
責務:
- company policyを評価
- allow / deny / threshold
- missing policy
- conflicting policy
- stale policy
を処理。

Policy EngineはDelegation Engineから分離する。

### Authority Evaluation
責務:
- AIに許可されたaction範囲を判定
- refund / discount / contract change等の権限確認
- authority unknown時はAUTO禁止

### Delegation Engine
責務:
- AUTO / POST_REVIEW / HUMAN_APPROVAL / BLOCKを決定
- minimum level ruleを強制
- risk / policy / authority / uncertainty / evaluator evidenceを統合

単一LLM出力を最終判定にしない。

### Independent Evaluator
責務:
- Core判定を独立に検査
- critical risk miss
- policy mismatch
- suspicious AUTO
- correlated failure signal
を評価する。

Evaluator自身も最終authorityではない。決定論的Critical ruleが優先する。

### Audit / Evidence
責務:
- input hash
- normalized state
- triggered rules
- policy version
- model tier/version
- delegation
- evaluator result
- timestamps
- evidence
を記録する。

PIIは必要最小限。

### Model Router
責務:
- CODE / CHEAP / STANDARD / STRONGの選択
- escalation reason記録
- cost budget enforcement
- fallback / outage behavior

具体的モデル名はCore domainへ露出させない。

## 3. Data Flow

```text
Raw Case
  ↓
Schema Validation
  ↓
Normalized Case
  ↓
Intent Extraction
  ↓
Risk Evaluation
  ↓
Policy Engine
  ↓
Authority Evaluation
  ↓
Preliminary Delegation
  ↓
Independent Evaluator
  ↓
Final Policy Guard
  ↓
Delegation Decision
  ↓
Audit / Evidence
  ↓
Result
```

## 4. Trust Boundaries

TB1: External case → ShadowGuard
- 完全非信頼

TB2: Policy input → Policy Engine
- versionedだが内容は検証対象

TB3: ShadowGuard → LLM Provider
- 外部Trust Boundary
- PII最小化
- timeout / outage / malformed output考慮

TB4: LLM Output → Domain
- 完全非信頼
- Schema Validation必須

TB5: Independent Evaluator → Final Decision
- Evaluatorも非信頼
- deterministic guard優先

## 5. Canonical Domain Objects

- CaseInput
- NormalizedCase
- IntentAssessment
- RiskAssessment
- PolicySnapshot
- PolicyEvaluation
- AuthorityAssessment
- DelegationDecision
- EvaluatorAssessment
- AuditEvidence
- ModelExecution
- ResultEnvelope

## 6. Determinism Strategy

同一条件で再現可能にするため、以下をResultへ含める。

- schema_version
- policy_version
- delegation_policy_version
- model_config_version
- prompt_version
- model tier
- normalized input hash

決定論的ルールが確定できる場合、LLM判定を上書きする。

## 7. Failure Behavior

原則Fail Closed。

- malformed input → BLOCK / invalid result
- schema invalid LLM output → retry制限後、HUMAN_APPROVALまたはBLOCK
- missing required policy → AUTO禁止
- model outage → AUTO禁止
- evaluator disagreement on critical risk → HUMAN_APPROVAL以上
- unresolved prompt injection → BLOCK
- legal/contract critical uncertainty → HUMAN_APPROVAL以上
- stale/conflicting policy → AUTO禁止

## 8. Persistence

SG-001では永続DBを必須にしない。ファイル入力→ファイル出力を優先する。

後続Taskでfixture runner、result aggregation、必要ならSQLite/PostgreSQLを検討する。

## 9. No-Go Architecture

MVPでは採用しない:

- Microservices
- Kubernetes
- Event Bus
- 複数DB
- plugin platform
- complex auth
- autonomous action gateway
