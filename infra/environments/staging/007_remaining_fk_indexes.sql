-- Additive FK lookup indexes for this product's small staging tables.
-- Apply after bootstrap and prior numbered staging migrations, in one transaction
-- with search_path set to the product schema, pg_catalog. Fail on lock contention.
SET LOCAL lock_timeout = '3s';
SET LOCAL statement_timeout = '30s';
CREATE INDEX IF NOT EXISTS idx_allocations_tenant_left ON allocations (tenant_id, left_id);
CREATE INDEX IF NOT EXISTS idx_allocations_tenant_right ON allocations (tenant_id, right_id);
CREATE INDEX IF NOT EXISTS idx_exception_cases_tenant_left_transaction ON exception_cases (tenant_id, left_transaction_id);
CREATE INDEX IF NOT EXISTS idx_exception_cases_tenant_right_transaction ON exception_cases (tenant_id, right_transaction_id);
CREATE INDEX IF NOT EXISTS idx_reconcile_runs_tenant_right_batch ON reconcile_runs (tenant_id, right_batch_id);
CREATE INDEX IF NOT EXISTS idx_source_artifact_commands_tenant_artifact ON source_artifact_commands (tenant_id, artifact_id);
