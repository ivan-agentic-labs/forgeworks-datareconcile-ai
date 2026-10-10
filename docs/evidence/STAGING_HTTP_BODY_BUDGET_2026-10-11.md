# 2026-10-11 staged HTTP request budget

## Exact source
- Release commit: `075e79a9c4fc26f4af16b2fcab47aac09c49e8e9`.
- Railway staging deployment `64d7aad2-c88b-4749-aca5-9d07016e1b15`: SUCCESS, one running replica, zero crashed at checkpoint.
- Request body bound: 8 MiB with declared/actual bytes checked, 16,384-chunk budget and 400/413 rejections. Includes pure ASGI synthetic regression tests; no rate-limit/DDoS claim.
- Staging is pinned to source SHA; docs-only main commits after this checkpoint need not be deployed.

## CI receipts
- G1 Contract Verification: **success** (https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/38087971520)
- G2 Disposable PostgreSQL RLS Negative Test: **success** (https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/38087971516)
- DataReconcile MVP Application CI: **success** (https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/38087971514)
- DataReconcile PostgreSQL Runtime Proof: **success** (https://github.com/ivan-agentic-labs/forgeworks-datareconcile-ai/actions/runs/38087971498)

## OPEN acceptance
Direct external /readyz and authenticated finance business-path proofs are not available from this execution environment; production, customer data, controller signoff, load, recovery and G3-G6 gates remain OPEN.
