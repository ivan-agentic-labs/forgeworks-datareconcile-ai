from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from datareconcile_ai.main import create_app
from datareconcile_ai.infrastructure.store import TENANT, USER

S = "forgeworks-development-secret-32-plus"
ISS = "https://issuer.synthetic.invalid"
AUD = "forgeworks-api"


def h(scope, tenant=TENANT):
    token = jwt.encode(
        {
            "sub": USER,
            "tenant_id": tenant,
            "scope": scope,
            "iss": ISS,
            "aud": AUD,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        S,
        algorithm="HS256",
    )
    return {"Authorization": "Bearer " + token}


def test_match_exception_resolve_finalize(tmp_path):
    app = create_app(str(tmp_path / "db.sqlite"), seed=True)
    with TestClient(app) as client:
        common = {
            "artifact_id": "33333333-3333-3333-3333-333333333333",
            "currency": "USD",
            "profile_version": "strict-v1",
        }
        left = client.post("/v1/import-batches", headers=h("import:create"), json={
            **common, "source_label": "left-fixture", "file_sha256": "a" * 64,
        })
        right = client.post("/v1/import-batches", headers=h("import:create"), json={
            **common, "source_label": "right-fixture", "file_sha256": "b" * 64,
        })
        assert left.status_code == right.status_code == 202
        left_id, right_id = left.json()["id"], right.json()["id"]
        rows = client.get(f"/v1/import-batches/{left_id}/rows", headers=h("import:read")).json()["items"]
        assert all(isinstance(row["amount_minor"], int) for row in rows)

        response = client.post(
            "/v1/reconciliation-runs",
            headers=h("reconcile:run"),
            json={"left_batch_id": left_id, "right_batch_id": right_id, "rule_version": "exact-1to1-v1"},
        )
        assert response.status_code == 202
        run = response.json()
        assert run["unmatched_count"] == 2
        exceptions = client.get(
            f"/v1/reconciliation-runs/{run['id']}/exceptions", headers=h("reconcile:read"),
        ).json()["items"]
        blocked = client.post(
            f"/v1/reconciliation-runs/{run['id']}/finalize",
            headers=h("report:finalize"),
            json={"expected_version": 1, "approved_summary_sha256": "c" * 64},
        )
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "OPEN_EXCEPTIONS"
        for exception in exceptions:
            result = client.post(
                f"/v1/exceptions/{exception['id']}/resolutions",
                headers=h("exception:approve"),
                json={
                    "decision": "accept-as-investigated",
                    "evidence_sha256": "d" * 64,
                    "expected_version": exception["version"],
                },
            )
            assert result.status_code == 201

        report = client.post(
            f"/v1/reconciliation-runs/{run['id']}/finalize",
            headers=h("report:finalize"),
            json={"expected_version": 1, "approved_summary_sha256": "c" * 64},
        )
        assert report.status_code == 201
        assert report.json()["totals"]["source_unbalanced_minor"] == 0
        assert client.get(f"/v1/reports/{report.json()['id']}/download", headers=h("report:read")).status_code == 200
        job = client.get(f"/v1/jobs/{run['job_id']}", headers=h("job:read"))
        assert job.status_code == 200
        import yaml
        import jsonschema
        from pathlib import Path

        contract = yaml.safe_load((Path(__file__).resolve().parents[2] / "contracts/openapi.yaml").read_text())
        jsonschema.Draft202012Validator({**contract, "$ref": "#/components/schemas/JobStatus"}).validate(job.json())
        assert job.json()["state"] == "SUCCEEDED"
        duplicate = client.post("/v1/import-batches", headers=h("import:create"), json={
            **common, "source_label": "left-fixture", "file_sha256": "a" * 64,
        })
        assert duplicate.status_code == 409


def test_cross_currency_and_auth_fail_closed(tmp_path):
    app = create_app(str(tmp_path / "db.sqlite"), seed=True)
    with TestClient(app) as client:
        common = {
            "artifact_id": "33333333-3333-3333-3333-333333333333",
            "source_label": "left-fixture",
            "file_sha256": "e" * 64,
            "profile_version": "strict-v1",
        }
        left = client.post("/v1/import-batches", headers=h("import:create"), json={**common, "currency": "USD"}).json()
        right = client.post("/v1/import-batches", headers=h("import:create"), json={
            **common, "currency": "EUR", "file_sha256": "f" * 64,
        }).json()
        rejected = client.post(
            "/v1/reconciliation-runs", headers=h("reconcile:run"),
            json={"left_batch_id": left["id"], "right_batch_id": right["id"], "rule_version": "exact"},
        )
        assert rejected.status_code == 409
        unauthorized = client.post(
            "/v1/import-batches", headers=h("report:read"),
            json={**common, "currency": "USD", "file_sha256": "1" * 64},
        )
        assert unauthorized.status_code == 403
