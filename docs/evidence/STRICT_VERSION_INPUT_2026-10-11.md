# Strict version input — 2026-10-11

Baseline: eaedd5fb2b13225d11a45c37432ba00891b3902d.

The API accepted boolean true, numeric string "1", and floating JSON 1.0 as version 1. Require strict integer expected_version inputs while retaining positive integer bounds. Invalid validation now returns a stable INVALID_REQUEST 422 problem envelope without echoing raw values or serializing nonfinite inputs.

Behavioral tests exercise actual product HTTP routes with a synthetic authorized principal and spy on the relevant store operation (APIShield proposal lookup, DataReconcile resolve/finalize). Rejected requests cannot reach that operation. Valid JSON 1e400 covers safe error serialization. Integer versions 1, 2 and 2147483647 remain accepted by models. Missing target IDs isolate input validation; this is not business acceptance or a full concurrency proof.

Baseline new suite: 12 fail, 3 pass. Failures cover forbidden coercion, stable envelope and nonfinite handling; not every failure means the old implementation accepted the value. Candidate new suite: 15 pass. Full local suite: 231 pass, 1 skipped. Remaining local skips require PostgreSQL or sandbox tooling. Independent OpenAPI validation, bootstrap and static contract checks pass. Required GitHub workflows must pass before merge, including applicable browser and sandbox proofs. No deployment or production acceptance claimed.
