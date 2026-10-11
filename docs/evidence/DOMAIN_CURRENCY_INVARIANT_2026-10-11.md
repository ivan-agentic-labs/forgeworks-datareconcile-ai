# Domain currency invariant — 2026-10-11

Baseline: 4049c3ed22567fce27539fd83b5b7bacf9f714fd.

The HTTP reconciliation route already rejected mixed batch currencies with a 409 CURRENCY_MISMATCH. Direct Store.run callers could bypass that domain invariant, create exceptions and expose totals combining different units. Enforce the existing same-currency rule in Store.run after tenant-visible batch lookup and before idempotency lookup or result writes. PostgresStore inherits this method. No exchange-rate conversion or accounting policy expansion is introduced.

Eight new SQLite regression cases: baseline six failures and two passes; candidate eight passes. Cover IDR/USD in both directions, USD/EUR, with and without command idempotency; rejection leaves runs, allocations, exceptions, command records and audit events unchanged. Valid USD and IDR matching and command replay still succeed without duplicate results. The existing HTTP mixed-currency regression also passes.

The native disposable PostgreSQL runtime proof now checks both currency directions with a limited runtime role and verifies unchanged result/command/audit counts. It is skipped locally when its dedicated localhost database is absent; required hosted runtime CI must pass before merge. This proof uses synthetic imports and provisioned test membership, not customer or staging business acceptance.

Local validation: 239 Python tests pass, one disposable-PostgreSQL test skipped; 15 JavaScript tests pass. Bootstrap scan, contract sanity, independent OpenAPI validation and git diff whitespace check pass. Hosted browser precision and PostgreSQL proofs remain required. No deployment, live database migration or production readiness claimed.
