# RelayGuard ADR v0.3

## ADR-001 MVPはモジュラーモノリス
単一デプロイを維持しつつ、Intake / Interpretation / Decision / Delegation / Generation / Verification / Policy / Approval / Audit / Provider Adapterへ分離する。

## ADR-002 LLMは信頼境界の外
LLM Output → Schema Validation → Domain Validation → Policy Check → State Transition を必須とする。

## ADR-003 GeneratorとVerifierを独立
別プロンプト・別コンテキスト・別実行。VerifierへGenerator内部推論を渡さない。

## ADR-004 Capability Roleでモデルを扱う
Interpreter / Generator / Verifierとして抽象化し、特定モデル名をdomain logicへ埋め込まない。

## ADR-005 Approved Decision Stateを意思の正本とする
自然言語返信や逆翻訳ではなく、versioned Decision StateをCanonical Sourceとする。

## ADR-006 全状態遷移をVersion/Hash Binding
Decision変更時は既存Draft / Verification / Final Approvalを失効。

## ADR-007 Fail Closedはサーバー側Domain Rule
UI警告だけでは回避不能。

## ADR-008 Prompt Injection対策は検出だけに依存しない
外部メールからpolicy/approval/tool permissionを変更できない構造にする。

## ADR-009 Audit LogとOperational Logを分離
Operational Logへraw email/PIIを原則送らない。

## ADR-010 外部ActionはMVP Coreから分離
Read → Interpret → Decide → Delegate → Generate → Verify → Approveまで。
Send等は将来Action Gateway。

## ADR-011 Evaluation Setをアーキテクチャ資産として管理
release-set / challenge-set / incident-setに分離。

## ADR-012 開発AIはArchitect / Builder / Reviewerへ役割分離
ReviewerへBuilder会話履歴を渡さない。

## ADR-013 Delegation Policy Engineを独立Domain Componentとする
委任レベル L0/L1/L2/L3 はGenerator/Verifierの副産物ではなく独立したPolicy判定とする。

### 理由
委任レベルは安全性・事業価値の中心であり、LLMの一時的自己評価に依存させられない。

### 他案
Verifierが直接delegation levelを返す。

### 採用理由
ルールベースのminimum level、LLM補助、組織ポリシーを分離できる。

## ADR-014 MVPではDelegationをShadow Modeで評価
L0/L1判定でも自動外部Actionを実行しない。

### 理由
委任判定性能を先に評価し、誤分類による実害を防ぐ。

## ADR-015 安全性KPIと自動化KPIを分離
Critical Incident RateとHuman Review Rateを同時に測定する。

### 理由
安全だけを最大化すると全件人間確認になり、製品価値を失うため。

## ADR-016 Deterministic DiffがLLM判定に優先
Critical typed mismatchがあればVerifierがmatchedでもBLOCK。

## ADR-017 顧客感情は補助信号、単独決定要因にはしない
怒り等だけでL3にしないが、金銭・解約・契約等と組み合わせて委任レベルを引き上げる。

## ADR-018 技術スタックはTypeScript中心を第一候補
Next.js / TypeScript / PostgreSQL / JSON Schema + Ajv / Vitest / Playwright / OpenTelemetry互換を推奨するが、製品要件が変われば再評価する。

# Architecture Invariants

1. 外部入力を信頼しない。
2. LLM出力を信頼しない。
3. Approved Decisionを意思の正本とする。
4. Generator / Verifierを分離。
5. Delegation Policyを独立させる。
6. 重大情報は型付き比較。
7. 不明を安全扱いしない。
8. Version/Hash binding。
9. Fail Closedをサーバー強制。
10. 外部Actionは別Trust Boundary。
11. SafetyとAutomationを別KPIで測定。

## ADR-019 要件ベースライン確定（2026-09-15）

Status: Accepted / Architect decision。製品入口はSPEC_INDEX.md。要件の統合はREQUIREMENTS.md、構造契約はSCHEMA.md v0.3、委任判定はDELEGATION.md v0.2、評価はEVALUATION.md v0.2に定義する。
理由: SD-04〜12を実装者が推測すると安全性・期待値・データ整合性が分岐するため、実装前に契約を固定する。
決定: 型・意味・承認・安全判定を分離し、初期のShadow実装と後半の外部入力/生成/承認フローを同一Domainの段階として扱う。旧例への暗黙互換は持たない。
採用しない案: 任意JSONを受理してLLMの判断へ委ねる、旧ShadowGuardのDomainを再利用する、BLOCKEDを人間の一括承認で解除する。
トレードオフ: v0.3 fixtureの更新が必要。未知情報を保守的に停止するためfalse escalationは評価して改善するが、安全ルールは緩めない。
再検討条件: Current仕様変更・独立監査の反例・実運用の新要件。自動化解放やMVP拡張は人間承認を必要とする。

