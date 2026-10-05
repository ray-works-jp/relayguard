# RelayGuard Phase 2 Test Infrastructure Specification (TEST_INFRA.md)

- **Document Version**: 1.0.0
- **Status**: ACTIVE / ENFORCED
- **Target System**: RelayGuard Phase 2 (Production Full Implementation)
- **Authority / Source of Truth**: `Relay_Guard/SPEC_INDEX.md`, `docs/SHADOW_GATE.md`, `ORIGINAL_REQUEST.md`
- **Role**: Integration / E2E / Adversarial QA (`teamwork_preview_test_writer_e2e`)

---

## 1. Executive Summary & Core Testing Principles

RelayGuard is a fail-closed, high-assurance email triage, generation, verification, and dispatch gateway designed to prevent dangerous AI misclassifications and unauthorized commitments. 

### 1.1 The Cardinal Quality Standard
The single most catastrophic defect in RelayGuard is **Dangerous Automation (False Auto)**: misclassifying or dispatching an email at `L0_AUTO` or `L1_POST_REVIEW` when the matter strictly requires human approval (`L2_PRE_APPROVAL`) or emergency halt (`L3_STOP`).

Our testing infrastructure enforces:
1. **Zero Tolerance for Dangerous Automation**: Any code or test failure that allows an unapproved discount, altered deadline, unauthorized promise, or dropped condition to pass verification or reach dispatch is a blocking failure.
2. **Fail-Closed Boundary**: Under any unexpected exception, parsing failure, schema violation, or network disconnect, the system must drop into `status = "rejected"` or `L3_STOP` without performing any external action.
3. **Cryptographic & Immutability Invariants**: All artifacts (source message, interpretation, decision, draft, verification, audit event) are cryptographically bound via canonical SHA-256 hashes (RFC 8785). Any tampering must invalidate downstream execution.
4. **Opaque-Box Verification**: End-to-end tests operate against external entrypoints (CLI, JSON schemas, public module contracts, mock communication boundaries) without relying on internal white-box mocks.

---

## 2. The 4-Tier Testing Methodology

To guarantee complete, defect-free coverage across the system lifecycle, RelayGuard Phase 2 adopts a rigorous 4-Tier testing methodology.

