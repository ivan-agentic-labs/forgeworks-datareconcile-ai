#!/usr/bin/env bash
set -euo pipefail
# Never execute against production or a network host. This probe is disposable only.
[[ "${G2_DISPOSABLE_DB:-}" == 'yes' ]] || { echo 'G2_DISPOSABLE_DB=yes required' >&2; exit 2; }
[[ "${PGHOST:-}" == '127.0.0.1' ]] || { echo 'only 127.0.0.1 is allowed' >&2; exit 2; }
[[ "${PGDATABASE:-}" == 'forgeworks_g2' ]] || { echo 'only disposable database forgeworks_g2 is allowed' >&2; exit 2; }
command -v psql >/dev/null || { echo 'psql unavailable' >&2; exit 2; }
root="$(cd "$(dirname "$0")/.." && pwd)"
app_role='forgeworks_g2_app_test'
app_password='forgeworks_g2_disposable_only'
tenant_a='00000000-0000-0000-0000-0000000000a1'
tenant_b='00000000-0000-0000-0000-0000000000b1'
batch_a='10000000-0000-0000-0000-0000000000a1'
batch_b='10000000-0000-0000-0000-0000000000b1'
psql_admin=(psql -X -v ON_ERROR_STOP=1)
cleanup() {
  "${psql_admin[@]}" -c "DROP OWNED BY ${app_role}; DROP ROLE IF EXISTS ${app_role};" >/dev/null 2>&1 || true
}
trap cleanup EXIT
"${psql_admin[@]}" -f "$root/migrations/versions/001_reconcile_mvp.sql"
"${psql_admin[@]}" <<SQL
DROP ROLE IF EXISTS ${app_role};
CREATE ROLE ${app_role} LOGIN PASSWORD '${app_password}';
GRANT USAGE ON SCHEMA public TO ${app_role};
GRANT SELECT, INSERT, UPDATE, DELETE ON import_batches, import_rows, reconcile_runs, exception_cases, reports TO ${app_role};
INSERT INTO tenants(id,slug,status) VALUES
  ('${tenant_a}','g2-disposable-a','ACTIVE'),('${tenant_b}','g2-disposable-b','ACTIVE')
ON CONFLICT (id) DO NOTHING;
INSERT INTO import_batches(tenant_id,id,source_label,file_sha256,currency,row_count,status) VALUES
  ('${tenant_a}','${batch_a}','synthetic-a',repeat('a',64),'USD',1,'IMPORTED'),
  ('${tenant_b}','${batch_b}','synthetic-b',repeat('b',64),'USD',1,'IMPORTED')
ON CONFLICT (tenant_id,id) DO NOTHING;
SQL
visible="$(PGPASSWORD="$app_password" psql -X -v ON_ERROR_STOP=1 -U "$app_role" -Atc "SELECT set_config('app.tenant_id','${tenant_a}',false); SELECT count(*) FROM import_batches;")"
[[ "$(printf '%s\n' "$visible" | tail -1)" == '1' ]] || { echo "RLS visibility check failed: $visible" >&2; exit 1; }
if PGPASSWORD="$app_password" psql -X -v ON_ERROR_STOP=1 -U "$app_role" -c "SET app.tenant_id='${tenant_a}'; INSERT INTO import_batches(tenant_id,id,source_label,file_sha256,currency,row_count,status) VALUES('${tenant_b}','20000000-0000-0000-0000-0000000000b1','cross-tenant',repeat('c',64),'USD',0,'IMPORTED');"; then
  echo 'RLS write isolation check failed: cross-tenant insert was accepted' >&2
  exit 1
else
  echo 'RLS negative test passed: non-owner role cannot read or write another tenant.'
fi
