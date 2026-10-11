# Browser integer transport precision — 2026-10-11

Baseline eccbf71aed0ff33296bb9d23b7ff14d9c66e5b92 used response.json(), which rounded monetary integers before BigInt formatting. The console now parses the original response text, retains unsafe canonical integer tokens as decimal strings using JSON reviver source context, and rejects unsafe values if source context is unavailable. Safe integer and decimal JSON types remain unchanged. Invalid successful JSON is rejected; HTTP errors still retain status with non-JSON error pages. Already-rounded numeric formatter arguments are rejected.

12 behavioral regressions exercise the actual console API helper with Fetch Response objects: positive/negative unsafe integers, int64 extremes and larger aggregate totals, safe types, malformed/exponent/nonfinite payloads, older-parser behavior, HTTP errors, and formatter safety. Baseline results:
ℹ tests 12
ℹ pass 2
ℹ fail 10

Candidate: all 12 regressions pass; all 15 JavaScript tests pass; 2 static console tests pass. Full GitHub application, contract and PostgreSQL checks must pass before merge. No deployment, browser fleet compatibility, production readiness or change to backend JSON contract is claimed. Clients outside this console still require explicit lossless integer handling.