## ADR-020 構造・承認の境界（SD-07/08/09）

SCHEMA.mdの全フィールドはrequired・closed objectで、追加propertyや暗黙coercionを拒否する。JSON Schemaだけで表現できない参照・hash・出典・権限はDomainで検証する。
Approved Decisionはユーザー操作からDomainが発行する。LLMは承認状態を付与できない。ユーザー修正は原文の書換えではなく、UserProvenanceで追跡する。
明示do_not_answerは回答を発明せず質問網羅性に記録する。重大な不明・法的主張・添付依存・injectionの解除には使わない。
L2はDecision承認とMVP最終承認を必要とし、L3は原因解消後の新bindingでのみ再判定する。legal_claimが存在する案件はMVP内でL3解除しない。

## ADR-021 評価の非緩和（SD-05/06/11）

毎PRでfull release-set、severityを問わないnumeric mutation missおよびL2/L3→L0/L1誤分類ゼロを既存仕様の強い側から採用する。欠損・NOT_RUNをPASSへ数えない。post機能未実装のShadow評価をMVP Release合格と呼ばない。
KPIはEVALUATION.mdの分母と正解評価者を固定し、fixtureと実観測を分ける。過剰停止だけで成功としない。

## ADR-022 実装裁量と運用境界（SD-12/13）

構造契約と製品挙動は本ベースラインに従う。内部API・ファイル配置・helper・テスト配置はBuilderが選べる。モデルやホスティングの銘柄は要求として固定しないが、IMPLEMENTATION.md §23のアクセス・PII・障害要件を満たすこと。
SHADOW_GATEの条件・禁止事項は変更しない。SG-001着手可能は全MVPの完成・Release可能を意味しない。

## ADR-023 SG-001の実装技術（2026-09-15）

Status: Accepted / 人間指示による技術選択。ADR-018のTypeScript中心構成は第一候補のまま変更しない。
決定: SG-001はPython 3.14で実装する。構造検証はJSON Schema（`packages/schemas/v0_3`）+ `jsonschema`、テストは`pytest`、金額比較とhashは標準ライブラリ`decimal`・`hashlib`、静的検証は`ruff`・`mypy`（プロジェクト専用`.venv`）。Node.js/TypeScript環境は導入しない。
理由: 実行環境にNode.jsがなく、既存のPython環境で契約と安全要件をoffline検証できるため。
影響: Schema・Domain・Policyの契約は変更しない。将来のTypeScript移植は今回の必須条件にしない。Antigravityは同じPython環境で独立検証する。

## ADR-024 SG-001保留判断の仕様反映（2026-09-16）

Status: Accepted / Architect decision。SCHEMA.md v0.4 §12、DELEGATION.md v0.3 §14を採用する。旧ADR-019の版指定を本決定で更新する。
DateTerm例外はtype=dateだけ。重大修飾値の欠落は保守的に停止する。識別不能なapproveは最低L2、actor=userの約束引受けと相手の約束を区別する。policy exceptionは許可検証経路のないSG-001でL3固定。変更をschema 0.4 / delegation-0.3へまとめ、旧版の暗黙受理を禁止する。
SIX公開原本の一度の取得をBuilderへ許可し、保存・版・hash・抽出規則はSCHEMA §12.3に従う。これはアプリの通信許可ではない。
仕様反映は完了。通貨集合の照合、実装修正、期待値再審査、正式QAは未完了。過剰停止増加を承知して採用し、原文にないexplicit値の捏造を禁止する。SHADOW_GATE・MVP範囲・Release条件は変更しない。
## ADR-025 質問回答の独立記録とGold審査（2026-09-16）

Status: Accepted / Architect decision。SCHEMA v0.5 §13、DELEGATION v0.4 §15をCurrentとする。schema_version=0.5 / policy_version=delegation-0.4。ADR-024の安全条件・通貨承認を維持する。
Decision.question_answersで質問解釈の承認と回答内容の承認を分離する。本文・出典・参照・主体をhashへ束縛する。自由文の独立意味検証がないSG-001では回答付き案件は最低L2。後半機能を先行実装しない。これにより回答確定表現のSPEC_BLOCKEDを仕様上解決するが、実装・独立QA完了ではない。

### 提出32件中Gold候補19件の審査（旧0.4 / delegation-0.3）

