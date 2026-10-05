# RelayGuard Implementation Spec v0.3

作成日: 2026-09-15  
Status: Current / Requirements baseline frozen

## 0. 本書の位置づけ

本書は、旧 `RelayGuard_残存設計仕様_v0.1.md` を置き換える実装仕様である。

本書の上位仕様は以下。

1. `CONTEXT.md`
2. `MASTER.md`
3. `AUDIT.md`
4. `SPEC_INDEX.md` が指定するCurrent製品要件（`PRD.md`）
5. `THREAT_MODEL.md`
6. `ADR.md`
7. `SCHEMA.md`
8. `DELEGATION.md`
9. `EVALUATION.md`

本書は上記を実装へ落とすための派生仕様であり、上位仕様と矛盾した場合は上位仕様を優先する。

---

# 1. 実装目標

MVPは、日本語ユーザーが英語メールへ対応するとき、

1. 原文を構造化して理解する
2. 日本語Decision Sheetでユーザー意思を固定する
3. Delegation Engineで委任レベルを判定する
4. 承認済み意思だけを根拠に英語返信案を生成する
5. 独立VerifierとDeterministic Diffで意味差分を検査する
6. 必要なら委任レベルを引き上げる
7. 人間が最終承認する
8. 安全候補のみコピー可能にする

ことを実現する。

MVPでは外部送信をしない。

---

# 2. 実装上の最重要品質

品質の中心はUI完成度ではなく、

> Critical事故を見逃さず、不要な人間確認をどこまで減らせるか

である。

したがって実装は以下の二軸で評価する。

## Safety Axis

- Critical unsafe-pass
- Unauthorized commitment miss
- Numeric mutation miss
- Rights / license mutation miss
- Prompt injection bypass
- stale state bypass
- approval bypass

## Delegation Axis

- Safe Delegation Rate
- Human Review Rate
- False Automation Rate
- False Escalation Rate
- Verification Cost per Case
- Human Minutes per Case

---

# 3. 推奨技術構成

MVP第一候補:

- Language: TypeScript
- Web: Next.js
- DB: PostgreSQL
- DB access: Drizzle ORM または同等の型付きSQL layer
- Runtime Schema: JSON Schema + Ajv
- Test: Vitest
- E2E: Playwright
- Observability: OpenTelemetry互換
- LLM: Provider Adapter経由
- Secrets: server-side secret manager / environment injection

ホスティング、DBサービス、LLM Providerは固定しない。

---

# 4. Repository Structure

```text
relayguard/
  apps/
    web/

  packages/
    domain/
    application/
    schemas/
    policy/
    delegation/
    diff-engine/
    llm-adapters/
    audit/
    evaluation/
    observability/

  prompts/
    interpreter/
    generator/
    verifier/

  eval/
    release-set/
    incident-set/

  # challenge-set はBuilderがアクセスできない
  # Reviewer管理の別private storage / private repositoryに置く

  db/
    migrations/

  docs/
    PRD.md
    Threat_Model.md
    ADR.md
    LLM_IO_Schema.md
    Delegation_Policy.md
    Evaluation_Spec.md
    Implementation_Spec.md
```

---

# 5. Domain Modules

## 5.1 Intake

責務:

- source message受領
- size limit
- normalization
- content hash作成
- raw contentの安全な保存

禁止:

- 原文をcommandとして扱う
- operational telemetryへ本文を送る

---

## 5.2 Interpretation

責務:

- メール本文から構造化情報抽出
- Evidence生成
- ambiguity / missing information抽出
- customer emotion / legal claim / injection risk抽出

処理:

```text
Raw Source
  ↓
Interpreter LLM
  ↓
JSON Schema Validation
  ↓
Domain Validation
  ↓
Interpretation Version
```

Schema失敗時は最大1回まで修正再試行し、それでも失敗したらFail Closed。

---

## 5.3 Decision

Interpretationはユーザー意思ではない。

Decision moduleがユーザー操作後のCanonical Stateを作る。

操作:

- approve
- modify
- unknown
- do_not_answer

Decision変更時:

