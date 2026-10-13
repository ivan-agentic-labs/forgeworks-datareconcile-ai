# DataReconcile AI — Complete Detailed Project Specification

**Version:** 2.2.0-detailed-full  
**Date:** 2026-10-13  
**Status:** FINAL  

> DataReconcile AI reconciles two single-currency CSV transaction lists using deterministic exact matching. Exceptions require human resolution. The final report must pass a zero-discrepancy conservation check and becomes immutable once approved. AI only explains exceptions.

---

## 1. Executive Definition

Finance teams upload two CSV files. The system normalizes amounts to signed integer minor units, normalizes references, performs exact matching, surfaces everything else as exceptions, requires human resolution, validates conservation, and emits an immutable report. No money is moved and no bank connection is made.

---

## 2. Detailed Workflow

1. Two CSVs are uploaded and quarantined.
2. Strict parsing occurs. Files exceeding 10,000 rows are rejected. Currency must be identical.
3. Normalization: amounts become signed integers; references are trimmed, uppercased, prefix-stripped (if configured), and space-collapsed; dates must match exactly in P0.
4. Batch hashes are frozen.
5. Deterministic exact matching runs (same signed amount + same date + equal normalized reference).
6. Unmatched items, amount mismatches, date mismatches, and ambiguous duplicates become exceptions.
7. Reviewer resolves every exception (manual match, ignore, adjust) or waives non-material items. Report generation is blocked while any exception remains open.
8. Conservation check: sum of matched + sum of resolved exceptions must equal original totals of both sources. Any non-zero discrepancy blocks the report.
9. Immutable report is generated with all digests. Subsequent changes create a new report version.

---

## 3. AI Explanation Boundary

The model may produce a short explanation that cites the deterministic reason code. It must not suggest a match, propose an amount change, or recommend a resolution. Explanations are stored separately from the official resolution record.

---

## 4. Closing

These rules are final for P0. DataReconcile AI will not auto-resolve exceptions and will not emit a report that fails conservation.

*End of DataReconcile AI Complete Detailed Specification*
