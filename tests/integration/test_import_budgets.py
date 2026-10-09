import pytest
from datareconcile_ai.infrastructure.store import Store, StoreValidationError, MAX_CSV_BYTES, MAX_IMPORT_ROWS

HEADER = "external_ref,currency,amount_minor,occurred_at\n"


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
