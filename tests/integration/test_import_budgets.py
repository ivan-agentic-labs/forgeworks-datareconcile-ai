import pytest
import hashlib
from datareconcile_ai.infrastructure.store import Store, StoreValidationError, MAX_CSV_BYTES, MAX_IMPORT_ROWS, MAX_INT64, TENANT

HEADER = "external_ref,currency,amount_minor,occurred_at\n"


def test_aggregate_minor_units_remain_exact_beyond_signed64(tmp_path):
    store = Store(str(tmp_path / "exact.db")); store.seed()
    content = HEADER + f"synthetic-a,USD,{MAX_INT64},2026-10-09T00:00:00Z\nsynthetic-b,USD,{MAX_INT64},2026-10-09T00:00:00Z\n"
    digest = hashlib.sha256(content.encode()).hexdigest()
    left = store.batch(TENANT, "left", digest, "USD", csv_content=content)
    right_content = content.replace("synthetic-", "bank-")
    right = store.batch(TENANT, "right", hashlib.sha256(right_content.encode()).hexdigest(), "USD", csv_content=right_content)
    run = store.run(TENANT, left["id"], right["id"], "exact-v1")
    totals = store.totals(TENANT, run["id"])
    assert totals["left_total_minor"] == 2 * MAX_INT64
    assert totals["right_total_minor"] == 2 * MAX_INT64
    assert totals["source_unbalanced_minor"] == 0
    assert totals["allocated_total_minor"] == 2 * MAX_INT64


def test_row_budget_accepts_boundary_and_rejects_overflow():
    rows = [f"synthetic-{index},USD,1,2026-10-09T00:00:00Z\n" for index in range(MAX_IMPORT_ROWS + 1)]
    assert len(Store.parse_csv(HEADER + "".join(rows[:-1]), "USD")) == MAX_IMPORT_ROWS
    with pytest.raises(StoreValidationError) as error:
        Store.parse_csv(HEADER + "".join(rows), "USD")
    assert error.value.code == "CSV_BUDGET_EXCEEDED"


def test_byte_budget_uses_utf8_bytes_not_character_count():
    content = HEADER + "é" * (MAX_CSV_BYTES // 2)
    assert len(content) < MAX_CSV_BYTES
    with pytest.raises(StoreValidationError) as error:
        Store.parse_csv(content, "USD")
    assert error.value.code == "CSV_BUDGET_EXCEEDED"


def test_unbounded_external_reference_is_rejected():
    with pytest.raises(StoreValidationError):
        Store.parse_csv(HEADER + "x" * 257 + ",USD,1,2026-10-09T00:00:00Z\n", "USD")


@pytest.mark.parametrize("control", ["\x00", "\x01", "\t", "\r", "\n", "\x7f"])
def test_quoted_financial_reference_rejects_embedded_control_characters(control):
    # Quoting permits embedded CR/LF in CSV; identifier and audit storage must not.
    raw = HEADER + f'"acct{control}002",USD,1,2026-10-09T00:00:00Z\n'
    with pytest.raises(StoreValidationError) as error:
        Store.parse_csv(raw, "USD")
    assert error.value.code == "CSV_EXTERNAL_REF_INVALID"
