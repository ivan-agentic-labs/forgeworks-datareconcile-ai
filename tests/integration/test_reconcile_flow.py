from datetime import datetime,timedelta,timezone
import jwt
from fastapi.testclient import TestClient
from datareconcile_ai.main import create_app
from datareconcile_ai.infrastructure.store import TENANT,USER
S='forgeworks-development-secret-32-plus';ISS='https://issuer.synthetic.invalid';AUD='forgeworks-api'
def h(scope,tenant=TENANT):
 t=jwt.encode({'sub':USER,'tenant_id':tenant,'scope':scope,'iss':ISS,'aud':AUD,'exp':datetime.now(timezone.utc)+timedelta(minutes=5)},S,algorithm='HS256');return {'Authorization':'Bearer '+t}
def test_match_exception_resolve_finalize(tmp_path):
 app=create_app(str(tmp_path/'db.sqlite'),seed=True)
 with TestClient(app) as c:
  common={'artifact_id':'33333333-3333-3333-3333-333333333333','currency':'USD','profile_version':'strict-v1'}
  left=c.post('/v1/import-batches',headers=h('import:create'),json={**common,'source_label':'left-fixture','file_sha256':'a'*64});right=c.post('/v1/import-batches',headers=h('import:create'),json={**common,'source_label':'right-fixture','file_sha256':'b'*64});assert left.status_code==right.status_code==202
  l=left.json()['id'];r=right.json()['id'];rows=c.get(f'/v1/import-batches/{l}/rows',headers=h('import:read')).json()['items'];assert all(isinstance(x['amount_minor'],int) for x in rows)
  run=c.post('/v1/reconciliation-runs',headers=h('reconcile:run'),json={'left_batch_id':l,'right_batch_id':r,'rule_version':'exact-1to1-v1'});assert run.status_code==202;run=run.json();assert run['unmatched_count']==1
  ex=c.get(f"/v1/reconciliation-runs/{run['id']}/exceptions",headers=h('reconcile:read')).json()['items'][0];blocked=c.post(f"/v1/reconciliation-runs/{run['id']}/finalize",headers=h('report:finalize'),json={'expected_version':1,'approved_summary_sha256':'c'*64});assert blocked.status_code==409
  res=c.post(f"/v1/exceptions/{ex['id']}/resolutions",headers=h('exception:approve'),json={'decision':'accept-as-investigated','evidence_sha256':'d'*64,'expected_version':1});assert res.status_code==201
  report=c.post(f"/v1/reconciliation-runs/{run['id']}/finalize",headers=h('report:finalize'),json={'expected_version':1,'approved_summary_sha256':'c'*64});assert report.status_code==201
  link=c.get(f"/v1/reports/{report.json()['id']}/download",headers=h('report:read'));assert link.status_code==200
  duplicate=c.post('/v1/import-batches',headers=h('import:create'),json={**common,'source_label':'left-fixture','file_sha256':'a'*64});assert duplicate.status_code==409

def test_cross_currency_and_auth_fail_closed(tmp_path):
 app=create_app(str(tmp_path/'db.sqlite'),seed=True)
 with TestClient(app) as c:
  common={'artifact_id':'33333333-3333-3333-3333-333333333333','source_label':'left-fixture','file_sha256':'e'*64,'profile_version':'strict-v1'}
  a=c.post('/v1/import-batches',headers=h('import:create'),json={**common,'currency':'USD'}).json();b=c.post('/v1/import-batches',headers=h('import:create'),json={**common,'currency':'EUR','file_sha256':'f'*64}).json()
  assert c.post('/v1/reconciliation-runs',headers=h('reconcile:run'),json={'left_batch_id':a['id'],'right_batch_id':b['id'],'rule_version':'exact'}).status_code==409
  assert c.post('/v1/import-batches',headers=h('report:read'),json={**common,'currency':'USD','file_sha256':'1'*64}).status_code==403
