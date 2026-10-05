# RelayGuard 要件定義書 v1.1

Status: REQUIREMENTS BASELINE FROZEN  
確定日: 2026-09-15  
決定責任: GPT Work / System Architect  
製品仕様の唯一の入口: [SPEC_INDEX.md](SPEC_INDEX.md)

本書はCurrent Core Specsの統合要件であり、独立した別正本ではない。構造契約はSCHEMA.md、具体的委任判定はDELEGATION.md、評価はEVALUATION.mdを参照する。文書確定は実装完了・試験合格・Release承認を意味しない。

## 1. 目的・対象ユーザー・課題

RelayGuardは、AIの理解・判断・約束をユーザーの言語で監督・修正・承認できるDelegation Control Layerである。MVPは日本語ユーザーによる英語メール返信判断に限定する。
初期ユーザーは日本語では意思決定できるが、英語の金額・期限・契約・権利等を十分に直接検証できない人。将来の事業者・エージェント運用者向け展開は仮説であり、今回の機能追加ではない。

最重要課題は、AIが危険な意味変更をしてもユーザーには安全に見えること。GeneratorとVerifierの相関失敗、無断の約束、stale承認、L2/L3案件のL0/L1誤分類を防ぐ。同時に全件を人間確認へ戻すだけでは委任価値を満たさない。
目標は「重大事故率を増やさず、人間確認率を下げる」。MVPでは実自動化ではなく、省略可能だった確認をShadow Modeで測る。AIの普遍的正しさや商業的成功を保証しない。

出典: PRD.md §§1–4,9,15、THREAT_MODEL.md §§1,4。

## 2. 製品と開発段階

ShadowGuardは別製品Domainではなく、RelayGuardのShadow Mode / SHADOW_GATEまでの開発段階。

| 段階 | 対象 | 完了・停止 |
|---|---|---|
| SG-001 | offline fixtureから構造検証、Approved Decisionとのbinding、事前委任判定、結果・監査metadataを得る最小経路 | §16のSG-001受入条件を満たす。実装は今回行わない |
| Shadow段階 | Schema/Domain、型付き比較、評価runner、固定100件、Policy/Delegation、Shadow記録・指標 | ../docs/SHADOW_GATE.mdの条件成立時に停止し結果を報告 |
| 後半MVP | 原文入力、Interpretation、意思決定UI、Generator、独立Reply Extractor/Verifier、Final Approval、コピー、パイロット | SHADOW_GATE後の明示的人間承認が必要。許可前に本格実装しない |

fixtureによるpost検査や偽providerは実LLM検証ではない。未実装段階はNOT_RUN。100件の事前判定が通っても全MVP Release合格とは呼ばない。SHADOW_GATEの本文・到達条件・再開条件は変更していない。

## 3. 成功条件

| ID | 必須成果 | 証拠 |
|---|---|---|
| SC-01 | 日本語だけで要求・重要条件・約束・不明点を判断できる | 後半パイロット10件以上と独立意味照合。実施前は未確認 |
| SC-02 | 定義されたCritical意味変更を安全として通さない | EVALUATION.mdのrelease-set、challenge-set、各Release blocker。集合外の安全保証ではない |
| SC-03 | ユーザーが最終意思決定権を保持 | trusted承認、version/hash、失効・迂回・競合テスト |
| SC-04 | 本来確認を省略可能だったcaseを実際の介入と区別して測れる | predicted level / actual intervention / outcome / 独立判定を記録 |
| SC-05 | 安全性を悪化させず不要な確認を減らす | 同一条件のbaseline比較。全件L2/L3化を価値検証成功としない |

具体的な指標分母・欠損・N/A・反実仮想の判定責任はEVALUATION.md §13に固定。MVPは最終承認を保持するため、L0予測を実際の自動化実績として報告しない。

## 4. MVP範囲・非範囲

範囲: 英語本文貼付 → Interpretation → 日本語Decision Sheet → ユーザー判断 → Approved Decision → 事前Delegation → 返信生成 → 独立抽出／typed diff／Verifier → Policy・事後Delegation → Final Approval → Copy。処理中の不正・不明・停止条件は各段階で実強制する。

非範囲: 自動送信、返金実行、購入、契約実行、無承認外部操作、Gmail OAuth/Draft、添付本文解析、URLクロール、組織/RBAC、workflow builder、長期メモリ、自律ループ、大規模分析ダッシュボード、不必要なマイクロサービス化。
アプリ内のDraftは範囲内、外部メールサービスへのDraft作成は範囲外。添付依存の検出は行うが、内容を推測しない。Product Manifest、SDK/API商品化、商品選定・代理交渉は将来仮説。

