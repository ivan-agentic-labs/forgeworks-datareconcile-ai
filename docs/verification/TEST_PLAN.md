# DataReconcile AI — Verifiable test and evaluation plan

| Test ID | Scenario | Fixture / setup | Expected acceptance result | Execution |
|---|---|---|---|---|
| FIN-T01 | CSV amount contains locale ambiguity | 1,234 ambiguous fixture | quarantine, no guess | NOT RUN |
| FIN-T02 | Concurrent review approvals | two stale writes | one accepted, other 409 | NOT RUN |
| FIN-T03 | Duplicate external reference across batches | duplicate rows | preserve provenance; no duplicate allocation | NOT RUN |
| FIN-T04 | Integer precision boundary | large minor unit fixture | no floating point or overflow | NOT RUN |
| FIN-T05 | Multi-currency pair | IDR vs USD rows | blocked P0 | NOT RUN |
| FIN-T06 | Intentional unbalanced ledger | missing entry | cannot finalize report | NOT RUN |

## Coverage and execution gates
- Unit: every pure domain invariant, deterministic cross-validation, state guard, authorization policy and financial arithmetic where relevant.
- Contract: OpenAPI semantic validation, JSON Schema, request/response/error examples, client generation, event backwards compatibility.
- Integration: PostgreSQL tenant/RLS/FKs/transactions, storage capability, OIDC+BFF flow, inbox/outbox/queue, provider-scoped permissions.
- E2E: five canonical success/failure paths including human approval and result retrieval; use separate tenants and consented/synthetic data.
- Agent evaluation: frozen labeled corpus with human adjudication, baseline comparison, model/version pinning, typed outputs, prompt injection and tool abuse fixtures.
- Security: SAST/SCA/secret/DAST and cross-tenant negative tests, SSRF sandbox escape, revocation, external effect uncertainty.
- Reliability: 2x planned load (tentative), forced worker crash, network partitions, point-in-time DB restore, region failure simulation.

## Metrics to establish on actual runs
- exact-match precision and recall on labeled ledger
- unmatched exception rate
- zero over-allocated transactions
- report conservation discrepancy = 0
- reviewer corrections per 1000 transactions

**No arbitrary success numbers:** Define threshold from buyer risk tolerance and pilot corpus before G1. Store observed accuracy and sample size, confidence/coverage when meaningful, source hash, run logs, costs, p95, failure distribution. A test case being designed is not a passed test.

## Evidence format
`{test_id, requirement_id, revision_sha, input_fixture_sha, dataset_version, environment, exact_command, expected, observed, pass_fail, reviewer, trace_id, issues}`.
