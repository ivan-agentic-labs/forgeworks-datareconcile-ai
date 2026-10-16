import base64
import hashlib
import json
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from datareconcile_ai.domain.report_signatures import attest_report, verify_report_attestation, ReportSignatureError
from datareconcile_ai.infrastructure.store import TENANT, USER
from datareconcile_ai.main import create_app
from test_matching_partition import batch
from test_reconcile_flow import h


def keys():
    key = Ed25519PrivateKey.generate()
    return key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(), key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def prepared(tmp_path):
    app = create_app(str(tmp_path/'signed.db'),seed=True)
    store = app.state.store
    left, right = batch(store,'left',[100,200]), batch(store,'right',[100,200])
    run = store.run(TENANT,left,right,'exact-v1')
    report, status = store.finalize(TENANT,run['id'],'a'*64,run['version'])
    assert status == 'OK'
    binding = {'tenant_id':TENANT,'report_id':report['id'],'run_id':report['run_id'],'artifact_sha256':report['artifact_sha']}
    return app, report, binding


def test_report_signature_actual_http_bytes(tmp_path, monkeypatch):
    app, report, binding = prepared(tmp_path)
    key, private, public = keys(); monkeypatch.setenv('RECONCILE_REPORT_SIGNING_KEY_PEM',private)
    with TestClient(app) as client:
        response = client.get(f"/v1/reports/{report['id']}/signature",headers=h('report:read'))
        assert response.status_code == 200, response.text
        assert response.headers['cache-control'] == 'no-store'
        envelope = response.json()
        payload = verify_report_attestation(envelope,public,binding)
        assert payload['report_json'] == report['content_json']
        key.public_key().verify(base64.urlsafe_b64decode(envelope['signature']),envelope['signed_payload'].encode())
        link = client.get(f"/v1/reports/{report['id']}/download",headers=h('report:read')).json()
        downloaded = client.get(link['download_url'])
        assert downloaded.content == payload['report_json'].encode()
        assert hashlib.sha256(downloaded.content).hexdigest() == binding['artifact_sha256']
        assert client.get(f"/v1/reports/{report['id']}/signature",headers=h('reconcile:read')).status_code == 403
        # Tenant-bound storage query never reveals the other organization's report.
        assert app.state.store.report('00000000-0000-0000-0000-000000000099',report['id']) is None
        other = '00000000-0000-0000-0000-000000000099'
        with app.state.store.conn() as db:
            db.execute('INSERT INTO tenants VALUES(?,?,?)',(other,'synthetic-other','ACTIVE'))
            db.execute('INSERT INTO memberships VALUES(?,?,?,?)',(other,USER,'editor','ACTIVE'))
        assert client.get(f"/v1/reports/{report['id']}/signature",headers=h('report:read',other)).status_code == 404


@pytest.mark.parametrize('private', ['', 'invalid', 'x'*16385], ids=['missing','malformed','oversized'])
def test_missing_or_malformed_signer_is_typed_unavailable(tmp_path,monkeypatch,private):
    app, report, _ = prepared(tmp_path)
    monkeypatch.setenv('RECONCILE_REPORT_SIGNING_KEY_PEM',private)
    with TestClient(app) as client:
        result = client.get(f"/v1/reports/{report['id']}/signature",headers=h('report:read'))
        assert result.status_code == 503
        assert result.json()['code'] == 'REPORT_SIGNING_KEY_UNAVAILABLE'


@pytest.mark.parametrize('field,value', [('algorithm','HS256'), ('key_sha256','0'*64), ('signed_payload_sha256','0'*64), ('signature','broken')])
def test_tampered_envelope_rejected(tmp_path,field,value):
    _, report, binding = prepared(tmp_path); _, private, public = keys()
    envelope = attest_report(report,TENANT,private); envelope[field] = value
    with pytest.raises(ReportSignatureError): verify_report_attestation(envelope,public,binding)


@pytest.mark.parametrize('field', ['tenant_id','report_id','run_id','artifact_sha256'])
def test_cross_report_replay_rejected(tmp_path,field):
    _, report, binding = prepared(tmp_path); _, private, public = keys()
    envelope = attest_report(report,TENANT,private)
    with pytest.raises(ReportSignatureError,match='REPORT_BINDING_MISMATCH'):
        verify_report_attestation(envelope,public,{**binding,field:'different'})
    with pytest.raises(ReportSignatureError,match='REPORT_EXPECTED_BINDING_REQUIRED'):
        verify_report_attestation(envelope,public,{key:value for key,value in binding.items() if key!=field})