- new immutable version
- new decision hash
- existing draft stale
- existing verification stale
- existing final approval invalid

---

## 5.4 Delegation Engine

Decision作成後に一次判定を行う。

Levels:

- L0_AUTO
- L1_POST_REVIEW
- L2_PRE_APPROVAL
- L3_STOP

MVPでは、L0/L1の「自動実行してよい」という推奨だけをShadow Modeとして記録し、実際の外部Actionは行わない。

L2/L3の承認要求・停止要求はShadowではなく、MVPでも安全制約として実際に強制する。

Policy minimum ruleはLLMより優先する。

例:

```text
legal_claim                  -> L3
unresolved_prompt_injection  -> L3
critical_missing_information -> L3
attachment_required_missing  -> L3
contradictory_commitments    -> L3
critical_deterministic_diff  -> L3

refund_or_credit             -> minimum L2
contractual_change           -> minimum L2
rights_or_license_change     -> minimum L2
new_guarantee                -> minimum L2
material_money_change        -> minimum L2
material_deadline_change     -> minimum L2
```

---

## 5.5 Generator

Generator入力:

- source_message
- approved_decision
- delegation_assessment
- response_language
- style_constraints

禁止事項:

- 未承認割引
- 未承認返金
- 未承認保証
- 未承認期限
- 未承認金額
- 未承認ライセンス
- 未承認権利
- 未承認個人情報開示

出力はDraftとして保存し、Decision Version/Hashと束縛する。

---

## 5.6 Reply Extractor

Generatorとは独立したコンテキストで最終返信から以下を再抽出する。

- commitments
- monetary terms
- dates
- quantities
- rights
- licenses
- guarantees
- refunds
- prohibitions
- conditions
- unanswered items

Generatorの自己申告は安全判定へ使わない。

---

## 5.7 Deterministic Diff Engine

必ずコード比較する:

- amount
- currency
- date
- deadline
- quantity
- rights
- exclusivity
- sublicensing
- refund
- guarantee
- approved commitment ID
- required-answer coverage
- decision version/hash

Critical mismatchはVerifier判定より優先する。

---

## 5.8 Verifier

Verifier入力:

- original source
- approved decision
- delegation assessment
- final reply
- extracted reply state

渡さない:

- Generator chain of thought
- Generator chat history
- Generator self score
- Generator rationale
- safe label

Verifierの目的:

- 条件節消失
- may → will
- 婉曲な新規約束
- semantic omission
- hidden commitment
- contradiction
- unsupported certainty
- customer emotion miss
- legal implication
- delegation level too low

Verifierはfindingを返すが、最終判定はPolicy Engine。

---

## 5.9 Policy Engine

例:

```text
if schema_invalid or incomplete_validation or delegation_level_is_L3:
    BLOCK

if decision_version_mismatch:
    BLOCK

if critical_deterministic_diff:
    BLOCK

if verifier_has_blocking_finding:
    BLOCK

if unresolved_critical_ambiguity:
    BLOCK

if attachment_required_missing:
    BLOCK

else:
    SAFE_CANDIDATE
```

Policy EngineはさらにDelegation再評価を行う。

前段より後段で安全側を緩和してはならない。

---

## 5.10 Approval

Final Approval時にサーバー側で再検証する。

必須:

- Draftが対象Decisionから生成された
- Decision Version一致
- Decision Hash一致
- Verificationが対象Draftを参照
- Verificationが対象Decisionを参照
- blocking finding = 0
- Policy status = SAFE_CANDIDATE
- Draft Hash一致

クライアントだけで承認状態を作らない。

---

# 6. Data Flow

```text
[Untrusted Email]
      |
      v
[Intake]
      |
      v
[Interpreter]
      |
      v
[Schema + Domain Validation]
      |
      v
[Interpretation]
      |
      v
[Decision Sheet]
      |
      v
[Approved Decision vN + Hash]
      |
      v
[Delegation Assessment #1]
      |
      v
[Generator]
      |
      v
[Draft]
      |
      v
[Reply Extractor]
      |
      +--------------------+
      |                    |
      v                    v
[Deterministic Diff]   [Verifier]
      |                    |
      +---------+----------+
                |
                v
          [Policy Engine]
                |
                v
      [Delegation Assessment #2]
           /          \
       BLOCKED     SAFE_CANDIDATE
                      |
                      v
                [Final Approval]
                      |
                      v
                    [Copy]
```

