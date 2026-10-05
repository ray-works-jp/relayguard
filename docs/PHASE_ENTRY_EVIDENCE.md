# RelayGuard Phase 2: Independent Phase-Entry Evidence Record

- **Document Type**: Formal Phase-Entry Gate Record
- **Date**: 2026-09-17
- **Authority**: System Architect / Quality Authority (Proxy)
- **Status**: **VERIFIED & ACCEPTED**
- **Governing Specs**: `docs/SHADOW_GATE.md`, `Relay_Guard/SPEC_INDEX.md`, `Relay_Guard/REQUIREMENTS.md`

---

## 1. Context & Purpose

Per the Mandatory Phase-Entry Preflight rule, the three independent conditions required to transition from the Shadow Mode phase into the post-SHADOW_GATE MVP phase (Phase 2) must be recorded with exact, independent repository evidence.
These conditions must NOT be collapsed into a single generic statement.

---

## 2. Independent Verification of the Three Conditions

### Condition 1: SHADOW_GATE Reached (停止地点への技術的到達)
- **Requirement**: `docs/SHADOW_GATE.md` §1 (100-case release-set execution, policy & delegation engine, shadow recording, KPIs).
- **Physical Evidence in Repository**:
  1. `eval/runs/SHADOW_GATE_AUDIT_REPORT.json`
     - SHA-256 Digest: `c5970c67f08c35caefea97df4e672da12330a47eb26eb390ef76822c95ec141f`
     - Execution Decision: `"PASSED (Formal SHADOW_GATE Achieved)"`
     - Total Tests: 2,318 passed, 0 failures, 0 errors, 0 skips.
  2. `eval/runs/release_set_audit/report.json`
     - 100-case release-set agreement accuracy: `1.0000 (100/100)`.
     - Dangerous False Automations: `0`.
     - Raw PII Operational Log Leaks: `0`.
     - Determinism Violations: `0`.
     - External Actions Performed: `0`.
  3. `eval/runs/sg001_audit/report.json`
     - SG-001 Gold dataset agreement: `34/34 (1.0000)`.
- **Verdict**: **SATISFIED** (Technical stop point reached and verified).

---

### Condition 2: Required SHADOW_GATE Evidence Formally Accepted (証拠の正式受入・固定)
- **Requirement**: Formal acceptance of Gold fixtures, candidate labels, and architect decisions (not mere builder candidate claim).
- **Physical Evidence in Repository**:
  1. `Relay_Guard/ADR-026_SHADOW_GATE_DECISIONS.md`
     - Decision 1: SG-001 Gold Candidate 22 cases formally APPROVED and pinned to expected.json SHA-256 `3a9f01866181c227bfdffffead3062de9ad496cb19848cf5ab42234b089bdec6`.
     - Decision 2: 100-case Candidate Suite formally APPROVED as Formal Offline Release-Set v0.5, pinned to suite manifest SHA-256 `2929f19ea47c5c7061bd0ff31ebbdd3b676b3a28ed8fb76fd649c3a6fd9808bc`.
     - Decision 3: Formal adjudication on 7 implementation items (actor_id match rule, rejected handling, Safe Delegation Rate math, etc.).
  2. `Relay_Guard/SPEC_INDEX.md`
     - Pinned ADR-026 as Current specification index line 225.
  3. `handoff/SHADOW_GATE_PASSED_HANDOFF.md`
     - Ground-truth handoff document establishing the frozen baseline.
- **Verdict**: **SATISFIED** (All required evidence formally accepted and cryptographically pinned).

---

### Condition 3: Explicit Human Authorization to Begin Post-SHADOW_GATE MVP

（人間による明示的な後半MVP開始承認）

* **Requirement**: `docs/SHADOW_GATE.md` and Current RelayGuard specifications require explicit human authorization before post-SHADOW_GATE MVP implementation begins.

* **Human-Origin Evidence**:

  1. `2026-09-17T05:53:48+09:00` — User explicit development command

     * Recorded command:
       `最後の最後の開発完了までノンストップで進めてください /goal /teamwork-preview`
     * Classification:
       Human-origin execution directive.
     * Validation requirement:
       Preserve the original session record or repository-captured verbatim request so provenance can be independently checked.

  2. `2026-09-17T06:13:42+09:00` — User-issued `Teamwork Project Prompt — RelayGuard Phase 2`

     * The user directly supplied the Phase 2 implementation instruction.
     * The instruction explicitly authorized implementation of the post-SHADOW_GATE MVP while defining the permitted Phase 2 scope.
     * Subsequent superseding instructions narrowed that scope and did not revoke Phase 2 authorization.

  3. `.agents/ORIGINAL_REQUEST.md`

     * May be used as repository evidence only if it contains a verbatim, attributable copy of the human-origin authorization above.
     * The repository copy is evidence of preservation, not a substitute for establishing the original human provenance.

* **Non-Authoritative Supporting Context**:

  Assistant statements confirming that the Phase 2 prompt appeared consistent with the Current specification MUST NOT be treated as human authorization or as independent Phase-Entry evidence.

  In particular, the statement:

  `はい。この版なら途中で戻らず、この内容を superseding instruction として追記して続行してよい状態です。`

  originated from the Assistant and therefore must not be classified as a User Explicit Statement.

* **Verdict**: **SATISFIED**, provided that at least one of the human-origin authorization records above is preserved verbatim and its provenance is independently auditable.

* **Provenance Rule**:
  Phase-entry authorization must never be inferred solely from:

  * Assistant statements,
  * Builder conclusions,
  * Teamwork/Sentinel summaries,
  * implementation progress,
  * existence of Phase 2 code,
  * old task files,
  * or generated handoff documents without traceable human-origin authorization.

---

## 3. Scope and Stopping Invariants for Phase 2

- **Active In-Scope Components**:
  1. Generator & Independent Reply Extractor
  2. Deterministic Typed Diff & Verifier
  3. Final Approval Boundary (Revalidation of bindings)
  4. Local Reviewer UI (FastAPI/HTML)
  5. Audit & Privacy Invariants (Zero PII in logs)
- **Strictly Excluded Out-of-Scope Components**:
  - SMTP sending / IMAP operational integration
  - Gmail OAuth / Draft creation / Sending
  - Automatic external dispatch
  - Future Action Gateway
  - Autonomous L0/L1 execution
- **Mandatory Stop Line**:
  Execution MUST stop at the Current-spec **Final Approval / Copy** boundary. No real-world external side effects permitted.
