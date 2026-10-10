-- Additive index for exception listing by tenant and reconciliation run.
-- Apply once using the staging migration/provisioning role with its
-- search_path set to fw_datareconcile_ai, pg_catalog. Never use a runtime role.
-- This SQL is also exercised in the disposable PostgreSQL runtime test.
CREATE INDEX IF NOT EXISTS idx_exception_cases_tenant_run
    ON exception_cases (tenant_id, run_id);
