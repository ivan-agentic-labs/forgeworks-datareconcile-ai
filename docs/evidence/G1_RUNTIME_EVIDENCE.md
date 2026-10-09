# G1 runtime evidence — datareconcile-ai

**Evidence date:** 2026-10-09
**Evidence source revision (current `main` at audit start):** `09b2628b53e1dd66c0b5fc80dc26323d4b558891`
**Repository:** `ivan-agentic-labs/forgeworks-datareconcile-ai`
**Evidence owner/reviewer:** no independent reviewer approval is recorded; this file reports reproducible results only.

This record supplements, and does not supersede, `docs/governance/MASTER_G1_DECISION.md`, `docs/verification/DESIGN_GATE_STATUS.md`, and `docs/verification/TEST_PLAN.md`. The source revision above is the exact revision tested and referenced by the Actions runs below. The documentation commit that adds this record necessarily has a different Git SHA.

## Status vocabulary and decision guard

- **VERIFIED** means the named command completed successfully in a disposable GitHub Actions job at the source revision, for the exact scope stated.
- **PASS_STATIC_LIMITED** means a local/static or synthetic test completed successfully, but it is not evidence of production deployment, external-service behavior, or the complete gate.
- **NOT_RUN** means no usable result exists in this snapshot.
- **BLOCKED** means an approval, external system, or required environment is unavailable.
- A bounded result is not a G1-D or G1-E approval. **G1-D remains conditional/not signed and G1-E remains open/blocked.**

## Exact local commands and observed outcomes

Executed from repository root at the source revision above on 2026-10-09. Every command below returned exit code `0`.

| Command | Observed result | Outcome |
|---|---|---|
| `python3 -m pytest -W error tests` | `16 passed in 1.71s` across E2E, integration, resilience, and unit tests | `PASS_STATIC_LIMITED` |
| `python3 scripts/verify_bootstrap.py` | `files_scanned: 97`, `errors: []` | `PASS_STATIC_LIMITED` |
| `python3 scripts/verify_contracts.py` | `operations: 12`, `event_schema: draft2020-12`, `errors: []` | `PASS_STATIC_LIMITED` |
| `python3 scripts/validate_openapi_independent.py` | `Independent OpenAPI validator: PASS for openapi.yaml` | `PASS_STATIC_LIMITED` locally; CI result below is `VERIFIED` |
| `bash -n scripts/probe_disposable_postgres.sh` | no diagnostics | `PASS_STATIC_LIMITED` |
| `bash -n scripts/probe_disposable_postgres_rls.sh` | no diagnostics | `PASS_STATIC_LIMITED` |
| `node --check apps/web/app.js` | no diagnostics | `PASS_STATIC_LIMITED` |
| `git diff --check` | no diagnostics | `PASS_STATIC_LIMITED` |

The application workflow itself runs `python -m pytest tests/integration` (not the full local suite), then the three verification scripts and `bash -n scripts/probe_disposable_postgres.sh`. The full-suite result above is the separately executed local command.

## GitHub Actions evidence at the source revision

All listed runs have `headSha = 09b2628b53e1dd66c0b5fc80dc26323d4b558891` and completed successfully.

| Workflow / run | Exact workflow command or probe | Evidence scope | Result |
|---|---|---|---|
| [G1 Contract Verification / 37877971633](https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/37877971633) | `python scripts/verify_bootstrap.py`; `python scripts/verify_contracts.py`; `python scripts/validate_openapi_independent.py` | Bootstrap scan, static OpenAPI/event checks, and independent third-party OpenAPI validation | `VERIFIED` for these bounded checks |
| [DataReconcile MVP Application CI / 37877971788](https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/37877971788) | `python -m pytest tests/integration`; the three verification scripts; `bash -n scripts/probe_disposable_postgres.sh` | Integration suite plus application workflow checks | `VERIFIED` for the workflow scope; not browser/E2E or worker proof |
| [G1 Disposable PostgreSQL DDL Proof / 37877997433](https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/37877997433) | `bash scripts/probe_disposable_postgres.sh` in PostgreSQL 17 service | Executes `migrations/versions/001_reconcile_mvp.sql` against an empty disposable database | `VERIFIED` for disposable DDL smoke only |
| [G2 Disposable PostgreSQL RLS Negative Test / 37878000156](https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/37878000156) | `bash scripts/probe_disposable_postgres_rls.sh` in PostgreSQL 17 service | Non-owner role sees one row for tenant A and cross-tenant INSERT is rejected while tenant A context is set | `VERIFIED` for the stated synthetic probe |
| [G2 Disposable PostgreSQL RLS Negative Test / 37877971651](https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/37877971651) | Same probe, duplicate successful run on the same source SHA | Independent repeated run of the same bounded RLS probe | `VERIFIED` for the stated synthetic probe |

