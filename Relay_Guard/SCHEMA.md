# RelayGuard 構造契約 v0.5

Status: Current / Architect決定済み（SD-07）  
正本入口: SPEC_INDEX.md。これは実装前の規範契約であり、実行可能なJSON Schemaやvalidatorの実装ではない。

## 1. 適用・互換性

v0.2の不完全なJSON例を本書で置き換える。v0.5は契約変更であり、旧形式を暗黙変換して受理しない。Builderはこの契約を厳格なJSON SchemaとDomain検証へ実装する。LLM出力はSchema → Domain → cross-field → Policy検証を通過して初めて状態に採用する。

以下の表のフィールドはすべてrequired。nullableは欠落を許可する意味ではない。全objectは列挙外property禁止。配列は型付き・null禁止、意味上の要素がなければ空配列。duplicate JSON keys、不正UTF-8、非有限数、型coercion、default値での補完、未対応versionを拒否する。組織機能や任意policy DSLを追加しない。

### 基本型

- ID: ASCII英数字・underscore・hyphenのみ、1〜128文字。同一文書内の全Claim IDは型を跨いで一意（参照・Decisionへのコピーを除く）。同種entity IDは案件内で一意。実DBのUUIDは内部表現として選択可。
- Text: UTF-8文字列。非空は空文字禁止、空許可は明記。制御文字は改行・tab以外禁止。
- Hash: lowercase hex 64文字のSHA-256。
- Version: 1以上の安全な整数。ゼロ、fraction、数値文字列は禁止。
- Decimal: 符号付き10進文字列。文法は -?(0|[1-9][0-9]*)(\.[0-9]+)?、全数字38桁以下・小数18桁以下。指数、桁区切り、通貨記号を含めない。比較は10進数として行いbinary floatにしない。
- Date: 実在する暦日 YYYY-MM-DD。年・月・日が原文と承認情報から一意に決まる場合のみ確定する。
- Timestamp: UTC、YYYY-MM-DDTHH:mm:ss.sssZ。実在する日時。
- Bool: true / false。Nullable<T>: Tまたはnull。
- Confidence: 0〜1の有限数（小数点以下3桁以内）またはnull。安全判定・承認の根拠にはしない。
- Value<T>: {status, value, raw_text}。statusはexplicit / unknown / not_stated / ambiguous。explicitならvalueはT、その他はnull。raw_textはText（空許可）。null=値なし、unknown=判断不能、not_stated=記載なし、ambiguous=複数解釈。既知の「なし」はvalue=falseまたは明示Textで表しunknownと混同しない。

## 2. 入力とEvidence

| 型 | requiredフィールド |
|---|---|
| SourceMessage | message_id:ID, subject:Nullable<Text>, body:非空Text, source_language:en, user_language:ja, content_hash:Hash |
| Evidence | evidence_id:ID, source_kind:source_message / reply, source_id:ID, source_hash:Hash, quote:非空Text, supports:ID[], confidence:Confidence |
| ClaimBase | id:ID, evidence_ids:ID[] |
| TextClaim | ClaimBase + text:Value<非空Text> |
| ClauseTerm | ClaimBase + text:Value<非空Text>, modality:Value<may / will / must / must_not>, condition:Value<非空Text>, scope:Value<非空Text>, monetary_term_ids:ID[], deadline_ids:ID[], commitment_ids:ID[] |
| MonetaryTerm | ClaimBase + amount:Value<Decimal>, currency:Value<通貨コード>, type:price / discount / credit / refund / payment / fee / other, condition:Value<非空Text> |
| DateTerm | ClaimBase + type:date / deadline, date:Value<Date>, timezone:Value<非空Text> |
| QuantityTerm | ClaimBase + quantity:Value<Decimal>, unit:Value<非空Text>, condition:Value<非空Text> |
| RightsLicenseTerm | ClaimBase + scope:Value<非空Text>, exclusivity:Value<Bool>, sublicensing:Value<Bool>, commercial_use:Value<Bool>, condition:Value<非空Text> |
| Commitment | ClaimBase + actor:user / counterparty / third_party / unknown, action:Value<非空Text>, object:Value<非空Text>, modality:Value<may / will / must / must_not>, condition:Value<非空Text>, scope:Value<非空Text>, deadline_id:Nullable<ID>, monetary_term_ids:ID[], authorization_state:requested / approved / rejected / unanswered / not_approved |
| Question | ClaimBase + text:Value<非空Text>, required_answer:Bool |
| Emotion | ClaimBase + type:anger / distrust / cancellation_intent / public_complaint / other, intensity:low / medium / high / unknown, target:Value<非空Text> |
| LegalClaim | ClaimBase + claim_type:Value<非空Text>, requires_human_review:true |
| Risk | ClaimBase + type:reputational / contradiction / missing_information / ambiguity / attachment / injection / policy_exception / other, description:Value<非空Text>, affects_critical:Bool, resolved:Bool |

