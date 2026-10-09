# Worker reliability harness

`src/datareconcile_worker/reliability.py` contains the synthetic worker job
runner used by the resilience tests. It persists a business-keyed job state,
deduplicates `SUCCEEDED` work, records retryable versus terminal failures, and
recovers a `RUNNING` lease left by a crashed process. The operation supplied to
the runner must be idempotent (the API `Store` enforces unique import digests,
reconciliation business keys, and source allocation uniqueness).

This worker has **no financial side effects**: it does not initiate, approve,
or execute transfers. It only exercises import/reconciliation/report workflow
reliability using synthetic fixtures.