```
┌────────────────────────────────────────────────────────────────────────┐
│               Tier 4: Real-World Workload Testing                      │
│   (Multi-step enterprise lifecycles, end-to-end flow, mock gateways)   │
├────────────────────────────────────────────────────────────────────────┤
│             Tier 3: Pairwise Combinatorial Testing                     │
│    (All-pairs orthogonal interactions across channels, levels, diffs)  │
├────────────────────────────────────────────────────────────────────────┤
│             Tier 2: Boundary Value Analysis (BVA)                      │
│ (Off-by-one dates, Decimal precision, extreme lengths, UTF-8 quirks)   │
├────────────────────────────────────────────────────────────────────────┤
│           Tier 1: Category-Partition Testing (Baseline)                │
│    (Nominal and error partitions per feature; exit codes; invariants)  │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Tier 1: Category-Partition Testing (Functional Baselines)
- **Objective**: Divide each system capability and interface into functional equivalence categories (input domains, operational states, decision outcomes) and execute representative test cases for each nominal and error partition.
- **Coverage**:
  - RelayGuard CLI invocation (`python -m relayguard <file.json>`)
  - Error classification taxonomy (9 canonical failure codes)
  - Cryptographic & canonical hash invariants
  - Pre-generation delegation assessment & mandatory minimum rules
  - Deterministic reply generation & prompt safety (R1)
  - Structured reply claim extraction & evidence binding (R1)
  - Deterministic typed diff comparison (R2)
  - Cryptographic verifier & emergency halt precedence (R2)
  - In-line gateway fail-closed dispatching (R3)
  - Reviewer UI API & L2 review queue state transitions (R4)
  - Controlled mock transports & zero-PII telemetry (R5)
- **Threshold**: **>= 5 test cases per feature category**.
- **Exit Criteria**: All nominal partitions succeed; all error partitions trigger exact failure codes and exit codes (0 = assessed, 1 = rejected, 2 = usage error).

### 2.2 Tier 2: Boundary Value Analysis (BVA)
- **Objective**: Stress inputs and internal state representations at their exact domain boundaries (minimum, maximum, just below, just above, and outside valid ranges).
- **Key Boundary Domains**:
  1. **Monetary Quantities & Precision**: Zero amount (`$0.00`), extreme values (`$999,999,999.99`), high fractional precision (`0.0001`), negative amounts, scientific notation rejection (`1e5`), ISO 4217 active vs. inactive currency codes.
  2. **Dates & Deadlines**: Exact current timestamps, leap years (e.g. Feb 29), timezone shifts (`UTC` vs. `UTC+9`), date-only vs. deadline datetime, ambiguous date formats.
  3. **Payload & Text Length**: 0-byte inputs, single-character strings, exactly 64 KB source payload limit, 64 KB + 1 byte (rejection boundary), extreme whitespace.
  4. **Character Encoding & Normalization**: Japanese full-width punctuation (e.g. `！`, `？`, `。`), Unicode NFKC/NFC equivalence, surrogate pairs, emoji, control characters (`\x00`, `\r\n`).
  5. **Claim Counts & Arrays**: Empty claim arrays, single claim, maximum allowed claims (100 items), duplicate claim IDs, circular evidence references.
- **Threshold**: **>= 5 test cases per boundary domain**.

### 2.3 Tier 3: Pairwise Combinatorial Testing (All-Pairs)
- **Objective**: Detect multi-parameter interaction defects that escape single-feature tests by generating an orthogonal array / pairwise combinatorial matrix covering orthogonal system factors.
- **Factor Dimensions**:
  | Dimension | Levels / Options |
  |-----------|------------------|
  | **Inbound Channel** | Mock SMTP, Mock IMAP, Mock Gmail Connector |
  | **Language** | English (`en`), Japanese (`ja`) |
  | **Pre-Assessment Level** | `L0_AUTO`, `L1_POST_REVIEW`, `L2_PRE_APPROVAL`, `L3_STOP` |
  | **Diff Finding Type** | None (Matched), Minor Text, Amount Discrepancy, Date Shift, Modality Escalation (`may` -> `will`), Dropped Condition |
  | **Approval State** | Auto-approved (`L0`), Post-review (`L1`), Human Approved (`L2`), Human Rejected (`L2`), Unapproved Pending (`L2`), Blocked (`L3`) |
  | **Transport Fault State** | Normal delivery, Connection timeout, MIME parse failure, Socket disconnect |
- **Combinatorial Coverage**: 100% 2-way (pairwise) coverage across all pairs of parameter levels.
- **Threshold**: Systematic pairwise test suite executing all generated pairs.

### 2.4 Tier 4: Real-World Workload Testing (Lifecycle Scenarios)
- **Objective**: Validate the cohesive, multi-step operation of RelayGuard under realistic, production-grade enterprise email workloads.
- **Workload Scenarios**:
  - **Scenario 1: Clean Low-Risk Inbound Auto-Resolution (`L0_AUTO`)**:
    Customer order status check -> Pre-assessment evaluates `L0_AUTO` -> Generator produces draft -> Extractor parses claims -> Diff confirms zero drift -> Verifier confirms `SAFE_CANDIDATE` -> Gateway automatically queues & sends message -> Hash chain logs `gateway.message_dispatched` -> Operational telemetry contains zero PII.
  - **Scenario 2: Angry Customer with Past Delivery Delay (`L2_PRE_APPROVAL`)**:
    Customer express frustration + delivery delay -> Pre-assessment enforces `minimum L2_PRE_APPROVAL` (`CUSTOMER_SENSITIVITY`) -> Generator produces draft -> Verifier approves draft proposal -> Gateway holds message in review queue -> Human operator logs into Reviewer UI, inspects diff, issues `FinalApproval` -> Gateway dispatches -> Post-review audit ticket generated.
  - **Scenario 3: Synthetic Reply Mutation Attack Rejection (AC-36 / `L3_STOP`)**:
    Customer requests refund -> Decision authorizes $50 -> Generator or tampered draft offers $150 and adds 2-year warranty -> Extractor independently extracts $150 & warranty claim -> Diff Engine detects critical amount mismatch and unauthorized guarantee -> Verifier triggers emergency halt: forces `policy_status = "BLOCK"` and escalates to `L3_STOP` -> Gateway permanently drops message -> Audit log records security rejection.
  - **Scenario 4: Immediate Legal Claim Halt (`L3_STOP`)**:
    Customer mentions attorney / litigation -> Pre-assessment triggers mandatory `legal_claim` rule -> Immediate `L3_STOP` -> Generator is never invoked (token & compute saved, zero risk of hallucinated promises) -> UI shows halted status.
  - **Scenario 5: Delivery Gateway Failure & Recovery Fail-Closed (AC-37)**:
    Approved L0 message dispatched -> Mock SMTP server simulates network timeout -> Gateway retries within bounds -> Fails closed without corrupting the audit hash chain -> Message remains safely tracked as undelivered.
- **Threshold**: Realistic multi-step end-to-end integration scenarios verifying complete system lifecycle.

---

## 3. Requirement & Acceptance Criteria Traceability Matrix

| Requirement | Description | Target Milestones | Primary Tier | Acceptance Criteria & Invariants |
|-------------|-------------|-------------------|--------------|----------------------------------|
| **R1** | Deterministic Generator & Structured Reply Extractor | M1 | Tier 1, Tier 2 | AC-33: Complete extraction of claims without leaking CoT; draft_hash binding; response language support (`en`, `ja`). |
| **R2** | Reply Diff Engine & Cryptographic Verifier | M2 | Tier 1, Tier 2, Tier 3 | AC-36: 100% detection and rejection of synthetic reply mutations; diff precedence overrides LLM; monotonic non-decrease of delegation level. |
| **R3** | In-Line Gateway & Safe Communication Adapter | M3 | Tier 1, Tier 3, Tier 4 | AC-37: Fail-closed delivery: only L0, L1, or approved L2 allowed; L3/BLOCK dropped; hash-chain audit binding. |
| **R4** | Reviewer UI & Operational Dashboard | M4 | Tier 1, Tier 4 | AC-33: Inspection of cases, L2 review queue, diff visualization, live KPI calculation (Safe Automation Rate, Review Overhead, Zero-Tolerance Score). |
| **R5** | Controlled Infrastructure & Security Invariants | M5 | Tier 1, Tier 2, Tier 4 | AC-38: Zero raw PII in logs; mockable isolated transports (zero live network); AC-39: Interactive demo execution. |
| **Quality Gates** | Static Analysis & Regression Integrity | M_FINAL | All Tiers | AC-30 (`ruff check` & `ruff format`), AC-31 (`mypy strict`), AC-32 (100% of 2,318+ regressions remain green). |

---

## 4. Opaque-Box Test Framework Design in `tests/e2e/`

### 4.1 Test Directory Structure
```
tests/
└── e2e/
    ├── __init__.py
    ├── conftest.py                     # Shared opaque-box fixtures, test harness helpers
    ├── test_e2e_tier1_features.py      # Tier 1: Category-Partition functional baselines
    ├── test_e2e_tier2_boundaries.py    # Tier 2: Boundary Value Analysis & stress limits
    ├── test_e2e_tier3_combinations.py  # Tier 3: Pairwise combinatorial interaction tests
    └── test_e2e_tier4_workloads.py     # Tier 4: Real-world enterprise lifecycle workloads
