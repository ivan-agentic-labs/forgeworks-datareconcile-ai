from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from datareconcile_ai.infrastructure.store import Store, StoreValidationError, TENANT, USER
from datareconcile_worker import RetryableJobError, WorkerJobRunner


def seeded_store(tmp_path: Path) -> Store:
    store = Store(str(tmp_path / "reliability.db"))
    store.seed()
    return store


def imported_pair(store: Store):
    left = store.batch(TENANT, "left-fixture", "a" * 64, "USD")
    right = store.batch(TENANT, "right-fixture", "b" * 64, "USD")
    return left, right


def test_duplicate_import_is_single_business_effect_under_concurrency(tmp_path):
    store = seeded_store(tmp_path)

    def import_once():
        try:
            row = store.batch(TENANT, "same-fixture", "a" * 64, "USD")
            return "accepted", row["id"]
        except StoreValidationError as exc:
            return exc.code, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: import_once(), range(4)))
    accepted = [value for value in results if value[0] == "accepted"]
    rejected = [value for value in results if value[0] == "DUPLICATE_IMPORT"]
    assert len(accepted) == 1
    assert len(rejected) == 3
    with store.conn() as db:
        assert db.execute("SELECT COUNT(*) FROM batches WHERE tenant_id=?", (TENANT,)).fetchone()[0] == 1


def test_duplicate_reconcile_is_idempotent_and_matching_is_deterministic(tmp_path):
    store = seeded_store(tmp_path)
    left, right = imported_pair(store)
    first = store.run(TENANT, left["id"], right["id"], "exact-1to1-v1")
    second = store.run(TENANT, left["id"], right["id"], "exact-1to1-v1")
    assert first["id"] == second["id"]
    assert first["source_revision"] == second["source_revision"]
    with store.conn() as db:
        allocations = db.execute(
            "SELECT left_id,right_id,matched_amount_minor FROM allocations WHERE tenant_id=? AND run_id=?",
            (TENANT, first["id"]),
        ).fetchall()
        assert len(allocations) == 2
        assert sum(row["matched_amount_minor"] for row in allocations) == 400
        assert len({row["left_id"] for row in allocations}) == len(allocations)
        assert len({row["right_id"] for row in allocations}) == len(allocations)


def test_worker_retry_survives_restart_and_terminal_failures_are_not_replayed(tmp_path):
    jobs = str(tmp_path / "jobs.db")
    first = WorkerJobRunner(jobs, max_attempts=3)
    retry = first.run("reconcile:retry-key", lambda: (_ for _ in ()).throw(RetryableJobError("DB_TIMEOUT")))
    assert retry.state == "FAILED_RETRYABLE"
    assert retry.attempt_count == 1

    restarted = WorkerJobRunner(jobs, max_attempts=3)
    successful_calls = []
    succeeded = restarted.run("reconcile:retry-key", lambda: successful_calls.append(True) or {"run": "same"})
    assert succeeded.state == "SUCCEEDED"
    assert succeeded.attempt_count == 2
    assert succeeded.value == {"run": "same"}
    assert successful_calls == [True]
    assert restarted.run("reconcile:retry-key", lambda: successful_calls.append(False)).value == {"run": "same"}
    assert successful_calls == [True]

    terminal_calls = []
    terminal = restarted.run(
        "reconcile:terminal-key",
        lambda: terminal_calls.append(True) or (_ for _ in ()).throw(ValueError("invalid fixture")),
    )
    assert terminal.state == "FAILED_TERMINAL"
    assert terminal.last_error_code == "ValueError"
    assert restarted.run("reconcile:terminal-key", lambda: terminal_calls.append(False)).state == "FAILED_TERMINAL"
    assert terminal_calls == [True]


def test_worker_restart_recovers_an_abandoned_running_lease(tmp_path):
    jobs = str(tmp_path / "restart.db")
    runner = WorkerJobRunner(jobs, max_attempts=2)

    class SimulatedProcessCrash(BaseException):
        pass

    with pytest.raises(SimulatedProcessCrash):
        runner.run("import:crash-key", lambda: (_ for _ in ()).throw(SimulatedProcessCrash()))
    assert runner.status("import:crash-key").state == "RUNNING"

    restarted = WorkerJobRunner(jobs, max_attempts=2)
    assert restarted.recover_running() == 1
    done = restarted.run("import:crash-key", lambda: {"accepted_rows": 3})
    assert done.state == "SUCCEEDED"
    assert done.attempt_count == 2


