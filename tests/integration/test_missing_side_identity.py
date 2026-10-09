import hashlib,json
from datareconcile_ai.infrastructure.store import Store,TENANT


def test_missing_side_is_null_and_audit_counts_actual_matches(tmp_path):
    store=Store(str(tmp_path/'db.sqlite'));store.seed()
    header='external_ref,currency,amount_minor,occurred_at\n'
    left=header+'l1,USD,100,2026-01-01T00:00:00Z\n'
    right=header+'r1,USD,100,2026-01-01T00:00:00Z\nr2,USD,200,2026-01-01T00:00:00Z\n'
    a=store.batch(TENANT,'left',hashlib.sha256(left.encode()).hexdigest(),'USD',csv_content=left)
    b=store.batch(TENANT,'right',hashlib.sha256(right.encode()).hexdigest(),'USD',csv_content=right)
    run=store.run(TENANT,a['id'],b['id'],'exact-v1')
    exception=store.exceptions(TENANT,run['id'])[0]
    assert exception['reason']=='MISSING_LEFT'
    assert exception['left_id'] is None and exception['right_id'] is not None
    event=store.audit_events(TENANT,run['id'])[0]
    assert json.loads(event['payload_json'])['matched_count']==1
    reverse=store.run(TENANT,b['id'],a['id'],'exact-v1')
    exception=store.exceptions(TENANT,reverse['id'])[0]
    assert exception['reason']=='MISSING_RIGHT'
    assert exception['left_id'] is not None and exception['right_id'] is None
