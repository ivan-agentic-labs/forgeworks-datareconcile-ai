# DataReconcile AI — Data model, relational constraints and transaction design

## Canonical relational aggregates (v4.1: authoritative)

Previous v4.0 terminology is mapped to **one** physical table per aggregate. Never generate two tables for one alias.

| Previous functional term | Canonical table | Mapping |
|---|---|---|
| `import_batches` | `import_batches` | Unchanged |
| `import_rows` | `import_rows` | Unchanged |
| `transactions` | `transactions` | Unchanged |
| `reconciliation_runs` | `reconcile_runs` | Renamed alias |
| `match_candidates` | `match_candidates` | Unchanged |
| `allocations` | `allocations` | Unchanged |
| `exception_cases` | `exception_cases` | Unchanged |
| `exception_resolutions` | `exception_resolutions` | Unchanged |
| `reconciliation_reports` | `reports` | Renamed alias |

All canonical tables must have a physical column contract below; shared per-product platform tables are covered in governance.

## RLS and role design (not executed migration)
- Separate migration/owner role from API/worker read-write roles; application roles never hold BYPASSRLS/superuser or table owner privileges.
- Enable RLS and FORCE where suitable, separate `USING` and `WITH CHECK`; set `app.tenant_id` with `SET LOCAL` inside transactional request after auth membership resolution.
- Transaction-pool reused sessions must not inherit tenant variables. Test PgBouncer/pooled mode after selected provider is known.
- Compound FK + membership/policy validation is required despite RLS; no cross-tenant object keys or storage ACL inheritance.
- Synthetic two-tenant fixtures cover SELECT/INSERT/UPDATE/DELETE, foreign keys, joined views, workers and pooled connections.

## SQL transaction boundaries
1. Job accepted: domain validation + write `jobs` + `outbox` + `idempotency_records` in a **single commit**; return 202 only after commit succeeds.
2. Worker lease: visibility timeout/fencing token; dedupe message ID in inbox; at-least-once delivery with idempotent handlers.
3. Approval: compare `version` and content SHA, actor role+tenant, policy, expiry and external permission; conflicting writers return 409.
4. External effect: commit unique effect reservation → invoke outside DB transaction → store external ID/outcome; timeout -> `UNKNOWN_REMOTE` -> provider-specific lookup/reconciliation; never retry blindly.
5. Artifact: quarantine content until checksum, MIME, virus/format checks and final tenant-owner authorization; download intent scoped and revocation bounded by provider semantics.

## Domain-specific invariants and source column dictionary
No LLM arithmetic or financial approval; immutable original batch digest; integer minor units only for currencies supported by explicit exponent table; serializable/locking rules for allocation uniqueness; cannot finalize unless conservation proof holds.

# DataReconcile AI — proposed physical model, not executed DDL

## Shared physical schema model (applied independently per product)

All tenant-owned tables: `tenant_id UUID NOT NULL`, `id UUID NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `PRIMARY KEY (tenant_id,id)`.
A child FK must use `(tenant_id,parent_id) REFERENCES parent(tenant_id,id)`; foreign UUID alone is insufficient. Database roles: migration owner != API/worker; API/worker roles have no SUPERUSER/BYPASSRLS privileges. Proposed RLS uses `tenant_id = nullif(current_setting('app.tenant_id',true),'')::uuid` with `USING` and `WITH CHECK`; tenant context set `SET LOCAL` **inside a transaction** using server-verified membership, never client supplied. Connection pool reuse without transaction isolation is prohibited.

Other independent core tables for every product: `tenants`, `users`, `memberships`, `jobs`, `outbox_events`, `inbox_receipts`, `idempotency_records`, `audit_events`, `artifact_references` (tenant-scoped). Their schema and cleanup/retention must be supplied by the shared-platform contract before migration code.

Immutable audit records require explicit retention/legal basis. Event idempotency does not imply exactly-once external effects; use reconciliation and unique natural business keys. Soft deletion alone is not a privacy deletion implementation.


## Domain tables

### `import_batches`

| Column | PostgreSQL design type / rule |
|---|---|
| `tenant_id` | `UUID NOT NULL` |
| `id` | `UUID NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `source_label` | `text NOT NULL` |
| `file_sha256` | `char(64) NOT NULL` |
| `currency` | `char(3) NOT NULL` |
| `profile_version` | `text NOT NULL` |
| `status` | `text NOT NULL` |
| `row_count` | `int NOT NULL DEFAULT 0` |