def test_independent_key_rejects_envelope_even_if_attacker_replaces_fingerprint(tmp_path):
    _, report, binding = prepared(tmp_path); _, private, public = keys()
    envelope = attest_report(report,TENANT,private)
    other, _, other_public = keys()
    der = other.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    envelope['key_sha256'] = hashlib.sha256(der).hexdigest()
    with pytest.raises(ReportSignatureError,match='REPORT_SIGNATURE_INVALID'):
        verify_report_attestation(envelope,other_public,binding)


def test_digest_rewrite_does_not_hide_signature_tampering(tmp_path):
    _, report, binding = prepared(tmp_path); _, private, public = keys()
    envelope = attest_report(report,TENANT,private)
    envelope['signed_payload'] += ' '
    envelope['signed_payload_sha256'] = hashlib.sha256(envelope['signed_payload'].encode()).hexdigest()
    with pytest.raises(ReportSignatureError,match='REPORT_SIGNATURE_INVALID'):
        verify_report_attestation(envelope,public,binding)


def test_report_tamper_or_absent_content_cannot_be_signed(tmp_path):
    _, report, _ = prepared(tmp_path); _, private, _ = keys()
    for content in ('changed',''):
        with pytest.raises(ReportSignatureError,match='REPORT_INTEGRITY_FAILURE'):
            attest_report({**dict(report),'content_json':content},TENANT,private)


