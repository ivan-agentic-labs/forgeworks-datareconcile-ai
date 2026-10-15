# DataReconcile AI — Verifiable test and evaluation plan

| Test ID | Scenario | Fixture / setup | Expected acceptance result | Execution |
|---|---|---|---|---|
| FIN-T01 | CSV amount contains locale ambiguity | 1,234 ambiguous fixture | quarantine, no guess | PASS_LOCAL — `tests/integration/test_financial_test_plan.py::test_fin_t01_locale_ambiguous_amount_is_quarantined_without_guess`; SQLite parser rejects quoted non-canonical amount before batch/row persistence. Local synthetic only. |
| FIN-T02 | Concurrent review approvals | two stale writes | one accepted, other 409 | PASS_LOCAL — `tests/integration/test_hardening.py::test_stale_resolution_is_single_winner_and_report_is_auditable` and `tests/resilience/test_worker_reliability.py::test_stale_resolution_conflict_allows_one_winner`; disposable SQLite/TestClient and ThreadPoolExecutor prove one 201/OK and one 409/STALE. No hosted concurrency claim. |
| FIN-T03 | Duplicate external reference across batches | duplicate rows | preserve provenance; no duplicate allocation | PASS_LOCAL — `tests/integration/test_financial_test_plan.py::test_fin_t03_cross_batch_duplicate_reference_preserves_provenance`; synthetic same-currency rows with the same references across source batches retain distinct source IDs and one allocation per side. Does not test external connector behavior. |
| FIN-T04 | Integer precision boundary | large minor unit fixture | no floating point or overflow | PASS_LOCAL — `tests/integration/test_financial_test_plan.py::test_fin_t04_int64_rows_and_aggregate_totals_remain_exact` and `tests/integration/test_hardening.py::test_strict_csv_schema_digest_and_integer_boundaries`; signed int64 rows and Python aggregate totals remain exact in disposable SQLite. No production database claim. |
| FIN-T05 | Multi-currency pair | IDR vs USD rows | blocked P0 | PASS_LOCAL — `tests/integration/test_currency_invariant.py::test_mixed_currency_is_rejected_without_results`; parameterized IDR/USD, USD/IDR, and USD/EUR pairs reject with `CURRENCY_MISMATCH` and create no reconciliation results. Same-currency local path is separately covered. |
| FIN-T06 | Intentional unbalanced ledger | missing entry | cannot finalize report | PASS_LOCAL — `tests/integration/test_exact_reference_date_v1.py::test_source_total_imbalance_blocks_report_even_after_review` and `::test_http_finalization_returns_409_for_reviewed_source_imbalance`; after synthetic review, a 10-minor-unit source discrepancy remains blocked as `CONSERVATION_FAILED`, with no report. No production acceptance claim. |

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
