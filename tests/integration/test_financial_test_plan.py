"""Deterministic synthetic coverage for the local financial verification plan."""

import hashlib

import pytest

from datareconcile_ai.infrastructure.store import (
    MAX_INT64,
    Store,
    StoreValidationError,
    TENANT,
)


HEADER = "external_ref,currency,amount_minor,occurred_at\n"


def import_csv(store: Store, label: str, content: str, currency: str = "USD"):
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return store.batch(TENANT, label, digest, currency, csv_content=content)


def test_fin_t01_locale_ambiguous_amount_is_quarantined_without_guess(tmp_path):
    store = Store(str(tmp_path / "fin-t01.sqlite"))
    # A quoted comma makes this a valid CSV field; it is still not a canonical
    # integer minor-unit representation and must not be interpreted as 1234.
    content = HEADER + 'invoice-ambiguous,USD,"1,234",2026-10-11T00:00:00Z\n'

    with pytest.raises(StoreValidationError) as error:
        import_csv(store, "locale-ambiguous", content)

    assert error.value.code == "CSV_AMOUNT_INVALID"
    with store.conn() as db:
        assert db.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM rows_").fetchone()[0] == 0


def test_fin_t03_cross_batch_duplicate_reference_preserves_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ENABLE_EXACT_REFERENCE_DATE_RULE", "true")
    store = Store(str(tmp_path / "fin-t03.sqlite"))
    left = import_csv(
        store,
        "left-duplicate-reference",
        HEADER
        + "invoice-100,USD,100,2026-10-11T00:00:00Z\n"
        + "invoice-200,USD,200,2026-10-11T00:00:00Z\n",
    )
    right = import_csv(
        store,
        "right-duplicate-reference",
        HEADER
        + "INVOICE-200,USD,200,2026-10-11T00:00:00Z\n"
        + "INVOICE-100,USD,100,2026-10-11T00:00:00Z\n",
    )

    run = store.run(TENANT, left["id"], right["id"], "exact-reference-date-v1")
    with store.conn() as db:
        allocations = db.execute(
            "SELECT left_id, right_id, matched_amount_minor FROM allocations "
            "WHERE tenant_id=? AND run_id=? ORDER BY matched_amount_minor",
            (TENANT, run["id"]),
        ).fetchall()
        exceptions = db.execute(
            "SELECT COUNT(*) FROM exceptions WHERE tenant_id=? AND run_id=?",
            (TENANT, run["id"]),
        ).fetchone()[0]

    left_rows = {row["id"]: row["external_ref"] for row in store.rows(TENANT, left["id"])}
    right_rows = {row["id"]: row["external_ref"] for row in store.rows(TENANT, right["id"])}
    assert run["unmatched"] == 0 and exceptions == 0
    assert len(allocations) == 2
    assert len({row["left_id"] for row in allocations}) == 2
    assert len({row["right_id"] for row in allocations}) == 2
    assert {(left_rows[row["left_id"]].upper(), right_rows[row["right_id"]].upper()) for row in allocations} == {
        ("INVOICE-100", "INVOICE-100"),
        ("INVOICE-200", "INVOICE-200"),
    }
    assert store.partition_valid(TENANT, run["id"])


def test_fin_t04_int64_rows_and_aggregate_totals_remain_exact(tmp_path):
    store = Store(str(tmp_path / "fin-t04.sqlite"))
    content = (
        HEADER
        + f"max-a,USD,{MAX_INT64},2026-10-11T00:00:00Z\n"
        + f"max-b,USD,{MAX_INT64},2026-10-11T00:00:00Z\n"
    )
    left = import_csv(store, "left-int64", content)
    right = import_csv(store, "right-int64", content.replace("max-a", "copy-a").replace("max-b", "copy-b"))

    run = store.run(TENANT, left["id"], right["id"], "exact-v1")
    totals = store.totals(TENANT, run["id"])
    expected = MAX_INT64 * 2

    assert totals["left_total_minor"] == expected
    assert totals["right_total_minor"] == expected
    assert totals["allocated_total_minor"] == expected
    assert totals["source_unbalanced_minor"] == 0
    assert totals["conservation_discrepancy_minor"] == 0
    assert all(isinstance(totals[key], int) for key in (
        "left_total_minor", "right_total_minor", "allocated_total_minor",
    ))
    _, status = store.finalize(TENANT, run["id"], "a" * 64, run["version"])
    assert status == "OK"
