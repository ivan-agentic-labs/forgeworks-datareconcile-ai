-- REVIEW CANDIDATE ONLY. SQLAlchemy PostgreSQL dialect compilation, NO live PostgreSQL.
-- NOT APPROVED AS EXECUTABLE MIGRATION. fw_datareconcile_ai_rw must be created with NOLOGIN,
-- checked grants and no table ownership or BYPASSRLS. A distinct migration
-- owner deploys schema. API service must authenticate membership, set SET LOCAL
-- app.tenant_id within transaction, and never pass SQL through to users.
-- Global tenants/users need dedicated authorization rules (not generic RLS).
-- No automatic fw_datareconcile_ai_rw GRANT is provided; least-privilege permissions undecided.
-- Audit events require retention controls and legal review.
-- PostgreSQL version/vendor and migration ordering are not yet approved.

CREATE TABLE tenants (
	id UUID NOT NULL, 
	slug TEXT NOT NULL, 
	status TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (slug)
)

;


CREATE TABLE users (
	id UUID NOT NULL, 
	issuer TEXT NOT NULL, 
	subject TEXT NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_users_issuer_sub UNIQUE (issuer, subject)
)

;


CREATE TABLE artifact_references (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	object_key TEXT NOT NULL, 
	sha256 CHAR(64) NOT NULL, 
	media_type TEXT NOT NULL, 
	status TEXT NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_artifact_references PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_artifact_references_tenant FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT uq_artifact_key UNIQUE (tenant_id, object_key)
)

;


CREATE TABLE audit_events (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	actor_key TEXT NOT NULL, 
	action TEXT NOT NULL, 
	resource_key TEXT NOT NULL, 
	data_class TEXT NOT NULL, 
	trace_id TEXT, 
	payload JSONB NOT NULL, 
	CONSTRAINT pk_audit_events PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_audit_events_tenant FOREIGN KEY(tenant_id) REFERENCES tenants (id)
)

;


CREATE TABLE idempotency_records (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	actor_key TEXT NOT NULL, 
	command_name TEXT NOT NULL, 
	idempotency_key TEXT NOT NULL, 
	request_sha256 CHAR(64) NOT NULL, 
	response_status INTEGER, 
	response_json JSONB, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_idempotency_records PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_idempotency_records_tenant FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT uq_idempotency_scope UNIQUE (tenant_id, actor_key, command_name, idempotency_key)
)

;


CREATE TABLE import_batches (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	source_label TEXT NOT NULL, 
	file_sha256 CHAR(64) NOT NULL, 
	currency CHAR(3) NOT NULL, 
	profile_version TEXT NOT NULL, 
	status TEXT NOT NULL, 
	row_count INTEGER DEFAULT 0 NOT NULL, 
	CONSTRAINT pk_import_batches_tenant_id_id PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_import_batches_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT uq_import_batches_tenant_id_source_label_file_sha256 UNIQUE (tenant_id, source_label, file_sha256)
)

;


CREATE TABLE import_rows (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	batch_id UUID NOT NULL, 
	row_number INTEGER NOT NULL, 
	raw_row_sha256 CHAR(64) NOT NULL, 
	parse_status TEXT NOT NULL, 
	parse_errors JSONB NOT NULL, 
	normalized_transaction_id UUID, 
	CONSTRAINT pk_import_rows_tenant_id_id PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_import_rows_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT uq_import_rows_tenant_id_batch_id_row_number UNIQUE (tenant_id, batch_id, row_number)
)

;


CREATE TABLE inbox_receipts (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	consumer_name TEXT NOT NULL, 
	event_key TEXT NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_inbox_receipts PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_inbox_receipts_tenant FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT uq_inbox_dedupe UNIQUE (tenant_id, consumer_name, event_key)
)

;


CREATE TABLE jobs (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	kind TEXT NOT NULL, 
	status TEXT NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	created_by UUID, 
	CONSTRAINT pk_jobs PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_jobs_tenant FOREIGN KEY(tenant_id) REFERENCES tenants (id)
)

;


CREATE TABLE memberships (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	user_id UUID NOT NULL, 
	role TEXT NOT NULL, 
	status TEXT NOT NULL, 
	CONSTRAINT pk_memberships PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_memberships_tenant FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT fk_memberships_user FOREIGN KEY(user_id) REFERENCES users (id), 
	CONSTRAINT uq_memberships_user UNIQUE (tenant_id, user_id)
)

