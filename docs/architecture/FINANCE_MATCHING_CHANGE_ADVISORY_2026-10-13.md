# Finance matching change advisory — 2026-10-13

**Status:** Awaiting independent code/domain review; not approved for production.  
**Change scope:** Add opt-in `exact-reference-date-v1` and require zero
source-total discrepancy before report finalization. Existing matching rule
identities remain unchanged. Synthetic fixture data and tests are adjusted to
have equal source totals while retaining explicit mismatches for review.

## Rationale and guardrails

- The revised owner product specification requires exact identity matching,
  ambiguous-duplicate exceptions, source-row partitioning, and zero unexplained
  discrepancy before finalization.
- Existing amount-only rules remain available for replay/compatibility and are
  not silently relabeled. The new identity rule requires matching currency,
  signed minor-unit amount, canonical UTC timestamp, transaction type, and
  normalized reference. Reference normalization is NFC, trim, uppercase, and
  whitespace collapse; no prefix is stripped absent a source-specific policy.
- The new rule is disabled by default. `ENABLE_EXACT_REFERENCE_DATE_RULE=true`
  can enable it only when `APP_ENV` is `development` or `test`; production and
  all other environments remain blocked in code until a separately reviewed
  release after controller signoff.
- Conflicting or ambiguous identities are never automatically allocated.
  Manual review records do not adjust source values; imbalance blocks report
  finalization.
- No bank connection, payment, transfer, real financial data, or production
  configuration is part of this change.

## Risks and controls

| Risk | Control / verification |
|---|---|
| False-positive allocation from normalization collision | Unique identity required on both source batches; collision test asserts no automatic allocation. |
| False-positive from amount/date/reference disagreement | Exact amount and canonical timestamp are part of the key; mismatch and missing identities produce review exceptions. |
| Incorrect report despite balanced allocations | Finalization requires valid full source-row partition, zero original-source total difference, and zero allocated-side discrepancy. |
| Existing client/replay behavior changes | Existing rule versions retain their algorithm and audit identity; new matching semantics are under a separate version string. Finalization safety applies to all rules. |
| Rule approved without domain expertise | Pull request requires independent review. OD-08 finance-controller acceptance and production use remain blocked. |

## Test / compatibility plan

- Run the full offline Python test suite, independent OpenAPI checks, and web
  tests; include rule-identity, normalized-reference collision, date mismatch,
  amount mismatch, unbalanced finalization, and balanced reviewed finalization.
- Run disposable PostgreSQL checks only if available and explicitly configured;
  this patch adds no database schema or migration.
- Do not merge until CI passes and the required independent review is complete.

### Local verification receipt

- `python -W error -m pytest -q -ra -p no:cacheprovider tests`: **421 passed, 1 skipped**; skip is `test_postgres_runtime.py` because disposable PostgreSQL is unavailable, explicitly **not** a runtime pass.
- `node --test tests/web/*.test.cjs`: **15 passed**.
- `python scripts/verify_bootstrap.py`: **PASS**, no findings.
- `python scripts/verify_contracts.py`: **PASS**, 14 operations, no errors.
- `python scripts/validate_openapi_independent.py`: **PASS**.
- `npm run check --prefix packages/sdk`: **PASS** (OpenAPI type generation + strict TypeScript check).
- `git diff --check`: **PASS**.
- External/disposable PostgreSQL runtime verification was not available in this local receipt.
- Production feature-gate test: **PASS** with the flag set; rule remains blocked.
- Default-off HTTP test: **PASS**, API returns `RECONCILIATION_RULE_DISABLED`.

## Rollback

Revert the application commit to remove the new rule and source-total gate.
Existing rows, runs, and reports are not rewritten. Reverting restores the
previous finalization behavior and therefore must be treated as a safety
rollback, not as production approval. No data migration or external effect is
required.

## Review record

- Initial independent code review found the production rule-gate gap; this was addressed with a default-off, development/test-only hard gate. Follow-up review of that gate is **pending in PR**.
- Finance-controller review of matching policy: **pending (OD-08)**
- Security/privacy/production release acceptance: **still open**
- Exact PR commit and CI receipt: **to be recorded after branch publication**
