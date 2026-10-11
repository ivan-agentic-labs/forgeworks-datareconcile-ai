"""Deterministic multi-runner lease recovery; no timing sleeps."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import json
import multiprocessing
import os
import sqlite3

import pytest

from datareconcile_worker import RetryableJobError, WorkerJobRunner
from datareconcile_ai.infrastructure.store import Store, TENANT


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def test_recovery_does_not_reclaim_live_work(tmp_path):
    runner = WorkerJobRunner(str(tmp_path / 'jobs.db'))
    started, release = Event(), Event()
    def operation():
        started.set()
        assert release.wait(5)
        return {'owner': 'original'}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(runner.run, 'active', operation)
        try:
            assert started.wait(5)
            recovered = runner.recover_running()
            calls = []
            duplicate = runner.run('active', lambda: calls.append(True))
        finally:
            release.set()
        completed = pending.result(timeout=5)
    assert recovered == 0
    assert calls == [] and duplicate.state == 'RUNNING'
    assert completed.value == {'owner': 'original'}


@pytest.mark.parametrize('outcome', ['success', 'retryable', 'terminal', 'invalid-result'])
@pytest.mark.parametrize('replacement_finished', [False, True])
def test_expired_attempt_cannot_overwrite_replacement(tmp_path, outcome, replacement_finished):
    clock = Clock()
    path = str(tmp_path / 'jobs.db')
    original = WorkerJobRunner(path, lease_seconds=10, clock=clock)
    replacement = WorkerJobRunner(path, lease_seconds=10, clock=clock)
    old_started, old_release, new_started, new_release = (Event() for _ in range(4))
    def old_operation():
        old_started.set()
        assert old_release.wait(5)
        if outcome == 'retryable':
            raise RetryableJobError('OLD_TIMEOUT')
        if outcome == 'terminal':
            raise ValueError('old failure')
        return object() if outcome == 'invalid-result' else {'owner': 'old'}
    def new_operation():
        new_started.set()
        assert new_release.wait(5)
        return {'owner': 'replacement'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(original.run, 'shared', old_operation)
        try:
            assert old_started.wait(5)
            clock.now += 10
            assert replacement.recover_running() == 1
            new = pool.submit(replacement.run, 'shared', new_operation)
            assert new_started.wait(5)
            if replacement_finished:
                new_release.set()
                assert new.result(timeout=5).state == 'SUCCEEDED'
            old_release.set()
            stale = old.result(timeout=5)
            assert stale.state == ('SUCCEEDED' if replacement_finished else 'RUNNING')
            assert stale.attempt_count == 2 and stale.last_error_code is None
            assert stale.value == ({'owner': 'replacement'} if replacement_finished else None)
        finally:
            old_release.set()
            new_release.set()
        result = new.result(timeout=5)
    assert result.state == 'SUCCEEDED' and result.value == {'owner': 'replacement'}
    assert result.attempt_count == 2


def test_expired_result_requires_recovery_and_respects_attempt_limit(tmp_path):
    clock = Clock()
    runner = WorkerJobRunner(str(tmp_path / 'jobs.db'), max_attempts=1, lease_seconds=10, clock=clock)
    def expires():
        clock.now += 10
        return {'expired': True}
    assert runner.run('last-attempt', expires).state == 'RUNNING'
    assert runner.recover_running() == 1
    result = runner.run('last-attempt', lambda: pytest.fail('retry exceeded budget'))
    assert result.state == 'FAILED_TERMINAL' and result.attempt_count == 1
    assert result.value is None
    assert runner.recover_running() == 0


def test_legacy_database_upgrade_preserves_success_and_recovers_unfenced_work(tmp_path):
    path = str(tmp_path / 'legacy.db')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE worker_jobs(job_key TEXT PRIMARY KEY,state TEXT NOT NULL,attempt_count INTEGER NOT NULL,last_error_code TEXT,result_json TEXT)')
        db.executemany('INSERT INTO worker_jobs VALUES(?,?,?,?,?)', [('done', 'SUCCEEDED', 1, None, json.dumps({'saved': 1})), ('orphan', 'RUNNING', 1, None, None)])
    runner = WorkerJobRunner(path, lease_seconds=10, clock=Clock())
    WorkerJobRunner(path, lease_seconds=10, clock=Clock())
    assert runner.status('done').value == {'saved': 1}
    assert runner.recover_running() == 1
    assert runner.run('orphan', lambda: {'recovered': True}).attempt_count == 2


@pytest.mark.parametrize('lease', [0, -1, float('nan'), float('inf'), True, '10'])
def test_invalid_lease_budget_is_rejected(tmp_path, lease):
    with pytest.raises(ValueError):
        WorkerJobRunner(str(tmp_path / 'jobs.db'), lease_seconds=lease)


def commit_then_exit(job_path, business_path, left, right):
    store = Store(business_path)
    runner = WorkerJobRunner(job_path, lease_seconds=10, clock=lambda: 1000.0)
    def operation():
        store.run(TENANT, left, right, 'exact-v1')
        os._exit(23)  # Skip all Python cleanup after the business transaction commits.
    runner.run('reconcile:after-commit', operation)


def test_process_exit_after_business_commit_replays_without_duplicate_results(tmp_path):
    clock = Clock()
    store = Store(str(tmp_path / 'business.db'))
    store.seed()
    left = store.batch(TENANT, 'left-fixture', 'a' * 64, 'USD')
    right = store.batch(TENANT, 'right-fixture', 'b' * 64, 'USD')
    path = str(tmp_path / 'jobs.db')
    process = multiprocessing.get_context('spawn').Process(
        target=commit_then_exit, args=(path, str(tmp_path / 'business.db'), left['id'], right['id']))
    process.start()
    process.join(timeout=10)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
        pytest.fail('Child process did not terminate within its test budget')
    assert process.exitcode == 23
    runner = WorkerJobRunner(path, lease_seconds=10, clock=clock)
    assert runner.status('reconcile:after-commit').state == 'RUNNING'
    with store.conn() as db:
        committed = db.execute('SELECT id FROM runs').fetchone()[0]
        before = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                  for table in ('runs', 'allocations', 'exceptions', 'audit_events')}
    clock.now += 10
    restarted = WorkerJobRunner(path, lease_seconds=10, clock=clock)
    assert restarted.recover_running() == 1
    result = restarted.run('reconcile:after-commit', lambda: {'run': store.run(TENANT, left['id'], right['id'], 'exact-v1')['id']})
    assert result.state == 'SUCCEEDED' and result.value == {'run': committed}
    assert result.attempt_count == 2
    with store.conn() as db:
        assert {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                for table in before} == before
