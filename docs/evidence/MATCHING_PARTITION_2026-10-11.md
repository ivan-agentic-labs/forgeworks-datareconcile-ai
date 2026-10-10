# Exact match and exception partition correction — 2026-10-11

An early amount mismatch could reserve a right-hand row as an exception before a later left-hand row matched that same right-hand row. Three of six row-order permutations reproduced the overlap before the fix.

The engine now completes all exact currency/amount/transaction-type matches before pairing remaining rows into exceptions. Each phase consumes rows once, uses deterministic input order, and avoids repeatedly scanning the right-hand list for mismatch candidates. Totals expose `row_partition_valid`. Finalization verifies that every row from each declared batch occurs exactly once in allocations or exceptions, that allocation values/types/currencies match their sources, and that exception counts match the run. Invalid partitions cannot produce a newly finalized report.

12 new synthetic cases cover six input-order permutations, duplicate amounts, missing-side rows, negative integer amounts, overlapping exception references and missing source coverage. Complete local suite: `python -W error -m pytest tests -q`: 165 passed, 1 skipped (PostgreSQL). PostgreSQL remains required in exact-commit Actions.

Existing immutable runs/reports are not silently rewritten; replay retains their original output. Historical data would require an explicit review/recomputation policy. This work does not introduce FX, partial matching, financial transfers or customer data.
