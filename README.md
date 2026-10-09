# DataReconcile AI

**Status: synthetic MVP milestone implemented and tested locally. Not deployed, not production-ready, and G1-E remains open.**

Deterministic transaction reconciliation, exceptions, approvals and auditability.

The first executable slice imports synthetic rows, uses integer minor units, performs deterministic same-currency 1:1 matching, creates exceptions, records authorized resolutions, and finalizes an immutable report. It never transfers funds or uses floating-point amounts.

## MVP run and test
```bash
python -m pip install -e 'apps/api[test]'
RECONCILE_SEED_FIXTURE=1 PYTHONPATH=apps/api/src uvicorn datareconcile_ai.main:app --reload
python -W error -m pytest tests/integration
```
The SQLite store and development issuer are test-only. See `docs/evidence/MVP_CHECKPOINT.md`.

## Documents
- Product scope: `docs/product/PRODUCT_SCOPE.md`
- Architecture and file ownership: `docs/architecture/`
- Source contracts: `contracts/openapi.yaml` and `contracts/events.schema.json`
- Candidate SQL: `docs/verification/sql-candidates/` (NOT migration scripts)
- Signoff / blockers: `docs/verification/DESIGN_GATE_STATUS.md` and `docs/governance/MASTER_G1_DECISION.md`

## Local verification
Install dependencies from `scripts/requirements-verification.txt` then run:

```bash
python scripts/verify_bootstrap.py
python scripts/verify_contracts.py
python scripts/validate_openapi_independent.py
```

CI contains a manual PostgreSQL disposable DDL smoke test. **No live RLS/two-tenant proof or sandbox evidence is claimed.**

## Non-goals at this stage
No production deployment, customer data, code-execution agent, public access, financial mutation, license assertion or fake passing tests.

## Governance
The owner approved proceeding with GitHub bootstrap. Technical G1-E controls are still pending until their tests actually pass and evidence is reviewed. See `docs/governance/MASTER_G1_DECISION.md` for pre-approval baseline language; the owner approval is recorded here as a later decision.