;


CREATE TABLE outbox_events (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	event_type TEXT NOT NULL, 
	event_version INTEGER DEFAULT 1 NOT NULL, 
	payload JSONB NOT NULL, 
	event_key TEXT NOT NULL, 
	delivered_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_outbox_events PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_outbox_events_tenant FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT uq_outbox_key UNIQUE (tenant_id, event_key)
)

;


CREATE TABLE reconcile_runs (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	left_batch_id UUID NOT NULL, 
	right_batch_id UUID NOT NULL, 
	rule_version TEXT NOT NULL, 
	status TEXT NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	CONSTRAINT pk_reconcile_runs_tenant_id_id PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_reconcile_runs_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT fk_reconcile_runs_tenant_id_left_batch_id FOREIGN KEY(tenant_id, left_batch_id) REFERENCES import_batches (tenant_id, id), 
	CONSTRAINT fk_reconcile_runs_tenant_id_right_batch_id FOREIGN KEY(tenant_id, right_batch_id) REFERENCES import_batches (tenant_id, id), 
	CONSTRAINT uq_reconcile_runs_tenant_id_left_batch_id_right_batch_28c88211 UNIQUE (tenant_id, left_batch_id, right_batch_id, rule_version)
)

;


CREATE TABLE transactions (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	batch_id UUID NOT NULL, 
	external_ref TEXT NOT NULL, 
	currency CHAR(3) NOT NULL, 
	amount_minor BIGINT NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	row_number INTEGER NOT NULL, 
	CONSTRAINT pk_transactions_tenant_id_id PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_transactions_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT fk_transactions_tenant_id_batch_id FOREIGN KEY(tenant_id, batch_id) REFERENCES import_batches (tenant_id, id), 
	CONSTRAINT uq_transactions_tenant_id_batch_id_row_number UNIQUE (tenant_id, batch_id, row_number)
)

;


CREATE TABLE allocations (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	run_id UUID NOT NULL, 
	left_transaction_id UUID NOT NULL, 
	right_transaction_id UUID NOT NULL, 
	rule_version TEXT NOT NULL, 
	matched_amount_minor BIGINT NOT NULL, 
	currency CHAR(3) NOT NULL, 
	approved_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_allocations_tenant_id_id PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_allocations_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT fk_allocations_tenant_id_run_id FOREIGN KEY(tenant_id, run_id) REFERENCES reconcile_runs (tenant_id, id), 
	CONSTRAINT fk_allocations_tenant_id_left_transaction_id FOREIGN KEY(tenant_id, left_transaction_id) REFERENCES transactions (tenant_id, id), 
	CONSTRAINT fk_allocations_tenant_id_right_transaction_id FOREIGN KEY(tenant_id, right_transaction_id) REFERENCES transactions (tenant_id, id), 
	CONSTRAINT uq_allocations_tenant_id_run_id_left_transaction_id UNIQUE (tenant_id, run_id, left_transaction_id), 
	CONSTRAINT uq_allocations_tenant_id_run_id_right_transaction_id UNIQUE (tenant_id, run_id, right_transaction_id), 
	CONSTRAINT ck_allocations_matched_amount_minor CHECK (matched_amount_minor <> 0)
)

;


CREATE TABLE exception_cases (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	run_id UUID NOT NULL, 
	reason_code TEXT NOT NULL, 
	status TEXT NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	evidence_sha256 CHAR(64), 
	CONSTRAINT pk_exception_cases_tenant_id_id PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_exception_cases_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT fk_exception_cases_tenant_id_run_id FOREIGN KEY(tenant_id, run_id) REFERENCES reconcile_runs (tenant_id, id)
)

;


CREATE TABLE match_candidates (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	run_id UUID NOT NULL, 
	left_transaction_id UUID NOT NULL, 
	right_transaction_id UUID NOT NULL, 
	rule_version TEXT NOT NULL, 
	reason_code TEXT NOT NULL, 
	CONSTRAINT pk_match_candidates_tenant_id_id PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_match_candidates_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT fk_match_candidates_tenant_id_run_id FOREIGN KEY(tenant_id, run_id) REFERENCES reconcile_runs (tenant_id, id), 
	CONSTRAINT fk_match_candidates_tenant_id_left_transaction_id FOREIGN KEY(tenant_id, left_transaction_id) REFERENCES transactions (tenant_id, id), 
	CONSTRAINT fk_match_candidates_tenant_id_right_transaction_id FOREIGN KEY(tenant_id, right_transaction_id) REFERENCES transactions (tenant_id, id), 
	CONSTRAINT uq_match_candidates_tenant_id_run_id_left_transaction_036e8a42 UNIQUE (tenant_id, run_id, left_transaction_id, right_transaction_id)
)