The RLS probe does **not** test all SELECT/INSERT/UPDATE/DELETE permutations, pooled-connection reset, transaction-context reset, role-bypass behavior, or production PostgreSQL configuration. The DDL job is a smoke execution, not a migration approval.

## Explicit criterion table

| Criterion | Current evidence and exact source | Status | Boundary / residual blocker |
|---|---|---|---|
| Independent OpenAPI semantic validation | `scripts/validate_openapi_independent.py`; Contract Verification run above | `VERIFIED` | No generated-client compilation or interoperability proof |
| Event schema and static contract shape | `scripts/verify_contracts.py` checks Draft 2020-12 schema shape, 12 operations, operation IDs, security/scope declarations, path parameters, and refs | `PASS_STATIC_LIMITED` | No broker delivery, compatibility window, or consumer contract test |
| Empty disposable PostgreSQL migration | `scripts/probe_disposable_postgres.sh` applies `migrations/versions/001_reconcile_mvp.sql` to PostgreSQL 17; DDL run above | `VERIFIED` | Disposable DDL smoke only; no approved production migration, data migration, or full FK semantics review |
| Non-owner two-tenant RLS isolation | `scripts/probe_disposable_postgres_rls.sh`; successful RLS runs above | `PASS_STATIC_LIMITED` | Evidence is limited to tenant-A visibility and cross-tenant INSERT rejection; full CRUD, reset, bypass, concurrency, and production configuration remain untested |
| Auth/tenant negative tests | `tests/integration/test_hardening.py` and full local pytest: wrong scope returns 403 and cross-currency/unsafe operations fail closed | `PASS_STATIC_LIMITED` | Synthetic application auth/tenant headers and SQLite store; real IdP/OIDC, CSRF, membership provisioning, and production DB authorization are not tested |
| E2E API/UI flow | `tests/e2e/test_fastapi_static_ui_flow.py`; local suite includes API import/rows/reconcile/resolve/finalize/download plus static console assertions | `PASS_STATIC_LIMITED` | TestClient/static HTML+JS; no real browser sandbox, external egress, deployed UI, or five-product E2E |
| Worker reliability | `tests/resilience/test_worker_reliability.py`; local suite covers idempotency, retry, terminal failure, restart recovery, concurrency, and stale resolution | `PASS_STATIC_LIMITED` | Synthetic SQLite worker model; no queue/provider fault injection, load, partition, or production worker run |
| Artifact/integrity and conservation | `tests/integration/test_reconcile_flow.py` and E2E flow assert immutable retry, ledger/artifact SHA stability, allocated totals, and zero conservation discrepancy | `PASS_STATIC_LIMITED` | Synthetic artifacts are not external-storage integrity or backup/restore evidence |
| Generated client compilation/interoperability | No generated-client command or retained run | `NOT_RUN` | Required before a complete contract gate |
| Real IdP/OIDC, CSRF, and session/access-control proof | No IdP integration environment or retained run | `NOT_RUN` | External identity provider and provisioning evidence unavailable |
| Browser sandbox/egress and unsafe-tool isolation | No independent runner, browser, SSRF, escape, or egress run | `NOT_RUN` | Required sandbox evidence unavailable |
| External object storage and capability enforcement | No external storage or deployed capability test | `NOT_RUN` | Local report/download behavior is not external-storage proof |
| Legal/domain/operations/cost signoff | No signed owner, finance, privacy/DPA, accessibility, operations, budget, or independent-review record | `BLOCKED` | Do not fabricate reviewer approval; OD-01–OD-09 remain open where applicable |
| Production backup/restore and DR | No production or staging restore drill | `NOT_RUN` | Restore, PITR, region-failure, and retention evidence unavailable |

## Residual gate decision

The available evidence supports a **partial, synthetic G1 runtime record only**. It does not close either design signoff or enforcement/runtime evidence. Keep real customer data, production deployment, finance mutation, and public release blocked until the residual IdP, browser/egress, external storage, generated-client, reviewer, legal/domain/ops/cost, and production DR evidence is accepted.