通貨コードは3文字大文字とし、曖昧な「$」からUSDを推測しない。検証済みISO通貨コード集合を実装で固定し版管理する。未対応コードは不正として拒否する。為替変換・日付補完・単位換算は行わない。

Evidence.quoteは指定source_hashの原文の完全一致部分文字列でなければ拒否。supportsは同じ文書内の存在するClaim IDのみ。Decision内の元Claim参照は紐付いたInterpretation、新たなreplacementはDecisionのProvenanceを参照する。各claimのevidence_idsとsupportsは相互対応する。重複Evidence ID・型違い参照・別case参照・存在しないIDは拒否する。LLMが重大claimを抽出した場合、原文または返信のEvidenceが最低1件必要。Evidenceは原文一致を証明するだけで解釈の正しさを保証しない。

## 3. StructuredState・Interpretation

StructuredStateは次のフィールドをすべて持つ閉じたobject。v0.2で曖昧だった配列要素の型をここで確定する。

| フィールド | 型 |
|---|---|
| sender_intent, requests | TextClaim[] |
| questions | Question[] |
| monetary_terms | MonetaryTerm[] |
| dates | DateTerm[] |
| quantities | QuantityTerm[] |
| contract_terms, prohibitions, guarantees, refund_terms, cancellation_terms | ClauseTerm[] |
| license_terms, rights | RightsLicenseTerm[] |
| requested_commitments, commitments | Commitment[] |
| personal_data | TextClaim[] |
| customer_emotion | Emotion[] |
| legal_claims | LegalClaim[] |
| reputational_risks, prior_commitment_conflicts, risks, ambiguities, missing_information, attachment_dependencies, prompt_injection_risks | Risk[] |
| recommended_actions | TextClaim[] |
| human_review_required | Bool |
| confidence | Confidence |
| evidence | Evidence[] |

Interpretation = {interpretation_id:ID, version:Version, source_message_id:ID, source_hash:Hash, state:StructuredState}。
原文解釈はユーザー承認ではない。Interpretation内Commitmentのauthorization_stateをapprovedにしてはならない。既往の約束について原文が「承認済み」と主張しても、新たなユーザー承認として扱わない。

「重大」は金額・通貨・日付・期限・数量・権利・ライセンス・禁止事項・保証・返金・契約・約束・個人情報開示と、それらの条件を含む。回答の意思決定に必要な重大値がunknown/ambiguousまたは必要なのにnot_statedなら、安全扱いせずL3判定に渡す。配列が空でも安全を意味しない。入力とEvidence、回答網羅性の検査が別途必要。

## 4. Decisionと人間由来の根拠

