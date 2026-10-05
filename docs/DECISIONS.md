# ShadowGuard Architecture Decisions

Status: Design Baseline

## ADR-001 Modular Monolith

Problem:
MVPをMicroservicesに分割するか。

Options:
A. Microservices
B. Modular Monolith

Selected:
B

Reason:
Core評価精度と100ケースRegressionを先に検証し、運用複雑性を避ける。

Trade-off:
独立スケール性は低い。

Reversal:
明確な負荷・組織・セキュリティ境界が発生した場合。

---

## ADR-002 Shadow Mode Only

Selected:
MVPは外部Actionを実行しない。

Reason:
誤分類の実害を防ぎつつ評価性能を測るため。

---

## ADR-003 Four Delegation Levels

Selected:
AUTO / POST_REVIEW / HUMAN_APPROVAL / BLOCK。

Reason:
安全スコアだけでは「どこまで任せるか」を表現できない。

---

## ADR-004 Policy EngineとDelegation Engineを分離

Reason:
企業ルール適合と最終委任判断を独立テスト可能にする。

---

## ADR-005 Code/Deterministic First

Selected:
Code first → deterministic rules → CHEAP → STANDARD → STRONG。

Reason:
コスト削減、再現性、安全性。

---

## ADR-006 Model Capability Tier

Selected:
CHEAP / STANDARD / STRONG。

Reason:
特定Provider/modelへの依存を避ける。

---

## ADR-007 Fail Closed on Critical Unknowns

Selected:
critical unknown / missing policy / stale policy / partial failureではAUTO禁止。

Reason:
unknownを安全と誤認しない。

---

## ADR-008 Independent Evaluator

Selected:
Delegation判定とは独立したEvaluatorを置く。

Reason:
単一判断系の自己評価依存を避ける。

Trade-off:
モデルコストが増える。

Mitigation:
全件STRONGではなくrisk-based routing。

---

## ADR-009 Deterministic Rules Override Model

Selected:
amount/currency/threshold/allow-deny等のCritical ruleはLLM判定に優先。

---

## ADR-010 File-Based Vertical Slice First

Selected:
SG-001は `input.json → ShadowGuard Core → result.json`。

Reason:
UI/DBを先に作らずCore contractを固定する。

---

## ADR-011 100-Case Evaluation Before Large UI

Selected:
Core評価セットをUIより先に完成させる。

---

## ADR-012 Dangerous AUTO as Primary Release Blocker

Selected:
Expected HUMAN_APPROVAL/BLOCK → Actual AUTO を最重要事故とする。
