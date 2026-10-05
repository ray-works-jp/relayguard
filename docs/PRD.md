# ShadowGuard PRD

Status: Design Baseline
Phase: Core MVP / Shadow Mode
Owner: GPT Work

## 1. Product Definition

ShadowGuardは、AIエージェントへ業務を委任した場合に、その案件をどこまで人間なしで安全に任せられるかを評価するシステムである。

初期対象はAIカスタマーサポート。過去の問い合わせまたは人工評価ケースをShadow Modeで処理し、以下の4段階へ分類する。

- AUTO
- POST_REVIEW
- HUMAN_APPROVAL
- BLOCK

ShadowGuardは「AIを安全に制限する製品」ではない。目的は、重大事故を防ぎながら、人間が確認しなくてよい案件を最大限増やすことである。

## 2. Primary Problem

企業がAIカスタマーサポートへ業務を委任すると、自動化率を上げたい一方で、誤返金・規定外値引き・契約変更・ライセンス変更・勝手な保証・PII漏洩・法的リスク・Prompt Injection等の事故が発生し得る。

最重要事故は、

> 本来 HUMAN_APPROVAL または BLOCK である案件を AUTO と判定すること。

である。

## 3. Primary User

MVPの主な利用者:

- AIカスタマーサポート導入を検討する企業
- 既存AIサポートの自動化範囲を測定したい運用者
- AIのhandoff policyを評価したいCS / Support Ops担当者
- AIエージェントの安全性と自動化率を同時に評価したい開発者

## 4. Primary Job To Be Done

「自社AIに、実際にはどこまで人間確認なしで任せられるか」を、過去データまたは人工ケースから測定できるようにする。

## 5. MVP Flow

```text
input
  ↓
Input Normalization
  ↓
Intent Extraction
  ↓
Risk Evaluation
  ↓
Policy Engine
  ↓
Authority Evaluation
  ↓
Delegation Engine
  ↓
Independent Evaluator
  ↓
Audit / Evidence
  ↓
report
```

初期実装では、最小縦断処理として次を成立させる。

```text
input.json
  ↓
ShadowGuard Core
  ↓
result.json
```

## 6. MVP Scope

含む:

- 単一ケースのJSON入力
- 入力Schema Validation
- 正規化
- Intent/Risk/Policy/Authorityの構造化評価
- 4段階Delegation判定
- 判定理由
- triggered policies
- evidence
- model tier記録
- policy/version記録
- deterministic rule優先
- Independent Evaluation
- 結果JSON
- 100ケース評価セットを実行可能にする基盤
- Safe Automation Rate等のメトリクス算出

含まない:

- 本物のメール送信
- 本物の返金
- 本物の値引き
- 本物の購入
- 契約変更
- その他不可逆Action
- Gmail等の外部サービス連携
- 大規模UI
- 高度なworkflow builder
- multi-tenancy
- Microservices
- Kubernetes

## 7. Delegation Levels

### AUTO
十分に低リスクで、人間確認なしで処理可能。

### POST_REVIEW
AI処理は可能だが、事後確認を推奨。

### HUMAN_APPROVAL
実行前に人間承認が必要。

### BLOCK
AIによる自律処理を許可しない。

## 8. Core Metrics

- Safe Automation Rate
- Dangerous AUTO Rate
- Human Review Rate
- False Negative Rate
- Policy Violation Detection Rate

補助指標:

- Delegation distribution
- Model escalation rate
- STRONG model usage rate
- Per-case estimated model cost
- Unknown / ambiguous rate
- Evaluator disagreement rate

## 9. Success Criteria

MVP完成条件:

1. 100件以上の評価ケースを自動処理できる。
2. 4段階Delegation判定ができる。
3. Policyを反映できる。
4. 判定理由を出せる。
5. 危険なAUTOを測定できる。
6. Safe Automation Rateを算出できる。
7. 同じ入力・同じPolicy version・同じModel configurationで判定を再現できる。
8. ケースをRegression Testへ変換できる。
9. Dangerous AUTOをRelease Gateとして扱える。
10. 外部Actionを一切実行しない。

## 10. Release Philosophy

SafetyとAutomation Rateを同時に最適化する。

すべてをHUMAN_APPROVAL/BLOCKへ寄せることは安全上は容易だが、製品価値を失う。反対にAUTO率だけを上げる変更は認めない。

最優先Release Blocker:

- Expected HUMAN_APPROVAL/BLOCK → Actual AUTO
- Prompt InjectionによるPolicy bypass
- stale/conflicting policyを安全側へ誤解
- high monetary / legal / contract / privacy riskのAUTO
- malformed LLM outputのsilent acceptance

## 11. Future Boundary

ShadowGuard Coreが成立した後にのみ、UI、外部データ取込、企業ポリシー管理、RelayGuardへの実行制御を検討する。