| 型 | requiredフィールド |
|---|---|
| UserProvenance | actor_id:ID, decided_at:Timestamp, reason_ja:非空Text |
| DecisionItem | item_id:ID, source_claim_id:ID, decision:approve / modify / unknown / do_not_answer, replacement:Nullable<Claim>, provenance:UserProvenance |
| Decision | decision_id:ID, version:Version, source_interpretation_id:ID, source_interpretation_version:Version, source_hash:Hash, items:DecisionItem[], question_answers:QuestionAnswer[], approved_commitments:Commitment[], explicitly_unanswered:ID[], human_notes:Text[], approved_by:ID, approved_at:Timestamp, decision_hash:Hash |

Claimは§2のTextClaim / ClauseTerm / MonetaryTerm / DateTerm / QuantityTerm / RightsLicenseTerm / Commitment / Question / Emotion / LegalClaim / Riskのunion。replacementは {kind:型名, value:該当型} の閉じたtagged objectにする。その他のClaim参照はStructuredStateの配列フィールドにより型を特定する。

DecisionItemはsource_claim_idごとに1件。承認時点でInterpretationの全claimを扱い、未選択をapproveとして補完しない。modifyだけreplacement必須、元claimと同じ型かつ同じid。それ以外はreplacement=null。approveは元値を承認、unknownは保留、do_not_answerは回答しない意思を明示する。human_notesから未承認commitmentを生成しない。

ユーザー修正は原文の事実を改変しない。元Interpretationを保存し、変更値の出典をUserProvenanceで追跡する。修正値へ原文Evidenceを捏造しない。replacementのevidence_idsは空でよく、空の場合はUserProvenance必須。元Evidenceを残す場合も修正値を原文が支持したとは表示しない。承認は認証されたユーザー操作（offline fixtureでは明示されたテスト由来）のみ。LLMやclientの自己申告approvedをそのまま受理しない。

approved_commitmentsはapprove/modifyした項目からDomainが構築する。未選択・unknown・do_not_answerから追加しない。authorization_state=approved、重複ID禁止。Interpretationのrequested_commitmentsとの対応を追跡し、元の未承認状態を書き換えない。

explicitly_unansweredはdo_not_answerで選択したQuestion IDの集合と完全一致する。required_answer=trueの質問でも明示的なdo_not_answerは「意図的未回答」として網羅性を満たすが、返金等の承認、法的主張の解決、重大な不明値の解消にはならない。unknownは回答済みでも意図的未回答でもない。必要質問が未解決ならBLOCK。返信が回答を捏造・約束していないことも検証する。

## 5. Binding・hash

Binding = {case_id:ID, source_hash:Hash, interpretation_id:ID, interpretation_version:Version, decision_id:ID, decision_version:Version, decision_hash:Hash, policy_version:非空Text}。
DraftBinding = {decision:Binding, draft_id:ID, draft_hash:Hash}。
各Bindingはserverに保持する最新の対象と完全一致を要求する。hashが同じでも別caseや別versionの組合せを認めない。decision_hashはglobal UNIQUEにしない。

hash規則:
- Source hash: {subject, body, source_language, user_language}をcanonical serializationしたUTF-8バイト列のSHA-256。原文本文をtrim・翻訳・Unicode正規化しない。
- Decision hash: Decisionからdecision_id / version / decision_hashを除いた全フィールド。case_idはBindingに保持する。異なるcaseで同一内容が同hashになることを許容する。
- Draft hash: 最終reply_textそのもののUTF-8バイト列。改行・空白変更も別hash。
- canonical serialization: object keyはASCIIコード順、配列順序は保持、空白なし、JSON文字列のquote/backslash/controlはJSON escape、その他UnicodeはUTF-8（slashや非ASCIIを任意escapeしない）。nullableを省略しない。整数は10進・先頭ゼロなし。Decimalは文字列のまま。上記hash対象には浮動小数値を入れず、Decision内Confidenceはhash対象から除く（承認・値・Evidence IDは除外しない）。
- ID集合として定義した配列だけ事前にASCII昇順に整列。その他の配列順序は意味があるものとして維持。
- metadataのinput_hash/output_hashはcanonical serializationしたLLM input/output payloadのhash。Confidenceは固定小数表記（末尾ゼロを除去、0は0、1は1、指数禁止）として記録し、これらexecution hashを承認bindingには使わない。

