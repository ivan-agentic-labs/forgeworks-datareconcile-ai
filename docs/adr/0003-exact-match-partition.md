# ADR 0003 — Reserve exact matches before exceptions

Status: implemented bug correction, 2026-10-11; external financial/domain acceptance remains open.

The intended exact 1:1 rule requires disjoint source-row usage. Reserve every exact match first, then pair the remaining rows as reviewed exceptions. Finalization checks row membership, equality of allocated amounts/currencies/types, unique source coverage and exception count. An invalid partition returns CONSERVATION_FAILED.

New executions may produce fewer mismatches than the prior order-dependent implementation. The matching policy remains same-currency exact 1:1; no identity or financial-effect policy changes. Existing run idempotency/business keys and immutable reports remain unchanged. No migration is required. Rollback must not publish new reports from invalid partitions; revert the commit only if a replacement integrity control is available.
