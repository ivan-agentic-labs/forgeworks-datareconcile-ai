"""The strict candidate rule requires a unique reference/date identity."""
import hashlib

import pytest

from datareconcile_ai.infrastructure.store import Store, TENANT


@pytest.fixture(autouse=True)
def enable_candidate_rule_for_tests(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ENABLE_EXACT_REFERENCE_DATE_RULE", "true")


def import_csv(store: Store, label: str, rows: list[str]) -> str:
    content = "external_ref,currency,amount_minor,occurred_at\n" + "".join(rows)
    digest = hashlib.sha256(content.encode()).hexdigest()
    return store.batch(TENANT, label, digest, "USD", csv_content=content)["id"]


def run_records(store: Store, left: str, right: str):
    run = store.run(TENANT, left, right, "exact-reference-date-v1")
    with store.conn() as db:
        allocations = list(db.execute(
            "SELECT * FROM allocations WHERE tenant_id=? AND run_id=?", (TENANT, run["id"]),
        ))
        exceptions = list(db.execute(
            "SELECT * FROM exceptions WHERE tenant_id=? AND run_id=?", (TENANT, run["id"]),
        ))
    return run, allocations, exceptions


def test_normalized_reference_and_equivalent_utc_timestamp_match_once(tmp_path):
    store = Store(str(tmp_path / "exact-identity.sqlite"))
    left = import_csv(store, "left", ["invoice  42,USD,100,2026-10-11T10:00:00+02:00\n"])
    right = import_csv(store, "right", ["INVOICE 42,USD,100,2026-10-11T08:00:00Z\n"])

    run, allocations, exceptions = run_records(store, left, right)

    assert run["unmatched"] == 0
    assert len(allocations) == 1
    assert not exceptions
    assert store.partition_valid(TENANT, run["id"])


def test_different_timestamp_does_not_match_same_reference_and_amount(tmp_path):
    store = Store(str(tmp_path / "different-date.sqlite"))
    left = import_csv(store, "left", ["invoice-42,USD,100,2026-10-11T08:00:00Z\n"])
    right = import_csv(store, "right", ["invoice-42,USD,100,2026-10-12T08:00:00Z\n"])

    run, allocations, exceptions = run_records(store, left, right)

    assert not allocations
    assert run["unmatched"] == 2
    assert {item["reason"] for item in exceptions} == {"MISSING_RIGHT", "MISSING_LEFT"}
    assert store.partition_valid(TENANT, run["id"])


def test_amount_difference_with_unique_reference_date_is_a_review_exception(tmp_path):
    store = Store(str(tmp_path / "amount-mismatch.sqlite"))
    left = import_csv(store, "left", ["invoice-42,USD,100,2026-10-11T08:00:00Z\n"])
    right = import_csv(store, "right", ["INVOICE-42,USD,90,2026-10-11T08:00:00Z\n"])

    run, allocations, exceptions = run_records(store, left, right)

    assert not allocations
    assert run["unmatched"] == 1
    assert exceptions[0]["reason"] == "AMOUNT_MISMATCH"
    assert exceptions[0]["left_id"] and exceptions[0]["right_id"]
    assert store.partition_valid(TENANT, run["id"])


def test_normalized_reference_collision_is_never_auto_allocated(tmp_path):
    store = Store(str(tmp_path / "collision.sqlite"))
    left = import_csv(store, "left", [
        "invoice 42,USD,100,2026-10-11T08:00:00Z\n",
        "INVOICE   42,USD,110,2026-10-11T08:00:00Z\n",
    ])
    right = import_csv(store, "right", ["Invoice 42,USD,100,2026-10-11T08:00:00Z\n"])

    run, allocations, exceptions = run_records(store, left, right)

    assert not allocations
    assert run["unmatched"] == 3
    assert {item["reason"] for item in exceptions} == {"AMBIGUOUS_IDENTITY"}
    assert store.partition_valid(TENANT, run["id"])


def test_source_total_imbalance_blocks_report_even_after_review(tmp_path):
    store = Store(str(tmp_path / "unbalanced.sqlite"))
    left = import_csv(store, "left", ["invoice-42,USD,100,2026-10-11T08:00:00Z\n"])
    right = import_csv(store, "right", ["invoice-42,USD,90,2026-10-11T08:00:00Z\n"])

    run, _, exceptions = run_records(store, left, right)
    assert store.resolve(TENANT, exceptions[0]["id"], "reviewer", "accept-as-investigated", "d" * 64, 1)[1] == "OK"

    _, status = store.finalize(TENANT, run["id"], "c" * 64, run["version"])

    assert status == "CONSERVATION_FAILED"
    assert store.totals(TENANT, run["id"])["source_unbalanced_minor"] == 10
    with store.conn() as db:
        assert db.execute("SELECT COUNT(*) FROM reports WHERE tenant_id=? AND run_id=?", (TENANT, run["id"])).fetchone()[0] == 0


def test_balanced_sources_with_reviewed_nonmatching_rows_can_finalize(tmp_path):
    store = Store(str(tmp_path / "balanced-review.sqlite"))
    left = import_csv(store, "left", ["left-ref,USD,100,2026-10-11T08:00:00Z\n"])
    right = import_csv(store, "right", ["right-ref,USD,100,2026-10-11T08:00:00Z\n"])

    run, _, exceptions = run_records(store, left, right)
    for exception in exceptions:
        assert store.resolve(TENANT, exception["id"], "reviewer", "accept-as-investigated", "d" * 64, 1)[1] == "OK"

    report, status = store.finalize(TENANT, run["id"], "c" * 64, run["version"])

    assert status == "OK"
    assert report["id"]
    assert store.totals(TENANT, run["id"])["source_unbalanced_minor"] == 0


def test_http_finalization_returns_409_for_reviewed_source_imbalance(tmp_path):
    from fastapi.testclient import TestClient

    from datareconcile_ai.main import create_app
    from test_hardening import headers, import_csv

    with TestClient(create_app(str(tmp_path / "api-unbalanced.sqlite"), seed=True)) as client:
        left = import_csv(
            client,
            "external_ref,currency,amount_minor,occurred_at\ninvoice-42,USD,100,2026-10-11T08:00:00Z\n",
            label="left-imbalance",
        )
        right = import_csv(
            client,
            "external_ref,currency,amount_minor,occurred_at\nINVOICE-42,USD,90,2026-10-11T08:00:00Z\n",
            label="right-imbalance",
        )
        assert left.status_code == right.status_code == 202
        response = client.post(
            "/v1/reconciliation-runs",
            headers=headers("reconcile:run"),
            json={
                "left_batch_id": left.json()["id"],
                "right_batch_id": right.json()["id"],
                "rule_version": "exact-reference-date-v1",
            },
        )
        assert response.status_code == 202
        run = response.json()
        exception = client.get(
            f"/v1/reconciliation-runs/{run['id']}/exceptions",
            headers=headers("reconcile:read"),
        ).json()["items"][0]
        resolution = client.post(
            f"/v1/exceptions/{exception['id']}/resolutions",
            headers=headers("exception:approve"),
            json={
                "decision": "accept-as-investigated",
                "evidence_sha256": "d" * 64,
                "expected_version": exception["version"],
            },
        )
        assert resolution.status_code == 201

        finalized = client.post(
            f"/v1/reconciliation-runs/{run['id']}/finalize",
            headers=headers("report:finalize"),
            json={"expected_version": run["version"], "approved_summary_sha256": "c" * 64},
        )

        assert finalized.status_code == 409
        assert finalized.json()["code"] == "CONSERVATION_FAILED"


def test_candidate_rule_is_disabled_in_production_even_if_feature_flag_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_EXACT_REFERENCE_DATE_RULE", "true")
    store = Store(str(tmp_path / "production-gate.sqlite"))
    left = import_csv(store, "left", ["invoice-42,USD,100,2026-10-11T08:00:00Z\n"])
    right = import_csv(store, "right", ["INVOICE-42,USD,100,2026-10-11T08:00:00Z\n"])

    from datareconcile_ai.infrastructure.store import StoreValidationError

    with pytest.raises(StoreValidationError) as exc:
        store.run(TENANT, left, right, "exact-reference-date-v1")
    assert exc.value.code == "RECONCILIATION_RULE_DISABLED"
    with store.conn() as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_candidate_rule_is_disabled_by_default_and_http_returns_typed_error(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from datareconcile_ai.main import create_app
    from test_hardening import headers, import_csv as http_import_csv

    monkeypatch.delenv("ENABLE_EXACT_REFERENCE_DATE_RULE", raising=False)
    with TestClient(create_app(str(tmp_path / "api-disabled.sqlite"), seed=True)) as client:
        left = http_import_csv(
            client,
            "external_ref,currency,amount_minor,occurred_at\ninvoice-42,USD,100,2026-10-11T08:00:00Z\n",
            label="left-disabled",
        )
        right = http_import_csv(
            client,
            "external_ref,currency,amount_minor,occurred_at\nINVOICE-42,USD,100,2026-10-11T08:00:00Z\n",
            label="right-disabled",
        )
        response = client.post(
            "/v1/reconciliation-runs",
            headers=headers("reconcile:run"),
            json={
                "left_batch_id": left.json()["id"],
                "right_batch_id": right.json()["id"],
                "rule_version": "exact-reference-date-v1",
            },
        )
        assert response.status_code == 422
        assert response.json()["code"] == "RECONCILIATION_RULE_DISABLED"