出典: PRD.md §§5,12,14、IMPLEMENTATION.md §§21–24。

## 5. 機能要件

| ID | 必須動作 |
|---|---|
| FR-01 | sourceを非信頼データとして受領し、入力上限・原文hash・安全な保存を適用 |
| FR-02 | 重要値・質問・要求・約束・リスク・不明点を構造化しEvidenceで原文と結ぶ |
| FR-03 | Decision Sheetでapprove / modify / unknown / do_not_answerを明示操作 |
| FR-04 | immutableなApproved Decisionをtrustedユーザー操作から確定。Interpretationを意思と混同しない |
| FR-05 | 生成前と検証後の2回Delegation判定。minimumとpost単調性をDomainで強制 |
| FR-06 | 承認済み意思から英語Draftを生成。金額・期限・権利・返金・保証・PII開示を無断追加しない |
| FR-07 | 独立Reply Extractorが最終返信から構造化値・約束・条件を再抽出 |
| FR-08 | 重要値、権利、条件、禁止事項、回答網羅、bindingをtyped diffで比較 |
| FR-09 | Verifierが条件脱落、隠れた約束、意味欠落、矛盾、断定、感情・法的含意を検査 |
| FR-10 | PolicyがBLOCK / SAFE_CANDIDATEを決定。Verifier単独のmatchedでは安全にしない |
| FR-11 | 最終承認時に主体・Decision/Draft/Verification/Assessmentの最新bindingを再確認 |
| FR-12 | SAFE_CANDIDATEを最終承認してコピー。外部Actionは実行しない |
| FR-13 | Source/Interpretation/Decision/Draft/policy変更に応じて下流結果・承認を失効 |
| FR-14 | 主体・case・操作に束縛したIdempotency-Keyと同時実行制御 |
| FR-15 | 入力から判断・生成・検証・委任・承認まで版とhashで監査可能 |

Decision Sheetは相手の目的、要求、回答必須質問、金額/通貨/日付/期限/数量、契約/ライセンス/権利/禁止事項、保証/返金/キャンセル、相手とこちらの約束、個人情報、感情/ブランド/法的主張/過去約束の矛盾、リスク、不明、推奨アクション、人間判断要否、信頼度を扱う。配列要素型はSCHEMA.md §3。

## 6. Delegation L0–L3

| 正式値 | 意味 | MVPの実効制約 |
|---|---|---|
| L0_AUTO | 人間確認なしで処理可能という推奨 | Shadow記録のみ。最終承認・コピー経路を維持 |
| L1_POST_REVIEW | AI処理後の人間確認という推奨 | Shadow記録のみ。事後確認を口実に最終承認を省略しない |
| L2_PRE_APPROVAL | 実行前承認 | Approved Decisionと検証後Final Approvalを実強制 |
| L3_STOP | 停止・エスカレーション | 生成・承認・コピーを禁止。原因解消と新bindingでのみ再評価 |

minimum rulesはDELEGATION.md §4を維持。法的主張、未解決injection、重大欠落、必要添付欠落、約束矛盾、Critical diffはL3。返金/クレジット、契約/権利/ライセンス変更、保証新設、material金額/期限変更はminimum L2。
SD-10で未定義だったmaterial、数量、PII、新規約束、policy exception、L0/L1境界、感情複合条件、補助riskの解釈はDELEGATION.md §12で固定した。金額大小でminimumを免除しない。confidenceで降格しない。

新しい回答を発明しない明示do_not_answerは質問網羅性に記録するが、重大な不明・法的主張・必要添付の解除には使わない。legal_claimが存在する案件はMVPではL3のまま手動対応。L3を一括承認で解除しない。

## 7. 安全要件

- SEC-01: 外部メール・引用・署名・添付言及・URLを命令とせず、policy/approval/tool権限を変更できない。
- SEC-02: LLM出力はSchema → Domain → cross-field → Policy検証後に採用。
- SEC-03: Generator、Reply Extractor、Verifierを独立コンテキスト・別実行とし、生成側の内部推論・会話・自己評価を検証側へ渡さない。
- SEC-04: represented_stateは生成側の自己申告。単独で安全証拠にしない。
- SEC-05: Critical typed diffはVerifierがmatchedでもBLOCK。不正・必要情報不足・矛盾はFail Closed。
- SEC-06: Approved Decisionが意思の正本。逆翻訳・自然文を正本にしない。
- SEC-07: null / unknown / not_stated / ambiguousを区別。silent coercion・無権限確定を禁止。
- SEC-08: version/hash、対象ID、case、競合、replay、staleをサーバーで検証。
- SEC-09: provider failureで旧safe結果をsilent reuseしない。
- SEC-10: raw PIIの運用ログ流出とclientへのsecret露出を禁止。
- SEC-11: authz、CSRF、XSS、injection、PII、replay、stale、idempotency、approval bypassを検証。

