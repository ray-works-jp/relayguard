# ADR-026: SHADOW_GATE 審査事項の正式裁定と要件固定

- **Status**: Accepted (Canonical Architecture Decision)
- **Date**: 2026-09-17
- **Decider**: System Architect / Quality Authority (Proxy)
- **Supervises**: `handoff/SHADOW_GATE_REVIEW_PACKAGE.md`, `SCHEMA.md` v0.5, `DELEGATION.md` v0.4, `EVALUATION.md` v0.2

---

## 1. Context & Problem Statement

Claude Code による連続開発フェーズにおいて、SG-001の安定化、オフライン評価基盤（`relayguard_eval`）、100件の評価セット候補、および Shadow 記録・KPI 計測基盤の実装が完了した。
しかし、`docs/SHADOW_GATE.md` に定める停止地点において、実装者と評価者の独立性確保、未承認 Gold 候補の確定、および 7 点の実装解釈（要確認事項）が未裁定のまま停止していた。
本 ADR は、これらすべての未承認・要確認項目に対して正式な Architect 裁定を下し、仕様および Gate 判定基準として恒久固定するものである。

---

## 2. Decisions (正式裁定)

### Decision 1: SG-001 Gold 候補 22 件の正式承認と版固定
- **裁定**: **APPROVED**
- **理由**:
  - `l2_answer_from_source_evidence` において、`basis=source_evidence` であっても quote の存在だけで回答の客観的真実性や法的拘束力までは保証されないため、`risk_factors.impact=medium` とする修正（SCHEMA v0.5 §13準拠）は妥当である。
  - ADR-025 で CHANGES_REQUESTED とされた 4 件の対応（`l1_emotion_only_notice` → `l2_anger_with_past_delay` 改名および `l1_style_feedback_notice` 新設、counterparty commitment の Question 化、attachment/prior commitment の unknown 指定）がすべて仕様通り反映されている。
- **固定対象**:
  - `fixtures/sg001/expected.json` SHA-256: `3a9f01866181c227bfdffffead3062de9ad496cb19848cf5ab42234b089bdec6`
  - 対象 22 件を正式 Gold データセット（Gold Benchmark v0.5）として認定する。

### Decision 2: 100件評価セット候補の正式 release-set 昇格
- **裁定**: **APPROVED as Formal Offline Release-Set v0.5**
- **理由**:
  - 20 カテゴリ × 5 変種（明示・婉曲・複合・履歴依存・攻撃的）の 100 件構成が網羅されており、入力とラベルが分離され `input_sha256` で厳格に束縛されている。
  - ラベル構成（L0: 4, L1: 2, L2: 27, L3: 57, rejected: 10）は高リスク業務メールの防御モデルとして整合している。
- **固定対象**:
  - `eval/release-set-candidates` suite manifest SHA-256: `2929f19ea47c5c7061bd0ff31ebbdd3b676b3a28ed8fb76fd649c3a6fd9808bc`

---

### Decision 3: 要確認 7 項目の正式裁定

#### (1) DecisionItem.provenance.actor_id と approved_by の一致
- **裁定**: **現状維持（DecisionItem での不一致は許容、question_answers のみ厳格一致強制）**
- **理由**: DecisionItem は他者（別エージェントやシステム）が下書き作成し、人間が approved_by として承認するワークフロー（代理起草）が存在するため。一方、`question_answers` は本人の直接回答責任を担保するため一致を必須とする。

#### (2) 期待 rejected の扱い
- **裁定**: **自動化不可（L3以上の制限）として扱い、L0/L1予測は False Automation に計上する**
- **理由**: 不正入力やポリシー違反が自動実行（L0/L1）されることは最大級のセキュリティ事故であるため。

#### (3) error_code 未定義の拒否ケース
- **裁定**: **任意の rejected（error_code=null）で一致とみなす**
- **理由**: 整合性エラー、不正ハッシュ、改ざん等の拒否理由が複数重複しうるため、Fail-Closed で確実に遮断されていれば安全上十分である。

#### (4) Safe Delegation Rate の計算式定義
- **裁定**:
  - `Safe Delegation Rate = (予測L0 かつ 安全判定true かつ 重大事故なし) / 全案件数`
  - L1（事後確認）は「事前確認のみ省略可能率 (Pre-Approval Bypass Rate)」として分離計上する。
- **理由**: L1 は事後レビューが必要であり、完全自動化（L0）とは監査・運用コストが明確に異なるため。

#### (5) ShadowOutcome の確定条件
- **裁定**: `final_outcome != unknown` または `safe_to_automate != null` の場合は `adjudicator_id` を必須とし、`verification_cost < 0` は厳格拒否する。
- **理由**: 監査証跡（Evidence Integrity）における責任者不明の事後評価および不正なコスト値を防止するため。

#### (6) Shadow store の改訂運用
- **裁定**: 同一 assessment に対する事後評価の改訂は追記専用ハッシュチェーンで行い、最新レコードを採用する。期間集計は「初回記録時刻」を基準とする。
- **理由**: 改ざん防止と時系列整合性の両立。

#### (7) 評価ハーネスの分類キー
- **裁定**: `threats`、`release_class=standard`、`category` キーは評価メタデータとして正式採用する。
