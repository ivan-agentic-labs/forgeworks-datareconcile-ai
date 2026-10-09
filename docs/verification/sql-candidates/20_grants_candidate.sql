-- DESIGN CANDIDATE FOR DISPOSABLE PROOF ONLY.
-- Privileges apply exclusively to tenant-scoped tables protected by RLS.
-- Keep global `tenants` and `users` restricted to a separately audited provisioning path.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE artifact_references TO fw_datareconcile_ai_rw;
-- Audit events: append-only for application role, no direct update/delete.
REVOKE ALL ON TABLE audit_events FROM PUBLIC;
REVOKE UPDATE, DELETE ON TABLE audit_events FROM fw_datareconcile_ai_rw;
GRANT SELECT, INSERT ON TABLE audit_events TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE idempotency_records TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE import_batches TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE import_rows TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE inbox_receipts TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE jobs TO fw_datareconcile_ai_rw;
-- G1-D conditional restriction: membership writes disabled for generic app role.
-- Identity/admin provisioning service requires a separate reviewed role and authz gate.
REVOKE INSERT, UPDATE, DELETE ON TABLE memberships FROM fw_datareconcile_ai_rw;
GRANT SELECT ON TABLE memberships TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE outbox_events TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE reconcile_runs TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE transactions TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE allocations TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE exception_cases TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE match_candidates TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE reports TO fw_datareconcile_ai_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE exception_resolutions TO fw_datareconcile_ai_rw;

-- Global identity tables must not be readable via PUBLIC (disposable-proof safeguard).
REVOKE ALL ON TABLE users, tenants FROM PUBLIC;
