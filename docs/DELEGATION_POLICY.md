# ShadowGuard Delegation Policy

Status: Design Baseline
Policy Version: 0.1

## 1. Objective

重大事故率を増やさず、人間確認率を下げる。

## 2. Levels

- AUTO
- POST_REVIEW
- HUMAN_APPROVAL
- BLOCK

## 3. Decision Principle

最終Delegationは単純な平均スコアでは決めない。

```text
minimum_level_from_hard_rules
+ policy evaluation
+ authority evaluation
+ risk/uncertainty
+ independent evaluator
= final delegation
```

Hard Ruleで定まるminimum levelをLLMは下げられない。

## 4. Mandatory Minimum Rules

### BLOCK
- unresolved_prompt_injection
- schema_integrity_failure
- malicious policy override attempt
- unsupported critical input
- critical internal integrity failure

### HUMAN_APPROVAL minimum
- legal threat / legal claim
- contract change
- license/right change
- refund request where policy/amount/currency is unknown
- discount beyond auto-authority threshold
- high monetary impact
- PII-sensitive requested action
- contradictory history unresolved
- missing policy for relevant action
- conflicting policy
- stale policy
- evaluator detects critical mismatch
- strong uncertainty on critical field
- model outage / partial pipeline failure where a decision would otherwise be needed

### POST_REVIEW minimum candidates
- moderate customer emotion without monetary/legal/contract risk
- low-impact policy exception with explicit authority
- low-risk ambiguity resolved with evidence but not fully deterministic

### AUTO candidates
AUTOは次をすべて満たす場合のみ許可候補。

- no critical/high-risk hard rule
- relevant policy exists and is current
- authority explicitly allows action
- no unresolved ambiguity on critical fields
- no prompt injection signal requiring escalation
- monetary amount/currency, if relevant, are known and within deterministic thresholds
- no legal/contract/license/rights modification
- pipeline complete
- schema valid
- Independent Evaluator has no blocking finding

## 5. Risk Factors

- monetary impact
- irreversibility
- legal exposure
- contract/license exposure
- privacy sensitivity
- security sensitivity
- customer emotion
- reputational risk
- ambiguity
- missing information
- contradictory context
- prompt injection risk
- policy uncertainty
- authority uncertainty

## 6. Tie / Disagreement Rule

複数評価が不一致の場合、低い安全レベルへは緩和しない。

例:
Core=AUTO, Evaluator=HUMAN_APPROVAL
→ HUMAN_APPROVAL以上。

## 7. Unknown Policy

重大項目ではunknownをAUTOへ変換しない。

- unknown amount
- unknown currency
- unknown policy
- unknown authority
- ambiguous contract/license/legal signal

は原則HUMAN_APPROVAL以上。

## 8. Customer Emotion

怒り、不信、解約示唆等は単独でBLOCKにしない。

ただし、
- money
- refund
- cancellation
- contract
- legal threat
- public complaint
と組み合わさる場合はlevelを引き上げる。

## 9. Metrics

- Dangerous AUTO Rate
- Safe Automation Rate
- Human Review Rate
- False Negative Rate
- Policy Violation Detection Rate

Dangerous AUTOを減らすことが最優先だが、AUTOを0にすることで達成したとは評価しない。
