"""Synthetic exact matching must partition rows independently of early mismatches."""
import hashlib
from itertools import permutations
import pytest
from datareconcile_ai.infrastructure.store import Store, TENANT


def batch(store, side, amounts):
    source = 'external_ref,currency,amount_minor,occurred_at\n' + ''.join(f'{side}-{i},IDR,{amount},2026-10-11T00:00:00Z\n' for i, amount in enumerate(amounts))
    return store.batch(TENANT, side, hashlib.sha256(source.encode()).hexdigest(), 'IDR', csv_content=source)['id']


def partition(store, left, right):
    run = store.run(TENANT, left, right, 'exact-v1')
    with store.conn() as db:
        allocations = list(db.execute('SELECT * FROM allocations WHERE tenant_id=? AND run_id=?', (TENANT, run['id'])))
        exceptions = list(db.execute('SELECT * FROM exceptions WHERE tenant_id=? AND run_id=?', (TENANT, run['id'])))
    return run, allocations, exceptions


@pytest.mark.parametrize('left_amounts', list(permutations([200, 100, 400])))
def test_exact_matches_reserved_before_exception_pairing(tmp_path, left_amounts):
    store = Store(str(tmp_path / 'matching.sqlite'))
    left, right = batch(store, 'left', left_amounts), batch(store, 'right', [100, 300, 400])
    run, allocations, exceptions = partition(store, left, right)
    allocated_right = {r['right_id'] for r in allocations}
    exception_right = {r['right_id'] for r in exceptions if r['right_id']}
    assert allocated_right.isdisjoint(exception_right)
    assert len(allocations) == 2
    assert len(exceptions) == run['unmatched'] == 1
    assert exceptions[0]['reason'] == 'AMOUNT_MISMATCH'
    assert len(allocated_right | exception_right) == 3


@pytest.mark.parametrize('left_amounts,right_amounts,matched', [([100,100,200],[100,300],1), ([100],[100,100,300],1), ([100,200],[300],0), ([-100,100],[-100,100],2)])
def test_every_row_is_allocated_or_excepted_exactly_once(tmp_path,left_amounts,right_amounts,matched):
    store = Store(str(tmp_path / 'partition.sqlite'))
    left, right = batch(store, 'left', left_amounts), batch(store, 'right', right_amounts)
    _, allocations, exceptions = partition(store,left,right)
    assert len(allocations) == matched
    for side, count in [('left',len(left_amounts)),('right',len(right_amounts))]:
        ids = [r[side+'_id'] for r in allocations] + [r[side+'_id'] for r in exceptions if r[side+'_id']]
        assert len(ids) == len(set(ids)) == count


def test_report_rejects_an_exception_reusing_allocated_source(tmp_path):
    from uuid import uuid4
    store = Store(str(tmp_path / 'tampered.sqlite'))
    left, right = batch(store,'left',[100,200]), batch(store,'right',[100,300])
    run, allocations, exceptions = partition(store,left,right)
    assert store.partition_valid(TENANT,run['id'])
    with store.conn() as db:
        db.execute("UPDATE exceptions SET right_id=?,status='RESOLVED' WHERE tenant_id=? AND id=?", (allocations[0]['right_id'],TENANT,exceptions[0]['id']))
    assert not store.partition_valid(TENANT,run['id'])
    assert not store.totals(TENANT,run['id'])['row_partition_valid']
    _, status = store.finalize(TENANT,run['id'],'a' * 64,run['version'])
    assert status == 'CONSERVATION_FAILED'


def test_report_rejects_missing_source_partition(tmp_path):
    store = Store(str(tmp_path / 'missing.sqlite'))
    left, right = batch(store,'left',[100,200]), batch(store,'right',[100,300])
    run, _, exceptions = partition(store,left,right)
    with store.conn() as db:
        db.execute('DELETE FROM exceptions WHERE tenant_id=? AND id=?',(TENANT,exceptions[0]['id']))
    assert not store.partition_valid(TENANT,run['id'])
    _, status = store.finalize(TENANT,run['id'],'a' * 64,run['version'])
    assert status == 'CONSERVATION_FAILED'