def test_key_type_is_fixed_to_ed25519(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1
    _, report, binding = prepared(tmp_path)
    key = generate_private_key(SECP256R1())
    private = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    with pytest.raises(ReportSignatureError,match='REPORT_SIGNING_KEY_UNAVAILABLE'): attest_report(report,TENANT,private)
    _, private, _ = keys()
    with pytest.raises(ReportSignatureError,match='REPORT_TRUSTED_KEY_INVALID'):
        verify_report_attestation(attest_report(report,TENANT,private),public,binding)


@pytest.mark.parametrize('payload', [[], {'unexpected':True}])
def test_even_signed_payload_requires_expected_schema(tmp_path,payload):
    _, report, binding = prepared(tmp_path); key, private, public = keys()
    envelope = attest_report(report,TENANT,private)
    body = json.dumps(payload).encode()
    envelope.update(signed_payload=body.decode(),signed_payload_sha256=hashlib.sha256(body).hexdigest(),signature=base64.urlsafe_b64encode(key.sign(body)).decode())
    with pytest.raises(ReportSignatureError,match='REPORT_PAYLOAD_INVALID'):
        verify_report_attestation(envelope,public,binding)


def test_http_integrity_failure_never_signs_tampered_bytes(tmp_path,monkeypatch):
    app, report, _ = prepared(tmp_path)
    _, private, _ = keys(); monkeypatch.setenv('RECONCILE_REPORT_SIGNING_KEY_PEM',private)
    with app.state.store.conn() as db:
        db.execute('UPDATE reports SET content_json=? WHERE tenant_id=? AND id=?',('changed',TENANT,report['id']))
    with TestClient(app) as client:
        response = client.get(f"/v1/reports/{report['id']}/signature",headers=h('report:read'))
        assert response.status_code == 409 and response.json()['code'] == 'REPORT_INTEGRITY_FAILURE'
        assert private not in response.text


@pytest.mark.parametrize('valid', [True, False])
def test_offline_cli_verifies_independent_files(tmp_path,valid):
    import subprocess
    import sys
    from pathlib import Path
    _, report, binding = prepared(tmp_path); _, private, public = keys()
    envelope = attest_report(report,TENANT,private)
    if not valid: binding['report_id'] = 'another-report'
    files = {'envelope.json':json.dumps(envelope),'public.pem':public,'binding.json':json.dumps(binding)}
    for name, content in files.items(): (tmp_path/name).write_text(content)
    result = subprocess.run([sys.executable,str(Path(__file__).resolve().parents[2]/'scripts/verify_report_signature.py'),
        '--envelope',str(tmp_path/'envelope.json'),'--public-key',str(tmp_path/'public.pem'),'--expected-binding',str(tmp_path/'binding.json')],capture_output=True,text=True)
    assert result.returncode == (0 if valid else 1)
    assert private not in result.stdout + result.stderr


def test_signed_report_content_hash_is_checked_independently(tmp_path):
    _, report, binding = prepared(tmp_path); key, private, public = keys()
    envelope = attest_report(report,TENANT,private)
    payload = json.loads(envelope['signed_payload']); payload['report_json'] = 'changed'
    body = json.dumps(payload).encode()
    envelope.update(signed_payload=body.decode(),signed_payload_sha256=hashlib.sha256(body).hexdigest(),signature=base64.urlsafe_b64encode(key.sign(body)).decode())
    with pytest.raises(ReportSignatureError,match='REPORT_CONTENT_DIGEST_MISMATCH'):
        verify_report_attestation(envelope,public,binding)


def _resign_modified_payload(envelope, signing_key, changes):
    payload = json.loads(envelope['signed_payload'])
    payload.update(changes)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {**envelope,
        "signed_payload": body.decode("utf-8"),
        "signed_payload_sha256": hashlib.sha256(body).hexdigest(),
        "signature": base64.urlsafe_b64encode(signing_key.sign(body)).decode(),
    }


@pytest.mark.parametrize("changes,code", [
    ({"source_revision": "another-source"}, "REPORT_CONTENT_BINDING_MISMATCH"),
    ({"approved_summary_sha256": "e" * 64}, "REPORT_CONTENT_BINDING_MISMATCH"),
    ({"ledger_sha256": "d" * 64}, "REPORT_LEDGER_DIGEST_MISMATCH"),
])
def test_even_validly_resigned_metadata_must_match_report_content(tmp_path, changes, code):
    _, report, binding = prepared(tmp_path)
    key, private, public = keys()
    envelope = attest_report(report, TENANT, private)
    forged = _resign_modified_payload(envelope, key, changes)
    with pytest.raises(ReportSignatureError, match=code):
        verify_report_attestation(forged, public, binding)


def test_signer_rejects_duplicate_keys_inside_report_content(tmp_path):
    _, report, _ = prepared(tmp_path)
    _, private, _ = keys()
    forged_content = report["content_json"].replace(
        '"source_revision":', '"source_revision":"duplicate","source_revision":', 1
    )
    altered = dict(report)
    altered["content_json"] = forged_content
    altered["artifact_sha"] = hashlib.sha256(forged_content.encode()).hexdigest()
    altered["ledger_sha"] = altered["artifact_sha"]
    with pytest.raises(ReportSignatureError, match="REPORT_CONTENT_DUPLICATE_KEY"):
        attest_report(altered, TENANT, private)


def test_signer_rejects_inconsistent_ledger_even_with_correct_content_digest(tmp_path):
    _, report, _ = prepared(tmp_path)
    _, private, _ = keys()
    with pytest.raises(ReportSignatureError, match="REPORT_LEDGER_DIGEST_MISMATCH"):
        attest_report({**dict(report), "ledger_sha": "0" * 64}, TENANT, private)


def test_verifier_requires_strict_expected_binding_types(tmp_path):
    _, report, binding = prepared(tmp_path)
    _, private, public = keys()
    envelope = attest_report(report, TENANT, private)
    assert json.loads(envelope["signed_payload"])["run_version"] == 1
    with pytest.raises(ReportSignatureError, match="REPORT_BINDING_MISMATCH"):
        verify_report_attestation(envelope, public, {**binding, "run_version": True})


def _report_with_overflowed_exponent(report):
    content = json.loads(report["content_json"])
    content["totals"]["untrusted_numeric_field"] = "__OVERFLOW_NUMBER__"
    raw = json.dumps(content, sort_keys=True, separators=(",", ":")).replace(
        '"__OVERFLOW_NUMBER__"', "1e999")
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return {**dict(report), "content_json": raw, "artifact_sha": digest, "ledger_sha": digest}


def test_signer_rejects_overflowed_financial_json_exponents(tmp_path):
    _, report, _ = prepared(tmp_path)
    _, private, _ = keys()
    with pytest.raises(ReportSignatureError, match="REPORT_CONTENT_NONFINITE_NUMBER"):
        attest_report(_report_with_overflowed_exponent(report), TENANT, private)


def test_verifier_rejects_validly_signed_overflowed_report_content(tmp_path):
    _, report, binding = prepared(tmp_path)
    signer, private, public = keys()
    envelope = attest_report(report, TENANT, private)
    forged = _report_with_overflowed_exponent(report)
    signed = _resign_modified_payload(envelope, signer, {
        "report_json": forged["content_json"],
        "artifact_sha256": forged["artifact_sha"],
        "ledger_sha256": forged["ledger_sha"],
    })
    expected = {**binding, "artifact_sha256": forged["artifact_sha"]}
    with pytest.raises(ReportSignatureError, match="REPORT_CONTENT_NONFINITE_NUMBER"):
        verify_report_attestation(signed, public, expected)
