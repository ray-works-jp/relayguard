# RelayGuard ファイル依存関係 v0.2

作成日: 2026-09-15  
Status: Current specification index — 要件ベースライン確定 2026-09-15

確定判断はADR.md ADR-019〜025、統合要件はREQUIREMENTS.md v1.1。SCHEMA.md v0.5（SD-07解消）、DELEGATION.md v0.4、EVALUATION.md v0.2、PRD.md/ADR.md/IMPLEMENTATION.md v0.3をCurrentとする。THREAT_MODEL.md v0.2の安全要件は維持する。旧JSON例・旧Taskは新契約へ暗黙互換としない。

製品仕様の入口は `Relay_Guard\SPEC_INDEX.md` のみとする。本書中のファイル名は同じRelay_Guardディレクトリを基準とする。
ShadowGuardはRelayGuardのShadow Mode / SHADOW_GATEまでの開発フェーズであり、独立した製品Domainではない。
Hard Stopは `..\docs\SHADOW_GATE.md` に従う。同文書の停止条件は変更しない。そこに残る外部文書の「参照正本」表記は製品仕様の別入口として採用しない。

正式Delegation enumは `L0_AUTO` / `L1_POST_REVIEW` / `L2_PRE_APPROVAL` / `L3_STOP`。
旧表記AUTO / POST_REVIEW / HUMAN_APPROVAL / BLOCKを正式Delegation Domain値として採用しない。PolicyのBLOCK結果はDelegation enumとは別であり、本作業で変更しない。

参照順は Role → SPEC_INDEX → Current Task → 必要なCurrent仕様・関連監査結果のみ。常設指示へ仕様本文を複製しない。

非正本：旧ShadowGuard製品仕様を含むdocs内文書（SHADOW_GATEの停止規定を除く）、docs内の旧GPT_WORK、旧初期設定文書、旧tasksのDomain・enum・仕様記述。これらはCurrent Core Specsを上書きしない。tasks/current.mdとbacklog.mdの旧Domain TaskはCurrent仕様へ再定義されるまで実装根拠に使わない。これらの本文は非正本として保持する。
削除済み旧版・archiveを正本参照先にせず、復元しない。下記Superseded列挙は採用禁止の履歴識別のみで、有効な参照ではない。

## 1. 正本と派生仕様

```text
CONTEXT.md
        │
        ├───────────────┐
        v               v
開発マスタープロンプト   セキュリティ監査プロンプト
        │               │
        └──────┬────────┘
               v
           PRD.md
               │
               v
       THREAT_MODEL.md
          │          │
          v          v
      ADR.md      SCHEMA.md
          │          │
          └────┬─────┘
               v
 DELEGATION.md
               │
               v
     EVALUATION.md
               │
               v
   IMPLEMENTATION.md
               │
               v
            Repository
               │
               v
   Independent Security Review
               │
               └──→ Architectへ仕様欠陥を返す
```

## 2. Current Core Specs — 以下の7件のみ

| ファイル | 役割 | 状態 |
|---|---|---|
| [PRD.md](PRD.md) | 製品要件 | Current Core |
| [THREAT_MODEL.md](THREAT_MODEL.md) | 脅威・Release Blocker | Current Core |
| [ADR.md](ADR.md) | Architecture invariants | Current Core |
| [SCHEMA.md](SCHEMA.md) | LLM/domain構造契約 | Current Core |
| [DELEGATION.md](DELEGATION.md) | L0–L3判定 | Current Core |
| [EVALUATION.md](EVALUATION.md) | 安全性＋委任性能評価 | Current Core |
| [IMPLEMENTATION.md](IMPLEMENTATION.md) | Builder向け実装仕様 | Current Core |

### 補助資料の役割（Taskに必要な場合のみ）

CONTEXT.mdは製品文脈、MASTER.mdは開発要求、AUDIT.mdは監査基準、BUILDER.mdは引継ぎ、REQUIREMENTS.mdは統合要件・仕様欠陥記録。Coreを置換する独立正本ではない。補助資料のCurrent呼称・歴史的上位仕様記述も本INDEXの分類に従う。

### 資料対応表

| ファイル | 役割 | 状態 |
|---|---|---|
| `CONTEXT.md` | 最新の製品文脈・仮説 | Canonical context |
| `MASTER.md` | 製品・安全設計要求 | Canonical instruction |
| `AUDIT.md` | 独立監査基準 | Canonical audit instruction |

## 3. Superseded

以下は実装判断に使用しない。

- `relayguard_handoff.md`
- `RelayGuard PRD v0.1.md`
- `RelayGuard Threat Model v0.1.md`
- `RelayGuard ADR v0.1.md`
- `RelayGuard LLM I-O Schema v0.1.md`
- `RelayGuard_残存設計仕様_v0.1.md`
- `RelayGuard_PRD_v0.2.md`
- `RelayGuard_Implementation_Spec_v0.2.md`

削除済み旧版は復元しない。archiveへの移動・参照は指示しない。

## 4. 今回の整合性修正

### A. Delegation判定順序

Canonical:

```text
Interpret
→ Decision Sheet
→ User Decision
→ Approved Decision State
→ Delegation Assessment #1
→ Generate
→ Verify
→ Delegation Assessment #2
```

PRD v0.2の「Delegation判定→ユーザーDecision」という順序は廃止。

### B. Shadow Mode

Canonical:

- L0/L1の「自動実行してよい」という推奨はMVPではShadow Mode。
- L2の事前承認要求は実際に強制。
- L3の停止要求は実際に強制。
- したがって「全レベルをShadow扱いして安全制約まで無効化」してはならない。

### C. challenge-set

