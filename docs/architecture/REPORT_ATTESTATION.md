# Report attestation

`GET /v1/reports/{id}/signature` requires `report:read`, verified membership and tenant-scoped report visibility. The service verifies the immutable report bytes against the stored SHA-256 before creating an Ed25519 attestation. Missing/tampered content is not signed. Responses use no-store caching.

The signed payload binds tenant ID, report ID, reconciliation run ID, report artifact SHA, ledger SHA, source revision, approved summary SHA, run version, finalization time and the exact stored report JSON string. Signature and payload hashes are distinct from the report artifact hash. No new report bytes or signature rows are written; this is a read-time attestation of an existing finalized report. Retain the envelope if a durable signature receipt is needed.

Configure `RECONCILE_REPORT_SIGNING_KEY_PEM` as an unencrypted Ed25519 PKCS8 PEM private key in the runtime secret manager. There is no development fallback and no key generation on requests. Missing, invalid, oversized or wrong-algorithm keys return REPORT_SIGNING_KEY_UNAVAILABLE/503. Never put private keys in source, CI logs or documentation. Test keys are ephemeral and generated only by tests. Real deployment configuration, key custody, rotation and revocation remain operational prerequisites.

Consumers must receive the trusted public key through an independent channel. `key_sha256` identifies its DER SubjectPublicKeyInfo hash; it never selects or authorizes a key. The envelope deliberately contains no purported trusted key. Verify with:

```sh
python scripts/verify_report_signature.py --envelope envelope.json --public-key trusted-public.pem --expected-binding expected-report.json
```

The separately prepared expected binding must contain `tenant_id`, `report_id`, `run_id` and `artifact_sha256`. It must come from the expected report/context, not be copied automatically from an untrusted envelope. Additional expected fields can be checked as well. The verifier enforces the fixed algorithm, independent key fingerprint, canonical signature encoding, payload SHA, signature, payload schema, expected binding, and actual report content SHA. It rejects duplicate outer JSON keys and bounds file sizes. Exit 0 means verified attestation; exit 1 means invalid/unavailable input. No network or report code is executed.

Signing the report establishes that the configured signer attested these bytes and metadata. It does not independently validate accounting judgments, approve a controller policy, certify transaction correctness, or trigger funds movement. Existing reviewer, partition and conservation checks remain prerequisites to finalization. Signing-key compromise and low-entropy hash privacy cannot be resolved by this feature alone. Production and domain acceptance remain open.
