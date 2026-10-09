# DataReconcile PostgreSQL runtime and missing-side semantics

Migrations 001/002 retain the canonical import/reconciliation/report tables and add runtime membership, allocations, resolutions and append-only audit tables. Runtime logins must be non-owner members of a NOLOGIN/NOSUPERUSER/NOBYPASSRLS role. Outer transactions set tenant and role locally, serialize conservatively using a tenant advisory lock, and close the connection. Nested commands reuse that transaction and cannot switch tenant or store. Production throughput, recovery and deployment remain unaccepted.

Money remains integer minor units. PostgreSQL SUM results are converted to exact integers by domain code. Allocation uniqueness and composite tenant foreign keys are database constraints. Report content is TEXT to preserve its exact bytes; JSON metadata is JSONB. Runtime cannot update/delete reports, resolutions, allocations or audit events.

MISSING_LEFT and MISSING_RIGHT now represent the absent transaction as null, rather than repeating an ID from the other batch. Both cannot be null. The API schema and generated client reflect this cardinality. Audit matched_count counts actual allocations and cannot become negative merely because the right batch has additional unmatched rows. No customer ledger or money transfer is performed.

Disposable CI exercises real CSV imports and SHA checks, duplicate imports, concurrent business-key replay, exact totals, competing exception resolution, report finalization and actual signed-byte download, immutable report storage, missing tenant context and cross-tenant SELECT/UPDATE/DELETE/INSERT denial. Source fixtures and external storage/identity integrations retain their stated limitations; no design-candidate SQL addendum is applied.