Evidence一致は解釈の正しさを証明しない。構造的PASSだけで製品が安全と判断しない。出典: THREAT_MODEL.md、ADR.md、SCHEMA.md。

## 8. 非機能要件・制約

モジュラーモノリスとrole別Provider Adapterを維持。特定モデルやSDKをdomainへ埋め込まず、prompt/schema/policyを版管理する。
技術の第一候補は既存ADR-018のTypeScript中心構成。モデル・配置・内部ファイル構造・helper・テスト配置の選択は契約を満たす担当者裁量。

確定した運用値・要件はIMPLEMENTATION.md §23: source上限64 KiB、LLM試行は全体予算の残り（2026-09-20裁定D-2。旧規定60秒）・Schema修正再試行1回・全体300秒（2026-09-23裁定D-7。旧規定120秒。試験用の上限）、主体/case/操作別idempotencyを24時間保持、PII通常保存30日・backup30日以内・非本文監査90日上限、case所有者隔離、保存/転送暗号化、秘密鍵分離、監査chain検査、競合書込拒否。
これらは新しいUI機能の追加ではなく、既存の保護・障害要件の具体化。初期開発はoffline合成/匿名化fixtureとし、実メール・実provider利用をSG-001の必須条件にしない。
商用SLA、売上、モデル精度を未検証の約束として追加しない。費用・latencyを測定し、安全検査を省略して性能を上げない。

## 9. 主要データ・状態

SourceMessage、Interpretation、Evidence、各typed Claim、DecisionItem/UserProvenance、Approved Decision、Binding/DraftBinding、DelegationAssessment、Draft、ReplyExtraction、DiffResult、Finding、Verification、FinalApproval、ShadowOutcome、AuditEvent、ModelExecution、Failureが主要契約。

詳細のrequired/enum/null/追加property/参照/hash/権限はSCHEMA.md v0.5。旧v0.2 JSON例の欠落をoptionalとして解釈しない。Builderは文書契約を実行可能なSchemaとDomain検証へ実装する。
decision_hashはglobal UNIQUEにしない。同じhashでも別case/versionを混ぜない。ユーザー修正は元原文と分離して出典を持つ。

正常系の状態はNEW → INPUT_READY → INTERPRETING → DECISION_REQUIRED → DECISION_APPROVED → DELEGATION_ASSESSED → GENERATING → DRAFT_READY → VERIFYING → SAFE_CANDIDATE → FINAL_REVIEW → FINAL_APPROVED → COPIED。
BLOCKEDからFINAL_REVIEWへの直接遷移は禁止。原因を解決し新bindingで再検証してから、新しい最終承認を取得する。
エラー分類はSCHEMA.md §9。rejectedは失敗、L3のassessedは停止判定が正常に得られた結果であり、処理の安全な実行完了ではない。

## 10. 外部境界

TB1 外部メール→Core、TB2 Core→LLM Provider、TB3 LLM出力→Domain、TB4 Generator→Verifier、TB5 Verifier→Policy、TB6 Policy→UI、TB7 Core→将来Action Gatewayを区別する。TB1/3/4/5の入力は非信頼。UI単独で安全判定を変えない。

APIは既存IMP §8のcase/interpretation/decision/delegation/draft/verification/final-approval/auditに限定する。型・bindingはSCHEMA.md、認証・所有権・競合はIMP §23が規範。
将来Action Gatewayはexplicit approval、immutable payload、action hash、idempotency、account binding、token vault、audit、stale rejection、least privilegeが必要。MVP外であり、今回設計・実装を拡張しない。

## 11. UI要件

メール貼付、Decision Sheet、返信案、差異確認、最終承認・コピーを扱う。重大判断・Critical findingは日本語のみで理解可能とし、原文/英文は展開して閲覧できる。
「安全です」でなく「定義済み検査を通過」と表示。confidenceを大きな緑色スコア等で安全性の代理にしない。不明・blocked・stale・loading・error・empty・disabledを区別し、委任レベルと日本語理由、自動実行されないことを明示する。
キーボード操作、フォーカス、意味のあるラベルとエラー通知を重要操作に適用する。具体的なページ分割やcomponent実装は担当者裁量。UI本格実装はGate再開承認後。

