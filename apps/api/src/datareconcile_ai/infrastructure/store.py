from __future__ import annotations
import sqlite3,uuid,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
TENANT='00000000-0000-0000-0000-000000000001';USER='00000000-0000-0000-0000-000000000010'
def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
class Store:
 def __init__(self,path):self.path=path;Path(path).parent.mkdir(parents=True,exist_ok=True) if path!=':memory:' else None;self.init()
 def conn(self):c=sqlite3.connect(self.path,check_same_thread=False);c.row_factory=sqlite3.Row;return c
 def init(self):
  with self.conn() as c:c.executescript('''CREATE TABLE IF NOT EXISTS tenants(id TEXT PRIMARY KEY,slug TEXT,status TEXT);CREATE TABLE IF NOT EXISTS memberships(tenant_id TEXT,user_id TEXT,role TEXT,status TEXT,PRIMARY KEY(tenant_id,user_id));CREATE TABLE IF NOT EXISTS batches(tenant_id TEXT,id TEXT,source_label TEXT,file_sha TEXT,currency TEXT,row_count INTEGER,status TEXT,job_id TEXT,created_at TEXT,PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,file_sha));CREATE TABLE IF NOT EXISTS rows_(tenant_id TEXT,id TEXT,batch_id TEXT,external_ref TEXT,currency TEXT,amount_minor INTEGER,occurred_at TEXT,status TEXT,PRIMARY KEY(tenant_id,id));CREATE TABLE IF NOT EXISTS runs(tenant_id TEXT,id TEXT,left_batch TEXT,right_batch TEXT,rule TEXT,status TEXT,job_id TEXT,unmatched INTEGER,version INTEGER,PRIMARY KEY(tenant_id,id));CREATE TABLE IF NOT EXISTS exceptions(tenant_id TEXT,id TEXT,run_id TEXT,reason TEXT,left_id TEXT,right_id TEXT,status TEXT,version INTEGER,PRIMARY KEY(tenant_id,id));CREATE TABLE IF NOT EXISTS resolutions(tenant_id TEXT,id TEXT,exception_id TEXT,reviewer_id TEXT,decision TEXT,evidence_sha TEXT,PRIMARY KEY(tenant_id,id));CREATE TABLE IF NOT EXISTS reports(tenant_id TEXT,id TEXT,run_id TEXT,ledger_sha TEXT,artifact_sha TEXT,finalized_at TEXT,PRIMARY KEY(tenant_id,id));''')
 def seed(self):
  with self.conn() as c:c.execute('INSERT OR IGNORE INTO tenants VALUES(?,?,?)',(TENANT,'synthetic-demo','ACTIVE'));c.execute('INSERT OR IGNORE INTO memberships VALUES(?,?,?,?)',(TENANT,USER,'editor','ACTIVE'))
 def member(self,t,u):
  with self.conn() as c:return c.execute("SELECT 1 FROM memberships WHERE tenant_id=? AND user_id=? AND status='ACTIVE'",(t,u)).fetchone() is not None
 def batch(self,t,label,sha,currency):
  bid,jid=str(uuid.uuid4()),str(uuid.uuid4());vals=[(100,'r1'),(200,'r2'),(300,'r3')] if label=='left-fixture' else [(100,'s1'),(250,'s2'),(300,'s3')]
  with self.conn() as c:
   c.execute('INSERT INTO batches VALUES(?,?,?,?,?,?,?,?,?)',(t,bid,label,sha,currency,len(vals),'IMPORTED',jid,now()))
   for amount,ref in vals:c.execute('INSERT INTO rows_ VALUES(?,?,?,?,?,?,?,?)',(t,str(uuid.uuid4()),bid,ref,currency,amount,now(),'IMPORTED'))
  return self.get_batch(t,bid)
 def get_batch(self,t,bid):
  with self.conn() as c:return c.execute('SELECT * FROM batches WHERE tenant_id=? AND id=?',(t,bid)).fetchone()
 def rows(self,t,bid):
  with self.conn() as c:return c.execute('SELECT * FROM rows_ WHERE tenant_id=? AND batch_id=? ORDER BY external_ref',(t,bid)).fetchall()
 def run(self,t,left,right,rule):
  l=self.get_batch(t,left);r=self.get_batch(t,right);rid,jid=str(uuid.uuid4()),str(uuid.uuid4());
  with self.conn() as c:c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)',(t,rid,left,right,rule,'SUCCEEDED',jid,0,1))
  lm=self.rows(t,left);rm=self.rows(t,right);used=set();un=0
  with self.conn() as c:
   for a in lm:
    match=next((b for b in rm if b['id'] not in used and b['currency']==a['currency'] and b['amount_minor']==a['amount_minor']),None)
    if match:used.add(match['id'])
    else:
     b=next((x for x in rm if x['id'] not in used),None); used.add(b['id']) if b else None;un+=1;c.execute('INSERT INTO exceptions VALUES(?,?,?,?,?,?,?,?)',(t,str(uuid.uuid4()),rid,'AMOUNT_MISMATCH',a['id'],b['id'] if b else a['id'],'OPEN',1))
   c.execute('UPDATE runs SET unmatched=? WHERE tenant_id=? AND id=?',(un,t,rid))
  return self.get_run(t,rid)
 def get_run(self,t,rid):
  with self.conn() as c:return c.execute('SELECT * FROM runs WHERE tenant_id=? AND id=?',(t,rid)).fetchone()
 def exceptions(self,t,rid):
  with self.conn() as c:return c.execute('SELECT * FROM exceptions WHERE tenant_id=? AND run_id=?',(t,rid)).fetchall()
 def exception(self,t,eid):
  with self.conn() as c:return c.execute('SELECT * FROM exceptions WHERE tenant_id=? AND id=?',(t,eid)).fetchone()
 def resolve(self,t,eid,reviewer,decision,evidence,version):
  e=self.exception(t,eid)
  if not e:return None,'NOT_FOUND'
  if e['version']!=version:return e,'STALE'
  rid=str(uuid.uuid4());
  with self.conn() as c:c.execute('INSERT INTO resolutions VALUES(?,?,?,?,?,?)',(t,rid,eid,reviewer,decision,evidence));c.execute("UPDATE exceptions SET status='RESOLVED',version=version+1 WHERE tenant_id=? AND id=?",(t,eid))
  return rid,'OK'
 def finalize(self,t,rid,summary,version):
  r=self.get_run(t,rid);openx=[e for e in self.exceptions(t,rid) if e['status']=='OPEN']
  if not r:return None,'NOT_FOUND'
  if r['version']!=version:return r,'STALE'
  if openx:return r,'OPEN_EXCEPTIONS'
  ledger=hashlib.sha256((rid+summary).encode()).hexdigest();artifact=hashlib.sha256((ledger+'immutable-report').encode()).hexdigest();report=str(uuid.uuid4())
  with self.conn() as c:c.execute('INSERT INTO reports VALUES(?,?,?,?,?,?)',(t,report,rid,ledger,artifact,now()))
  return self.report(t,report),'OK'
 def report(self,t,rid):
  with self.conn() as c:return c.execute('SELECT * FROM reports WHERE tenant_id=? AND id=?',(t,rid)).fetchone()
