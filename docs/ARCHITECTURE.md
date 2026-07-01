# AKS Controlled Executor

## Decision

Hermes is no longer the free executor for AKS data entry.

Codex CLI role:
- build and maintain the controlled executor;
- write scripts;
- write tests;
- audit logs;
- improve documentation.

Hermes role:
- optional conversational supervisor;
- read reports;
- pass user instructions;
- never execute free-form AKS browser actions.

Executor role:
- deterministic execution;
- no improvisation;
- dry-run by default;
- submission only with validation file.

N8N role, optional later:
- orchestration;
- scheduling;
- validation UI;
- notifications;
- log archive.

## Target flow

1. Audit environment.
2. Extract pending feed read-only.
3. Match candidates read-only.
4. Generate validation report.
5. Romain validates exact candidates.
6. Submitter processes only validated candidates.
7. Post-save verification.
8. Immutable run log.
