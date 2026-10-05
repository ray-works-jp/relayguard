# SHADOW MODE HARD STOP & SHADOW_GATE 規定

参照正本：`C:\Users\HP\Documents\RelayGuard\RelayGuard_要件定義書_v1.0.md`

## 1. 停止規定の定義

Shadow Mode相当の実装が完了した時点で、開発を必ず停止する。

停止地点は、以下が成立した時点とする。

- Schema / Domainが実装済み
- Evaluation Runnerが動作する
- release-set 100件を実行できる
- Policy Engineが動作する
- Delegation EngineがL0 / L1 / L2 / L3を判定できる
- Shadow Modeとして以下を記録できる
  - predicted_delegation_level
  - actual_human_intervention
  - final_outcome
  - would_have_been_safe_to_automate
- Safe Delegation Rate
- False Automation Rate
- Human Review Rate
- Critical Incident関連指標

**この地点を `SHADOW_GATE` とする。**

---

## 2. SHADOW_GATE 到達時の禁止事項

`SHADOW_GATE` 到達後は、明示的な人間承認があるまで以下へ進んではならない。

- Generatorの本格実装
- Reply Extractor
- Verifier
- Final Approval
- RelayGuard UIの本格実装
- 外部メール連携
- Gmail連携
- 外部Action
- RelayGuard後半フェーズ

---

## 3. 停止時の報告義務

SHADOW_GATE到達時には新機能を実装せず、結果だけを報告して停止する。

報告内容：

1. 100件の評価結果
2. Dangerous AUTO / False Automation
3. L0 / L1 / L2 / L3の分布
4. Safe Delegation Rate
5. Critical / High問題
6. モデル別推論コスト
7. ShadowGuard単体として成立する兆候
8. RelayGuard後半へ進むべきかの判断材料

---

## 4. 再開条件

人間から明示的に「RelayGuard後半へ進め」と指示されるまで次フェーズを開始しない。

---

## 5. 解除の記録（2026-09-20）

§4が要求する「人間から明示的に『RelayGuard後半へ進め』」の記録。

- **判断日**: 2026-09-20
- **判断者**: 人間（リポジトリ所有者） / Architect裁定 D-1
- **内容**: **条件付き追認**。2026-09-17〜19に実装された後半MVP
  （Generator / Reply Extractor / Verifier / Final Approval / UI）を事後追認する。
- **条件**: 追認は着手の許可であり、**それだけでは「正式Gate通過」ではない**。
  正式Gate通過の表示には、裁定D-4の定める**3つのGateすべてのPASS**が必要。

### 3つのGate（裁定D-4）

| Gate | 対象 | 実行 |
|---|---|---|
| A. Shadow Core | Spec/manifestハッシュ、ruff・format・mypy、pytest全件、SG-001、100件release-set、ゼロトレランス指標 | `scripts/run_shadow_gate_audit.py` |
| B. Reply Extractor 耐性 | 承認済み回答内に仕込んだ45種の攻撃payloadを1件も見逃さないこと | 同上（`scripts/fuzz_extractor.py`） |
| C. UI | ローカルReviewerの契約・検査・表示テスト | 同上（`pytest packages/ui/tests`） |

3Gateは `scripts/run_shadow_gate_audit.py` が一括実行する。1つでもFAILなら BLOCKED。

### この記録の限界

追認と3Gate PASSは、**実装が仕様どおり動くことの機械的確認**であり、承認水準は
**「2. Builder検証済み」**にとどまる（1実装済み / 2 Builder検証済み / 3 Architect承認済み / 4 独立QA済み / 5 Release承認済み）。
Builderの実行結果をArchitect独立検証・独立QAの代替として記録してはならない。
実LLM評価、実メールパイロット、独立QA（Antigravity）、独立セキュリティ監査は**未実施**であり、
Release承認・商用提供可能の宣言ではない。§2の外部メール連携・外部Actionの禁止は**解除していない**。
