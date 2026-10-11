import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from datareconcile_ai.main import create_app
from datareconcile_ai.infrastructure.store import TENANT, USER
from test_hardening import headers

CSV = b'external_ref,currency,amount_minor,occurred_at\nsource-row,USD,17,2026-01-01T00:00:00Z\n'


def auth(scope, key):
    return {**headers(scope), "Idempotency-Key":key}


def intent(client, body=CSV, key="artifact-upload-key-001"):
    values = {"kind":"source", "filename":"synthetic.csv", "size_bytes":len(body), "sha256":hashlib.sha256(body).hexdigest(), "declared_media_type":"text/csv"}
    response = client.post('/v1/artifacts/upload-intents', headers=auth('artifact:create', key), json=values)
    assert response.status_code == 201, response.text
    return response.json(), values


def upload(client, body=CSV, key="artifact-upload-key-001"):
    record, values = intent(client, body, key)
    result = client.put(record['upload_url'], content=body)
    assert result.status_code == 201, result.text
    commit = {"sha256":values["sha256"], "size_bytes":len(body), "object_generation":result.json()['object_generation']}
    return record, commit


def test_upload_commit_import_download_and_response_contract(tmp_path):
    app = create_app(str(tmp_path/'db.sqlite'), seed=True)
    with TestClient(app) as client:
        record, commit = upload(client)
        url = f"/v1/artifacts/{record['artifact_id']}/commit"
        result = client.post(url, headers=auth('artifact:commit','artifact-commit-key-001'), json=commit)
        assert result.status_code == 202 and result.json()['status']=='AVAILABLE', result.text
        assert client.post(url, headers=auth('artifact:commit','artifact-commit-key-001'), json=commit).json()==result.json()
        import_values = {"source_label":"uploaded-source", "artifact_id":record['artifact_id'], "file_sha256":commit['sha256'], "currency":"USD", "profile_version":"strict-v1"}
        imported = client.post('/v1/import-batches', headers=headers('import:create'), json=import_values)
        assert imported.status_code == 202 and imported.json()['row_count']==1, imported.text
        with app.state.store.conn() as db:
            row=db.execute('SELECT * FROM rows_ WHERE batch_id=?',(imported.json()['id'],)).fetchone()
            assert row['external_ref']=='source-row' and row['amount_minor']==17
        download=client.post(f"/v1/artifacts/{record['artifact_id']}/download-intents",headers=auth('artifact:download','artifact-download-key-001'))
        assert download.status_code==201,download.text
        assert client.get(download.json()['download_url']).content==CSV
        assert client.get(download.json()['download_url'].replace(record['artifact_id'],'33333333-3333-3333-3333-333333333333')).status_code==403
        # Revocation invalidates already-issued transfer capabilities.
        with app.state.store.conn() as db:
            db.execute("UPDATE memberships SET status='REVOKED' WHERE tenant_id=? AND user_id=?",(TENANT,USER))
        assert client.get(download.json()['download_url']).status_code==403


@pytest.mark.parametrize("stored_bytes", ["dGFtcGVy", "%%%invalid-base64%%%"])
def test_pending_wrong_digest_generation_and_tampering_are_rejected(tmp_path, stored_bytes):
    app=create_app(str(tmp_path/'db.sqlite'),seed=True)
    with TestClient(app) as client:
        record,values=intent(client)
        assert client.put(record['upload_url'],content=b'wrong').status_code==409
        commit={"sha256":values['sha256'],"size_bytes":len(CSV),"object_generation":"missing"}
        url=f"/v1/artifacts/{record['artifact_id']}/commit"
        assert client.post(url,headers=auth('artifact:commit','artifact-commit-key-001'),json=commit).status_code==409
        uploaded=client.put(record['upload_url'],content=CSV);commit['object_generation']=uploaded.json()['object_generation']
        assert client.post(url,headers=auth('artifact:commit','artifact-commit-key-001'),json=commit).status_code==202
        with app.state.store.conn() as db:
            db.execute("UPDATE source_artifacts SET content_base64=? WHERE tenant_id=? AND id=?",(stored_bytes,TENANT,record['artifact_id']))
        result=client.post(f"/v1/artifacts/{record['artifact_id']}/download-intents",headers=auth('artifact:download','artifact-download-key-001'))
        assert result.status_code==409 and result.json()['code']=='ARTIFACT_INTEGRITY_FAILURE'


def test_upload_idempotency_concurrency_and_conflict(tmp_path):
    app=create_app(str(tmp_path/'db.sqlite'),seed=True)
    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            records=list(pool.map(lambda _:intent(client)[0],range(8)))
        assert len({r['artifact_id'] for r in records})==1
        _,values=intent(client)
        values['filename']='different.csv'
        response=client.post('/v1/artifacts/upload-intents',headers=auth('artifact:create','artifact-upload-key-001'),json=values)
        assert response.status_code==409 and response.json()['code']=='IDEMPOTENCY_CONFLICT'


@pytest.mark.parametrize('body',[b'not,csv\ninvalid,source\n',b'\xff',b'external_ref,currency,amount_minor,occurred_at\nx,USD,"unterminated\n'])
def test_invalid_source_remains_quarantined(tmp_path,body):
    app=create_app(str(tmp_path/'db.sqlite'),seed=True)
    with TestClient(app) as client:
        record,commit=upload(client,body)
        result=client.post(f"/v1/artifacts/{record['artifact_id']}/commit",headers=auth('artifact:commit','artifact-commit-key-001'),json=commit)
        assert result.status_code==422,result.text
        row=app.state.store.conn().execute('SELECT status FROM source_artifacts').fetchone()
        assert row['status']=='QUARANTINED'


def test_production_transfers_fail_closed(tmp_path,monkeypatch):
    app=create_app(str(tmp_path/'db.sqlite'),seed=True)
    with TestClient(app) as client:
        record,_=intent(client)
        monkeypatch.setenv('APP_ENV','production')
        result=client.put(record['upload_url'],content=CSV)
        assert result.status_code==503 and result.json()['code']=='EXTERNAL_STORAGE_REQUIRED'
