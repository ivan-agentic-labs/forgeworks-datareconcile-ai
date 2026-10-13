# DataReconcile AI — revised owner product specification (2026-10-13)

**Source basis:** `DataReconcile_AI_Full_Detailed_v2.2.md`, `DataReconcile_AI_Expanded_Parent_v3.0.md`, `DataReconcile_AI_Ultra_Detailed_Extension.md` and the matching `IR/` catalogue in the owner's uploaded `ForgeWorks_5_Projects_Long_Narrative_plus_IR.zip`.

**Document state:** owner design requirements; not independent evidence of implemented or hosted functionality. This replaces the old bootstrap-era design-review and handoff prose, while preserving actual code/contracts/migrations/tests and dated audit evidence.

## Product scope
Deterministic exact matching of two same-currency transaction CSVs. It remains a separate backend service connected through the planned shared ForgeWorks front end; not a separate production domain.

## Owner P0 workflow / controls
1. Quarantine two CSV files and strictly parse input. Owner-designed limit 10,000 rows per file, reject currency mismatches.
2. Normalize signed money as integer minor units. Normalize references by trimming, uppercasing, optional prefix removal, whitespace collapse; use exact dates.
3. Freeze source batch hashes and match only identical signed amount, exact date and normalized reference; ambiguous duplicates remain unmatched.
4. Generate typed unmatched/mismatched/ambiguous exceptions, never silently choose a match.
5. Require authorized manual resolutions/waivers; no open exceptions at report generation.
6. Verify conservation independently for both original lists before finalizing a report. Zero unexplained discrepancy required.
7. Finalize immutable report with source/effect digests and audit history. AI may explain deterministic reason codes, but never decide matches or adjust values.

**Engineering status (2026-10-13):** `exact-reference-date-v1` is implemented
as an explicit opt-in candidate; existing rule versions retain their historical
identity. It compares signed amount, canonical UTC timestamp, normalized
reference (NFC, trim, uppercase, whitespace collapse), currency and transaction
type, and leaves ambiguous identities as review exceptions. Finalization now
blocks when source totals differ, even if exceptions were marked
`accept-as-investigated`. Source-specific reference-prefix removal is not
configured. These code and local-test changes do not represent finance
controller signoff, customer-data acceptance, or production approval; OD-08 and
release gates remain open. The candidate is disabled by default and hard-blocked
in production; only development/test can enable it with
`ENABLE_EXACT_REFERENCE_DATE_RULE=true` until a separately reviewed release.

## Limits and non-goals
Owner-designed P0 has no bank connections, fund transfers, auto-resolve, AI amount decisions, or probabilistic matching. Do not conflate reconciliation with money movement.

## Implementation records and proof
The uploaded catalogue contains **320 IR IDs but 8 distinct topic patterns**, each repeated 40 times. ID count is not completion count. The distinctive topics are:

- 01. CSV parse
- 02. normalization
- 03. exact matching
- 04. exception creation
- 05. human resolution
- 06. conservation check
- 07. immutable report
- 08. AI explanation boundary

For each topic, bind the implemented source file, requirement ID, positive/negative test, fixture digest, result, commit SHA, environment, reviewer and known limits. A generic repeated checklist is not a passed test.

## Production acceptance
The latest repository source and actual hosted runtime take precedence over an older blueprint's claim of implementation. Explicitly verify real identity and authorization, RLS/tenant isolation, bounded provider permissions, reconciliation, audit, backup/restore and domain-review acceptance before marking RELEASED. Current gate remains open until source-SHA-bound evidence is accepted.

See [shared-app boundary](../platform/ONE_APP_FIVE_SERVICES.md), [current gate evidence](../verification/CURRENT_GATE_EVIDENCE.md) and [hosted runbook](../../ops/runbooks/RUNTIME_RELEASE_VERIFICATION.md).

## Complete uploaded source

Read [the complete owner documents and IR catalogue](source/README.md). These files are preserved byte-for-byte; this page is a summary. The source index records each file size and Git blob SHA.