---

# 7. Database Schema

## cases

```text
id uuid PK
status enum
source_language
user_language
created_at
updated_at
```

## messages

```text
id uuid PK
case_id FK
external_id nullable
subject_ciphertext nullable
body_ciphertext
content_hash
created_at
```

## interpretations

```text
id uuid PK
case_id FK
message_id FK
version int
schema_version
payload_json
model_execution_id FK
created_at
UNIQUE(case_id, version)
```

## decision_versions

```text
id uuid PK
case_id FK
version int
interpretation_id FK
payload_json
decision_hash
created_at
UNIQUE(case_id, version)
INDEX(decision_hash)

`decision_hash` はbinding / integrity確認用であり、異なるcaseで同一内容が存在し得るためグローバルUNIQUEにはしない。
```

## delegation_assessments

```text
id uuid PK
case_id FK
decision_version_id FK
phase enum(pre_generation, post_verification)
level enum
minimum_level enum
reason_codes_json
risk_factors_json
shadow_mode bool
created_at
```

## drafts

```text
id uuid PK
case_id FK
decision_version_id FK
reply_ciphertext
reply_hash
model_execution_id FK
created_at
```

## verifications

```text
id uuid PK
case_id FK
decision_version_id FK
draft_id FK
status enum
payload_json
policy_version
created_at
```

## findings

```text
id uuid PK
verification_id FK
type enum
severity enum
blocking bool
payload_json
created_at
```

## final_approvals

```text
id uuid PK
case_id FK
decision_version_id FK
draft_id FK
verification_id FK
approved_at
approval_hash
UNIQUE(case_id, draft_id, verification_id)
```

## model_executions

```text
id uuid PK
role enum
provider_key
model_key
prompt_version
schema_version
input_hash
output_hash
latency_ms
status
created_at
```

Raw本文は保存しない。

## audit_events

```text
id uuid PK
case_id FK
actor_type enum
actor_id nullable
event_type
entity_type
entity_id
previous_hash nullable
event_hash
metadata_json
created_at
```

---

# 8. API

## Case

`POST /v1/cases`

`GET /v1/cases/{caseId}`

## Interpretation

`POST /v1/cases/{caseId}/interpretations`

## Decision

`POST /v1/cases/{caseId}/decisions`

`GET /v1/cases/{caseId}/decisions/{version}`

## Delegation

`POST /v1/cases/{caseId}/delegation-assessments`

## Draft

`POST /v1/cases/{caseId}/drafts`

必須:

```json
{
  "decision_version": 3,
  "decision_hash": "..."
}
```

## Verification

`POST /v1/cases/{caseId}/verifications`

## Final Approval

`POST /v1/cases/{caseId}/final-approvals`

サーバー側で状態を再検証する。

## Audit

`GET /v1/cases/{caseId}/audit`

---

# 9. Idempotency

LLM起動系POSTは `Idempotency-Key` を受け付ける。

同一key + 同一input hash:
- 同じ結果を返す。

同一key + 異なるinput hash:
- conflict。

---

# 10. UI State Machine

正常経路:
NEW → INPUT_READY → INTERPRETING → DECISION_REQUIRED → DECISION_APPROVED → DELEGATION_ASSESSED → GENERATING → DRAFT_READY → VERIFYING → SAFE_CANDIDATE → FINAL_REVIEW → FINAL_APPROVED → COPIED。

検証失敗・L3・重大不明はBLOCKEDへ進み停止する。BLOCKEDからFINAL_REVIEWへの直接遷移はない。
原因解消後はSource/Interpretation/Decision等の変更箇所から新bindingで再実行し、SAFE_CANDIDATEを新たに得る。旧承認を復活させない。
Shadow Modeでlevelを表示しても外部Actionは起こさない。SHADOW_GATE以前に後半UIを実装する指示ではない。