元データ／Interpretation／Decisionが変更されたら下流全体を失効。Draft編集は旧抽出・Verification・Approvalを失効。policy_version変更は両Delegation Assessment・Verification・Approvalを失効させ、新版の再評価を必須とする。旧hashを書き換えて通さない。承認判定と記録は同一の排他制御／transaction内で行う。

## 6. LLM Envelope・実行権限

すべての論理LLM入出力は {meta:ExecutionMeta, payload:役割別payload} の閉じたobject。
ExecutionMeta = {schema_version:"0.5", prompt_version:非空Text, model_execution_id:ID, case_id:ID, role:interpreter / generator / reply_extractor / verifier, direction:input / output}。
metaはtrusted adapterが発行してrequestに束縛する。model側が返す場合は完全一致を検査する。実行IDは試行ごとに新規。fixtureはfixture由来とModelExecutionに記録し、実モデル実行と混同しない。

| role | input payload | output payload |
|---|---|---|
| interpreter | {source_message:SourceMessage} | Interpretation |
| generator | {source_message:SourceMessage, approved_decision:Decision, delegation_assessment:DelegationAssessment, response_language:en, style_constraints:Style} | DraftProposal |
| reply_extractor | {source_message:SourceMessage, final_reply_text:非空Text, binding:DraftBinding} | ReplyExtraction |
| verifier | {source_message:SourceMessage, approved_decision:Decision, delegation_assessment:DelegationAssessment, final_reply_text:非空Text, reply_extracted_state:ReplyExtraction, binding:DraftBinding} | VerificationProposal |

Style = {tone:professional, concise:Bool}。
DraftProposal = {reply_text:非空Text, binding:Binding, represented_state:StructuredState}。
Draft = {draft_id:ID, binding:Binding, reply_text:非空Text, draft_hash:Hash, model_execution_id:ID}。DomainがProposalから構築する。
ReplyExtraction = {extraction_id:ID, binding:DraftBinding, state:StructuredState}。reply由来claimのEvidenceはsource_kind=reply、source_id=draft_id、source_hash=draft_hash。原文由来のEvidenceを返信一致の証拠に代用しない。
VerifierにはGeneratorのrepresented_state、内部推論、会話、自己評価、safe labelを渡さない。Reply ExtractorもGeneratorの自己申告を受け取らない。Reply ExtractorとVerifierのコンテキスト・実行はGeneratorから独立させる。

## 7. Finding・比較

FindingType: amount_changed / currency_changed / date_changed / quantity_changed / right_changed / license_changed / guarantee_added / refund_added / commitment_added / prohibition_removed / required_answer_missing / condition_removed / ambiguity_resolved_without_authority / attachment_dependency / prompt_injection_risk / unsupported_claim / state_mismatch / customer_emotion_missed / legal_claim_detected / delegation_level_too_low。

Finding = {finding_id:ID, type:FindingType, severity:critical / high / medium / low, blocking:Bool, origin:deterministic_diff / verifier / domain, expected_claim_ids:ID[], actual_claim_ids:ID[], evidence_ids:ID[], explanation_ja:非空Text}。
不存在のexpected IDやactual IDを作らない。削除・追加差異では片側空を許可する。state_mismatch等の構造エラーは両側空を許可するがbinding検査の根拠を説明する。重大な値・条件・権限・約束の変更はcriticalかつblocking=true。criticalをnon-blockingにできない。LLMのseverityを使ってDomainのblockingを解除しない。

DiffResult = {binding:DraftBinding, findings:Finding[], checked_fields:Text[], complete:Bool}。
typed diffは金額/通貨/日付/期限/数量/権利/独占/再許諾/返金/保証/約束/禁止事項/条件/回答網羅/bindingをすべて検査する。型付き比較ができない重大項目は「差異なし」でなく不確定BLOCK。権利・条件等の自然文はEvidence付き独立抽出とVerifierを併用し、文字列一致だけで意味一致を保証しない。
金額はDecimalの値と通貨を別々に比較。日付は原文とtimezoneも参照し、未指定timezoneを推測しない。数量は値とunit。Commitmentはactor/action/object/modality/condition/scopeと関連金額・期限を比較する。ID一致のみを内容一致と扱わない。