15件のlevel/minimum/reason_codes/risk_factorsを提出された構造化入力に対する事前判定Goldとして承認する。原文からの抽出完全性や返信安全性の評価を代用しない。
承認: l0_calendar_day_notice、l0_required_question_do_not_answer、l2_clause_approved_unidentifiable、l2_clause_modified_same_value、l2_clause_modified_substantively、l2_personal_data_modified、l2_refund_commitment_stated、l2_required_question_unknown、l3_ambiguous_currency、l3_commitment_actor_unknown、l3_critical_decision_unknown、l3_deadline_timezone_not_stated、l3_injection_marked_resolved、l3_legal_claim、l3_policy_exception_marked_resolved。
CHANGES_REQUESTED:
- l1_emotion_only_notice: 原文にthree days lateがあり怒りと過去遅延対応の複合。L2/minimum L2、CUSTOMER_SENSITIVITY。元入力を残し、L1正常系は過去誤対応等を含まない別原文で作る。
- l2_counterparty_commitment_accepted: Let us know if that works for youという回答依頼の抽出が欠落。Questionと明示的なDecisionを追加し、未回答と引受けを混同しない。元の相手Commitmentのみからユーザーの合意を作らない。
- l3_attachment_required: L3/理由は維持。未知の契約添付に依存するためimpact/irreversibility=unknown、uncertainty=high、customer_sensitivity=low。
- l3_prior_commitment_conflict: L3/理由は維持。矛盾する既往義務の影響を確定できないためimpact/irreversibility=unknown、uncertainty=high、customer_sensitivity=low。
regression10件・structural_only1件はGold承認対象外。spec_blocked2件は新契約で回答を実際に記録した別入力として再提出する。回答内容をArchitectが推測して埋めない。
0.5へのfixture移行は明示的な作業とし、承認済み15件も版/hash/追加配列変更後の整合確認を行う。0.4入力のランタイム自動変換は禁止。SG-001完了承認・版固定・独立QAは未実施。
審査対象expected.json SHA-256: 99493015a91a6d3715f31e4652fdfbbaea11d48ee62e02c4a194d084ebeb7f0c
- l0_calendar_day_notice: cf973e9d0f5bf059b755bb07d262a63ddfe8e386a17dc23d7d5928d315a773ec
- l0_required_question_do_not_answer: 13e9af54a0cc5f27678166803d9d0f41c480c08153cf0ea1c6d12c9406382bec
- l1_emotion_only_notice: f0aead1269a6b104f70be06af22d6cd7fe686bce317c3a103527d4960824fbb5
- l2_clause_approved_unidentifiable: 784af8a1abe114941cb5e8ba261ea1cb3e9d3ffaeb6015c0fa047945f0d53d80
- l2_clause_modified_same_value: aceac88013888d44a0ccf4f245f363ec13debeac1a6f70bff5990f94f15f301d
- l2_clause_modified_substantively: 27735d0d1722a9b7d73e7c38174939c8a5861efb8cf8734b65f2229a0f6aa04f
- l2_counterparty_commitment_accepted: 3c46777f34f381401d3019dcffb0e1455eaf594329226ef8bcc4a2898c6fd7f3
- l2_personal_data_modified: fa8b8c90f05de026874757f4e5943ee3cab0441c99a1efec93c83d565dfb4783
- l2_refund_commitment_stated: d026e319ff5f626548a25ea8d54e214753fe1861a1ea6f798f686d28d57368e9
- l2_required_question_unknown: bbea2ba447fb7ab6e85ed58cc3e067dfb6377273c75dad3126e821b146055e21
- l3_ambiguous_currency: 492e30868106cb7e4bc50ffacc707f837295ee598d2a58f64e060a44f349f318
- l3_attachment_required: 8e7cc942ff5277cdb1f552ed6d64cffa7b02d77fe2c4f69ee6e97a8c5bddbb25
- l3_commitment_actor_unknown: c50b64fcbd7ee2b8815498a399c3139e359179c38e49f3620c84e98661f008af
- l3_critical_decision_unknown: 7a50d8c057227bc3fe2665ecd014dfc7054fab1eddbbce97c43d074bdece2952
- l3_deadline_timezone_not_stated: 1ec1fdf9b5e8ce23c188b18a21ca61dafef0c8308f91eedfa24c0661e43c34d0
- l3_injection_marked_resolved: 9befc37b9acd4f5be24241cf3195ae9ec48458ec010b3c19f44020b2fa8a3369
- l3_legal_claim: d5c3f8ce2034571a7c5ff01678c84ebbe82ec6202f2fd931cdc53df69b8bf412
- l3_policy_exception_marked_resolved: 38fa84d60e23199baddefc049145c9ed86e081430d59108f788e0bfe44066713
- l3_prior_commitment_conflict: 16eaf2ae85460cb0dd15ff1998fd0694afb0f541afeac309ab218734e57d5532
