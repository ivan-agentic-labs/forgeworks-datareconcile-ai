from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi.testclient import TestClient

from datareconcile_ai.infrastructure.store import TENANT, USER
from datareconcile_ai.main import create_app

SECRET = "forgeworks-development-secret-32-plus"
ISSUER = "https://issuer.synthetic.invalid"
AUDIENCE = "forgeworks-api"
ROOT = Path(__file__).resolve().parents[2]


def headers(scope: str, *, idempotency_key: str | None = None) -> dict[str, str]:
    token = jwt.encode(
        {
            "sub": USER,
            "tenant_id": TENANT,
            "scope": scope,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )
    result = {"Authorization": f"Bearer {token}"}
    if idempotency_key:
        result["Idempotency-Key"] = idempotency_key
    return result


def import_body(label: str, digest: str) -> dict[str, str]:
    return {
        "artifact_id": "33333333-3333-3333-3333-333333333333",
        "currency": "USD",
        "profile_version": "strict-v1",
        "source_label": label,
        "file_sha256": digest,
    }


def test_fastapi_and_static_ui_import_rows_reconcile_resolve_finalize_report(tmp_path):
    app = create_app(str(tmp_path / "e2e.db"), seed=True)
    with TestClient(app) as client:
        left_response = client.post(
            "/v1/import-batches",
            headers=headers("import:create", idempotency_key="e2e-import-left-0001"),
            json=import_body("left-fixture", "a" * 64),
        )
        right_response = client.post(
            "/v1/import-batches",
            headers=headers("import:create", idempotency_key="e2e-import-right-0001"),
            json=import_body("right-fixture", "b" * 64),
        )
        assert left_response.status_code == right_response.status_code == 202
        left, right = left_response.json(), right_response.json()
        assert left["row_count"] == right["row_count"] == 3

        duplicate_import = client.post(
            "/v1/import-batches",
            headers=headers("import:create", idempotency_key="e2e-import-left-retry"),
            json=import_body("left-fixture", "a" * 64),
        )
        assert duplicate_import.status_code == 409
        assert duplicate_import.json()["code"] == "DUPLICATE_IMPORT"

        row_pages = {
            side: client.get(
                f"/v1/import-batches/{batch['id']}/rows",
                headers=headers("import:read"),
            )
            for side, batch in (("left", left), ("right", right))
        }
        assert all(page.status_code == 200 for page in row_pages.values())
        rows = {side: page.json()["items"] for side, page in row_pages.items()}
        assert all(isinstance(row["amount_minor"], int) for side in rows.values() for row in side)
        assert sum(row["amount_minor"] for row in rows["left"]) == 600
        assert sum(row["amount_minor"] for row in rows["right"]) == 600

        reconcile_body = {
            "left_batch_id": left["id"],
            "right_batch_id": right["id"],
            "rule_version": "exact-1to1-v1",
        }
        first_run = client.post(
            "/v1/reconciliation-runs",
            headers=headers("reconcile:run", idempotency_key="e2e-reconcile-0001"),
            json=reconcile_body,
        )
        retry_run = client.post(
            "/v1/reconciliation-runs",
            headers=headers("reconcile:run", idempotency_key="e2e-reconcile-retry"),
            json=reconcile_body,
        )
        assert first_run.status_code == retry_run.status_code == 202
        run = first_run.json()
        assert retry_run.json()["id"] == run["id"]
        replay_run = client.post(
            "/v1/reconciliation-runs",
            headers=headers("reconcile:run", idempotency_key="e2e-reconcile-0001"),
            json=reconcile_body,
        )
        assert replay_run.status_code == 202
        assert replay_run.json() == run
        conflict_run = client.post(
            "/v1/reconciliation-runs",
            headers=headers("reconcile:run", idempotency_key="e2e-reconcile-0001"),
            json={**reconcile_body, "rule_version": "unambiguous-amount-v2"},
        )
        assert conflict_run.status_code == 409
        assert conflict_run.json()["code"] == "IDEMPOTENCY_CONFLICT"
        assert run["unmatched_count"] == 2

        exception_page = client.get(
            f"/v1/reconciliation-runs/{run['id']}/exceptions",
            headers=headers("reconcile:read"),
        )
        assert exception_page.status_code == 200
        exceptions = exception_page.json()["items"]
        assert len(exceptions) == 2
        exception = exceptions[0]
        assert exception["status"] == "OPEN"

        blocked = client.post(
            f"/v1/reconciliation-runs/{run['id']}/finalize",
            headers=headers("report:finalize", idempotency_key="e2e-finalize-blocked"),
            json={"expected_version": 1, "approved_summary_sha256": "c" * 64},
        )
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "OPEN_EXCEPTIONS"

        stale = client.post(
            f"/v1/exceptions/{exception['id']}/resolutions",
            headers=headers("exception:approve", idempotency_key="e2e-resolution-stale"),
            json={
                "decision": "accept-as-investigated",
                "evidence_sha256": "d" * 64,
                "expected_version": exception["version"] + 1,
            },
        )
        assert stale.status_code == 409
        assert stale.json()["code"] == "STALE_VERSION"

        resolution = client.post(
            f"/v1/exceptions/{exception['id']}/resolutions",
            headers=headers("exception:approve", idempotency_key="e2e-resolution-0001"),
            json={
                "decision": "accept-as-investigated",
                "evidence_sha256": "d" * 64,
                "expected_version": exception["version"],
            },
        )
        assert resolution.status_code == 201
        for remaining in exceptions[1:]:
            resolved = client.post(
                f"/v1/exceptions/{remaining['id']}/resolutions",
                headers=headers("exception:approve", idempotency_key="e2e-resolution-0002"),
                json={
                    "decision": "accept-as-investigated",
                    "evidence_sha256": "d" * 64,
                    "expected_version": remaining["version"],
                },
            )
            assert resolved.status_code == 201
        stale_after_resolution = client.post(
            f"/v1/exceptions/{exception['id']}/resolutions",
            headers=headers("exception:approve", idempotency_key="e2e-resolution-retry"),
            json={
                "decision": "accept-as-investigated",
                "evidence_sha256": "d" * 64,
                "expected_version": exception["version"],
            },
        )
        assert stale_after_resolution.status_code == 409

        report_response = client.post(
            f"/v1/reconciliation-runs/{run['id']}/finalize",
            headers=headers("report:finalize", idempotency_key="e2e-finalize-0001"),
            json={"expected_version": 1, "approved_summary_sha256": "c" * 64},
        )
        assert report_response.status_code == 201
        report = report_response.json()
        totals = report["totals"]
        for key in (
            "left_total_minor",
            "right_total_minor",
            "allocated_total_minor",
            "allocated_left_total_minor",
            "allocated_right_total_minor",
            "conservation_discrepancy_minor",
        ):
            assert isinstance(totals[key], int)
        assert totals["left_total_minor"] == totals["right_total_minor"] == 600
        assert totals["allocated_total_minor"] == 100
        assert totals["allocated_left_total_minor"] == totals["allocated_right_total_minor"] == 100
        assert totals["source_unbalanced_minor"] == 0
        assert totals["conservation_discrepancy_minor"] == 0

        download = client.get(
            f"/v1/reports/{report['id']}/download",
            headers=headers("report:read"),
        )
        assert download.status_code == 200
        assert download.json()["totals"] == totals
        assert download.json()["source_revision"] == report["source_revision"]
        transferred = client.get(download.json()["download_url"])
        assert transferred.status_code == 200
        import hashlib
        assert hashlib.sha256(transferred.content).hexdigest() == report["artifact_sha256"]
        assert transferred.json()["totals"] == totals
        # A previously issued capability must not survive membership revocation.
        with client.app.state.store.conn() as db:
            db.execute("UPDATE memberships SET status='REVOKED' WHERE tenant_id=? AND user_id=?", (TENANT, USER))
        revoked_transfer = client.get(download.json()["download_url"])
        assert revoked_transfer.status_code == 403
        with client.app.state.store.conn() as db:
            db.execute("UPDATE memberships SET status='ACTIVE' WHERE tenant_id=? AND user_id=?", (TENANT, USER))
        assert client.get(download.json()["download_url"].replace(report["id"], "00000000-0000-0000-0000-000000000999")).status_code == 403
        assert client.get(download.json()["download_url"] + "tampered").status_code == 403
        with client.app.state.store.conn() as db:
            original = db.execute("SELECT content_json FROM reports WHERE id=?", (report["id"],)).fetchone()[0]
            db.execute("UPDATE reports SET content_json=? WHERE id=?", ('{}', report["id"]))
        assert client.get(download.json()["download_url"]).status_code == 409
        with client.app.state.store.conn() as db:
            db.execute("UPDATE reports SET content_json=? WHERE id=?", (original, report["id"]))


        # Finalization is immutable: retries return the original report and do
        # not permit changing the approved summary or ledger artifact.
        retry_report = client.post(
            f"/v1/reconciliation-runs/{run['id']}/finalize",
            headers=headers("report:finalize", idempotency_key="e2e-finalize-retry"),
            json={"expected_version": 1, "approved_summary_sha256": "e" * 64},
        )
        assert retry_report.status_code == 201
        assert retry_report.json() == report


def test_static_console_exposes_the_same_flow_and_no_transfer_boundary():
    html = (ROOT / "apps/web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "apps/web/app.js").read_text(encoding="utf-8")
    paths = [
        "/v1/import-batches",
        "/v1/import-batches/${state.batches[side].id}/rows",
        "/v1/reconciliation-runs",
        "/v1/reconciliation-runs/${state.run.id}/exceptions",
        "/v1/exceptions/${$('exceptionId').value}/resolutions",
        "/v1/reconciliation-runs/${state.run.id}/finalize",
        "/v1/reports/${state.report.id}/download",
    ]
    positions = [js.index(path) for path in paths]
    assert positions == sorted(positions)
    assert "integer minor units" in html
    assert "conservation" in html.lower()
    assert "STALE_VERSION" in js
    assert "No-transfer boundary" in html
    assert "/v1/transfers" not in html + js
    assert "financial transfer" in html
