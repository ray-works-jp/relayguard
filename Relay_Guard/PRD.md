# RelayGuard PRD v0.3

## 1. Product Definition

RelayGuardは、AIへ業務を委任するときに、AIが何を理解し、何を判断し、何を約束し、何を実行しようとしているかを、ユーザーが自分の言語で監督・修正・承認できるようにする Delegation Control Layer である。

MVPは「日本語ユーザーが英語メールへ安全に返信する」ユースケースに限定する。

RelayGuardは単なる翻訳・メール生成アプリではない。最新の中心仮説は、RelayGuardを「安全のために人間確認を増やす製品」ではなく、**人間確認が不要な案件を増やし、AIへ委任できる範囲を安全に拡大する Delegation Engine** として設計することである。

## 2. Core Problem

AI能力が高まるほど、ユーザー自身が直接検証できない範囲も拡大する。

最重要事故は、

> AIが危険な意味変更や約束を行ったにもかかわらず、ユーザーには安全に見えてしまうこと。

である。

同時に、すべての案件を人間確認に戻す設計では、AI委任の価値を失う。

したがってRelayGuardは、

- 重大事故を止める
- 不要な人間確認を減らす

という二つを同時に最適化する。

## 3. Primary User

初期ユーザーは、日本語では判断できるが英語の契約条件・交渉・金額・期限・権利等を十分な精度で直接確認できないユーザー。

長期的には、できるだけAIへ業務を任せたい一方で、顧客体験・金銭・契約・ブランド事故を避けたい事業者・AI運用者も対象となり得る。

## 4. Primary Job

英語原文を直接読まなくても、

- 相手が何を求めているか
- 何を回答すべきか
- 何を約束することになるか
- 何が不明・危険か
- どこまでAIへ任せられるか

を日本語で判断できるようにする。

## 5. MVP Flow

英語メール入力
→ 原文解析
→ 日本語Decision Sheet
→ ユーザーが承認・修正・不明・回答しないを指定
→ Approved Decision Stateを確定
→ Delegation Engineによる委任レベル判定
→ Generatorが返信案生成
→ 独立Reply Extractor / Verifier / Deterministic Diff
→ Policy再評価
→ 最終承認
→ コピー

MVPでは自動送信しない。

## 6. Delegation Levels

- L0_AUTO
- L1_POST_REVIEW
- L2_PRE_APPROVAL
- L3_STOP

MVPではL0/L1もShadow Modeで判定のみ行い、実際の自動外部操作は解放しない。

## 7. Decision Sheet

最低限、以下を構造化する。

- 相手の目的
- 要求
- 回答必須質問
- 金額
- 通貨
- 日付
- 期限
- 数量
- 契約条件
- ライセンス条件
- 権利
- 禁止事項
- 保証
- 返金条件
- キャンセル条件
- 相手が求める約束
- こちらが行う約束
- 個人情報
- 顧客感情
- ブランドリスク
- 法的主張
- 過去の約束との矛盾
- リスク
- 不明点
- 推奨アクション
- 人間判断要否
- 信頼度

## 8. Safety Requirements

1. GeneratorとVerifierを論理的に分離する。
2. VerifierへGeneratorの内部推論・会話履歴を渡さない。
3. 重要情報は自然言語だけでなく構造化データでも比較する。
4. 不明・矛盾・重大差異ではFail Closed。
5. Decision Stateをユーザー意思の正本とする。
6. 状態をversion/hashで束縛する。
7. 原文を命令ではなく非信頼データとして扱う。
8. LLM出力はSchema / Domain / Policy validation後にのみ採用する。
9. 監査可能性を維持する。
10. Verifier単独の自己申告を安全証拠としない。

## 9. Delegation Engine Goal

RelayGuardは「AIを制限する」こと自体を目的としない。

目的は、

> 重大事故率を増やさず、人間確認率を下げること。

である。

## 10. Core KPIs

- Safe Delegation Rate
- Human Review Rate
- Escalation Rate
- Critical Incident Rate
- False Automation Rate
- False Escalation Rate
- Verification Cost per Case
- Human Minutes per Case

## 11. Release Quality Gate

最初のRelease Gateは、100件以上の意図的に危険な評価セットに対して、

- 勝手な金額変更
- 通貨変更
- 期限変更
- 数量変更
- 権利変更
- ライセンス変更
- 返金
- 保証
- 新規約束

を重大事故として見逃さないこと。

さらに、委任レベル判定が過剰にL2/L3へ寄りすぎていないかも評価する。

## 12. MVP Non-Goals

- 自動送信
- 自動返金
- 自動購入
- 自動契約
- 無承認外部操作
- Gmail OAuth
- Gmail Draft
- 添付本文解析
- URLクロール
- 組織/RBAC
- workflow builder
- 長期メモリ
- 自律エージェントループ

## 13. Success Criteria

主要成功条件:

1. ユーザーが英語原文を直接読まずに安全に返信判断できる。
2. Critical意味変更を安全として通過させない。
3. 不要な人間確認を減らせる。
4. ユーザーが最終意思決定権を保持する。
5. Shadow Modeで「本来どこまで自動化できたか」を測定できる。

## 14. Agent-readable Product Design

将来的にRelayGuard自身も、代理AIから評価可能なProduct Manifestを持つ。

候補項目:

- purpose
- supported_tasks
- unsupported_tasks
- pricing
- permissions_required
- data_access
- data_retention
- external_actions
- human_approval_required
- limitations
- refund_policy
- security_controls
- auditability
- failure_behavior
- evidence
- version

## 15. Product Boundary

RelayGuardは「AIが常に正しいことを保証する製品」ではない。

AI委任を構造化し、重大差異・不明・権限逸脱を検出し、案件ごとに適切な委任レベルへ振り分け、人間が主導権を保持したままAIへ任せられる範囲を拡大する製品である。

## 16. 確定ベースラインと段階境界

本製品はRelayGuard。ShadowGuardは独立Domainではなく、Shadow Mode / SHADOW_GATEまでの開発段階を指す。
要件の統合はREQUIREMENTS.md、詳細契約はSPEC_INDEX.md指定のCurrent Core Specsに従う。入力構造・判断出典・bindingはSCHEMA.md、委任の具体条件はDELEGATION.md、合格・測定条件はEVALUATION.md、運用境界はIMPLEMENTATION.mdを参照する。
初期受入はoffline fixtureで構造・Decision・minimum委任判定を再現できること。Shadow段階は100件評価と記録・指標を揃える。後半の日本語UI・返信生成・独立検証・最終承認・実メールpilotはSHADOW_GATEの人間再開承認後。
本書§13の利用価値は実パイロットによって確認する。fixture通過のみで「英語を読まず安全に返信できた」としない。Gate到達条件と再開条件は../docs/SHADOW_GATE.mdを変更しない。