;


CREATE TABLE reports (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	run_id UUID NOT NULL, 
	ledger_sha256 CHAR(64) NOT NULL, 
	artifact_sha256 CHAR(64) NOT NULL, 
	finalized_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_reports_tenant_id_id PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_reports_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT fk_reports_tenant_id_run_id FOREIGN KEY(tenant_id, run_id) REFERENCES reconcile_runs (tenant_id, id), 
	CONSTRAINT uq_reports_tenant_id_run_id UNIQUE (tenant_id, run_id)
)

;


CREATE TABLE exception_resolutions (
	tenant_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	exception_id UUID NOT NULL, 
	reviewer_id UUID NOT NULL, 
	decision TEXT NOT NULL, 
	evidence_sha256 CHAR(64) NOT NULL, 
	expected_version INTEGER NOT NULL, 
	CONSTRAINT pk_exception_resolutions_tenant_id_id PRIMARY KEY (tenant_id, id), 
	CONSTRAINT fk_exception_resolutions_tenant_id FOREIGN KEY(tenant_id) REFERENCES tenants (id), 
	CONSTRAINT fk_exception_resolutions_tenant_id_exception_id FOREIGN KEY(tenant_id, exception_id) REFERENCES exception_cases (tenant_id, id), 
	CONSTRAINT uq_exception_resolutions_tenant_id_exception_id_expec_536f3742 UNIQUE (tenant_id, exception_id, expected_version)
)

;

-- INDEXES
CREATE INDEX ix_exception_cases_tenant_id_run_id_status ON exception_cases (tenant_id, run_id, status);

-- RLS POLICIES (candidate, role not yet provisioned)
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY p_memberships_tenant ON memberships FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY p_jobs_tenant ON jobs FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_events FORCE ROW LEVEL SECURITY;
CREATE POLICY p_outbox_events_tenant ON outbox_events FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE inbox_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE inbox_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY p_inbox_receipts_tenant ON inbox_receipts FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE idempotency_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_records FORCE ROW LEVEL SECURITY;
CREATE POLICY p_idempotency_records_tenant ON idempotency_records FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;
-- Audit is append-only for the application role; owner/retention procedure is separate.
CREATE POLICY p_audit_events_read ON audit_events FOR SELECT TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY p_audit_events_append ON audit_events FOR INSERT TO fw_datareconcile_ai_rw WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE artifact_references ENABLE ROW LEVEL SECURITY;
ALTER TABLE artifact_references FORCE ROW LEVEL SECURITY;
CREATE POLICY p_artifact_references_tenant ON artifact_references FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE import_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_batches FORCE ROW LEVEL SECURITY;
CREATE POLICY p_import_batches_tenant ON import_batches FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions FORCE ROW LEVEL SECURITY;
CREATE POLICY p_transactions_tenant ON transactions FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE reconcile_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconcile_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY p_reconcile_runs_tenant ON reconcile_runs FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE match_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_candidates FORCE ROW LEVEL SECURITY;
CREATE POLICY p_match_candidates_tenant ON match_candidates FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE allocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE allocations FORCE ROW LEVEL SECURITY;
CREATE POLICY p_allocations_tenant ON allocations FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE exception_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE exception_cases FORCE ROW LEVEL SECURITY;
CREATE POLICY p_exception_cases_tenant ON exception_cases FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE exception_resolutions ENABLE ROW LEVEL SECURITY;
ALTER TABLE exception_resolutions FORCE ROW LEVEL SECURITY;
CREATE POLICY p_exception_resolutions_tenant ON exception_resolutions FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports FORCE ROW LEVEL SECURITY;
CREATE POLICY p_reports_tenant ON reports FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
ALTER TABLE import_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_rows FORCE ROW LEVEL SECURITY;
CREATE POLICY p_import_rows_tenant ON import_rows FOR ALL TO fw_datareconcile_ai_rw USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
