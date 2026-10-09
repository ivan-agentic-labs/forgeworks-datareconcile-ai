import hashlib

import pytest
from fastapi.testclient import TestClient

from datareconcile_ai.infrastructure.store import Store, StoreValidationError, TENANT
from datareconcile_ai.main import create_app
from test_hardening import headers


def test_non_demo_api_rejects_metadata_only_import(tmp_path):
    app = create_app(str(tmp_path / "db.sqlite"), seed=True)
    # Re-open provisioned identity data without enabling the demo fixture mode.
    app = create_app(str(tmp_path / "db.sqlite"))
    with TestClient(app) as client:
        result = client.post("/v1/import-batches", headers=headers("import:create"), json={"source_label":"metadata-only", "artifact_id":"33333333-3333-3333-3333-333333333333", "file_sha256":"a"*64, "currency":"USD", "profile_version":"strict-v1"})
        assert result.status_code == 422
        assert result.json()["code"] == "SOURCE_BYTES_REQUIRED"
    with app.state.store.conn() as db:
        assert db.execute("SELECT count(*) FROM batches").fetchone()[0] == 0


def test_non_demo_store_uses_actual_csv_bytes(tmp_path):
    store = Store(str(tmp_path / "db.sqlite"))
    body = "external_ref,currency,amount_minor,occurred_at\nactual,USD,17,2026-01-01T00:00:00Z\n"
    batch = store.batch(TENANT, "real-source-test", hashlib.sha256(body.encode()).hexdigest(), "USD", csv_content=body)
    assert batch["row_count"] == 1
    with store.conn() as db:
        row = db.execute("SELECT * FROM rows_ WHERE batch_id=?", (batch["id"],)).fetchone()
        assert row["amount_minor"] == 17
        assert row["external_ref"] == "actual"


def test_fixture_mode_cannot_survive_environment_change(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "db.sqlite")); store.seed()
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(StoreValidationError) as error:
        store.batch(TENANT, "left-fixture", "a"*64, "USD")
    assert error.value.code == "SOURCE_BYTES_REQUIRED"
    with pytest.raises(ValueError, match="development/test"):
        store.seed()