VerificationProposal = {binding:DraftBinding, overall_status:matched / minor_differences / blocked, findings:Finding[], unanswered_items:ID[], new_commitments:Commitment[], uncertain_items:ID[], delegation_reassessment:LevelProposal, human_review_required:Bool}。
LevelProposal = {level:DelegationLevel, reason_codes:ReasonCode[]}。
Verification = {verification_id:ID, binding:DraftBinding, extraction_id:ID, verifier_execution_id:ID, diff:DiffResult, proposal:VerificationProposal, policy_status:BLOCK / SAFE_CANDIDATE, policy_version:非空Text}。
proposalは非信頼。最終policy_statusはDomainのみが付与する。complete=false、blocking finding、未解決必要質問、重大不明、binding不一致なら必ずBLOCK。

## 8. Delegation・Shadow評価

DelegationLevel: L0_AUTO / L1_POST_REVIEW / L2_PRE_APPROVAL / L3_STOP。順序はL0 < L1 < L2 < L3。
RiskFactors = {impact:low / medium / high / unknown, uncertainty:low / medium / high / unknown, irreversibility:low / medium / high / unknown, customer_sensitivity:low / medium / high / unknown}。

ReasonCode: LEGAL_CLAIM / UNRESOLVED_PROMPT_INJECTION / CRITICAL_MISSING_INFORMATION / ATTACHMENT_REQUIRED_MISSING / CONTRADICTORY_COMMITMENTS / CRITICAL_DIFF / REFUND_OR_CREDIT / CONTRACTUAL_CHANGE / RIGHTS_OR_LICENSE_CHANGE / NEW_GUARANTEE / MATERIAL_MONEY_CHANGE / MATERIAL_DEADLINE_CHANGE / QUANTITY_CHANGE / PERSONAL_DATA_DISCLOSURE / NEW_COMMITMENT / POLICY_EXCEPTION / CUSTOMER_SENSITIVITY / LOW_RISK_INFORMATIONAL / LOW_RISK_POST_REVIEW / UNCLASSIFIED_RISK / ANSWER_REVIEW_REQUIRED / INVALID_INPUT / INCOMPLETE_PIPELINE / STALE_STATE / VERIFIER_BLOCK。
未登録コードを自由文字列として採用しない。追加はversioned仕様変更。

DelegationAssessment = {assessment_id:ID, binding:Binding, phase:pre_generation / post_verification, draft_binding:Nullable<DraftBinding>, level:DelegationLevel, minimum_level:DelegationLevel, reason_codes:ReasonCode[], risk_factors:RiskFactors, shadow_mode:true, human_review_required:Bool}。
preではdraft_binding=null、postでは必須。同一Decisionのpost levelはpreより低くできない。minimumはDomain policyが算出する。L2/L3ではhuman_review_required=true必須。L0/L1では推奨としてfalse/true（L0=false、L1=true）とするが、MVPの最終承認を省略しない。shadow_mode=trueは外部実行禁止を表し、L2/L3制約を無効にしない。

ShadowOutcome = {assessment_id:ID, predicted_delegation_level:DelegationLevel, actual_human_intervention:Bool, final_outcome:safe / critical_incident / noncritical_incident / unknown, would_have_been_safe_to_automate:Nullable<Bool>, adjudicator_id:Nullable<ID>, evaluation_kind:fixture / observed, human_seconds:Nullable<非負整数>, verification_cost:Nullable<Decimal>, cost_currency:Nullable<通貨コード>}。
final_outcome=unknownならwould_have_been_safe_to_automate=null。判定確定時はadjudicator_id必須。実観測とfixtureでKPIを分離。コスト未測定は0でなくnull。L1の事後確認は実際の人間介入として数える。