---

# 11. UI原則

- 「安全です」と断言しない。
- 「定義済み検査を通過」と表現する。
- Confidenceを大きな緑色スコアで見せない。
- Critical findingは日本語のみでも理解可能。
- 原文/英文返信は展開式。
- `不明`を明示。
- Delegation Levelは理由コードとセットで表示。
- L0/L1でもMVPでは「自動実行されない」ことを明示。

---

# 12. Error Taxonomy

## SafetyBlock
重大差異、未承認commitment、critical ambiguity。

## SchemaInvalid
LLM構造化出力不正。

## StaleState
Decision Version/Hash不一致。

## ProviderUnavailable
timeout / rate limit / outage。

## UnsupportedInput
未対応添付、巨大thread等。

## InjectionSuspected
攻撃パターン検出。

## PolicyViolation
禁止された状態遷移。

## InternalIntegrityError
hash/FK/audit chain不整合。

## DelegationConflict
Policy minimumより低いlevelが提案された。

---

# 13. Test Strategy

## Schema Contract Tests
- required
- enum
- type
- unknown ID
- decimal/date
- null/unknown/ambiguous

## Domain Unit Tests
- Decision version invalidation
- Commitment authorization
- Delegation minimum rules
- Policy block rules

## Property Tests
例:

```text
approved amount != reply amount -> BLOCK
new critical commitment -> BLOCK
hash mismatch -> final approval impossible
legal claim -> minimum L3
refund -> minimum L2
```

## Diff Mutation Tests

- 500 → 50
- USD → EUR
- May 12 → May 21
- 10 users → 100 users
- non-exclusive → exclusive
- may → will
- conditional refund → unconditional refund

## LLM Contract Tests
文章一致ではなくSchema/Evidence/Invariantsを確認。

## Evaluation Tests
100件release-set。

## Adversarial Tests
Reviewer管理challenge-set。

challenge-set本体はBuilderがアクセスできるmain repositoryへ置かない。
Reviewer管理の別private storage / private repositoryからCIの独立レビュー工程で供給する。

## E2E
Input → Decision → Delegate → Generate → Verify → Approval。

## Security
- authz
- CSRF
- XSS
- injection
- secret leakage
- PII logging
- replay
- stale state
- idempotency
- approval bypass

---

# 14. CI Gates

## PR

1. lint
2. typecheck
3. unit
4. schema
5. diff/property
6. API integration
7. full 100 release-set（selected eval smokeは追加検査のみ）

## Main / Release Candidate

1. full 100 release-set
2. E2E
3. security regression
4. challenge-set
5. audit integrity
6. delegation classification regression

---

# 15. Observability

Operational metrics:

- request count
- latency
- provider error
- schema retry
- safety block count
- delegation level counts
- human review rate
- false escalation
- final approval count
- stale state rejection
- evaluation pass/fail

Operational telemetryへ送らない:

- raw email body
- raw reply text
- email address
- personal name
- full contract content
- full LLM prompt

Trace IDs:

- case_id
- model_execution_id
- decision_version
- delegation_assessment_id
- draft_id
- verification_id
- prompt_version
- schema_version
- policy_version

---

# 16. Audit

最低限:

- input hash
- interpretation version
- decision version/hash
- delegation assessments
- model/provider role
- prompt version
- draft hash
- verification
- findings
- final approval
- timestamp

Operational telemetryとは分離する。

---

# 17. Evaluation Implementation

100件release-setをmachine-readable fixtureとして保持する。

1ケース:

```yaml
case_id: RG-EVAL-001
source: {}
expected_interpretation: {}
approved_decision: {}
expected_delegation:
  minimum_level: L2_PRE_APPROVAL
unsafe_candidate_reply:
  text: "..."
expected_verification:
  overall_status: blocked
expected_final_delegation:
  level: L3_STOP
release_class: critical
```

評価Runnerは以下を出す。

- Safety metrics
- Delegation metrics
- Category breakdown
- Regression diff
- model/prompt/schema/policy version

---

# 18. Release Gates

