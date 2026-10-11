# Worker reliability harness

`src/datareconcile_worker/reliability.py` contains the synthetic worker job
runner used by the resilience tests. It persists a business-keyed job state,
deduplicates `SUCCEEDED` work, records retryable versus terminal failures, and
recovers an expired `RUNNING` lease left by a crashed process. Recovery never
reclaims a live lease just because a different process starts. Each attempt has
a persisted expiry (default 300 seconds, configurable with `lease_seconds`);
all success and failure writes compare the attempt number and require an
unexpired lease. Superseded operations cannot overwrite their replacement.
Expired work requires `recover_running()` before retrying, subject to the
attempt budget. Restart recovery may therefore wait until lease expiry.

There is no heartbeat or cancellation of the old operation. After expiry,
operations may overlap; fencing protects durable job results, and domain
idempotency must protect business effects. Set the lease to cover the bounded
operation duration. This SQLite harness is not a distributed production queue.
Its runners must share one local database and a consistent wall clock; the
injected `clock` is for deterministic tests. Legacy databases gain a nullable
expiry column, preserve completed results, and treat old unfenced running rows
as expired. Stop all old runner versions before upgrading; mixed old/new
versions cannot preserve fencing.

The operation supplied to
the runner must be idempotent (the API `Store` enforces unique import digests,
reconciliation business keys, and source allocation uniqueness).

This worker has **no financial side effects**: it does not initiate, approve,
or execute transfers. It only exercises import/reconciliation/report workflow
reliability using synthetic fixtures.