**Keys/indexes:** `PRIMARY KEY (tenant_id,id)`; `UNIQUE (tenant_id, source_label, file_sha256)`.
**Domain constraints:** no change to source hash after ingest.

### `transactions`

| Column | PostgreSQL design type / rule |
|---|---|
| `tenant_id` | `UUID NOT NULL` |
| `id` | `UUID NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `batch_id` | `uuid NOT NULL` |
| `external_ref` | `text NOT NULL` |
| `currency` | `char(3) NOT NULL` |
| `amount_minor` | `bigint NOT NULL` |
| `occurred_at` | `timestamptz NOT NULL` |
| `row_number` | `int NOT NULL` |

**Keys/indexes:** `PRIMARY KEY (tenant_id,id)`; `UNIQUE (tenant_id, batch_id, row_number)`.
**Scoped FK:** `(tenant_id,batch_id) -> import_batches(tenant_id,id)`.
**Domain constraints:** no float; reversal sign interpreted per explicit rule; precision validation before cast.

### `reconcile_runs`

| Column | PostgreSQL design type / rule |
|---|---|
| `tenant_id` | `UUID NOT NULL` |
| `id` | `UUID NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `left_batch_id` | `uuid NOT NULL` |
| `right_batch_id` | `uuid NOT NULL` |
| `rule_version` | `text NOT NULL` |
| `status` | `text NOT NULL` |
| `version` | `int NOT NULL DEFAULT 1` |

**Keys/indexes:** `PRIMARY KEY (tenant_id,id)`; `UNIQUE (tenant_id, left_batch_id, right_batch_id, rule_version)`.
**Scoped FK:** `(tenant_id,left_batch_id) -> import_batches(tenant_id,id)`; `(tenant_id,right_batch_id) -> import_batches(tenant_id,id)`.
**Domain constraints:** batches must belong same tenant and share currency.

### `match_candidates`

| Column | PostgreSQL design type / rule |
|---|---|
| `tenant_id` | `UUID NOT NULL` |
| `id` | `UUID NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `run_id` | `uuid NOT NULL` |
| `left_transaction_id` | `uuid NOT NULL` |
| `right_transaction_id` | `uuid NOT NULL` |
| `rule_version` | `text NOT NULL` |
| `reason_code` | `text NOT NULL` |

**Keys/indexes:** `PRIMARY KEY (tenant_id,id)`; `UNIQUE (tenant_id, run_id, left_transaction_id, right_transaction_id)`.
**Scoped FK:** `(tenant_id,run_id) -> reconcile_runs(tenant_id,id)`; `(tenant_id,left_transaction_id) -> transactions(tenant_id,id)`; `(tenant_id,right_transaction_id) -> transactions(tenant_id,id)`.
**Domain constraints:** candidates are not approved allocations.

### `allocations`

| Column | PostgreSQL design type / rule |
|---|---|
| `tenant_id` | `UUID NOT NULL` |
| `id` | `UUID NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `run_id` | `uuid NOT NULL` |
| `left_transaction_id` | `uuid NOT NULL` |
| `right_transaction_id` | `uuid NOT NULL` |
| `rule_version` | `text NOT NULL` |
| `matched_amount_minor` | `bigint NOT NULL CHECK (matched_amount_minor <> 0)` |
| `currency` | `char(3) NOT NULL` |
| `approved_at` | `timestamptz` |

**Keys/indexes:** `PRIMARY KEY (tenant_id,id)`; `UNIQUE (tenant_id, run_id, left_transaction_id)`; `UNIQUE (tenant_id, run_id, right_transaction_id)`.
**Scoped FK:** `(tenant_id,run_id) -> reconcile_runs(tenant_id,id)`; `(tenant_id,left_transaction_id) -> transactions(tenant_id,id)`; `(tenant_id,right_transaction_id) -> transactions(tenant_id,id)`.
**Domain constraints:** P0 supports 1:1 exact amount/currency matching ONLY, including separately specified refund sign semantics; allocation stores immutable amount/currency evidence matching both source records. No partial match, FX conversion, fees, or rounding until a separate signed-off extension. Enforce non-overlap and amount/currency equality in serializable transaction or explicit row locking, then verify with concurrent negative tests.

### `exception_cases`

