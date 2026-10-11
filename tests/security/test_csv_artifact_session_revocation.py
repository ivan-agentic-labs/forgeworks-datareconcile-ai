"""Verify live session revocation for signed CSV upload and download URLs."""
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4
import time

import jwt
import pytest
from fastapi import HTTPException

from datareconcile_ai.infrastructure.artifact_ingestion import ArtifactIngestion

SECRET = "synthetic-csv-artifact-session-secret-with-adequate-length"


@pytest.fixture(autouse=True)
def config(monkeypatch):
    # Test mode uses no network object storage, but exercises the same signed
    # capabilities that production emits with AUTH_MODE=supabase.
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("ARTIFACT_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("DEV_AUTH_SECRET", "different-synthetic-auth-secret")
    monkeypatch.delenv("S3_ENDPOINT", raising=False)


def ids():
    return tuple(str(uuid4()) for _ in range(4))


def token_from(url):
    return parse_qs(urlsplit(url).query)["token"][0]


def store_with_session(allowed, *, raise_on_check=False):
    def session_active(_tenant, _actor, _sid):
        if raise_on_check:
            raise RuntimeError("simulated unavailable session backend")
        return allowed
    return SimpleNamespace(session_active=session_active, member=lambda t, a: True)


def denied(fn, status, code):
    with pytest.raises(HTTPException) as exc:
        fn()
    assert exc.value.status_code == status
    assert exc.value.detail["code"] == code


@pytest.mark.parametrize("action", ["upload", "download"])
def test_signed_csv_capability_requires_same_active_session(action):
    tenant, actor, artifact, sid = ids()
    store = store_with_session(True)
    service = ArtifactIngestion(store)
    url, _ = service.capability(tenant, artifact, action, actor=actor, session_id=sid)
    claims = service.verify_capability(token_from(url), artifact, action)
    assert claims["session_id"] == sid
    assert claims["tenant_id"] == tenant
    assert claims["actor_id"] == actor


@pytest.mark.parametrize("action", ["upload", "download"])
def test_revoked_login_denies_unexpired_signed_csv_capability(action):
    tenant, actor, artifact, sid = ids()
    service = ArtifactIngestion(store_with_session(False))
    url, expires = service.capability(tenant, artifact, action, actor=actor, session_id=sid)
    assert expires
    denied(lambda: service.verify_capability(token_from(url), artifact, action), 403, "INVALID_ARTIFACT_CAPABILITY")


def test_unavailable_session_checker_fails_closed():
    tenant, actor, artifact, sid = ids()
    signer = ArtifactIngestion(store_with_session(True))
    url, _ = signer.capability(tenant, artifact, "download", actor=actor, session_id=sid)
    checker = ArtifactIngestion(store_with_session(False, raise_on_check=True))
    denied(lambda: checker.verify_capability(token_from(url), artifact, "download"),
           503, "ARTIFACT_SESSION_CHECK_UNAVAILABLE")
    checker.store = SimpleNamespace(member=lambda *_: True)
    denied(lambda: checker.verify_capability(token_from(url), artifact, "download"),
           503, "ARTIFACT_SESSION_CHECK_UNAVAILABLE")


@pytest.mark.parametrize("session_id", [None, "", "invalid", {}, 42])
def test_supabase_cannot_issue_unbound_csv_artifact_url(session_id):
    tenant, actor, artifact, _ = ids()
    service = ArtifactIngestion(store_with_session(True))
    denied(lambda: service.capability(tenant, artifact, "upload", actor=actor, session_id=session_id),
           503, "ARTIFACT_SESSION_BINDING_REQUIRED")


def test_legacy_signed_csv_transfer_without_session_is_rejected():
    tenant, actor, artifact, _ = ids()
    service = ArtifactIngestion(store_with_session(True))
    claims = {"iss": "datareconcile-artifacts", "aud": "artifact-transfer",
              "sub": artifact, "tenant_id": tenant, "actor_id": actor,
              "action": "download", "jti": str(uuid4()), "exp": int(time.time())+300}
    legacy = jwt.encode(claims, SECRET, algorithm="HS256")
    denied(lambda: service.verify_capability(legacy, artifact, "download"),
           403, "INVALID_ARTIFACT_CAPABILITY")


def test_csv_capability_cannot_switch_artifact_or_action():
    tenant, actor, artifact, sid = ids()
    service = ArtifactIngestion(store_with_session(True))
    url, _ = service.capability(tenant, artifact, "upload", actor=actor, session_id=sid)
    token = token_from(url)
    denied(lambda: service.verify_capability(token, str(uuid4()), "upload"),
           403, "INVALID_ARTIFACT_CAPABILITY")
    denied(lambda: service.verify_capability(token, artifact, "download"),
           403, "INVALID_ARTIFACT_CAPABILITY")


def test_local_dev_csv_capability_remains_compatible(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "development")
    tenant, actor, artifact, _ = ids()
    service = ArtifactIngestion(store_with_session(True))
    url, _ = service.capability(tenant, artifact, "download", actor=actor)
    assert service.verify_capability(token_from(url), artifact, "download")["session_id"] is None
