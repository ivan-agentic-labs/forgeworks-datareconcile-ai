-- DataReconcile MVP disposable migration; no transfers and no review-only addendum.
CREATE TABLE IF NOT EXISTS tenants(id uuid PRIMARY KEY,slug text UNIQUE NOT NULL,status text NOT NULL);
CREATE TABLE IF NOT EXISTS import_batches(tenant_id uuid NOT NULL,id uuid NOT NULL,source_label text NOT NULL,file_sha256 char(64) NOT NULL,currency char(3) NOT NULL,row_count integer NOT NULL,status text NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,file_sha256),FOREIGN KEY(tenant_id) REFERENCES tenants(id));
CREATE TABLE IF NOT EXISTS import_rows(tenant_id uuid NOT NULL,id uuid NOT NULL,batch_id uuid NOT NULL,external_ref text NOT NULL,currency char(3) NOT NULL,amount_minor bigint NOT NULL,occurred_at timestamptz NOT NULL,row_status text NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,batch_id,external_ref),FOREIGN KEY(tenant_id,batch_id) REFERENCES import_batches(tenant_id,id));
CREATE TABLE IF NOT EXISTS reconcile_runs(tenant_id uuid NOT NULL,id uuid NOT NULL,left_batch_id uuid NOT NULL,right_batch_id uuid NOT NULL,rule_version text NOT NULL,status text NOT NULL,unmatched_count integer NOT NULL,version integer NOT NULL DEFAULT 1,PRIMARY KEY(tenant_id,id),FOREIGN KEY(tenant_id,left_batch_id) REFERENCES import_batches(tenant_id,id),FOREIGN KEY(tenant_id,right_batch_id) REFERENCES import_batches(tenant_id,id));
CREATE TABLE IF NOT EXISTS exception_cases(tenant_id uuid NOT NULL,id uuid NOT NULL,run_id uuid NOT NULL,reason_code text NOT NULL,left_transaction_id uuid NOT NULL,right_transaction_id uuid NOT NULL,status text NOT NULL,version integer NOT NULL DEFAULT 1,PRIMARY KEY(tenant_id,id),FOREIGN KEY(tenant_id,run_id) REFERENCES reconcile_runs(tenant_id,id));
CREATE TABLE IF NOT EXISTS reports(tenant_id uuid NOT NULL,id uuid NOT NULL,run_id uuid NOT NULL,ledger_sha256 char(64) NOT NULL,artifact_sha256 char(64) NOT NULL,finalized_at timestamptz NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,run_id),FOREIGN KEY(tenant_id,run_id) REFERENCES reconcile_runs(tenant_id,id));

-- Tenant context is set by the trusted application connection after authentication.
-- FORCE also protects against accidental owner bypass in disposable verification.
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['import_batches','import_rows','reconcile_runs','exception_cases','reports'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', table_name);
  END LOOP;
END $$;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname=current_schema() AND tablename='import_batches' AND policyname='import_batches_tenant') THEN
    CREATE POLICY import_batches_tenant ON import_batches USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname=current_schema() AND tablename='import_rows' AND policyname='import_rows_tenant') THEN
    CREATE POLICY import_rows_tenant ON import_rows USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname=current_schema() AND tablename='reconcile_runs' AND policyname='reconcile_runs_tenant') THEN
    CREATE POLICY reconcile_runs_tenant ON reconcile_runs USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname=current_schema() AND tablename='exception_cases' AND policyname='exception_cases_tenant') THEN
    CREATE POLICY exception_cases_tenant ON exception_cases USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname=current_schema() AND tablename='reports' AND policyname='reports_tenant') THEN
    CREATE POLICY reports_tenant ON reports USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
  END IF;
END $$;
