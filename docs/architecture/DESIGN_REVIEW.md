# DataReconcile AI — Product Design Review (canonical summary)
**Status:** `DESIGN REVIEW CANDIDATE`. G1 domain signoff `BLOCKED`. This note **does not claim tested functionality**.

## Purpose and scope
**ICP:** Financial operations personnel reconciling same-currency CSV/bank/ledger exports.

**P0 workflow:** Private upload → schema validate → canonical transaction import → exact same-currency 1:1 match → exception queue → human approval → immutable reconciliation report.

**Explicit exclusions:** No financial transfers, no accounting certification, no FX, no partial/many-to-many matching in first release.

**Subsystems:** Upload/quarantine; parser+normalizer; integer matching; exception manager; approval+audit; export/reversal.

## API inventory (as currently specified)
| Method/path | `operationId` | Scope |
|---|---|---|
| `POST /v1/import-batches` | `post_v1_import_batches` | `import:create` |
| `GET /v1/import-batches/{id}/rows` | `get_v1_import_batches_id_rows` | `import:read` |
| `POST /v1/reconciliation-runs` | `post_v1_reconciliation_runs` | `reconcile:run` |
| `GET /v1/reconciliation-runs/{id}/exceptions` | `get_v1_reconciliation_runs_id_exceptions` | `reconcile:read` |
| `POST /v1/exceptions/{id}/resolutions` | `post_v1_exceptions_id_resolutions` | `exception:approve` |
| `POST /v1/reconciliation-runs/{id}/finalize` | `post_v1_reconciliation_runs_id_finalize` | `report:finalize` |
| `GET /v1/reports/{id}/download` | `get_v1_reports_id_download` | `report:read` |
| `POST /v1/artifacts/upload-intents` | `post__v1_artifacts_upload_intents` | `artifact:create` |
| `POST /v1/artifacts/{artifact_id}/commit` | `post__v1_artifacts_artifact_id_commit` | `artifact:commit` |
| `GET /v1/artifacts/{artifact_id}` | `get__v1_artifacts_artifact_id` | `artifact:read` |
| `POST /v1/artifacts/{artifact_id}/download-intents` | `post__v1_artifacts_artifact_id_download_intents` | `artifact:download` |
| `GET /v1/jobs/{job_id}` | `get__v1_jobs_job_id` | `job:read` |

`openapi.yaml` is the source. These routes are not running. Remaining contract hardening: independent validator and SDK; verify existing cursor pagination semantics in runtime; security tests and example/runtime parity.

## Database inventory and handling
From candidate SQL (18 tables): `tenants`, `users`, `artifact_references`, `audit_events`, `idempotency_records`, `import_batches`, `import_rows`, `inbox_receipts`, `jobs`, `memberships`, `outbox_events`, `reconcile_runs`, `transactions`, `allocations`, `exception_cases`, `match_candidates`, `reports`, `exception_resolutions`.

- Keep physical table names from `docs/verification/sql-candidates/10_schema_candidate.sql` as **candidate canonical**; historical aliases may not be implemented simultaneously.
- Apply `tenant_id` composite relations, invariant constraints and optimistic version where review/approval is relevant.
- Validate DDL in disposable PostgreSQL with owned migration role, nonowner runtime login role, multiple tenants; DDL presently unexecuted.

## Product-specific invariants and required negative proofs
| ID | Invariant | Negative case required | Evidence |
|---|---|---|---|
| `DR-INV-01` | Use integer minor units and matching currency; no float | Non-exact or cross-currency candidates cannot auto match | Runtime test + reviewer signoff |
| `DR-INV-02` | Each transaction allocated once in same reconciliation run | Concurrent duplicate/over-allocation must violate constraint | Runtime test + reviewer signoff |
| `DR-INV-03` | Confirmed run cannot silently change after finalization | Mutation of finalized allocation rejected; correction creates new revision | Runtime test + reviewer signoff |
| `DR-INV-04` | Every match conserves amount and references both source evidence | Injected unmatched amount or source mismatch rejected | Runtime test + reviewer signoff |

## Modules/files planned for ownership (domain and adapters)
- `apps/api/src/datareconcile_ai/domain/entities.py`
- `apps/api/src/datareconcile_ai/infrastructure/persistence/models.py`
- `apps/api/src/datareconcile_ai/infrastructure/persistence/repositories.py`
- `apps/api/src/datareconcile_ai/infrastructure/llm/provider_adapter.py`
- `apps/api/src/datareconcile_ai/domain/money.py`
- `apps/api/src/datareconcile_ai/domain/matching_rules.py`
- `apps/api/src/datareconcile_ai/domain/allocation_policy.py`
- `apps/api/src/datareconcile_ai/domain/conservation.py`
- `apps/api/src/datareconcile_ai/application/commands/create_import.py`
- `apps/api/src/datareconcile_ai/application/commands/run_exact_match.py`
- `apps/api/src/datareconcile_ai/application/commands/resolve_exception.py`
- `apps/api/src/datareconcile_ai/application/commands/finalize_report.py`
- `apps/api/src/datareconcile_ai/infrastructure/csv/strict_parser.py`
- `apps/api/src/datareconcile_ai/infrastructure/report/immutable_exporter.py`
- `apps/api/src/datareconcile_ai/infrastructure/ai/explanation_adapter.py`
- `apps/api/src/datareconcile_ai/infrastructure/storage/object_reader.py`
- `apps/api/src/datareconcile_ai/application/commands/commit_artifact.py`
- `apps/api/src/datareconcile_ai/infrastructure/storage/object_store.py`
- `apps/api/src/datareconcile_ai/infrastructure/security/tenant_context.py`
- `apps/api/src/datareconcile_ai/infrastructure/persistence/outbox.py`

## Failure semantics
Import schema uncertain or amount mismatch: exception requiring manual investigation. If downstream AI/provider fails, persist recoverable explicit job state and do not fabricate a successful output. Remote writes require `approval_snapshot` and idempotent effect ledger.

## Evidence and customer acceptance
**Required positive proof:** Zero loss or fabrication on controller-approved synthetic fixtures and auditable exact matched/unmatched totals.

**Main threats:** Data residency, duplicated bank rows, clock/currency, fraud impact, PII, uncontrolled retention.

**Data/IP/approval:** Processor/controller roles and vendor processing terms must be signed off before real data..

## P0 gates and signoff
- Founder/product owner: validates use-case acceptance from qualified user/buyer; **OPEN**.
- API reviewer: external OAS validation, SDK build, authorization negative tests; **NOT RUN**.
- DB/security reviewer: two-tenant SQL execution, constraints, RLS, IAM and sandbox where required; **NOT RUN**.
- Domain specialist: accessibility, finance, graders, provenance, GitHub contract per product; **OPEN**.
- Ops owner: cost/vendor, data policy, restore and incident evidence; **OPEN**.

**Outcome:** Documentation improved and canonical routes/tables inventoried; no independent product-domain approval or G1 PASS granted.
