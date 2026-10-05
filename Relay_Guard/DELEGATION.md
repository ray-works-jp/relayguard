# RelayGuard Delegation Policy Engine v0.4

## 1. 目的

案件ごとに、人間をどこまで介在させる必要があるかを判定する。

主要最適化目標:

> 重大事故率を増やさず、人間確認率を下げる。

## 2. Delegation Levels

### L0 AUTO
人間確認なしで処理可能。

MVPではShadow Modeのみ。

### L1 POST_REVIEW
AIが処理し、後から人間確認。

### L2 PRE_APPROVAL
実行前に人間承認必須。

### L3 STOP
AIだけで判断しない。停止・エスカレーション。

## 3. 判定入力

- monetary_impact
- refund_or_credit
- contractual_change
- rights_change
- license_change
- guarantee
- deadline_change
- quantity_change
- personal_data
- legal_claim
- customer_emotion
- reputational_risk
- prior_commitment_conflict
- ambiguity
- missing_information
- attachment_dependency
- prompt_injection_risk
- verifier_findings
- deterministic_diff
- policy_exception

## 4. 強制Minimum Rules

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

AIはminimum levelを下げられない。

## 5. 補助Risk Scoring

ルールで確定しない案件のみ、

impact / uncertainty / irreversibility / customer_sensitivity

を補助評価に使う。未校正の数値積を閾値判定に使わず、§12の明示ルールへ写像する。

Confidence単独で委任レベルを下げない。

## 6. Customer Emotion

怒り、不信、解約示唆、公開苦情等は単独決定要因にしない。

ただし、

- 金銭
- 過去の誤対応
- 契約
- 解約
- 公開苦情

と組み合わせた場合は委任レベルを上げる。

## 7. Shadow Mode

MVPで記録:

```text
predicted_delegation_level
actual_human_intervention
final_outcome
would_have_been_safe_to_automate
```

L0/L1判定でも自動送信しない。

## 8. KPI

- Safe Delegation Rate
- Human Review Rate
- Escalation Rate
- Critical Incident Rate
- False Automation Rate
- False Escalation Rate
- Verification Cost per Case
- Human Minutes per Case

最重要:

Safe Delegation Rate
= 重大事故なしで人間確認を省略可能だった案件 / 全案件

## 9. Pre/Post Verification

Approved Decision確定後に一次判定し、Verification後に再評価する。

```text
Interpret
  ↓
Decision
  ↓
Delegation Assessment #1
  ↓
Generate
  ↓
Verify + Deterministic Diff
  ↓
Delegation Assessment #2
  ↓
Final Approval
```

後段評価は前段より低い安全レベルへ勝手に緩和しない。

## 10. Release Policy

自動化率を上げる変更は、

Critical Incident Rateを悪化させない証拠

がなければ採用しない。

## 11. 将来

十分なShadow Mode実績と新しいThreat Modelを通過した後にのみ、L0/L1の実自動化を解放する。

## 12. Architect確定ルール — policy_version=delegation-0.4

この節はSD-10の決定。§4のminimumを一切緩和せず、未定義だった低リスク境界を固定する。判定結果・入力契約はSCHEMA.mdに従う。

