"""RelayGuard offline evaluation harness (EVALUATION.md v0.2 §§2-7, 13-14).

Development evaluation only. Labels are Builder candidates unless an Architect approval is
recorded elsewhere; nothing here reports a formal Gold label, a formal release-set, a
Release Gate PASS or a SHADOW_GATE decision. Post-verification stages (Generator, Reply
Extractor, Verifier, Final Approval) are not implemented and are reported as NOT_RUN.
"""

RUNNER_VERSION = "rg-eval-0.1"
FIXTURE_VERSION = "0.2"