def test_concurrent_reconcile_allocations_are_unique(tmp_path):
    store = seeded_store(tmp_path)
    left, right = imported_pair(store)

    def reconcile_once():
        return store.run(TENANT, left["id"], right["id"], "exact-1to1-v1")["id"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        run_ids = list(pool.map(lambda _: reconcile_once(), range(6)))
    assert len(set(run_ids)) == 1
    with store.conn() as db:
        run_id = run_ids[0]
        allocations = db.execute(
            "SELECT left_id,right_id FROM allocations WHERE tenant_id=? AND run_id=?",
            (TENANT, run_id),
        ).fetchall()
        assert len(allocations) == 2
        assert len({row["left_id"] for row in allocations}) == 2
        assert len({row["right_id"] for row in allocations}) == 2


def test_stale_resolution_conflict_allows_one_winner(tmp_path):
    store = seeded_store(tmp_path)
    left, right = imported_pair(store)
    run = store.run(TENANT, left["id"], right["id"], "exact-1to1-v1")
    exception = store.exceptions(TENANT, run["id"])[0]

    def resolve_once():
        return store.resolve(
            TENANT,
            exception["id"],
            USER,
            "accept-as-investigated",
            "d" * 64,
            1,
        )[1]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _: resolve_once(), range(2)))
    assert statuses == ["OK", "STALE"]
    assert store.exception(TENANT, exception["id"])["status"] == "RESOLVED"


def test_finalized_report_is_immutable_and_conserves_allocated_minor_units(tmp_path):
    store = seeded_store(tmp_path)
    left, right = imported_pair(store)
    run = store.run(TENANT, left["id"], right["id"], "exact-1to1-v1")
    exception = store.exceptions(TENANT, run["id"])[0]
    assert store.resolve(TENANT, exception["id"], USER, "accept-as-investigated", "d" * 64, 1)[1] == "OK"

    report, status = store.finalize(TENANT, run["id"], "c" * 64, 1)
    assert status == "OK"
    totals = store.totals(TENANT, run["id"])
    assert totals["allocated_left_total_minor"] == totals["allocated_right_total_minor"] == 400
    assert totals["conservation_discrepancy_minor"] == 0

    same_report, retry_status = store.finalize(TENANT, run["id"], "e" * 64, 1)
    assert retry_status == "ALREADY_FINALIZED"
    assert same_report["id"] == report["id"]
    assert same_report["ledger_sha"] == report["ledger_sha"]
    assert same_report["artifact_sha"] == report["artifact_sha"]
    assert same_report["approved_summary_sha"] == "c" * 64
    with store.conn() as db:
        assert db.execute("SELECT COUNT(*) FROM reports WHERE tenant_id=? AND run_id=?", (TENANT, run["id"])).fetchone()[0] == 1


@pytest.mark.parametrize(
    "payload",
    [object(), {"score": float("nan")}, {"payload": "x" * (1024 * 1024)}],
    ids=["unsupported-object", "nonfinite-number", "oversized-result"],
)
def test_worker_rejects_invalid_result_instead_of_forging_success(tmp_path, payload):
    runner = WorkerJobRunner(str(tmp_path / "invalid-result.db"))
    key = "reconcile:invalid-result"
    invalid = runner.run(key, lambda: payload)
    assert invalid.state == "FAILED_TERMINAL"
    assert invalid.last_error_code == "RESULT_SERIALIZATION_INVALID"
    assert invalid.value is None and invalid.attempt_count == 1
    assert runner.run(key, lambda: {"unexpected": True}) == invalid


def test_worker_preserves_valid_json_shape(tmp_path):
    runner = WorkerJobRunner(str(tmp_path / "valid-result.db"))
    value = {"matched": [1, 2], "conservation_ok": True}
    result = runner.run("reconcile:valid", lambda: value)
    assert result.state == "SUCCEEDED"
    assert result.value == value