1. 入力契約違反、未対応policy_version、欠落・stale bindingは正常assessmentを作らずrejected。L0/L1へfallbackしない。
2. §4のL3条件が1つでもあればL3。legal_claims非空、重大判断に影響するunknown/ambiguous/必要値欠落、必要添付未取得、未解決injection、矛盾する約束、Critical typed diffを含む。LLMのresolved=trueまたは人間の単なる「承認」でこれらを解除しない。
3. §4のL2条件が1つでもあればminimum L2。「material」は承認対象の金額・通貨・期限を新設／変更すること。金額大小の免除閾値を設けない。単に相手が金額を書いたことと、こちらが金銭を約束することを区別する。
4. 数量の新設／変更、個人情報の新規開示、policy exception、新規の非金銭commitmentもminimum L2。ユーザーの未承認のまま返信へ入った重大変更ならL2承認待ちに落とさずL3。
5. 未解決の非重大な不明点、必要質問のunknown、分類できないリスクはminimum L2。必要質問のunknownが重大意思に影響すればL3。policy exceptionの可否そのものが不明ならL3。
6. L0は、既知の情報の回答または受領確認だけで、新規commitment・金銭/期限/数量/権利/ライセンス/返金/保証/契約変更・PII開示・未解決事項・感情リスク・policy exceptionがなく、必要質問が全て回答または明示do_not_answerで処理済みの場合に限る。
7. L1は、L0と同じ重大条件なし・意思確定済みで、残る要素が文体・顧客感情への配慮のみの案件。怒り・不信だけでL2/L3にせずL1の事後確認候補とする。金銭・契約・解約・過去誤対応・公開苦情との複合ならminimum L2、法的主張等があればL3。
8. 以上に該当しない案件はL2。分類不能の重大リスクならL3。confidenceで降格しない。post評価はmax(pre, post minimum, post提案)より低くしない。

RiskFactorsは分類根拠の説明用。impactは新規の重大約束ならhigh、その他の個別回答ならmedium、受領/既知情報のみならlow。uncertaintyは未解決重大ならhigh、非重大ならmedium、解決済みならlow。irreversibilityは外部義務・権利変更ならhigh、その他の新規約束ならmedium、約束なしならlow。customer_sensitivityは法的/公開苦情ならhigh、その他の感情リスクならmedium、なしならlow。判定不能の軸はunknownでありlowに置換しない。
minimum_levelは上記ルールからDomainが算出する。複数ruleの最大レベルを採用し、すべての発火reason_codesを記録する。低リスク分類も理由を必須にする。

## 13. 承認・停止・復帰（SD-08）

L2の事前承認はまずApproved Decisionを意味する。未承認Decisionで生成しない。MVPではL0/L1を含め、検証通過後の別の最終承認をコピー前に必須とする。post評価でL2になっても最終承認を省略しない。
L3は生成・最終承認・コピーを許可しない。停止理由は表示できるが、表示画面への遷移を承認権限にしない。
解除は対象原因の解消を新しいSource/Interpretation/Decisionへ反映し、該当する独立検証を再実行した新しいbindingの評価だけで行う。旧assessmentを降格・上書きしない。
legal_claimは案件に存在する間L3。ユーザーが承認してもAI処理再開の免除にならない。MVPでは手動対応へ引き継ぐ。
Schema不正やbinding不一致は修正した入力で新規処理する。旧safe結果の再利用は禁止。必要添付はMVPで解析しないため、未取得のまま処理を進めない。

## 14. SG-001の決定可能な保守的境界（ADR-024）

本節は§12の不足を確定する。schema_version=0.5 / policy_version=delegation-0.4。L3を先に適用し、L2理由が発火しても降格しない。全発火理由を記録する。

### 14.1 必要値

以下の中核値・修飾値はすべてexplicitを要求し、unknown/ambiguous/not_statedはL3 + CRITICAL_MISSING_INFORMATION。唯一の例外はDateTerm.type=dateのtimezone=not_stated。timezone=unknown/ambiguousは例外でない。元Claimとreplacement双方を検査し、Decisionで元の重大不明を消さない。

| Claim | 必要値 |
|---|---|
| MonetaryTerm | amount, currency, condition |
| DateTerm | date, timezone（上記例外のみ） |
| QuantityTerm | quantity, unit, condition |
| ClauseTerm | text, modality, condition, scope |
| RightsLicenseTerm | scope, exclusivity, sublicensing, commercial_use, condition |
| Commitment | action, object, modality, condition, scope。actor=unknownもL3 |
| personal_dataのTextClaim | text |

情報量不足の停止が増えることを受容する。False Escalationは測定し、L3増加を品質改善やRelease合格とみなさない。低リスク条件より本表を優先する。