`challenge-set` はBuilderが参照できるmain repositoryへ保存しない。

Reviewer専用のprivate storage / private repositoryに置き、独立レビュー工程からのみ供給する。

### D. decision_hash

`decision_hash` はglobal UNIQUEにしない。
異なるcaseに同一内容が存在できるため、binding/integrity用indexとして扱う。

## 5. 変更伝播ルール

### PRD変更
→ Threat Model
→ ADR / Schema / Delegation
→ Evaluation
→ Implementation
→ Repository

### Threat Model変更
→ ADR
→ Schema
→ Delegation
→ Evaluation
→ Implementation
→ Security Tests

### Schema変更
→ Prompt contracts
→ Diff Engine
→ DB/API
→ Evaluation fixtures
→ UI
→ Audit

### Delegation Policy変更
→ Evaluation expected levels
→ UI state
→ Release Gates
→ KPI
→ Action Gateway assumptions

### Evaluation変更
→ CI Gate
→ Release Gate
→ Reviewer challenge strategy

## 6. Builderの入力

Builderには以下のみをcurrent specとして渡す。

1. `PRD.md`
2. `THREAT_MODEL.md`
3. `ADR.md`
4. `SCHEMA.md`
5. `DELEGATION.md`
6. `EVALUATION.md`
7. `IMPLEMENTATION.md`

Builderはhandoffの歴史的議論から独自仕様を生成しない。

## 7. Adversarial Reviewerの入力

Reviewer:

- Repository
- current specification set
- Security Audit Prompt
- private challenge-set

Reviewerへ渡さない:

- Builder会話履歴
- Builder自己評価
- Builder内部推論

## 8. SHA-256 Manifest

以下は一本化前に記録された内容識別値（履歴）であり、参照名更新後の現行ファイルのハッシュ一致を保証しない。ファイル名のみ現在名に対応付けている。

- `CONTEXT.md`: `5da103bae5974fcb39b330b30c1d9294a2946459dede4d6e99ce6fbfb6b09e39`
- `MASTER.md`: `97d34f6116d5eee743b7868a28843fbf0b07cf02d52c146129ac402d86080021`
- `AUDIT.md`: `561f5022a176bc2b446c64c31aa0acf8a0625f5ccee502c8037647a188449cc6`
- `PRD.md`: `633599011f6540357450db85f9a37290369a692349f9707ed9e02a4a43d9b902`
- `THREAT_MODEL.md`: `5563e20848fb4b4719c854c22ff939455d57b7d011e34f30d4302d983b75c97c`
- `ADR.md`: `4cc91c79493c70b7219d7988b2fc746155bd2a87273b7d289ecc5384ddde3db9`
- `SCHEMA.md`: `196aef6d3b5c6499dbd4f7ada734dc2654fb032049e28855ab87c0c8eb40bbd8`
- `DELEGATION.md`: `74ace7fe6e7b9f46a248f53a4a28791fe582b4068dbda30813e72896a85b2e77`
- `EVALUATION.md`: `260ba1554659090b92230feddd02beb12c4bc607ef4aca162c9dec86f490d074`
- `IMPLEMENTATION.md`: `c49ec51e8831b6290a8ffe18a39ed77a44fbe9d796f8981fde09cfd933b79992`

## 9. 次の工程

要件ベースラインは確定。SG-001の入力・結果・受入条件はREQUIREMENTS.md §16とSCHEMA.md §10。これは実装・検証PASSの宣言ではない。
既存の旧Domain Taskは実装根拠にしない。担当者はCurrent契約に基づき実装し、必要な検証を行う。Shadow段階の条件を満たしたら../docs/SHADOW_GATE.mdに従い停止する。後半の開始には人間承認が必要。

2026-09-16 SG-001補足: SCHEMA §12 / DELEGATION §14 / ADR-024をCurrentとして採用。実装・通貨照合・期待値承認・QAの完了を意味しない。

Current補足: ADR-025 / SCHEMA §13 / DELEGATION §15。回答契約とGold審査は同ADRを参照。実装・QAは未完了。

2026-09-17 SHADOW_GATE裁定補足: ADR-026をCurrentとして採択。SG-001 Gold 22件承認、100件評価セット正式昇格、要確認7項目の裁定を確定。

2026-09-20 Architect裁定補足（D-1〜D-4）: ADR-027をCurrentとして採択（返信内リンクの全面禁止。承認済み回答の中でも送信不可）。
IMPLEMENTATION.md §23のLLM試行timeoutを「1回60秒」から「処理全体の残り予算」へ改訂（全体120秒のhard limitは不変・裁定D-2）。
SHADOW_GATE解除は条件付きで追認（裁定D-1）。「正式Gate通過」の表示には Shadow Core / fuzz_extractor / UIテスト の3Gate全PASSが必要（裁定D-4）。
解除の記録は ../docs/SHADOW_GATE.md §5。ADR-027はCurrentの安全不変条件として扱い、記載の再検討条件は変更提案の条件であって自動解除の例外ではない。
**「正式Gate通過」はRelease承認ではなく、外部メール連携・外部Actionの解禁も意味しない**（SHADOW_GATE §2の禁止は継続）。実LLM評価・実メールパイロット・独立QA・独立セキュリティ監査はNOT_RUN。

2026-09-23 Architect裁定補足（D-7）: IMPLEMENTATION.md §23 の処理全体上限を120秒から300秒へ改訂（D-2の「全体120秒のhard limitは不変」を置き換える）。
実測1例（571語、effort=medium で初回約125秒）に基づく**試験用の上限**であり、長文一般の完了保証ではない。修復1回・超過時Fail Closed・失敗試行の結果を流用しない条件は不変。
