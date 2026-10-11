"""Signed financial report downloads fail closed on Supabase session revocation."""
import time
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException

from datareconcile_ai.infrastructure.report_downloads import issue_download, verify_download

SECRET = "synthetic-financial-report-signing-secret-different-from-development"


@pytest.fixture(autouse=True)
def staging_config(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "supabase")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ARTIFACT_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("DEV_AUTH_SECRET", "unrelated-development-authentication-secret")


def ids():
    return tuple(str(uuid4()) for _ in range(4))


def denied(fn, code, status):
    with pytest.raises(HTTPException) as exc:
        fn()
    assert exc.value.status_code == status
    assert exc.value.detail["code"] == code


def test_download_bound_to_issuing_active_session():
    tenant, actor, report, sid = ids()
    token, expiry = issue_download(tenant, actor, report, "b" * 64, sid)
    checked = []
    def active(t, a, s):
        checked.append((t, a, s))
        return True
    claims = verify_download(token, report, SimpleNamespace(session_active=active))
    assert expiry > int(time.time())
    assert checked == [(tenant, actor, sid)]
    assert claims["sha256"] == "b" * 64


def test_valid_signature_and_expiry_cannot_override_revoked_session():
    tenant, actor, report, sid = ids()
    token, expiry = issue_download(tenant, actor, report, "b" * 64, sid)
    assert expiry > int(time.time())
    denied(lambda: verify_download(token, report, SimpleNamespace(session_active=lambda *_: False)),
           "REPORT_SESSION_REVOKED", 403)


def test_missing_or_failing_session_backend_rejects_download():
    tenant, actor, report, sid = ids()
    token, _ = issue_download(tenant, actor, report, "b" * 64, sid)
    denied(lambda: verify_download(token, report), "REPORT_SESSION_CHECK_UNAVAILABLE", 503)
    def outage(*_):
        raise RuntimeError("synthetic auth.sessions connection failure")
    denied(lambda: verify_download(token, report, SimpleNamespace(session_active=outage)),
           "REPORT_SESSION_CHECK_UNAVAILABLE", 503)


@pytest.mark.parametrize("missing", [None, "", "not-a-uuid", {}, 123])
def test_no_unbound_supabase_report_download_link_can_be_minted(missing):
    tenant, actor, report, _ = ids()
    denied(lambda: issue_download(tenant, actor, report, "b" * 64, missing),
           "REPORT_SESSION_BINDING_REQUIRED", 503)


def test_pre_fix_legacy_signed_report_capability_has_no_session_and_is_rejected():
    tenant, actor, report, sid = ids()
    old_claims = {"iss": "forgeworks-reports", "aud": "report-download", "sub": report,
                  "tenant_id": tenant, "actor": actor, "sha256": "b" * 64,
                  "exp": int(time.time()) + 300}
    token = jwt.encode(old_claims, SECRET, algorithm="HS256")
    calls = []
    denied(lambda: verify_download(token, report, SimpleNamespace(session_active=lambda *_: calls.append(True) or True)),
           "INVALID_REPORT_CAPABILITY", 403)
    assert calls == []


def test_report_capability_cannot_be_reused_for_different_id():
    tenant, actor, report, sid = ids()
    token, _ = issue_download(tenant, actor, report, "b" * 64, sid)
    calls = []
    denied(lambda: verify_download(token, str(uuid4()), SimpleNamespace(session_active=lambda *_: calls.append(True))),
           "INVALID_REPORT_CAPABILITY", 403)
    assert calls == []


def test_offline_development_links_remain_compatible(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "development")
    tenant, actor, report, _ = ids()
    token, _ = issue_download(tenant, actor, report, "b" * 64)
    assert verify_download(token, report)["session_id"] is None
