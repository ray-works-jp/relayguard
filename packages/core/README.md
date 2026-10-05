# relayguard core — SG-001 Shadow Core

SG-001の最小実行経路。offline `ShadowCoreInput` → 厳格JSON解析 → JSON Schema → Domain/binding検証 → 事前Delegation判定（`delegation-0.4`）→ 結果・監査metadata。network・外部Action・LLMなし。正本は `Relay_Guard/SPEC_INDEX.md` → SCHEMA.md §10/§12/§13 / DELEGATION.md §12/§14/§15 / ADR-024・025。

## 実行（リポジトリ直下、PowerShell）

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install pytest jsonschema ruff mypy
.venv\Scripts\ruff.exe check
.venv\Scripts\ruff.exe format --check
.venv\Scripts\mypy.exe
.venv\Scripts\python.exe -m pytest
$env:PYTHONPATH = "packages\core"; .venv\Scripts\python.exe -m relayguard fixtures\sg001\l2_refund_commitment_stated.input.json
```

CLIの終了コード: 0=assessed、1=rejected、2=使用方法エラー。出力はUTF-8のShadowCoreResult JSON。
fixture再生成: `.venv\Scripts\python.exe scripts\build_sg001_fixtures.py`（期待値は`fixtures/sg001/expected.json`に分離）。

## 構成

| パス | 役割 |
|---|---|
| `packages/schemas/v0_5/*.schema.json` | ShadowCoreInput / ShadowCoreResult の実行可能Schema（closed object・全required） |
| `relayguard/strict_json.py` | 不正UTF-8・BOM・重複キー・非有限数・孤立サロゲート拒否。小数はDecimal |
| `relayguard/schema_validation.py` | pattern全一致、int/Decimal厳格型、rg-* format（Decimal・Date・Timestamp・通貨・Confidence） |
| `relayguard/canonical.py` | canonical serialization、source/decision hash |
| `relayguard/integrity.py` | 参照・Evidence・hash・binding・Decision整合・承認偽装の検査 |
| `relayguard/delegation.py` | delegation-0.4 事前判定 |
| `relayguard/audit.py` | 監査event hash chain |
| `relayguard/currency.py` + `reference/iso4217/` | 固定ISO 4217集合と原本・manifest |
| `relayguard/shadow_core.py` | 実行経路、結果不変条件の自己検査、metadataのみの運用ログ |

## 対象版と判定規則（schema 0.5 / delegation-0.4 / ADR-024・025）

Current仕様に追従済み。判断根拠はSCHEMA.md §12とDELEGATION.md §14。

- 版: `schema_version="0.5"` / `policy_version="delegation-0.4"`。旧版・混在は受理しない（Schema版不正=SchemaInvalid、未対応policy=PolicyViolation）。失敗結果も0.5で返す。
- 必要値（§14.1）: MonetaryTerm=amount/currency/condition、DateTerm=date/timezone、QuantityTerm=quantity/unit/condition、ClauseTerm=text/modality/condition/scope、RightsLicenseTerm=scope/exclusivity/sublicensing/commercial_use/condition、Commitment=action/object/modality/condition/scope（actor=unknownもL3）、personal_dataのTextClaim=text。explicit以外はL3 + CRITICAL_MISSING_INFORMATION。唯一の例外は`DateTerm.type=date`の`timezone=not_stated`。
- approve/modifyの境界（§14.2）: 条項・権利/ライセンス・PIIのapprove、および実質差のないmodifyは識別不能としてminimum L2 + UNCLASSIFIED_RISK。実質差（id/evidence_idsの差を除く）のあるmodifyだけCONTRACTUAL_CHANGE / NEW_GUARANTEE / REFUND_OR_CREDIT / RIGHTS_OR_LICENSE_CHANGE / PERSONAL_DATA_DISCLOSUREを記録。Commitmentはactor=user（元・有効値のいずれか）ならNEW_COMMITMENT、counterparty/third_partyのみならUNCLASSIFIED_RISK。
- policy exception（§14.3）: `Risk.type=policy_exception`はどのRisk配列にあってもL3 + POLICY_EXCEPTION。resolved=true・approve・modify・do_not_answerで解除しない。
- L3優先: L2理由が同時に発火しても降格せず、発火した理由をすべて記録する。
- L0/L1は積極的確認が必要（§12.6-8）。ルール未発火だけではL0にしない。非重大ClaimのTextClaim/Question本文がexplicit以外、Emotion.targetがunknown/ambiguousならL2。
- **回答契約（SCHEMA §13 / DELEGATION §15）**: `Decision.question_answers`に回答本文・根拠（user_assertion / source_evidence）・参照・承認主体を記録し、decision hashへ含める。質問のapprove/modifyだけでは回答確定にならず、有効な回答もdo_not_answerもなければ最低L2＋`UNCLASSIFIED_RISK`。有効な回答が1件でもあれば独立意味検証がないため最低L2＋`ANSWER_REVIEW_REQUIRED`。回答があってもL3条件は解除しない。
- RiskFactorsは§12・§15の文言から導く。impactは識別済みの新規重大約束/変更でhigh、判定不能（重大Decision保留・識別不能な条項・未知添付・矛盾する既往義務・未記録の回答）でunknown、新規重大義務のない個別回答でmedium（basisを問わない。source_evidenceのquote参照は回答の意味を証明しないため既知情報のlowにしない）、受領・通知のみでlow。irreversibilityは外部義務・権利変更でhigh、その他の新規約束でmedium、義務を否定できない場合unknown、約束なしでlow。uncertaintyは未解決重大でhigh、未解決非重大または回答ありでmedium、それ以外はlow。customer_sensitivityは法的/公開苦情でhigh、その他の感情・評判リスクでmedium、なしでlow。
- その他（既存の維持）: 単なる金額言及（price/payment/fee/other）と承認済み約束の区別、感情はL1・複合でL2、Evidence.quoteは本文/件名の完全一致部分文字列、金額・数量の負数拒否、事前判定段階のreply由来Evidence拒否。

## 通貨（SCHEMA §12.3）

`reference/iso4217/` にSIXの原本と`manifest.json`（取得日時・HTTP結果・content type・形式・構造マーカー・原本hash・抽出条件・採用一覧hash・除外根拠）を固定。実行時は同ディレクトリのmanifestを読むだけで、通信も自動更新も行わない。集合版は`rg-iso4217-20260915-f581922d2a56`（155コード）。**2026-09-16 Architect承認済み。**

| 原本 | 役割 | 形式 |
|---|---|---|
| `list-one.xml` | List One（現行通貨・基金）。採用集合の正本 | XML |
| `list-two.doc` | List Two（Maintenance Agency登録の基金コード）。分類の裏付け | MS Word（OLE） |
| `list-three.xml` | List Three（廃止通貨）。廃止コードの照合 | XML |

`relayguard.currency.verify_stored_originals()` が保存済み原本のhash・形式・構造マーカーを再検査する。HTMLエラーページは拡張子やcontent typeにかかわらず必ず拒否する。

2026-09-16の訂正: 以前保存していた`list-two.xml`はSIXのsoft-404（HTTP 200で返るHTMLエラーページ）だった。抽出には一度も使っていないが、補助原本としては無効なため削除し、公式ページが公開している`.doc`を再取得した。List TwoはUYWとXADを基金コードとして掲載しており、両者の除外根拠が裏付けられた。採用155コードは変更なし。

## 期待値の区分（`fixtures/sg001/expected.json` 35件）

`approval_status`で審査対象を区別する。100件Release Gateの代替にはならない。

| status | 件数 | 意味 |
|---|---|---|
| `gold_proposed` | 22 | 承認済み15件（0.5移行後の再確認）＋ADR-025の修正4件＋回答付き新規2件 |
| `regression` | 12 | 入力を保持した回帰記録。旧版入力・回答なしの必要質問approve・境界入力 |
| `structural_only` | 1 | `structural_coverage`。構造変異テストの土台で、意味の正解ラベルではない |

## 未確定（Architect判断・承認待ち）

- Gold候補22件の承認（0.5移行により承認済み15件も版/hashが変わるため再確認が必要）。
- False Escalationの増加量（§14.1受容済みだが未測定）。
- 回答の意味検証・回答網羅検証は後半機能でNOT_RUN。SG-001は記録・承認・参照・hash・事前判定のみ。

通貨集合`rg-iso4217-20260915-f581922d2a56`（155コード）は2026-09-16にArchitect承認済み。
