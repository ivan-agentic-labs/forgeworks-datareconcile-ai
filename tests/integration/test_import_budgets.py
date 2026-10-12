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


@pytest.mark.parametrize("invisible", [
    "\\u200b", "\\u200d", "\\u202e", "\\u2066", "\\u2028", "\\u2029", "\\ufeff",
])
def test_financial_reference_rejects_invisible_unicode_and_bidi_format_controls(invisible):
    character = invisible.encode("ascii").decode("unicode_escape")
    source = HEADER + f'"invoice{character}002",USD,1,2026-10-09T00:00:00Z\\n'.replace('\\n', '\n')
    with pytest.raises(StoreValidationError) as error:
        Store.parse_csv(source, "USD")
    assert error.value.code == "CSV_EXTERNAL_REF_INVALID"


def test_visible_utf8_reference_remains_lossless():
    records = Store.parse_csv(HEADER + "café-2026,USD,1,2026-10-09T00:00:00Z\n", "USD")
    assert records[0]["external_ref"] == "café-2026"


@pytest.mark.parametrize("timestamp", [
    "2026-10-09 00:00:00Z",
    "2026-10-09X00:00:00Z",
    "2026-10-09T00:00Z",
    "20261009T000000Z",
    "2026-10-09T00:00:00.1234567Z",
    "2026-10-09T00:00:00",
    "2026-10-09T00:00:00+07:00junk",
])
def test_ambiguous_or_precision_truncated_financial_timestamps_fail(timestamp):
    with pytest.raises(StoreValidationError) as error:
        Store.parse_csv(HEADER + f"synthetic-a,USD,1,{timestamp}\n", "USD")
    assert error.value.code == "CSV_TIMESTAMP_INVALID"


@pytest.mark.parametrize("timestamp,expected", [
    ("2026-10-09T00:00:00Z", "2026-10-09T00:00:00Z"),
    ("2026-10-09T07:00:00+07:00", "2026-10-09T00:00:00Z"),
    ("2026-10-09T00:00:00.123456Z", "2026-10-09T00:00:00.123456Z"),
])
def test_explicit_rfc3339_financial_timestamp_preserves_utc_value(timestamp, expected):
    rows = Store.parse_csv(HEADER + f"synthetic-a,USD,1,{timestamp}\n", "USD")
    assert rows[0]["occurred_at"] == expected


def test_rfc3339_unknown_timezone_offset_does_not_claim_known_utc():
    source = HEADER + "unknown-zone,USD,100,2026-10-09T00:00:00-00:00\n"
    with pytest.raises(StoreValidationError) as error:
        Store.parse_csv(source, "USD")
    assert error.value.code == "CSV_TIMESTAMP_INVALID"


def test_explicit_known_utc_offsets_remain_supported():
    source = HEADER + "known-utc,USD,100,2026-10-09T00:00:00+00:00\n"
    result = Store.parse_csv(source, "USD")
    assert result[0]["occurred_at"] == "2026-10-09T00:00:00Z"
