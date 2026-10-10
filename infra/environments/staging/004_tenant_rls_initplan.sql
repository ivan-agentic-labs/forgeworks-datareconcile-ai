-- Preserve import_batches tenant RLS, caching current_setting once per query.
-- Apply only via staging migration role with search_path=fw_datareconcile_ai,pg_catalog.
ALTER POLICY import_batches_tenant ON import_batches
  USING (tenant_id = NULLIF((SELECT current_setting('app.tenant_id', true)), '')::uuid)
  WITH CHECK (tenant_id = NULLIF((SELECT current_setting('app.tenant_id', true)), '')::uuid);
