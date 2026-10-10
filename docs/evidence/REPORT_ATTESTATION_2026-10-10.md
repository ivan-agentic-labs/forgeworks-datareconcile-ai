# Report attestation evidence — 2026-10-10

Added an authenticated tenant-scoped report signature endpoint, Ed25519 signer without fallback, independently trusted offline verification function/CLI, HTTP contract and generated SDK. Signatures bind actual stored/downloaded report bytes and report identity.

Local validation: 187 passed, 1 disposable PostgreSQL skip, warnings treated as errors. Twenty-two added test cases cover actual HTTP/download byte equality, algorithm/key/digest/signature tampering, missing independent binding, cross-report replay, wrong key types, source tampering, explicit signer configuration, cross-tenant HTTP visibility and CLI exit status. Contract sanity, independent OpenAPI validation and generated SDK compilation pass.

The mandatory PostgreSQL workflow additionally finalizes a synthetic report, requests its real attestation from the PostgreSQL-backed HTTP app, verifies it with an independent public key and expected identity, and checks equality with downloaded bytes. Workflow completion determines that proof; a local skip does not.

All signing keys in tests are generated ephemerally. No production key, real ledger, finance transfer, production deployment or independent domain signoff was used.
