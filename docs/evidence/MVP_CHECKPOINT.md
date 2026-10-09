# MVP checkpoint — DataReconcile AI

Status: `TESTED` for synthetic same-currency exact 1:1 flow.

Implemented: tenant-scoped import batches, duplicate file digest rejection, integer minor-unit rows, same-currency guard, deterministic 1:1 matching, unmatched exception queue, authorization-bound resolution, stale version guard, immutable report digest, and signed download token stub.

Command: `PYTHONPATH=apps/api/src python -W error -m pytest tests/integration -q`  
Observed: 2 passed, exit 0, local Sandbox.

Not run: PostgreSQL/RLS, real artifact quarantine, CSV parser against uploaded files, FX/partial matching (out of scope), financial transfer (never enabled), backup/restore, and production deployment. No floating-point arithmetic or real financial data is used.