Release blocker:

1. Critical unsafe-pass > 0
2. numeric mutation miss > 0
3. unauthorized commitment miss > 0
4. refund/guarantee/license/right miss > 0
5. stale state bypass > 0
6. approval bypass > 0
7. prompt injection policy bypass > 0
8. L2/L3 caseをL0/L1へ誤分類 > 0
9. raw PII operational-log leak > 0
10. unresolved Critical Reviewer finding > 0

---

# 19. Implementation Order

## Epic 0 Repository Foundation
- monorepo
- strict TS
- CI
- secrets
- no-content logging

## Epic 1 Canonical Schemas
- Interpretation
- Evidence
- Decision
- Delegation
- Draft
- Verification
- Finding

## Epic 2 Evaluation Harness
- release-set loader
- matcher
- reporting
- initial 100 fixtures

## Epic 3 Domain + Diff + Policy
- version/hash
- deterministic diff
- fail closed
- delegation minimum rules

## Epic 4 Interpretation + Decision
- input
- interpreter
- Decision Sheet
- evidence
- immutable version

## Epic 5 Delegation Engine
- pre-generation assessment
- Shadow Mode recording
- reason codes
- KPI events

## Epic 6 Generator
- provider adapter
- prompt package
- draft persistence

## Epic 7 Verification Core
- reply extractor
- deterministic diff
- verifier
- findings
- post-verification delegation reassessment

## Epic 8 Final Approval
- server transition checks
- stale-state rejection
- copy action

## Epic 9 Audit / Privacy / Observability
- audit events
- metadata traces
- PII-safe telemetry

## Epic 10 Adversarial Review
- independent security review
- challenge-set
- fixes
- regression

## Epic 11 Human Pilot
- low-risk real emails
- no auto-send
- incident-set collection
- Shadow Mode delegation evaluation

---

# 20. Architect / Builder / Reviewer Contract

## Architect

責務:

- PRD
- Threat Model
- ADR
- Schema
- Delegation Policy
- Evaluation
- Release Gate

Reviewer指摘を、

- specification defect
- implementation defect
- test defect

へ分類する。

## Builder

承認済み仕様だけを根拠に実装する。

禁止:

- 独自仕様追加
- safety shortcut
- silent schema coercion
- test expectation緩和
- policy bypass
- Provider SDKのdomain流入
- prompt散在

## Adversarial Reviewer

読む:

- Repository
- PRD
- Threat Model
- ADR
- Schema
- Delegation Policy
- Evaluation Spec
- Security Audit Prompt

読まない:

- Builderとの会話履歴
- Builder自己評価
- Builder内部推論

---

# 21. Future Action Gateway

MVP外。

将来Gmail Draft等を追加する際は新Trust Boundaryを作る。

必須:

- explicit approval
- immutable action payload
- action hash
- idempotency
- account binding
- token vault
- audit
- stale verification rejection
- least privilege

送信権限はDraft作成とは分離する。

---

# 22. 要件確定と段階別着手条件

Current版はSPEC_INDEX.mdで決まる。LLM/domainの詳細構造はSCHEMA.md v0.5を正本とする。本文のDB/API概略・JSON例は役割説明であり、省略をnullable/requiredの実装判断に使わない。BindingやUserProvenanceは列または検証済みpayloadで永続化し、全cross-field条件をDomainで強制する。

SG-001は検証済みfixtureのSource → Interpretation → Approved Decision → 事前Delegation判定を扱う。入力と結果はSCHEMA.md §10。実LLM、DB、UI、外部送信は不要。旧tasksのrequested_action/authority/domain enumを復活させない。
後続は型付き比較、評価runner、100件fixture、Policy/Delegation/Shadow記録を揃える。これは../docs/SHADOW_GATE.mdの条件を満たすための作業であり、Generator/Reply Extractor/Verifier/Final Approval/UIの本格実装の承認ではない。
到達後は停止し、人間承認まで後半へ進まない。モデル・実装順の細部は担当者裁量でよいが、未実装の検査をPASSにしない。

# 23. 運用・障害・整合性要件の確定（SD-12）