## 12. 評価・Release Gate

release-setは20カテゴリ×5変種の固定100件。challenge-setはReviewer専用private storageでBuilderへ事前公開しない。incident-setに事故/near missを蓄積する。全カテゴリ・変種はEVALUATION.md §§4–5を正本とする。
毎PRのfull回帰、変更時の再評価、phase別NOT_RUN、fixture正解管理、指標定義はEVALUATION.md §§10,13–14。

Release blockerはCritical unsafe-pass、numeric mutation miss、無承認約束、返金/保証/権利/ライセンス見逃し、stale/approval/browser-only/injection bypass、L2/L3→L0/L1誤分類、raw PII運用ログ漏洩、provider障害でのsafe再利用、challenge重大見逃し、未解決Critical Reviewer finding。すべて0が必須。severityで範囲を狭めない。
false escalation・minor omission・style・latency・token cost単独はRelease blockerではない。これらを改善しても安全Gateを緩めない。

Schema、Domain、typed mutation、property、LLM contract、API integration、E2E、security、監査、委任回帰を各対応段階で検証する。未実装・未実施はPASSではない。SHADOW_GATEの人間判断を自動Release判定で置き換えない。

## 13. 監査・Observability

入力hash、Interpretation/Decision版、Decision hash、両委任判定、model/provider role、prompt/schema/policy版、Draft hash、Verification/findings、FinalApproval、時刻を追跡可能にする。
運用指標はrequest、latency、provider error、schema retry、block、level counts、human review、false escalation、final approval、stale rejection、eval pass/fail。
raw email/reply、email address、氏名、契約全文、LLM prompt全文は運用telemetryへ送らない。監査も無制限な本文保存場所にしない。保持と暗号化はIMP §23に従う。
独立監査はシナリオ、発生条件、影響、検出可能性、現防御、突破方法、修正、回帰を記録し、Critical/High/Medium/LowとRelease時期で分類する。Generator/Verifierの相関失敗を優先する。

## 14. Specification defectの決定結果

ここでのRESOLVEDは仕様判断が完了した意味であり、実装検証PASSではない。SD履歴は次の決定とCurrent本文で追跡する。

| ID | 状態 | 決定・規範所在 |
|---|---|---|
| SD-01 | RESOLVED | Current版はSPEC_INDEXのみ。IMP §22の旧版固定参照を更新 |
| SD-02 | RESOLVED | Core7件と補助資料を分離。BUILDERの正本リストをINDEX参照へ統一 |
| SD-03 | RESOLVED | Approved Decision後に事前判定、MVP外部Draft禁止。Context等の歴史的記述は非規範 |
| SD-04 | RESOLVED | BLOCKED→FINAL_REVIEW直接経路を削除。新bindingで再検証。IMP §§10,24 |
| SD-05 | RESOLVED | 毎PR full100、smokeは代替不可。EV §13 / IMP §14 |
| SD-06 | RESOLVED | numeric miss・L2/L3誤分類のseverity限定を除き既存の強いGateへ統一 |
| SD-07 | RESOLVED | SCHEMA v0.3で全主要型、required、closed object、enum、Evidence、出典、metadata、binding、拒否条件を確定 |
| SD-08 | RESOLVED | L2二段承認、L3は原因解消・新binding、legal claim免除なし。DP §13 |
| SD-09 | RESOLVED | do_not_answerとunknownを区別、修正出典はUserProvenance。SCHEMA §4 |
| SD-10 | RESOLVED | DP §12の明示的L0/L1条件と安全側minimum。数値スコアで自動降格しない |
| SD-11 | RESOLVED | EV §§13–14で分母、正解責任、NOT_RUN、phase、パイロットを定義 |
| SD-12 | RESOLVED | IMP §23で主体隔離、PII、保存、監査、競合、idempotency、上限/障害を定義 |
| SD-13 | RESOLVED | 要件確定、SG-001、Shadow Gate、MVP Releaseを別の判定として表示 |

根拠・理由・トレードオフはADR-019〜022。未対応の新事実が出た場合は新しいspecification defectとして扱い、Builderが期待値を緩めて埋めない。

## 15. 未決事項の扱い

製品挙動・安全境界に関する既知SDは上記で確定した。以下は要件不足として放置する項目ではなく、実装・運用開始時に満たす選定条件である。
- provider/model、hosting、DB実装、暗号鍵保管製品、認証ライブラリ：Current契約を満たすものを担当者が選ぶ。実データ利用前に適合を確認する。
- 実LLM精度、独立QA、パイロット結果：未実施。結果が不合格なら該当段階は完了しない。
- 後半開始、外部自動化、MVP拡張、価格・販売形態：今回決めない。人間判断または別Task。
- 既存tasks/current.md等に旧DomainのTaskが残る場合は実装根拠にしない。SG-001の新契約は§16とSCHEMA.md §10。

