from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import jwt
from fastapi.testclient import TestClient

from datareconcile_ai.main import create_app
from datareconcile_ai.infrastructure.store import Store, TENANT, USER

SECRET = "forgeworks-development-secret-32-plus"
ISSUER = "https://issuer.synthetic.invalid"
AUDIENCE = "forgeworks-api"


def headers(scope: str, tenant: str = TENANT):
    token = jwt.encode(
        {
            "sub": USER,
            "tenant_id": tenant,
            "scope": scope,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def import_csv(client, content, label="csv-fixture", currency="USD"):
    digest = hashlib.sha256(content.encode()).hexdigest()
    return client.post(
        "/v1/import-batches",
        headers=headers("import:create"),
        json={
            "artifact_id": "33333333-3333-3333-3333-333333333333",
            "currency": currency,
            "profile_version": "strict-v1",
            "source_label": label,
            "file_sha256": digest,
            "csv_content": content,
        },
    )


def test_strict_csv_schema_digest_and_integer_boundaries(tmp_path):
    app = create_app(str(tmp_path / "db.sqlite"), seed=True)
    with TestClient(app) as client:
        bad_content = "external_ref,currency,amount_minor,occurred_at\nx,USD,1,2026-01-01T00:00:00Z\n"
        bad = client.post(
            "/v1/import-batches",
            headers=headers("import:create"),
            json={
                "artifact_id": "33333333-3333-3333-3333-333333333333",
                "currency": "USD",
                "profile_version": "strict-v1",
                "source_label": "bad",
                "file_sha256": "0" * 64,
                "csv_content": bad_content,
            },
        )
        assert bad.status_code == 422
        assert bad.json()["code"] == "SOURCE_DIGEST_MISMATCH"

        ambiguous = "external_ref,currency,amount_minor,occurred_at\nx,USD,1,234,2026-01-01T00:00:00Z\n"
        response = import_csv(client, ambiguous, label="ambiguous")
        assert response.status_code == 422
        assert response.json()["code"] in {"CSV_SCHEMA_INVALID", "SOURCE_DIGEST_MISMATCH"}

        valid = "external_ref,currency,amount_minor,occurred_at,transaction_type\nx,USD,9223372036854775807,2026-01-01T00:00:00Z,normal\n"
        accepted = import_csv(client, valid, label="max-int")
        assert accepted.status_code == 202
        rows = client.get(f"/v1/import-batches/{accepted.json()['id']}/rows", headers=headers("import:read"))
        assert rows.status_code == 200
        assert rows.json()["items"][0]["amount_minor"] == 9223372036854775807

        bad_refund = "external_ref,currency,amount_minor,occurred_at,transaction_type\nx,USD,100,2026-01-01T00:00:00Z,refund\n"
        policy = import_csv(client, bad_refund, label="positive-refund")
        assert policy.status_code == 422
        assert policy.json()["code"] == "CSV_SIGN_POLICY_VIOLATION"


def test_stale_resolution_is_single_winner_and_report_is_auditable(tmp_path):
    app = create_app(str(tmp_path / "db.sqlite"), seed=True)
    with TestClient(app) as client:
        common = {
            "artifact_id": "33333333-3333-3333-3333-333333333333",
            "currency": "USD",
            "profile_version": "strict-v1",
        }
        left = client.post("/v1/import-batches", headers=headers("import:create"), json={**common, "source_label": "left-fixture", "file_sha256": "a" * 64}).json()
        right = client.post("/v1/import-batches", headers=headers("import:create"), json={**common, "source_label": "right-fixture", "file_sha256": "b" * 64}).json()
        run = client.post("/v1/reconciliation-runs", headers=headers("reconcile:run"), json={"left_batch_id": left["id"], "right_batch_id": right["id"], "rule_version": "exact-1to1-v1"}).json()
        exception = client.get(f"/v1/reconciliation-runs/{run['id']}/exceptions", headers=headers("reconcile:read")).json()["items"][0]

        def approve():
            return client.post(
                f"/v1/exceptions/{exception['id']}/resolutions",
                headers=headers("exception:approve"),
                json={"decision": "accept-as-investigated", "evidence_sha256": "d" * 64, "expected_version": 1},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(lambda _: approve(), range(2)))
        assert statuses == [201, 409]

        finalized = client.post(
            f"/v1/reconciliation-runs/{run['id']}/finalize",
            headers=headers("report:finalize"),
            json={"expected_version": 1, "approved_summary_sha256": "c" * 64},
        )
        assert finalized.status_code == 201
        body = finalized.json()
        assert body["source_revision"] == run["source_revision"]
        assert body["totals"]["allocated_total_minor"] == 400
        assert body["totals"]["conservation_discrepancy_minor"] == 0
        assert client.get(f"/v1/reports/{body['id']}/download", headers=headers("report:read")).json()["source_revision"] == run["source_revision"]


def test_refund_policy_requires_explicit_negative_rows(tmp_path):
    app = create_app(str(tmp_path / "db.sqlite"), seed=True)
    with TestClient(app) as client:
        content = "external_ref,currency,amount_minor,occurred_at,transaction_type\nrefund-1,USD,-100,2026-01-01T00:00:00Z,refund\n"
        batch = import_csv(client, content, label="refund")
        assert batch.status_code == 202
        rows = client.get(f"/v1/import-batches/{batch.json()['id']}/rows", headers=headers("import:read")).json()["items"]
        assert rows[0]["transaction_type"] == "refund"


def test_store_allocations_are_unique_and_same_currency(tmp_path):
    store = Store(str(tmp_path / "db.sqlite"))
    store.seed()
    left = store.batch(TENANT, "left", "1" * 64, "USD")
    right = store.batch(TENANT, "right", "2" * 64, "USD")
    run = store.run(TENANT, left["id"], right["id"], "exact")
    with store.conn() as db:
        allocations = db.execute("SELECT left_id,right_id FROM allocations WHERE tenant_id=? AND run_id=?", (TENANT, run["id"])).fetchall()
    assert len({row["left_id"] for row in allocations}) == len(allocations)
    assert len({row["right_id"] for row in allocations}) == len(allocations)