## 9. Approval・Audit・エラー

FinalApproval = {approval_id:ID, binding:DraftBinding, verification_id:ID, assessment_id:ID, approved_by:ID, approved_at:Timestamp, approval_hash:Hash}。
approval_hashはapproval_hash自身を除く全フィールドのcanonical hash。正しいhashだけでは承認権限の証明にならない。serverの主体・最新状態の確認必須。

AuditEvent = {event_id:ID, case_id:ID, actor_type:user / system / fixture, actor_id:Nullable<ID>, event_type:非空Text, entity_id:ID, entity_hash:Hash, previous_hash:Nullable<Hash>, event_hash:Hash, created_at:Timestamp}。
event_hashは自身を除く全フィールドのcanonical hash。caseごとに直前イベントhashと対応させ、先頭のみprevious_hash=null。raw内容をmetadataへ逃がさない。
ModelExecution = {model_execution_id:ID, execution_kind:provider / fixture, role:interpreter / generator / reply_extractor / verifier, provider_key:Nullable<Text>, model_key:Nullable<Text>, prompt_version:非空Text, schema_version:"0.5", input_hash:Hash, output_hash:Nullable<Hash>, latency_ms:非負整数, status:succeeded / failed}。provider実行ではprovider/model必須、失敗時output_hash=null可。

ErrorCode: SafetyBlock / SchemaInvalid / StaleState / ProviderUnavailable / UnsupportedInput / InjectionSuspected / PolicyViolation / InternalIntegrityError / DelegationConflict。
Failure = {code:ErrorCode, explanation_ja:非空Text, retryable:Bool, case_id:Nullable<ID>}。壊れた入力からcase IDを採用せずnull可。失敗を成功Domain Objectへ変換しない。

## 10. Shadow Coreの入出力（SG-001用）

ShadowCoreInput = {schema_version:"0.5", case_id:ID, source_message:SourceMessage, interpretation:Interpretation, approved_decision:Decision, policy_version:非空Text}。
信頼されたアプリ／fixture呼出し元が承認済みDecisionを供給する。外部メールのJSONをこのまま信頼する入力口を作らない。policy_versionはインストール済みDELEGATION.md対応ルールを識別し、本文からpolicy定義を受け取らない。expected_*をproduction inputに入れない。

ShadowCoreResultはtagged union:
- 成功: {status:assessed, schema_version:"0.5", case_id:ID, assessment:DelegationAssessment, input_hash:Hash, audit:AuditEvent[], external_action_performed:false}
- 失敗: {status:rejected, schema_version:"0.5", failure:Failure, external_action_performed:false}

L3も有効なassessment結果であり、安全／外部実行成功を意味しない。失敗時に架空Decisionやdefault L0を作らない。初期実装は事前判定のみ。後半のDraft・Verifier・Approvalは契約として定義するがSHADOW_GATEの解除なく実装開始しない。

## 11. 契約受入条件

正常な全型を1件以上、各required欠落、追加property、不正enum、unknown ID、別case参照、型違い参照、duplicate ID、Evidence捏造、nullable誤用、数字文字列coercion、未知versionを検証する。
Decision→Draft→Verification→Approvalについて各hash/版/対象の単独改変を拒否する。ユーザー修正出典、do_not_answerと必要質問、LLMのapproved偽装、minimum降格、post降格、critical finding非blocking化を拒否する。
Schema検査だけで意味の安全性を証明したと扱わず、Domain・Policy・独立検証・EVALUATION.mdの回帰を別々に要求する。

### SD-07補足: 集合・条件・エラーの閉じ方

