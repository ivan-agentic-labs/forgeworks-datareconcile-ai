from __future__ import annotations
import os
from pathlib import Path
from datetime import datetime,timezone,timedelta
from uuid import UUID
from typing import Annotated
import jwt
from fastapi import FastAPI,Depends,Header,HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from datareconcile_ai.infrastructure.store import Store
ROOT=Path(__file__).resolve().parents[4]
class Import(BaseModel):model_config=ConfigDict(extra='forbid');source_label:str;artifact_id:UUID;file_sha256:str=Field(pattern=r'^[0-9a-f]{64}$');currency:str=Field(pattern=r'^[A-Z]{3}$');profile_version:str
class Reconcile(BaseModel):model_config=ConfigDict(extra='forbid');left_batch_id:UUID;right_batch_id:UUID;rule_version:str
class Resolve(BaseModel):model_config=ConfigDict(extra='forbid');decision:str;evidence_sha256:str=Field(pattern=r'^[0-9a-f]{64}$');expected_version:int
class Finalize(BaseModel):model_config=ConfigDict(extra='forbid');expected_version:int;approved_summary_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')
def reject(status,code,detail):raise HTTPException(status_code=status,detail={'type':'about:blank','title':'Request rejected','status':status,'code':code,'detail':detail,'request_id':'runtime'})
def auth(authorization:Annotated[str|None,Header()]=None):
 if not authorization or not authorization.startswith('Bearer '):reject(401,'UNAUTHENTICATED','Bearer token is required')
 try:return jwt.decode(authorization[7:],os.getenv('DEV_AUTH_SECRET','forgeworks-development-secret-32-plus'),algorithms=['HS256'],issuer=os.getenv('AUTH_ISSUER','https://issuer.synthetic.invalid'),audience=os.getenv('AUTH_AUDIENCE','forgeworks-api'))
 except jwt.PyJWTError:reject(401,'INVALID_TOKEN','Token signature, issuer, audience, or expiry is invalid')
def scope(required,store):
 def dep(c=Depends(auth)):
  if not c.get('tenant_id') or not c.get('sub') or not store.member(c['tenant_id'],c['sub']):reject(403,'TENANT_CONTEXT_INVALID','Verified membership is required')
  if required not in set(str(c.get('scope','')).split()):reject(403,'INSUFFICIENT_SCOPE',f'Scope {required} is required')
  return c
 return dep