### 14.2 approveとmodifyの境界

新規/既存を表すSchemaフィールドは今回追加しない。
contract_terms/prohibitions/cancellation_terms、guarantees、refund_terms、rights/license_terms、personal_dataについて、approveは識別不能としてminimum L2 + UNCLASSIFIED_RISK。
modifyでは元値とreplacementの実質的な内容差（id/evidence_idsだけの差を除く）を比較する。差がなければapproveと同じ。差があればそれぞれCONTRACTUAL_CHANGE、NEW_GUARANTEE、REFUND_OR_CREDIT、RIGHTS_OR_LICENSE_CHANGE、PERSONAL_DATA_DISCLOSUREをminimum L2で記録する。後二者を含む理由は変更による開示/義務のリスクを表し、実際に外部送信したという監査記録ではない。
Commitmentのapprove/modifyは、元/有効値のactor=userなら承認によるユーザー義務の引受けとしてNEW_COMMITMENT、counterparty/third_partyのみならUNCLASSIFIED_RISK（いずれもminimum L2）。元/有効値のいずれかがactor=unknownならL3 + CRITICAL_MISSING_INFORMATION。相手の約束をユーザーの約束として記録しない。
unknown/do_not_answerは新規承認の根拠としないが、既存の重大不明・L3条件を消さない。その他の金額・期限・数量・返金等のルールは併存し、該当する理由をすべて残す。

### 14.3 policy exceptionと評価

policy_exceptionはSG-001では常にL3 + POLICY_EXCEPTION。§12の「minimum L2」は下限であり、例外許可を検証できない本段階ではL3を採用する。resolved=true、affects_critical=false、approve、modify、do_not_answerでも解除しない。
現行20件の期待値は未承認。元入力を保った回帰ケースの期待値を本版で再評価し、L2正常ケースが必要なら根拠のある別の合成原文から作る。原文にない値で既存Interpretationを埋めてはならない。新旧版混在、date/deadline例外、actor別、同値modify、policy例外の偽装解除を回帰対象とする。
入力・level・minimum_level・全reason_codes・risk_factorsをArchitectが再審査した後に対象版を固定し、Antigravity独立QAへ渡す。20件は100件Release Gateの代用ではない。
## 15. SG-001の回答記録と低リスク境界（ADR-025）

SCHEMA §13に従うQuestionAnswerはユーザーの回答意思の正本であり、客観的真実や返信の実施済み記録ではない。
質問approve/modifyだけでは回答確定にならない。必要質問に有効な回答もdo_not_answerもなければminimum L2 + UNCLASSIFIED_RISK。重大意思に関わる不明は従来どおりL3。
有効なQuestionAnswerが1件でもあれば、独立意味検証がないSG-001ではminimum L2 + ANSWER_REVIEW_REQUIRED。自由文をknown-infoと自己分類してL0/L1へ下げない。既存L3と他の全発火理由は維持する。
したがってSG-001のL0/L1は回答レコードなしで§12.6–7を満たす受領/通知/意図的未回答に限る。これは本段階の保守的境界であり、製品全体の既知情報回答の将来候補を廃止するものではない。
回答表現がないためimpact=mediumは永遠に到達しない、というテスト前提を廃止する。回答に新規重大義務がなく個別回答と判断できればimpact=medium。既知情報のみと根拠から判断できればlow、重大約束/変更はhigh、判断できなければunknown。回答レコードがあるだけで軸をlowにしない。未検証の回答意味が残るSG-001ではuncertaintyは最低medium、重大不明ならhigh。
未知添付に依存する契約内容や、矛盾する既往義務の影響・不可逆性は、Claim配列が空だからlowにはできない。判断根拠が欠ける軸をunknownとする。
怒りと過去の遅延対応の複合は§12.7の過去誤対応に該当しminimum L2 + CUSTOMER_SENSITIVITY。「質問がない」だけでL1にしない。