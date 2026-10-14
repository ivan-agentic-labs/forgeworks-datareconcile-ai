# DataReconcile AI — Hosted disposable private-object lifecycle proof
**Date:** 2026-10-14 (UTC). **Environment:** Railway ForgeWorks AI staging, Singapore. **Scope:** staging only.

## Observed evidence
- Staging deployment: `6ca6c055-1fc8-4e93-8766-8ac3d749d430` — terminal Railway `SUCCESS`.
- Deployed source SHA: `70ee65026b244006c70197f580119c0421820a01`; the exact revision and runtime manifest were verified by the [five-service public proof](https://github.com/ivan-agentic-labs/forgeworks-apishield-agent/actions/runs/38533777988).
- The Railway deploy log for that deployment records `STORAGE_PROBE_PASS: upload, integrity, deletion and verified absence`.
- Script: `scripts/storage_probe.py`. The probe allocates fresh random tenant/artifact UUIDs, writes a bounded synthetic byte sequence to private S3-compatible storage, verifies a persisted SHA-256 read, deletes **only its own generated object key**, then requires the same object to return the expected missing-object error. No access tokens or object identifiers are printed in the success receipt.
- The private Supabase staging bucket is constrained by the per-product and environment bucket mapping in `object_storage.py`. The five ForgeWorks staging buckets are `public=false` and have a 1 MiB file limit. A read-only Supabase inspection after the tests found zero objects remaining in each bucket.
- The first new deploy did **not** pass: Railway's 60-second pre-deploy timeout expired despite the probe log. The setting was changed to 180 seconds without removing the pre-deploy command; the later deployment above reached SUCCESS.

## What this does NOT prove
This is **not** production or customer-data lifecycle acceptance. It does not certify object malware scanning, retention/legal hold, tenant-authorized business endpoints, backup/restore of archived artifacts, IAM key restrictions, durable asynchronous workers, production SLO or independent review. Real user workflows and revocation tests remain OPEN.

Do not mark production acceptance PASS based solely on this synthetic hosted object test.
