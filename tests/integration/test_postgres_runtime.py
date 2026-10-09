"""Disposable PostgreSQL proof for exact money, concurrency, report bytes and tenant RLS."""
import hashlib,os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from datareconcile_ai.infrastructure.store import TENANT,USER,StoreValidationError
from datareconcile_ai.infrastructure.postgres_store import PostgresStore, ROLE


def test_postgres_import_match_resolve_finalize_download_and_rls(monkeypatch):
    owner=os.getenv('RECONCILE_DISPOSABLE_OWNER_DSN')
    if not owner:pytest.skip('Disposable PostgreSQL unavailable; NOT a runtime pass')
    info=conninfo_to_dict(owner)
    if os.getenv('G1_DISPOSABLE_DB')!='yes' or info.get('host') not in {'127.0.0.1','localhost'} or info.get('dbname')!='forgeworks_runtime':
        pytest.fail('Refusing non-disposable PostgreSQL configuration')
    root=Path(__file__).resolve().parents[2];other=str(uuid4())
    with psycopg.connect(owner) as db:
        if db.execute("SELECT to_regclass('import_batches')").fetchone()[0]:pytest.fail('Proof requires a fresh empty database')
        for name in ['001_reconcile_mvp.sql','002_reconcile_runtime.sql','003_source_artifact_ingestion.sql','004_artifact_immutability.sql']:
            db.execute((root/'migrations/versions'/name).read_text())
        db.execute("CREATE ROLE fw_runtime_test LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD 'synthetic-local-runtime-test-only'")
        db.execute('GRANT fw_datareconcile_ai_rw TO fw_runtime_test')
        db.execute('INSERT INTO tenants VALUES(%s,%s,%s)',(TENANT,'synthetic-demo','ACTIVE'))
        db.execute('INSERT INTO tenants VALUES(%s,%s,%s)',(other,'synthetic-other','ACTIVE'))
        db.execute('INSERT INTO memberships VALUES(%s,%s,%s,%s)',(TENANT,USER,'editor','ACTIVE'))
    info.update(user='fw_runtime_test',password='synthetic-local-runtime-test-only');runtime=make_conninfo(**info)
    with pytest.raises(ValueError,match='superuser'):PostgresStore(owner)
    store=PostgresStore(runtime)
    with pytest.raises(StoreValidationError) as missing_source:
        store.batch(TENANT,'metadata-only','a'*64,'USD')
    assert missing_source.value.code=='SOURCE_BYTES_REQUIRED'
    assert not store.member(TENANT, "unmapped-oidc-subject")
    # Runtime login and its group cannot own tenant/provisioning tables either.
    for table, new_owner in [('memberships','fw_runtime_test'),('tenants',ROLE)]:
        with psycopg.connect(owner) as db:
            db.execute(psycopg.sql.SQL('ALTER TABLE {} OWNER TO {}').format(psycopg.sql.Identifier(table),psycopg.sql.Identifier(new_owner)))
        try:
            with pytest.raises(ValueError,match='own product tables'):
                PostgresStore(runtime)
        finally:
            with psycopg.connect(owner) as db:
                db.execute(psycopg.sql.SQL('ALTER TABLE {} OWNER TO postgres').format(psycopg.sql.Identifier(table)))
                db.execute(psycopg.sql.SQL('REVOKE ALL ON {} FROM {}').format(psycopg.sql.Identifier(table),psycopg.sql.Identifier(new_owner)))

    assert store.member(TENANT,USER) and not store.member(other,USER)
    header='external_ref,currency,amount_minor,occurred_at\n'
    left=header+'l1,USD,100,2026-01-01T00:00:00Z\n'
    right=header+'r1,USD,100,2026-01-01T00:00:00Z\nr2,USD,200,2026-01-01T00:00:00Z\n'
    a=store.batch(TENANT,'left',hashlib.sha256(left.encode()).hexdigest(),'USD',csv_content=left)
    b=store.batch(TENANT,'right',hashlib.sha256(right.encode()).hexdigest(),'USD',csv_content=right)
    with pytest.raises(StoreValidationError) as duplicate:
        store.batch(TENANT,'left',hashlib.sha256(left.encode()).hexdigest(),'USD',csv_content=left)
    assert duplicate.value.code=='DUPLICATE_IMPORT'
    assert store.get_batch(other,a['id']) is None
    with psycopg.connect(runtime) as db:
        db.execute('SET LOCAL ROLE fw_datareconcile_ai_rw')
        assert db.execute('SELECT count(*) FROM import_batches').fetchone()[0]==0
    with store.conn(TENANT) as db:
        assert db.execute('UPDATE batches SET source_label=? WHERE tenant_id=?',('forbidden',other)).rowcount==0
        assert db.execute('DELETE FROM batches WHERE tenant_id=?',(other,)).rowcount==0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute('INSERT INTO batches(tenant_id,id,source_label,file_sha,currency,row_count,status) VALUES(?,?,?,?,?,?,?)',(other,str(uuid4()),'forbidden','e'*64,'USD',0,'IMPORTED'))
    peers=[PostgresStore(runtime),PostgresStore(runtime)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids=list(pool.map(lambda index:peers[index%2].run(TENANT,a['id'],b['id'],'exact-v1')['id'],range(8)))
    assert len(set(ids))==1
    rid=ids[0];exception=store.exceptions(TENANT,rid)[0]
    assert exception['reason']=='MISSING_LEFT' and exception['left_id'] is None
    totals=store.totals(TENANT,rid)
    assert totals['left_total_minor']==100 and totals['right_total_minor']==300
    assert totals['allocated_total_minor']==100 and totals['conservation_discrepancy_minor']==0
    def resolve(index):return peers[index].resolve(TENANT,exception['id'],USER,'accept-as-investigated','d'*64,1)[1]
    with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(resolve,range(2)))
    assert sorted(outcomes)==['OK','STALE']
    report,status=store.finalize(TENANT,rid,'c'*64,1)
    assert status=='OK' and hashlib.sha256(report['content_json'].encode()).hexdigest()==report['artifact_sha']
    assert store.report(other,report['id']) is None
    with store.conn(TENANT) as db:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):db.execute('UPDATE reports SET content_json=? WHERE id=?',('{}',report['id']))
    from fastapi.testclient import TestClient
    from datareconcile_ai.main import create_app
    from test_reconcile_flow import h
    monkeypatch.setenv('RECONCILE_DATABASE_URL',runtime)
    with TestClient(create_app()) as client:
        from test_artifact_ingestion import upload, auth, CSV
        record,commit=upload(client)
        committed=client.post(f"/v1/artifacts/{record['artifact_id']}/commit",headers=auth('artifact:commit','pg-artifact-commit-001'),json=commit)
        assert committed.status_code==202 and committed.json()['status']=='AVAILABLE',committed.text
        with store.conn(TENANT) as db:
            for statement,parameters in [
                ("UPDATE source_artifacts SET content_base64=? WHERE id=?",('dGFtcGVy',record['artifact_id'])),
                ("UPDATE source_artifacts SET sha256=? WHERE id=?",('e'*64,record['artifact_id'])),
                ("UPDATE source_artifacts SET status='QUARANTINED' WHERE id=?",(record['artifact_id'],))]:
                with pytest.raises(psycopg.errors.RaiseException):
                    db.execute(statement,parameters)
        imported=client.post('/v1/import-batches',headers=h('import:create'),json={'source_label':'uploaded-csv','artifact_id':record['artifact_id'],'file_sha256':commit['sha256'],'currency':'USD','profile_version':'strict-v1'})
        assert imported.status_code==202 and imported.json()['row_count']==1,imported.text
        download=client.post(f"/v1/artifacts/{record['artifact_id']}/download-intents",headers=auth('artifact:download','pg-artifact-download-001'))
        assert download.status_code==201 and client.get(download.json()['download_url']).content==CSV,download.text
        with store.conn(other) as db:
            assert db.execute('SELECT count(*) FROM source_artifacts').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM source_artifact_commands').fetchone()[0]==0
            assert db.execute("UPDATE source_artifacts SET status='DELETED' WHERE tenant_id=?",(TENANT,)).rowcount==0
        with psycopg.connect(runtime) as db:
            db.execute('SET LOCAL ROLE fw_datareconcile_ai_rw')
            assert db.execute('SELECT count(*) FROM source_artifacts').fetchone()[0]==0
        from datareconcile_ai.infrastructure.artifact_ingestion import ArtifactIngestion
        ingestion_peers=[ArtifactIngestion(peer) for peer in peers]
        values={'kind':'source','filename':'parallel.csv','size_bytes':len(CSV),'sha256':hashlib.sha256(CSV).hexdigest(),'declared_media_type':'text/csv'}
        with ThreadPoolExecutor(max_workers=4) as pool:
            records=list(pool.map(lambda i:ingestion_peers[i%2].intent(TENANT,USER,'pg-parallel-artifact-001',values)['artifact_id'],range(8)))
        assert len(set(records))==1
        response=client.get(f"/v1/reports/{report['id']}/download",headers=h('report:read'))
        assert response.status_code==200,response.text
        downloaded=client.get(response.json()['download_url'])
        assert downloaded.status_code==200
        assert hashlib.sha256(downloaded.content).hexdigest()==report['artifact_sha']
        job=client.get(f"/v1/jobs/{store.get_run(TENANT,rid)['job_id']}",headers=h('job:read'))
        assert job.status_code==200 and job.json()['state']=='SUCCEEDED'
