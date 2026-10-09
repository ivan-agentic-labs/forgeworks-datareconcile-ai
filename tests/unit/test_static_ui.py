from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_static_console_covers_reconciliation_lifecycle_and_safety_copy():
    html = (ROOT / "apps/web/index.html").read_text()
    js = (ROOT / "apps/web/app.js").read_text()
    required_paths = [
        "/v1/import-batches",
        "/v1/import-batches/${state.batches[side].id}/rows",
        "/v1/reconciliation-runs",
        "/v1/reconciliation-runs/${state.run.id}/exceptions",
        "/v1/exceptions/${$('exceptionId').value}/resolutions",
        "/v1/reconciliation-runs/${state.run.id}/finalize",
        "/v1/reports/${state.report.id}/download",
    ]
    assert all(path in js for path in required_paths)
    assert "integer minor units" in html
    assert "No-transfer boundary" in html
    assert "STALE_VERSION" in js
    assert "conservation" in html.lower()


def test_static_console_preserves_large_integer_precision_and_uses_safe_dom_writes():
    js = (ROOT / "apps/web/app.js").read_text()
    assert "BigInt(String(value))" in js
    assert "sum + BigInt(String(row.amount_minor))" in js
    assert "innerHTML" not in js
    assert "textContent" in js
