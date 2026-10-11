"""The exact matching domain rejects mixed units before creating any results."""
import hashlib

import pytest

from datareconcile_ai.infrastructure.store import Store, StoreValidationError, TENANT, USER


def batch(store, currency, label):
    source = f'external_ref,currency,amount_minor,occurred_at\n{label},{currency},100,2026-10-11T00:00:00Z\n'
    return store.batch(TENANT, label, hashlib.sha256(source.encode()).hexdigest(),
                       currency, csv_content=source)['id']


def result_counts(store):
    with store.conn() as db:
        return {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                for table in ('runs', 'allocations', 'exceptions', 'source_artifact_commands', 'audit_events')}


@pytest.mark.parametrize('currencies', [('IDR', 'USD'), ('USD', 'IDR'), ('USD', 'EUR')])
@pytest.mark.parametrize('idempotency_key', [None, 'currency-invariant-0001'])
def test_mixed_currency_is_rejected_without_results(tmp_path, currencies, idempotency_key):
    store = Store(str(tmp_path / 'currency.sqlite'))
    left = batch(store, currencies[0], 'left')
    right = batch(store, currencies[1], 'right')
    before = result_counts(store)
    with pytest.raises(StoreValidationError) as error:
        store.run(TENANT, left, right, 'exact-v1', actor=USER, idempotency_key=idempotency_key)
    assert error.value.code == 'CURRENCY_MISMATCH'
    assert result_counts(store) == before


@pytest.mark.parametrize('currency', ['USD', 'IDR'])
def test_same_currency_matching_and_replay_remain_valid(tmp_path, currency):
    store = Store(str(tmp_path / 'currency.sqlite'))
    left, right = batch(store, currency, 'left'), batch(store, currency, 'right')
    run = store.run(TENANT, left, right, 'exact-v1', actor=USER, idempotency_key='same-currency-0001')
    assert run['unmatched'] == 0
    before = result_counts(store)
    replay = store.run(TENANT, left, right, 'exact-v1', actor=USER, idempotency_key='same-currency-0001')
    assert replay['id'] == run['id']
    assert result_counts(store) == before
