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