## 初期開発プロファイル
ローカルの合成または不可逆に匿名化したfixtureを使う。実個人情報・実メールのprovider送信はこの段階の受入条件に含めない。fixture actorは実ユーザー承認を装わず、schemaのexecution_kindで区別する。SG-001はnetworkなしで実行できる。

## 外部入力を扱う段階の必須条件
- 操作主体を認証し、case所有者以外によるread/write/approveを拒否する。client指定ownerやcase_idだけで権限を認めない。組織/RBAC機能の追加ではなく、個人データの隔離要件である。
- source/replyだけでなくInterpretation、Decision、Finding、Evidence等のPIIを含み得るpayloadも保存時に暗号化する。転送は暗号化し、秘密鍵はserver管理・repository/client/telemetry外で保持する。
- LLM providerは送信目的・データ保持・学習利用・送信先を確認して選定し、条件不明のまま実メールを送信しない。必要payloadのみ送信する。モデル銘柄は固定しない。
- 原文、返信、構造化PIIの保管は既定30日、ユーザーが明示削除した対象は通常保存から除去する。バックアップも30日以内の保持とし、復元時に削除対象を復活させない。metadataのみの監査は90日を上限とする。運用設定を明示し、この要件を満たさない保存先を採用しない。
- 監査chainの欠損/不一致を検出したcaseはInternalIntegrityErrorで承認不可。hash chainだけで外部改ざん防止を保証したと主張しない。監査保存先への書込権限をアプリの必要権限に限定する。
- Idempotency-Keyは認証主体・case・操作ごとに隔離し、同key/同inputで同結果、異inputでconflict。24時間は保持し、同時要求は一つだけが状態を確定する。retryで古いbindingの成功結果を再承認しない。
- Decision更新・Draft編集・policy更新と承認の競合はtransactionまたは同等のcompare-and-setで解決し、古いversionによる書込を拒否する。

## 実行上限・障害
入力subject+bodyのUTF-8合計は64 KiBまで。超過を切り捨てて継続せずUnsupportedInput。添付/URLを勝手に取得しない。
LLM試行1回のtimeoutは処理全体の残り予算とし、Schema修正の再試行は1回まで。処理全体は最大300秒の予算内で、超過・rate limit・partial outputは明示エラー。無限retryや旧safe結果の流用をしない。呼び出しはstreamingとし、モデルが応答生成中にHTTP timeoutで切断されることを防ぐ。（2026-09-20 Architect裁定D-2により改訂。旧規定は「1回60秒」固定。長文メールの解釈が完了前に切断され実環境でAPITimeoutErrorとなったため。）（2026-09-23 Architect裁定D-7(b)により全体上限を120秒から300秒へ改訂。571語の合成メール1例で effort=medium の初回が約125秒となり、120秒では完了できなかったため。300秒はこの実測に基づく**試験用の上限**であり、長文一般の完了を保証しない。修復1回まで・超過時Fail Closed・失敗した試行の結果を流用しない条件は不変。メール長による段階化は閾値の根拠がないため採用しない。）
Schema修正は形式の再生成に限り、ユーザー意思・policy・元の期待値を変更しない。retry回数とmodel_execution_idを記録する。実費・latency・エラーを計測し、unknownを0扱いしない。
可用性や性能の商用SLAは本MVPの約束に含めない。latencyや費用の改善目的で安全検査を省略しない。provider・配備・ライブラリの選定はこの契約を満たす範囲で実装担当が決める。

# 24. 承認・停止の適用

BLOCKEDは閲覧・原因説明だけを許可し、FINAL_REVIEWへ直接進めない。SCHEMA.mdの新しいbindingで再評価を完了してSAFE_CANDIDATEになった場合のみ、別の新しい最終承認を受ける。
L3は生成/承認/コピー不可。L2の事前承認はApproved Decisionで証跡化し、post評価後は全レベルで別のFinal Approvalを要求する。詳細はDELEGATION.md §13。
誤った合法化やinjectionの「承認による解除」を実装しない。安全条件・権限条件をUIでoverrideしない。
