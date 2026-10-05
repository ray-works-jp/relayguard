# relayguard_eval — オフライン評価基盤とShadow記録

EVALUATION.md v0.2（§§2–8, 13–14）とSCHEMA.md v0.5 §8（ShadowOutcome）に基づく開発用の評価基盤。network・外部Action・LLMなし。

**表示の限界**: ラベルはBuilder候補（`builder_candidate` / SG-001の`gold_proposed`・`regression`）。正式Gold・正式release-set・Release Gate PASS・SHADOW_GATE判断ではない。reportは常に`release_gate=NOT_EVALUATED`、`shadow_gate=NOT_DETERMINED`。期待ラベルは実装と同じBuilderが作成したため、実装との一致はラベルの正しさを示さない。

## 実行（リポジトリ直下）

```powershell
.venv\Scripts\python.exe scripts\build_release_candidates.py
$env:PYTHONPATH = "packages\core;packages\evaluation"
.venv\Scripts\python.exe -m relayguard_eval run --suite release-set-candidates --out eval\runs\release-set-candidates
.venv\Scripts\python.exe -m relayguard_eval run --suite sg001 --out eval\runs\sg001 --baseline <旧report.json>
.venv\Scripts\python.exe -m relayguard_eval shadow-record --result result.json --observation obs.json --store shadow.jsonl
.venv\Scripts\python.exe -m relayguard_eval shadow-kpi --store shadow.jsonl --kind observed --from 2026-10-01T00:00:00.000Z
```

終了コード: 0=実行完了（不一致はreportに記録）、2=使用方法・入力エラー、3=suite/storeを全体として評価できない（fail closed）。

## 構成

| パス | 役割 |
|---|---|
| `eval/release-set-candidates/cases/*.case.json` | fixture_version 0.2のケースメタデータと期待ラベル（`packages/schemas/eval/eval_case_0_2.schema.json`） |
| `eval/release-set-candidates/inputs/*.input.json` | ShadowCoreInputのみ。ケースから`input_sha256`で固定。expected_*を含まない |
| `packages/evaluation/authoring/` | 100件の作成元（合成データ、20カテゴリ×5変種） |
| `relayguard_eval/cases.py` | suite読込。契約違反・hash不一致・重複・部分的なpostラベルは全体停止（Nを黙って減らさない） |
| `relayguard_eval/runner.py` | 固定clock/IDで実行、別seedで再実行して決定性を検査、運用ログへの本文漏洩を検査 |
| `relayguard_eval/metrics.py` | §13の指標とRelease blocker件数（PASS表示なし、post段階はNOT_RUN） |
| `relayguard_eval/shadow.py` | ShadowOutcome検証、assessmentへの束縛、追記専用hash chain store、KPI |
| `relayguard_eval/report.py` | 再現可能なreport.json（時刻なし）、日本語summary.md、regression diff |
| `eval/runs/<suite>/` | 審査用に保存したrun結果。現行コードとの一致をテストで検査 |

## 指標とNOT_RUN

- pre_generation段階のみ実行。post_verification / final_delegationは`NOT_RUN`（Generator・Reply Extractor・Verifier・Final ApprovalはSHADOW_GATE後）。
- 分母0は`N/A`。未実施は`NOT_RUN`。欠測のcost/timeは0にせず欠測率を併記。通貨は混合しない。
- fixture runのHuman Review / Safe Delegation / Critical Incidentは、人間の評価記録（`--observations`、evaluation_kind=fixture）がなければ`NOT_RUN`。
- 仕様にない評価側の判断は`HARNESS_DEFINITIONS`としてreportに毎回表示する。

## Shadow記録

- 予測側（assessment_id、predicted_delegation_level）は検証済みのassessed ShadowCoreResultからコピーし、呼出し側は指定できない。
- 観測側8項目は明示必須（既定値なし）。`final_outcome=unknown`なら`would_have_been_safe_to_automate=null`。確定した結果・安全判定には`adjudicator_id`必須。costと通貨は同時にnull/非null、負数拒否。
- storeは追記専用JSONL hash chain。同一assessmentの後続entryは改訂（事後評価）で、予測・evaluation_kind・bindingは変更不可。chain破損時はKPIを計算しない。
- fixtureとobservedは同時に集計しない。期間集計はassessmentの初回記録時刻で区切る。
- Safe Delegation RateはL0予測かつ独立評価で安全・重大事故なしのcase / N。L1は事後確認を要するため含めず、事前確認のみ省略可能率を別表示する。