```

### 4.2 Test Runner Commands & Pass/Fail Semantics

All tests are executed using Python 3.14 via the committed virtual environment:

```powershell
# 1. Execute the entire E2E test suite (Tiers 1-4)
.venv\Scripts\pytest.exe tests/e2e -v

# 2. Execute Tier 1 baseline feature tests only
.venv\Scripts\pytest.exe tests/e2e/test_e2e_tier1_features.py -v

# 3. Execute with strict regression suite (2,318+ tests + E2E)
.venv\Scripts\pytest.exe packages/core/tests packages/evaluation/tests tests/e2e -q

# 4. Verify static quality gates
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
.venv\Scripts\mypy.exe --config-file pyproject.toml
```

### 4.3 Pass/Fail Semantics & Invariants
- **CLI Exit Codes**:
  - `0`: Assessed successfully (`status = "assessed"`).
  - `1`: Fail-closed rejection (`status = "rejected"`).
  - `2`: Usage / CLI invocation error.
- **Result Status**:
  - Only two top-level statuses exist: `"assessed"` and `"rejected"`. Any other value is invalid.
  - When `"rejected"`, the payload must contain `failure.code` matching one of the 9 canonical codes and `retryable: false`.
- **Hash Invariants**:
  - Canonical JSON: Sorted keys, no whitespace separators (`','`, `':'`), strict UTF-8 (RFC 8785).
  - Chain integrity: `event[i].previous_hash == event[i-1].event_hash`.
  - Tail entity binding: `audit[-1].entity_hash == canonical_hash(assessment)`.
- **Security Invariants**:
  - Network isolation: No socket connection attempts (`socket.create_connection`, `socket.socket.connect` blocked).
  - Zero PII: Operational logger (`relayguard.shadow_core`, `relayguard.gateway`, etc.) output inspected at `DEBUG` level contains zero email bodies, credit cards, or customer names.

---

## 5. Test Data Management & Cryptographic Vector Integrity

1. **Synthetic Data Only**: All test fixtures use synthetic email content and dummy actor IDs (e.g. `fixture_actor_01`, `case_e2e_001`). No real personal data or live mailbox credentials are used.
2. **Deterministic Time**: Fixed timestamps (e.g. `2026-09-15T09:30:00.000Z`) are injected via test runtimes to guarantee byte-for-byte reproducibility of hashes.
3. **Isolation**: Every test creates independent, self-contained fixtures using `tmp_path`. No test relies on preceding test state or global variables.
4. **Invalidation Invariants**:
   - Any modification of `expected.json` SHA-256 (`3a9f01866181c227bfdffffead3062de9ad496cb19848cf5ab42234b089bdec6`) triggers gate failure.
   - Any modification of release-set candidates manifest SHA-256 (`2929f19ea47c5c7061bd0ff31ebbdd3b676b3a28ed8fb76fd649c3a6fd9808bc`) triggers gate failure.