## 16. 受入基準

| ID | 条件 | 期待結果 |
|---|---|---|
| AC-01 | 日本語のみの後半パイロット | §3 SC-01、EV §14を満たす |
| AC-02 | 欠落/追加property/enum/型/ID/nullable/decimal/date不正 | 拒否、silent coercionなし |
| AC-03 | Source/Interpretation/Decision変更後の旧結果 | 下流stale、旧承認無効 |
| AC-04 | hash/対象/case/version不一致 | サーバーで拒否 |
| AC-05 | Critical typed mutation、Verifier matched | BLOCK、L3 |
| AC-06 | 未承認の割引/返金/保証/約束 | 検出・BLOCK |
| AC-07 | legal/injection/重大欠落/添付欠落/矛盾 | L3。入力不正ならrejected、L0既定値なし |
| AC-08 | L2承認対象 | Approved Decisionと最終承認を実強制 |
| AC-09 | L0/L1予測 | Shadowのみ、外部実行なし |
| AC-10 | メール内攻撃指示 | policy/approval/権限を書換え不可 |
| AC-11 | Generator自己申告/内部推論 | 独立検証側へ流さない |
| AC-12 | timeout/partial/Schema再試行枯渇 | 明示エラー、旧safeを流用しない |
| AC-13 | idempotency/replay/競合 | 同scope同入力は同結果、異入力conflict、二重確定なし |
| AC-14 | PIIを含む正常/異常処理 | operational log漏洩なし、保存・所有権要件適合 |
| AC-15 | 監査・binding改変 | 追跡可能、改変・chain不整合で承認拒否 |
| AC-16 | 100件/独立challenge回帰 | blocker=0、未実施をPASSにしない |
| AC-17 | blocked/stale/unknown/委任表示 | 日本語で理解可能、安全・自動化の誤認を誘わない |
| AC-18 | Shadow outcome/KPI | Gold/予測/介入/結果を分離、欠損とN/Aを正しく表示 |

### SG-001の確定した引渡し要件

Goal: SCHEMA.md §10のoffline入力から厳格検証、Decision binding、事前委任判定、監査metadataを得られる最小実行経路。
Constraints: Core7仕様、安全不変条件、旧Domain排除、network/外部Actionなし、L0既定fallbackなし。
Acceptance Criteria:
1. 正常なL0/L1/L2/L3 fixtureがDELEGATION.md §12の期待結果になる。
2. 全required/enum/型/追加property/参照/出典/hash/policy versionの不正をrejectedとする。
3. 同じ入力・policyの判定level/reason/minimumは同じ。実行時刻や実行IDの差を判定非決定性と混同しない。
4. sourceから承認を偽装できない。fixture承認を実ユーザー承認と表示しない。
5. legal、未解決injection、重大unknown、必要添付、矛盾を低レベルへ落とさない。
6. resultとauditに必要な版/hash/理由があり、raw PIIを運用ログに出さない。
7. 対応するlint/typecheck/unit/contract testsを通す。まだない後半検査を合格表示しない。
Out of Scope: UI、DB、実LLM、Generator/Reply Extractor/Verifier本実装、Final Approval本実装、外部連携、100件runner本体、次Taskの自動実装。

Taskファイルの配置と実装細部は担当者裁量。本書の確定だけでClaude Codeへの外部メッセージ送信や実装起動を行わない。

## 17. Builderへの前提

構造契約は文書として確定済みであり、実行可能JSON Schema・validator・fixture・テストはBuilderの実装成果。コードを作ったことと安全評価完了を区別する。
新機能、MVP拡張、安全/Release Gate緩和、SHADOW_GATE解除は人間承認なしに行わない。仕様に反しない内部実装は自律判断し、製品挙動の新しい不足だけSPEC_BLOCKEDとして返す。
ReviewerはRepository・Current仕様・監査プロンプト・private challengeを使い、Builderの会話・内部推論・自己評価を根拠にしない。

## 18. 確定の限界

この改訂は要件・Architect判断・関連Current文書の整合化のみ。実装、実モデル評価、実メールパイロット、独立セキュリティ監査は実施していない。
安全要件とRelease Gateを緩和せず、docs/SHADOW_GATE.mdを維持する。次工程は確定契約に基づくSG-001の実装であり、今回その実装は行わない。
