-- Staging only: fresh private schema in the connected Supabase project.
-- Apply exactly once through the migration/provisioning role. Never at app startup.
CREATE SCHEMA fw_datareconcile_ai;
REVOKE ALL ON SCHEMA fw_datareconcile_ai FROM PUBLIC, anon, authenticated;
SET LOCAL search_path TO fw_datareconcile_ai, pg_catalog;
ALTER DEFAULT PRIVILEGES IN SCHEMA fw_datareconcile_ai REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA fw_datareconcile_ai REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
-- Source: 001_reconcile_mvp.sql
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

-- Source: 002_reconcile_runtime.sql
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
GRANT USAGE ON SCHEMA fw_datareconcile_ai TO fw_datareconcile_ai_rw;
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

-- Source: 003_source_artifact_ingestion.sql
-- Development/disposable proof only; not external object storage or scanning.
CREATE TABLE source_artifacts(
 tenant_id uuid NOT NULL REFERENCES tenants(id), id uuid NOT NULL,
 kind text NOT NULL, filename text NOT NULL, sha256 char(64) NOT NULL,
 size_bytes integer NOT NULL CHECK(size_bytes BETWEEN 1 AND 1048576),
 declared_media_type text, status text NOT NULL CHECK(status IN ('INTENT_ISSUED','QUARANTINED','AVAILABLE','REJECTED','DELETED')),
 created_at timestamptz NOT NULL, object_generation text, content_base64 text,
 PRIMARY KEY(tenant_id,id)
);
CREATE TABLE source_artifact_commands(
 tenant_id uuid NOT NULL, actor text NOT NULL, action text NOT NULL,
 command_key text NOT NULL, request_sha char(64) NOT NULL, artifact_id uuid NOT NULL,
 PRIMARY KEY(tenant_id,actor,action,command_key),
 FOREIGN KEY(tenant_id,artifact_id) REFERENCES source_artifacts(tenant_id,id)
);
ALTER TABLE source_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_artifacts FORCE ROW LEVEL SECURITY;
ALTER TABLE source_artifact_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_artifact_commands FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_boundary ON source_artifacts USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
CREATE POLICY tenant_boundary ON source_artifact_commands USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
GRANT SELECT,INSERT,UPDATE ON source_artifacts TO fw_datareconcile_ai_rw;
GRANT SELECT,INSERT ON source_artifact_commands TO fw_datareconcile_ai_rw;

-- Source: 004_artifact_immutability.sql
-- Enforce immutability below the application adapter after first byte upload.
CREATE FUNCTION enforce_source_artifact_immutability() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.id IS DISTINCT FROM OLD.id
 OR NEW.kind IS DISTINCT FROM OLD.kind OR NEW.filename IS DISTINCT FROM OLD.filename
 OR NEW.sha256 IS DISTINCT FROM OLD.sha256 OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
 OR NEW.declared_media_type IS DISTINCT FROM OLD.declared_media_type OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
  RAISE EXCEPTION 'Source artifact intent metadata is immutable';
 END IF;
 IF OLD.content_base64 IS NOT NULL AND
 (NEW.content_base64 IS DISTINCT FROM OLD.content_base64 OR NEW.object_generation IS DISTINCT FROM OLD.object_generation) THEN
  RAISE EXCEPTION 'Uploaded source artifact bytes and generation are immutable';
 END IF;
 IF NEW.status IS DISTINCT FROM OLD.status AND NOT
 ((OLD.status='INTENT_ISSUED' AND NEW.status IN ('QUARANTINED','REJECTED'))
 OR (OLD.status='QUARANTINED' AND NEW.status IN ('AVAILABLE','REJECTED'))) THEN
  RAISE EXCEPTION 'Source artifact state transition is not permitted';
 END IF;
 IF NEW.status IN ('QUARANTINED','AVAILABLE') AND (NEW.content_base64 IS NULL OR NEW.object_generation IS NULL) THEN
  RAISE EXCEPTION 'Source artifact availability requires uploaded bytes and generation';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER source_artifact_immutable BEFORE UPDATE ON source_artifacts FOR EACH ROW EXECUTE FUNCTION enforce_source_artifact_immutability();

-- Auth-managed tables remain untouched. Return only a boolean for the JWT-bound user.
CREATE FUNCTION fw_datareconcile_ai.session_active(session_id uuid, user_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
 SELECT auth.uid() = $2 AND EXISTS (
   SELECT 1 FROM auth.sessions s JOIN auth.users u ON u.id=s.user_id
   WHERE s.id=$1 AND s.user_id=$2
     AND (s.not_after IS NULL OR s.not_after > now())
     AND u.deleted_at IS NULL AND (u.banned_until IS NULL OR u.banned_until <= now())
 );
$$;
REVOKE ALL ON FUNCTION fw_datareconcile_ai.session_active(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION fw_datareconcile_ai.session_active(uuid, uuid) TO fw_datareconcile_ai_rw;
GRANT USAGE ON SCHEMA fw_datareconcile_ai TO fw_datareconcile_ai_rw;
-- Restrict all product tables, including unexposed tenants, as defense in depth.
DO $$ DECLARE t record; BEGIN
 FOR t IN SELECT tablename FROM pg_tables WHERE schemaname='fw_datareconcile_ai' LOOP
   EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY','fw_datareconcile_ai',t.tablename);
   EXECUTE format('ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY','fw_datareconcile_ai',t.tablename);
   EXECUTE format('REVOKE ALL ON %I.%I FROM PUBLIC, anon, authenticated','fw_datareconcile_ai',t.tablename);
 END LOOP;
END $$;
RESET search_path;
