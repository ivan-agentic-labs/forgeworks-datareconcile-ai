# G3 optional ambiguity-safe finance matching policy

## Purpose

The legacy `exact-v1` matching rule can pair repeated amounts by CSV row
order. Amount, currency and transaction type alone cannot prove which
individual transaction corresponds to which when the same key occurs twice.

The new **opt-in** `rule_version: unambiguous-amount-v2` avoids silently
creating those potentially false allocations. It does not change existing
`exact-v1` runs, and it is **not yet approved by a finance controller for
customer use**.

## Deterministic rules

For each import batch, build a frequency table of the key:
`(currency, amount_minor, transaction_type)`.

- Automatically allocate **one-to-one** only if a key occurs exactly once on
  each side of the reconciliation.
- Do not allocate any occurrence from a bucket with duplicates on **either**
  side. Produce an explicit `AMBIGUOUS_AMOUNT` open exception for each
  affected source row on both sides.
- Report otherwise unmatched rows separately as `MISSING_RIGHT` or
  `MISSING_LEFT`; never fabricate a relationship between differing amounts
  merely because those rows appear next to one another in uploaded CSV.
- All source rows still appear exactly once in the allocations-or-exceptions
  conservation partition.
- Reports cannot be finalized until every exception receives a version-fenced,
  evidence-digest-bound reviewer decision through the existing workflow.
- The existing digest, tenant isolation, signed report and immutable-run
  semantics remain unchanged. Same source pairs may be run under separate
  `rule_version` values; each rule produces an independent audit identity.

## Verification

`tests/integration/test_unambiguous_amount_v2.py` uses actual synthetic
CSV source bytes, tests both-sided and one-sided duplicate buckets, repeated
CSV order permutations, conservation, review before finalization, and
backward-compatible `exact-v1` operation. Existing PostgreSQL runtime tests
must stay green. No money movement, bank API or real financial data is used.

## Owner acceptance still required

A controller must review whether unique amount+currency+type without
cross-system references and time-window corroboration is sufficient for
auto-allocation. That is a **business accounting policy**, not a fact proven by
unit tests. Do not select `unambiguous-amount-v2` in a production tenant
until the rule and exception reason have received independent finance signoff.

**Production NO-GO** until owner-approved source data, reconciliation
policy, reviewer roles, retention, access control, and report acceptance
have independent evidence.