ID[]の集合用途（evidence_ids、supports、explicitly_unanswered、reason_codes、monetary_term_ids、Findingの参照ID）は重複禁止。理由コードも集合として整列する。Source/Interpretation/Decision/Bindingのcaseは外側の同一caseと一致させる。
金額・数量の負数はdecimalとしては表現可能だが、price/refund/quantityで負数を許す意味は本MVPに定義しないためDomain拒否する。discountは額として非負、値引率はquantityのunit=percentとして0〜100に制約する。通貨・日付・単位・modalityの推測補完はしない。
Value<Bool>のfalseとnot_stated/nullは異なる。文字列"unknown"はstatusの代用にしない。explicitなvalueに意味が確定できないplaceholderを入れて通すことも禁止する。
Failure.retryableはProviderUnavailableの一時障害のみtrue可、その他はfalse。再入力による新規処理は自動retryと区別する。
schema_versionは0.5固定、未知policy_versionは拒否。ModelExecutionとEnvelopeのID/role/prompt/schema/caseの対応はアプリが検証する。provider outputに権限付与を委ねない。

ClauseTermの条件・modality・scope・関連金額/期限/commitmentは重大比較対象。Textだけの一致で条件脱落を見逃さない。deadline_idsは同stateのDateTerm、monetary_term_idsはMonetaryTerm、commitment_idsはCommitmentを参照する。型違い/未知参照を拒否する。

## 12. SG-001 Architect補足（2026-09-16 / ADR-024）

Current契約は§13のschema_version="0.5" / policy_version="delegation-0.4"。ADR-024の判断1〜3も維持する。0.4以前・その他の版・旧policyとの混在はrejected。Schema版不正はSchemaInvalid、未対応policyはPolicyViolation。失敗結果は処理側の0.5を返し、旧入力を変換・版だけ書換えて受理しない。既存bindingと評価結果は再利用しない。

### 12.1 重大値の欠落

DELEGATION.md §14の表を規範とする。DateTerm.type=dateは期日・締切ではない純粋な暦日、deadlineは履行期限を表す。timezoneのnot_stated例外はtype=dateだけ。deadlineは暦日表記だけでも例外にしない。時刻・時差・締切を含む内容をdateへ分類して迂回してはならない。表現できない時刻依存はmissing_informationまたはambiguityの重大Riskとして残しL3とする。これは型だけで原文の意味を証明できるという意味ではなく、抽出・独立検証にも適用する契約である。

explicitは原文Evidenceまたは正当なユーザー由来の値に限る。fixtureのL2件数を維持するために未記載のcondition/scope等を創作しない。「条件なし」を含む既知値にも根拠を要求する。元の重大不明はapprove/modify/do_not_answerだけで解消しない。原文とInterpretationの誤りは新しいbindingで訂正する。

### 12.2 policy exception

Risk.typeにpolicy_exceptionを追加し、他のrequiredフィールドはRiskと同じ。StructuredState.risksへ格納する。ほかのRisk配列にこのtypeがあっても検出を省略しない。resolved/affects_critical/description/Decision/confidenceにかかわらずSG-001ではL3、理由POLICY_EXCEPTION。例外許可の信頼経路は未実装であり、通常承認を代用しない。入力が契約違反ならassessmentよりrejectedを優先する。

### 12.3 通貨原本の固定

正本はSIX ISO 4217 Maintenance AgencyのList One（Current Currency & Funds）。
https://www.six-group.com/en/products-services/financial-information/market-reference-data/data-standards.html