def create_app(db_path=None,seed=False):
 store=Store(db_path or os.getenv('RECONCILE_DB_PATH',str(ROOT/'.runtime/reconcile.db')))
 if seed:store.seed()
 app=FastAPI(title='DataReconcile AI MVP',version='0.1.0');app.state.store=store
 @app.exception_handler(HTTPException)
 async def errors(_,e):return JSONResponse(status_code=e.status_code,content=e.detail if isinstance(e.detail,dict) else {'type':'about:blank','title':'Request rejected','status':e.status_code,'code':'REQUEST_REJECTED','detail':str(e.detail),'request_id':'runtime'})
 @app.get('/healthz')
 def health():return {'status':'ok','service':'datareconcile-ai'}
 @app.post('/v1/import-batches',status_code=202)
 def imp(body:Import,c=Depends(scope('import:create',store))):
  with store.conn() as db:
   if db.execute('SELECT 1 FROM batches WHERE tenant_id=? AND file_sha=?',(c['tenant_id'],body.file_sha256)).fetchone():return reject(409,'DUPLICATE_IMPORT','This file digest was already imported')
  r=store.batch(c['tenant_id'],body.source_label,body.file_sha256,body.currency);return {'id':r['id'],'status':r['status'],'created_at':r['created_at'],'source_label':r['source_label'],'file_sha256':r['file_sha'],'currency':r['currency'],'row_count':r['row_count'],'job_id':r['job_id']}
 @app.get('/v1/import-batches/{bid}/rows')
 def rows(bid:UUID,c=Depends(scope('import:read',store))):
  if not store.get_batch(c['tenant_id'],str(bid)):return reject(404,'RESOURCE_NOT_FOUND','Import is not visible')
  items=[{'id':x['id'],'batch_id':x['batch_id'],'external_ref':x['external_ref'],'currency':x['currency'],'amount_minor':x['amount_minor'],'occurred_at':x['occurred_at'],'row_status':x['status']} for x in store.rows(c['tenant_id'],str(bid))];return {'items':items,'next_cursor':None,'has_more':False}
 @app.post('/v1/reconciliation-runs',status_code=202)
 def reconcile(body:Reconcile,c=Depends(scope('reconcile:run',store))):
  l=store.get_batch(c['tenant_id'],str(body.left_batch_id));r=store.get_batch(c['tenant_id'],str(body.right_batch_id))
  if not l or not r:return reject(404,'RESOURCE_NOT_FOUND','Import is not visible')
  if l['currency']!=r['currency']:return reject(409,'CURRENCY_MISMATCH','Only same-currency matching is supported')
  x=store.run(c['tenant_id'],str(body.left_batch_id),str(body.right_batch_id),body.rule_version);return {'id':x['id'],'status':x['status'],'created_at':x['job_id'] and datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'left_batch_id':x['left_batch'],'right_batch_id':x['right_batch'],'rule_version':x['rule'],'job_id':x['job_id'],'unmatched_count':x['unmatched']}
 @app.get('/v1/reconciliation-runs/{rid}/exceptions')
 def exceptions(rid:UUID,c=Depends(scope('reconcile:read',store))):
  items=[{'id':x['id'],'run_id':x['run_id'],'reason_code':x['reason'],'left_transaction_id':x['left_id'],'right_transaction_id':x['right_id'],'status':x['status']} for x in store.exceptions(c['tenant_id'],str(rid))];return {'items':items,'next_cursor':None,'has_more':False}
 @app.post('/v1/exceptions/{eid}/resolutions',status_code=201)
 def resolve(eid:UUID,body:Resolve,c=Depends(scope('exception:approve',store))):
  rid,status=store.resolve(c['tenant_id'],str(eid),c['sub'],body.decision,body.evidence_sha256,body.expected_version)
  if status=='NOT_FOUND':return reject(404,'RESOURCE_NOT_FOUND','Exception is not visible')
  if status=='STALE':return reject(409,'STALE_VERSION','Exception version is stale')
  return {'id':rid,'status':'RECORDED','created_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'exception_id':str(eid),'reviewer_id':c['sub'],'decision':body.decision,'evidence_sha256':body.evidence_sha256}
 @app.post('/v1/reconciliation-runs/{rid}/finalize',status_code=201)
 def finalize(rid:UUID,body:Finalize,c=Depends(scope('report:finalize',store))):
  r,status=store.finalize(c['tenant_id'],str(rid),body.approved_summary_sha256,body.expected_version)
  if status=='NOT_FOUND':return reject(404,'RESOURCE_NOT_FOUND','Run is not visible')
  if status=='STALE':return reject(409,'STALE_VERSION','Run is stale')
  if status=='OPEN_EXCEPTIONS':return reject(409,'OPEN_EXCEPTIONS','All exceptions require an authorized resolution')
  return {'id':r['id'],'status':'FINALIZED','created_at':r['finalized_at'],'run_id':r['run_id'],'ledger_sha256':r['ledger_sha'],'artifact_sha256':r['artifact_sha'],'finalized_at':r['finalized_at']}
 @app.get('/v1/reports/{rid}/download')
 def download(rid:UUID,c=Depends(scope('report:read',store))):
  r=store.report(c['tenant_id'],str(rid))
  if not r:return reject(404,'RESOURCE_NOT_FOUND','Report is not visible')
  return {'report_id':r['id'],'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat().replace('+00:00','Z'),'download_token':r['artifact_sha']}
 @app.get('/v1/jobs/{jid}')
 def job(jid:UUID,c=Depends(scope('job:read',store))):
  with store.conn() as db:r=db.execute('SELECT * FROM runs WHERE tenant_id=? AND job_id=?',(c['tenant_id'],str(jid))).fetchone()
  if not r:return reject(404,'RESOURCE_NOT_FOUND','Job is not visible')
  return {'id':r['job_id'],'kind':'reconciliation','state':r['status'],'created_at':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'state_version':r['version'],'attempt_count':1,'last_error_code':None}
 return app
app=create_app(seed=os.getenv('RECONCILE_SEED_FIXTURE','0')=='1')
