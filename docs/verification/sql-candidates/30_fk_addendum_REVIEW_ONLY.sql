-- DESIGN-ONLY SQL. NOT VALIDATED BY A LIVE POSTGRESQL INSTANCE.
-- Review business semantics, existing data, and ON DELETE decision before adoption.
-- Apply after 10_schema_candidate.sql, on an isolated disposable database only.

ALTER TABLE import_rows
  ADD CONSTRAINT fk_g1_import_rows_batch_id
  FOREIGN KEY (tenant_id, batch_id)
  REFERENCES import_batches (tenant_id, id)
  ON DELETE RESTRICT;

ALTER TABLE import_rows
  ADD CONSTRAINT fk_g1_import_rows_normalized_transaction_id
  FOREIGN KEY (tenant_id, normalized_transaction_id)
  REFERENCES transactions (tenant_id, id)
  ON DELETE RESTRICT;