Claude Codeに、この公開原本と分類確認に必要な同サイトのList Two/Threeを一度の取得作業でHTTPS取得することを許可する。認証・アップロード・実行時通信は不要かつ対象外。offline要件はアプリ実行とテストに維持する。
保存先はpackages/core/reference/iso4217/。原本は応答バイト列のままlist-one.xml（補助原本はlist-two/list-threeと取得形式の拡張子）、記録は同ディレクトリのmanifest.json。
記録項目: source_url、retrieved_at_utc、原本の公表版/日付（存在しない場合null）、各原本SHA-256、抽出条件、採用コードのASCII昇順一覧とそのhash、除外コードと根拠、集合版識別子。
集合はList Oneの現行国・地域通貨。基金・貴金属・テスト・無通貨コードを除く。X始まりだけで除外せず地域通貨を含める。分類不明は採用せずArchitectへ示す。歴史リストに同コードの過去記録があるだけでは現行コードを除外しない。
集合版はrg-iso4217-YYYYMMDD-<採用一覧hashの先頭12桁>（日付はUTC取得日）。一覧hashはコードをASCII昇順・LF区切り・末尾LFあり・UTF-8 BOMなしで計算する。旧rg-iso4217-active-2026-09は未承認のまま引き継がない。
差分・除外根拠の照合後に固定集合を実装する。自動更新は禁止し、後日の変更は原本差分、回帰検証、Architectレビューとpolicy改版を伴う。原本を取得できない場合は通貨検証を未完了と報告する。
## 13. 質問の承認と回答内容の確定（ADR-025 / 2026-09-16）

schema_version="0.5" / policy_version="delegation-0.4"。0.4以前は拒否し、暗黙移行しない。後半機能の実装許可ではない。

Decision.question_answers: QuestionAnswer[]をrequiredで追加する。回答がなければ空配列。Interpretationへ回答承認を追加しない。
QuestionAnswerはrequired・closed object:
{question_id:ID, answer_text:非空Text, basis:user_assertion / source_evidence, evidence_ids:ID[], related_claim_ids:ID[], provenance:UserProvenance}。

- question_idは同じInterpretation.questionsの既存ID、配列内一意。配列はquestion_idのASCII昇順。Questionの対応DecisionItemがapprove/modifyである場合のみ記録可能。unknown/do_not_answerと回答の併存、重複、未知ID、型違い参照はPolicyViolationで拒否する。
- provenance.actor_idはDecision.approved_byと一致し、信頼されたユーザー操作またはfixture由来であること。回答文・根拠・参照もその承認対象に含める。LLMの自己申告、genericな質問approve、human_notesから回答を生成しない。
- user_assertionはユーザーが明示した回答内容。evidence_idsは空配列とし、原文に書いてあったと偽装しない。source_evidenceは同じInterpretation内の原文Evidenceを1件以上参照する。quote一致だけで回答の意味や客観的真実まで証明したとは扱わない。
- related_claim_idsは重複禁止・ASCII昇順。回答が表す既存Claim（必要ならQuestion以外）を参照する。参照先Decisionはapprove/modifyでなければならない。重大な約束・値・条件は対応する型付きClaimと承認を必要とする。参照だけで本文との意味一致を証明したとしない。
- 新規の重大意思を自由文だけへ隠してはならない。現契約で型付き表現・出典・承認を揃えられない回答は記録して安全処理を続けず、SPEC_BLOCKEDとして必要な契約解決へ戻す。Schema/参照の成立は意味検証の代用ではない。
- question_answers全体をdecision_hash対象に含める。回答・根拠・参照・provenance変更で新しいDecision版/hashを作り、下流bindingを失効する。既存canonical規則を使う。回答本文はPIIを含み得るため運用ログへ出さない。
- 必要質問は、有効なQuestionAnswerが1件あるかexplicitly_unansweredにある場合のみ、事前の意思確定が済んだと数える。元の質問本文がunknown/ambiguousなら回答レコードで解決した扱いにしない。「返信で実際に回答した」は別であり、後半の回答網羅検証を要する。
- SG-001は回答の記録・承認・参照・hash・事前判定のみ。自然文の独立意味検証・生成・最終承認・送信は実装せずNOT_RUN。QuestionAnswerがあるだけでL0/L1を許可しない（DELEGATION §15）。

受入: 必須配列欠落、重複/未知/別型のquestion_id、unknown/do_not_answer併存、空回答、出典偽装、不正なEvidence/Claim参照、承認主体不一致、単独改変による旧hash/binding再利用を拒否する。必要質問approveのみは未回答のまま。回答付きでもlegal/injection/重大欠落等のL3を解除しない。