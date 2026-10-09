# datareconcile-ai — handoff desain (belum disetujui)

## Outcome dan batas P0
**Outcome:** Rekonsiliasi 1:1 transaksi denominasi sama dengan nilai integer minor.

**Alur:** Import -> validate -> normalize -> deterministic match -> exception -> approve -> immutable audit/report.

**Larangan utama:** Tidak mentransfer dana, tidak mengubah nominal oleh LLM; conservation, duplicate, refund dan reversal perlu review keuangan.

## Batas modul dan kepemilikan file
- `apps/web`: UI, session via BFF; tidak menyimpan bearer token di localStorage.
- `apps/api/src/presentation`: HTTP routing, request parsing, scope checking, RFC 9457 error.
- `apps/api/src/application`: perintah, authorization, idempotency, transaksi, approval.
- `apps/api/src/domain`: invariants dan state machine murni tanpa kode SDK/HTTP/SQL.
- `apps/api/src/infrastructure`: DB adapter, provider AI, integrasi domain khusus.
- `apps/worker`: outbox delivery, retries, dedupe dan timeout; side effect eksternal hanya setelah approval.
- `contracts`: `openapi.yaml` dan `events.schema.json`; perubahan breaking harus menyertakan ADR.
- `infra`: role/privileges, migrasi database, object storage, isolation and observability.
- `tests`: unit, contract, security, e2e, eval, load, restore, failure injection.

## API P0 (sumber kebenaran: `openapi.yaml`)
- `POST /v1/import-batches`
- `GET /v1/import-batches/{id}/rows`
- `POST /v1/reconciliation-runs`
- `GET /v1/reconciliation-runs/{id}/exceptions`
- `POST /v1/exceptions/{id}/resolutions`
- `POST /v1/reconciliation-runs/{id}/finalize`
- `GET /v1/reports/{id}/download`
- `POST /v1/artifacts/upload-intents`
- `POST /v1/artifacts/{artifact_id}/commit`
- `GET /v1/artifacts/{artifact_id}`
- `POST /v1/artifacts/{artifact_id}/download-intents`
- `GET /v1/jobs/{job_id}`

## Database P0 (sumber kebenaran sementara: `10_schema_candidate.sql`)
18 tabel terencana: tenants, users, artifact_references, audit_events, idempotency_records, import_batches, import_rows, inbox_receipts, jobs, memberships, outbox_events, reconcile_runs, transactions, allocations, exception_cases, match_candidates, reports, exception_resolutions.

- `00_role_candidate.sql` → `10_schema_candidate.sql` → `20_grants_candidate.sql` adalah urutan kandidat pada DB kosong.
- Role `fw_datareconcile_ai_rw` bukan pemilik tabel, bukan superuser, tanpa LOGIN dan tanpa BYPASSRLS.
- Data tenant membutuhkan RLS + application authorization (bukan RLS saja).
- Global `users`, `tenants` tidak diberikan hak via group role tenant; provisioning identitas memerlukan jalur tersendiri.
- `migration` dan `rollback` terpisah dari SQL kandidat; belum dapat dinyatakan valid.

## Failure state yang wajib diimplementasikan dan diuji
- Webhook/event berulang → idempotency dan inbox dedupe.
- Queue retry melewati deadline → status terminal dan audit; tidak terjadi double side-effect.
- Browser/network/model timeout → partial job, approval tetap menolak artefak lama.
- Context tenant kosong/berubah → default deny; session reset antarrequest.
- Backup/restore → data dan ownership diverifikasi pada disposable environment.
- Provider eksternal di-revoke → token invalid dan akses berhenti.

## Acceptance G1-D/G1-E
- G1-D dapat diajukan setelah owner menyetujui PRD, workflow, non-goals, kontrak API/data, batas keamanan, cost ceiling dan risiko residual.
- G1-E tetap NOT RUN hingga validator OpenAPI independen, PostgreSQL17 disposable, dan pengujian isolasi/role selesai.
- Tidak ada signoff fiktif dan tidak ada klaim production-ready.
