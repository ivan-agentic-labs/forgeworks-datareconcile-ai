import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from datareconcile_ai.infrastructure.store import TENANT, USER
from datareconcile_ai.main import Resolve, Finalize, create_app

PROPOSAL = '33333333-3333-3333-3333-333333333333'


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    app = create_app(str(tmp_path_factory.mktemp('version') / 'db.sqlite'), seed=True)
    with TestClient(app, raise_server_exceptions=False) as value:
        yield value


def headers(scope):
    token = jwt.encode({'sub': USER, 'tenant_id': TENANT, 'scope': scope,
                        'iss': 'https://issuer.synthetic.invalid', 'aud': 'forgeworks-api',
                        'exp': datetime.now(timezone.utc) + timedelta(minutes=5)},
                       'forgeworks-development-secret-32-plus', algorithm='HS256')
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'Idempotency-Key': 'version-regression-0001'}


CASES = [
    ('resolve', '/v1/exceptions/' + PROPOSAL + '/resolutions', 'exception:approve', {'decision': 'accept-as-investigated', 'evidence_sha256': 'a' * 64}, 'expected_version'),
    ('finalize', '/v1/reconciliation-runs/' + PROPOSAL + '/finalize', 'report:finalize', {'approved_summary_sha256': 'a' * 64}, 'expected_version'),
]


@pytest.mark.parametrize('method,path,scope,base,field', CASES)
@pytest.mark.parametrize('version', [True, '1', 1.0, 1.5, float('inf'), 0])
def test_invalid_version_is_rejected_before_store(client, monkeypatch, method, path, scope, base, field, version):
    called = []
    original = getattr(client.app.state.store, method)
    def tracked(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(client.app.state.store, method, tracked)
    response = client.post(path, headers=headers(scope), content=json.dumps({**base, field: version}).replace('Infinity', '1e400'))
    assert response.status_code == 422
    assert response.json()['code'] == 'INVALID_REQUEST'
    assert not called
    assert 'input' not in response.json()


@pytest.mark.parametrize('version', [1, 2, 2147483647])
def test_integer_versions_remain_accepted(version):
    assert Resolve(decision='accept-as-investigated', evidence_sha256='a' * 64, expected_version=version).expected_version == version
    assert Finalize(approved_summary_sha256='a' * 64, expected_version=version).expected_version == version