| Column | PostgreSQL design type / rule |
|---|---|
| `tenant_id` | `UUID NOT NULL` |
| `id` | `UUID NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `run_id` | `uuid NOT NULL` |
| `reason_code` | `text NOT NULL` |
| `status` | `text NOT NULL` |
| `version` | `int NOT NULL DEFAULT 1` |
| `evidence_sha256` | `char(64)` |

**Keys/indexes:** `PRIMARY KEY (tenant_id,id)`; `INDEX (tenant_id, run_id, status)`.
**Scoped FK:** `(tenant_id,run_id) -> reconcile_runs(tenant_id,id)`.
**Domain constraints:** exception disposition auditable.

### `exception_resolutions`

| Column | PostgreSQL design type / rule |
|---|---|
| `tenant_id` | `UUID NOT NULL` |
| `id` | `UUID NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `exception_id` | `uuid NOT NULL` |
| `reviewer_id` | `uuid NOT NULL` |
| `decision` | `text NOT NULL` |
| `evidence_sha256` | `char(64) NOT NULL` |
| `expected_version` | `int NOT NULL` |

**Keys/indexes:** `PRIMARY KEY (tenant_id,id)`; `UNIQUE (tenant_id, exception_id, expected_version)`.
**Scoped FK:** `(tenant_id,exception_id) -> exception_cases(tenant_id,id)`.
**Domain constraints:** conflicting approvals fail transaction.

### `reports`

| Column | PostgreSQL design type / rule |
|---|---|
| `tenant_id` | `UUID NOT NULL` |
| `id` | `UUID NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `run_id` | `uuid NOT NULL` |
| `ledger_sha256` | `char(64) NOT NULL` |
| `artifact_sha256` | `char(64) NOT NULL` |
| `finalized_at` | `timestamptz NOT NULL` |

**Keys/indexes:** `PRIMARY KEY (tenant_id,id)`; `UNIQUE (tenant_id, run_id)`.
**Scoped FK:** `(tenant_id,run_id) -> reconcile_runs(tenant_id,id)`.
**Domain constraints:** conservation and exception disposition snapshot immutable.

## Transaction boundaries

- Creating a job: validate actor+tenant+resource; insert job and outbox in same PostgreSQL commit, then return HTTP 202. Broker delivery happens after transaction commit.
- External mutation: reserve unique business effect key and approval snapshot inside DB transaction; call external API outside transaction; reconcile remote effect ID after uncertain timeout.
- Final approval: optimistic `version`/If-Match plus exact content digest; reject stale updates.
- Tenant isolation test: same IDs searched under different tenant contexts must not disclose existence or associated storage objects.

## Schema proof not yet collected

Column design is not a generated migration and has not been executed against PostgreSQL. FK/index names, enum strategy, JSONB evidence fields, full SQL migration, query plans, retention and concurrency isolation must be validated during implementation.


> **DDL status:** conceptual physical design; no migration executed or database schema proved. Exact FK constraint names, indexes, query plans, row locks and RLS enforcement require G2/G4 evidence. The appended v3.2 dictionary is historic source input, not an executed implementation.


## v4.1 — Added physical model definitions and closure notes

These are **design-only table contracts**, not executed migrations. Explicit FK/index names, datatype behavior, RLS, and transaction isolation remain subject to PostgreSQL tests.

### `import_rows`

| Column | PostgreSQL design type / rule |
|---|---|
| `tenant_id` | `UUID NOT NULL` |
| `id` | `UUID NOT NULL` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` |
| `batch_id` | `UUID NOT NULL` |
| `row_number` | `INTEGER NOT NULL` |
| `raw_row_sha256` | `CHAR(64) NOT NULL` |
| `parse_status` | `TEXT NOT NULL` |
| `parse_errors` | `JSONB NOT NULL DEFAULT '[]'::jsonb` |
| `normalized_transaction_id` | `UUID` |

**Keys/indexes:** `PRIMARY KEY (tenant_id,id)`; `UNIQUE (tenant_id,batch_id,row_number)`.
**Scoped FK:** `(tenant_id,batch_id) -> import_batches`; optional `(tenant_id,normalized_transaction_id) -> transactions`.
**Domain constraints:** Rows preserve immutable source lineage; malformed rows cannot silently become normalized transactions; `row_number > 0`.


### Domain-specific mapping decisions

- `reconcile_runs` and `reports` are physical names; `reconciliation_runs` and `reconciliation_reports` were narrative aliases, not extra tables.
- The legacy GET `/v1/reports/{id}/download` remains a read-only compatibility endpoint returning a short-lived capability; new clients use artifact download intent after resolving a report artifact id. It must not redirect or expose raw objects without authorization.
- Exact 1:1 same-currency matching only for P0. A qualified controller must validate signed fixtures before financial domain signoff.
