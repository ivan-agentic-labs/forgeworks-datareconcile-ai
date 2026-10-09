-- Runtime extension, applied separately by the migration role. No customer data migration.
ALTER TABLE import_batches ADD COLUMN profile_version text NOT NULL DEFAULT 'strict-v1';
ALTER TABLE import_batches ADD COLUMN artifact_id uuid;
ALTER TABLE import_batches ADD COLUMN job_id uuid;
ALTER TABLE import_batches ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE import_rows ADD COLUMN transaction_type text NOT NULL DEFAULT 'normal';
ALTER TABLE import_rows ADD COLUMN row_number integer;
ALTER TABLE import_rows ADD COLUMN raw_row_sha char(64);
CREATE UNIQUE INDEX import_rows_number_unique ON import_rows(tenant_id,batch_id,row_number);
ALTER TABLE reconcile_runs ADD COLUMN job_id uuid;
ALTER TABLE reconcile_runs ADD COLUMN source_revision char(64);
ALTER TABLE reconcile_runs ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
CREATE UNIQUE INDEX reconcile_business_key ON reconcile_runs(tenant_id,left_batch_id,right_batch_id,rule_version);
ALTER TABLE exception_cases ALTER COLUMN left_transaction_id DROP NOT NULL;
ALTER TABLE exception_cases ALTER COLUMN right_transaction_id DROP NOT NULL;
ALTER TABLE exception_cases ADD COLUMN resolution_policy text;
ALTER TABLE exception_cases ADD CONSTRAINT exception_left_tenant_fk FOREIGN KEY(tenant_id,left_transaction_id) REFERENCES import_rows(tenant_id,id);
ALTER TABLE exception_cases ADD CONSTRAINT exception_right_tenant_fk FOREIGN KEY(tenant_id,right_transaction_id) REFERENCES import_rows(tenant_id,id);
ALTER TABLE exception_cases ADD CONSTRAINT exception_has_transaction CHECK(left_transaction_id IS NOT NULL OR right_transaction_id IS NOT NULL);
ALTER TABLE reports ADD COLUMN source_revision char(64);
ALTER TABLE reports ADD COLUMN totals_json jsonb;
ALTER TABLE reports ADD COLUMN approved_summary_sha char(64);
ALTER TABLE reports ADD COLUMN run_version integer;
ALTER TABLE reports ADD COLUMN content_json text;
CREATE TABLE memberships(tenant_id uuid NOT NULL REFERENCES tenants(id),user_id uuid NOT NULL,role text NOT NULL,status text NOT NULL,PRIMARY KEY(tenant_id,user_id));
CREATE TABLE allocations(tenant_id uuid NOT NULL,id uuid NOT NULL,run_id uuid NOT NULL,left_id uuid NOT NULL,right_id uuid NOT NULL,rule_version text NOT NULL,matched_amount_minor bigint NOT NULL,currency char(3) NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,run_id,left_id),UNIQUE(tenant_id,run_id,right_id),FOREIGN KEY(tenant_id,run_id) REFERENCES reconcile_runs(tenant_id,id),FOREIGN KEY(tenant_id,left_id) REFERENCES import_rows(tenant_id,id),FOREIGN KEY(tenant_id,right_id) REFERENCES import_rows(tenant_id,id));
CREATE TABLE resolutions(tenant_id uuid NOT NULL,id uuid NOT NULL,exception_id uuid NOT NULL,reviewer_id uuid NOT NULL,decision text NOT NULL,evidence_sha char(64) NOT NULL,expected_version integer NOT NULL,created_at timestamptz NOT NULL,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,exception_id,expected_version),FOREIGN KEY(tenant_id,exception_id) REFERENCES exception_cases(tenant_id,id));
CREATE TABLE audit_events(tenant_id uuid NOT NULL,id uuid NOT NULL,event_type text NOT NULL,aggregate_id uuid NOT NULL,aggregate_version integer NOT NULL,actor_id uuid,occurred_at timestamptz NOT NULL,payload_json jsonb NOT NULL,PRIMARY KEY(tenant_id,id));
CREATE INDEX audit_aggregate ON audit_events(tenant_id,aggregate_id);
CREATE ROLE fw_datareconcile_ai_rw NOLOGIN NOSUPERUSER NOBYPASSRLS;
GRANT USAGE ON SCHEMA public TO fw_datareconcile_ai_rw;
DO $$
DECLARE tbl text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['import_batches','import_rows','reconcile_runs','exception_cases','reports','allocations','resolutions','audit_events','memberships']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY',tbl);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY',tbl);
    IF tbl IN ('allocations','resolutions','audit_events','memberships') THEN
      EXECUTE format('CREATE POLICY tenant_boundary ON %I USING (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid) WITH CHECK (tenant_id=nullif(current_setting(''app.tenant_id'',true),'''')::uuid)',tbl);
    END IF;
    EXECUTE format('GRANT SELECT ON %I TO fw_datareconcile_ai_rw',tbl);
    IF tbl <> 'memberships' THEN
      EXECUTE format('GRANT INSERT ON %I TO fw_datareconcile_ai_rw',tbl);
    END IF;
    IF tbl NOT IN ('memberships','reports','allocations','resolutions','audit_events') THEN
      EXECUTE format('GRANT UPDATE,DELETE ON %I TO fw_datareconcile_ai_rw',tbl);
    END IF;
  END LOOP;
END $$;
