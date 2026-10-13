"""Accounting policy labels must be implemented; a source never matches itself."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from datareconcile_ai.infrastructure.store import Store, StoreValidationError, TENANT
from datareconcile_ai.main import create_app
from test_hardening import headers, import_csv


@pytest.fixture(autouse=True)
def enable_candidate_rule_for_tests(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ENABLE_EXACT_REFERENCE_DATE_RULE", "true")


def _batch(store, label):
    source = (
        "external_ref,currency,amount_minor,occurred_at\n"
        f"{label}-1,USD,100,2026-10-11T00:00:00Z\n"
    )
    digest = hashlib.sha256(source.encode()).hexdigest()
    return store.batch(TENANT, label, digest, "USD", csv_content=source)["id"]


@pytest.mark.parametrize("rule", ["future-v3", "EXACT-V1", "", "unambiguous-amount-v3", "exact-v1 "])
def test_unknown_financial_rules_cannot_mislabel_legacy_matching(tmp_path, rule):
    store = Store(str(tmp_path / "policy.sqlite"))
    left, right = _batch(store, "left"), _batch(store, "right")
    with pytest.raises(StoreValidationError) as exc:
        store.run(TENANT, left, right, rule)
    assert exc.value.code == "UNSUPPORTED_RECONCILIATION_RULE"
    with store.conn() as db:
        for table in ("runs", "allocations", "exceptions"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("rule", ["exact", "exact-v1", "exact-1to1-v1", "unambiguous-amount-v2", "exact-reference-date-v1"])
def test_self_reconciliation_is_denied_for_every_supported_rule(tmp_path, rule):
    store = Store(str(tmp_path / "self.sqlite"))
    left = _batch(store, "same-import")
    with pytest.raises(StoreValidationError) as exc:
        store.run(TENANT, left, left, rule)
    assert exc.value.code == "IDENTICAL_SOURCE_BATCHES"
    with store.conn() as db:
        for table in ("runs", "allocations", "exceptions"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("rule", ["exact", "exact-v1", "exact-1to1-v1", "unambiguous-amount-v2", "exact-reference-date-v1"])
def test_known_rules_remain_supported_without_changing_their_identity(tmp_path, rule):
    store = Store(str(tmp_path / "supported.sqlite"))
    left, right = _batch(store, "left"), _batch(store, "right")
    run = store.run(TENANT, left, right, rule)
    assert run["rule"] == rule
    with store.conn() as db:
        allocated = db.execute("SELECT COUNT(*) FROM allocations WHERE tenant_id=? AND run_id=?", (TENANT, run["id"])).fetchone()[0]
    assert allocated == (0 if rule == "exact-reference-date-v1" else 1)


def test_http_denies_unknown_rule_and_same_import_without_new_runs(tmp_path):
    with TestClient(create_app(str(tmp_path / "http.sqlite"), seed=True)) as client:
        source1 = "external_ref,currency,amount_minor,occurred_at\nleft-1,USD,100,2026-10-11T00:00:00Z\n"
        source2 = "external_ref,currency,amount_minor,occurred_at\nright-1,USD,100,2026-10-11T00:00:00Z\n"
        a = import_csv(client, source1, label="left")
        b = import_csv(client, source2, label="right")
        assert a.status_code == 202 and b.status_code == 202, (a.text, b.text)
        identifier_a, identifier_b = a.json()["id"], b.json()["id"]
        endpoint = "/v1/reconciliation-runs"
        rejects = [
            (identifier_a, identifier_b, "unknown-version", "UNSUPPORTED_RECONCILIATION_RULE"),
            (identifier_a, identifier_a, "exact-v1", "IDENTICAL_SOURCE_BATCHES"),
        ]
        for left, right, rule, code in rejects:
            result = client.post(endpoint, headers=headers("reconcile:run"), json={
                "left_batch_id": left, "right_batch_id": right, "rule_version": rule,
            })
            assert result.status_code == 422, result.text
            assert result.json()["code"] == code
        with client.app.state.store.conn() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
