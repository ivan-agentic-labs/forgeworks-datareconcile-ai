# G1 evidence index

This index is pinned to the audited source snapshot `09b2628b53e1dd66c0b5fc80dc26323d4b558891`. A checked item means that the bounded evidence exists; it does **not** mean G1-D or G1-E is closed. Full criterion details and limitations are in [`docs/evidence/G1_RUNTIME_EVIDENCE.md`](../evidence/G1_RUNTIME_EVIDENCE.md).

- [x] Independent OpenAPI validation in CI — **VERIFIED**, [run 37877971633](https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/37877971633)
- [x] Event schema and static contract checks — **PASS_STATIC_LIMITED**, same contract run and local `verify_contracts.py`
- [x] PostgreSQL DDL against an empty disposable instance — **VERIFIED**, [run 37877997433](https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/37877997433)
- [x] Non-owner two-tenant RLS visibility/cross-tenant INSERT negative probe — **PASS_STATIC_LIMITED**, [run 37878000156](https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/37878000156)
- [x] Synthetic application auth/tenant negative tests — **PASS_STATIC_LIMITED**, local `pytest -W error tests`
- [x] API/static-console E2E flow — **PASS_STATIC_LIMITED**, local `pytest -W error tests`
- [x] Worker retry/restart/idempotency reliability tests — **PASS_STATIC_LIMITED**, local `pytest -W error tests`
- [x] Artifact SHA, immutability, and conservation assertions — **PASS_STATIC_LIMITED**, local integration/E2E tests
- [ ] Generated TypeScript client compilation/interoperability — **NOT_RUN**
- [ ] Full RLS SELECT/INSERT/UPDATE/DELETE matrix, transaction-context reset, and role-bypass checks — **NOT_RUN**
- [ ] Real IdP/OIDC session, CSRF, provisioning, and access-control tests — **NOT_RUN**
- [ ] Product-specific unsafe-tool, browser sandbox, SSRF, and egress isolation — **NOT_RUN**
- [ ] External storage capability/integrity evidence — **NOT_RUN**
- [ ] Owner/independent reviewer signoffs and retained logs — **BLOCKED**
- [ ] Production backup/restore, legal/domain/operations/cost signoff — **NOT_RUN/BLOCKED**

The disposable PostgreSQL jobs are synthetic CI evidence only. The RLS probe covers tenant-A visibility and cross-tenant INSERT rejection for a non-owner role; it is not a complete CRUD, pooled-connection, bypass, or production authorization proof. Residual blockers remain and no reviewer approval is implied.
