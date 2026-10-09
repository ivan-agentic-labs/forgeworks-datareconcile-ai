from __future__ import annotations
from datareconcile_ai.infrastructure.report_downloads import issue_download, verify_download
from datareconcile_ai.presentation.authentication import decode_bearer

import os
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from datareconcile_ai.infrastructure.store import Store, StoreValidationError

ROOT = Path(__file__).resolve().parents[4]


class Import(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_label: str = Field(min_length=1, max_length=200)
    artifact_id: UUID
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    profile_version: str = Field(min_length=1, max_length=100)
    # JSON transport is intentionally synthetic/test-only; production artifact
    # ingestion remains an explicit quarantine/upload workflow.
    csv_content: str | None = Field(default=None, max_length=2_000_000)


class Reconcile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left_batch_id: UUID
    right_batch_id: UUID
    rule_version: str = Field(min_length=1, max_length=100)


class Resolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_version: int = Field(ge=1)


class Finalize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    approved_summary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def reject(status: int, code: str, detail: str):
    raise HTTPException(
        status_code=status,
        detail={
            "type": "about:blank",
            "title": "Request rejected",
            "status": status,
            "code": code,
            "detail": detail,
            "request_id": "runtime",
        },
    )


def auth(authorization: Annotated[str | None, Header()] = None):
    return decode_bearer(authorization)


def scope(required: str, store: Store):
    def dependency(c=Depends(auth)):
        # Tenant context is derived only from the verified token and membership;
        # no request body/path value can widen the authorization scope.
        if not c.get("tenant_id") or not c.get("sub") or not store.member(c["tenant_id"], c["sub"]):
            reject(403, "TENANT_CONTEXT_INVALID", "Verified membership is required")
        if required not in set(str(c.get("scope", "")).split()):
            reject(403, "INSUFFICIENT_SCOPE", f"Scope {required} is required")
        return c

    return dependency


def _batch_response(row):
    return {
        "id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "source_label": row["source_label"],
        "file_sha256": row["file_sha"],
        "currency": row["currency"],
        "row_count": row["row_count"],
        "job_id": row["job_id"],
        "profile_version": row["profile_version"],
    }


def _report_response(row):
    import json

    totals = json.loads(row["totals_json"]) if row["totals_json"] else None
    return {
        "id": row["id"],
        "status": "FINALIZED",
        "created_at": row["finalized_at"],
        "run_id": row["run_id"],
        "ledger_sha256": row["ledger_sha"],
        "artifact_sha256": row["artifact_sha"],
        "finalized_at": row["finalized_at"],
        "source_revision": row["source_revision"],
        "approved_summary_sha256": row["approved_summary_sha"],
        "run_version": row["run_version"],
        "totals": totals,
    }


def create_app(db_path=None, seed=False):
    if os.getenv("RECONCILE_DATABASE_URL"):
        from datareconcile_ai.infrastructure.postgres_store import PostgresStore
        store = PostgresStore(os.environ["RECONCILE_DATABASE_URL"])
    else:
        if os.getenv("APP_ENV", "development") not in {"development", "test"}:
            raise ValueError("SQLite is restricted to development/test")
        store = Store(db_path or os.getenv("RECONCILE_DB_PATH", str(ROOT / ".runtime/reconcile.db")))
    if seed:
        store.seed()
    app = FastAPI(title="DataReconcile AI MVP", version="0.2.0")
    app.state.store = store

    @app.exception_handler(HTTPException)
    async def errors(_, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail if isinstance(exc.detail, dict) else {
                "type": "about:blank", "title": "Request rejected", "status": exc.status_code,
                "code": "REQUEST_REJECTED", "detail": str(exc.detail), "request_id": "runtime",
            },
            media_type="application/problem+json" if exc.status_code >= 400 else "application/json",
        )

    @app.get("/healthz")
    def health():
        return {"status": "ok", "service": "datareconcile-ai"}

    @app.post("/v1/import-batches", status_code=202)
    def imp(body: Import, c=Depends(scope("import:create", store))):
        try:
            row = store.batch(
                c["tenant_id"], body.source_label, body.file_sha256, body.currency,
                profile_version=body.profile_version, artifact_id=str(body.artifact_id), csv_content=body.csv_content,
            )
        except StoreValidationError as exc:
            status = 409 if exc.code == "DUPLICATE_IMPORT" else 422
            return reject(status, exc.code, exc.detail)
        return _batch_response(row)

    @app.get("/v1/import-batches/{bid}/rows")
    def rows(bid: UUID, c=Depends(scope("import:read", store))):
        if not store.get_batch(c["tenant_id"], str(bid)):
            return reject(404, "RESOURCE_NOT_FOUND", "Import is not visible")
        items = [
            {
                "id": x["id"], "batch_id": x["batch_id"], "external_ref": x["external_ref"],
                "currency": x["currency"], "amount_minor": x["amount_minor"],
                "occurred_at": x["occurred_at"], "row_status": x["status"],
                "transaction_type": x["transaction_type"], "row_number": x["row_number"],
            }
            for x in store.rows(c["tenant_id"], str(bid))
        ]
        return {"items": items, "next_cursor": None, "has_more": False}

    @app.post("/v1/reconciliation-runs", status_code=202)
    def reconcile(body: Reconcile, c=Depends(scope("reconcile:run", store))):
        left = store.get_batch(c["tenant_id"], str(body.left_batch_id))
        right = store.get_batch(c["tenant_id"], str(body.right_batch_id))
        if not left or not right:
            return reject(404, "RESOURCE_NOT_FOUND", "Import is not visible")
        if left["currency"] != right["currency"]:
            return reject(409, "CURRENCY_MISMATCH", "Only same-currency matching is supported")
        try:
            run = store.run(c["tenant_id"], str(body.left_batch_id), str(body.right_batch_id), body.rule_version)
        except StoreValidationError as exc:
            return reject(404 if exc.code == "RESOURCE_NOT_FOUND" else 422, exc.code, exc.detail)
        return {
            "id": run["id"], "status": run["status"], "created_at": run["created_at"],
            "left_batch_id": run["left_batch"], "right_batch_id": run["right_batch"],
            "rule_version": run["rule"], "job_id": run["job_id"],
            "unmatched_count": run["unmatched"], "source_revision": run["source_revision"],
            "version": run["version"],
        }

    @app.get("/v1/reconciliation-runs/{rid}/exceptions")
    def exceptions(rid: UUID, c=Depends(scope("reconcile:read", store))):
        if not store.get_run(c["tenant_id"], str(rid)):
            return reject(404, "RESOURCE_NOT_FOUND", "Run is not visible")
        items = [
            {
                "id": x["id"], "run_id": x["run_id"], "reason_code": x["reason"],
                "left_transaction_id": x["left_id"], "right_transaction_id": x["right_id"],
                "status": x["status"], "version": x["version"], "resolution_policy": x["resolution_policy"],
            }
            for x in store.exceptions(c["tenant_id"], str(rid))
        ]
        return {"items": items, "next_cursor": None, "has_more": False}

    @app.post("/v1/exceptions/{eid}/resolutions", status_code=201)
    def resolve(eid: UUID, body: Resolve, c=Depends(scope("exception:approve", store))):
        result, status = store.resolve(c["tenant_id"], str(eid), c["sub"], body.decision, body.evidence_sha256, body.expected_version)
        if status == "NOT_FOUND":
            return reject(404, "RESOURCE_NOT_FOUND", "Exception is not visible")
        if status == "STALE":
            return reject(409, "STALE_VERSION", "Exception version is stale")
        if status == "INVALID_DECISION":
            return reject(422, "INVALID_DECISION", "Decision must be an explicitly supported review disposition")
        if status == "POLICY_VIOLATION":
            return reject(422, "REFUND_REVERSAL_POLICY_VIOLATION", "Refund/reversal decisions require a matching explicit transaction_type policy")
        return {
            "id": result, "status": "RECORDED", "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "exception_id": str(eid), "reviewer_id": c["sub"], "decision": body.decision,
            "evidence_sha256": body.evidence_sha256,
        }

    @app.post("/v1/reconciliation-runs/{rid}/finalize", status_code=201)
    def finalize(rid: UUID, body: Finalize, c=Depends(scope("report:finalize", store))):
        report, status = store.finalize(c["tenant_id"], str(rid), body.approved_summary_sha256, body.expected_version)
        if status == "NOT_FOUND":
            return reject(404, "RESOURCE_NOT_FOUND", "Run is not visible")
        if status == "STALE":
            return reject(409, "STALE_VERSION", "Run is stale")
        if status == "OPEN_EXCEPTIONS":
            return reject(409, "OPEN_EXCEPTIONS", "All exceptions require an authorized resolution")
        if status == "ALLOCATION_NOT_UNIQUE":
            return reject(409, "ALLOCATION_NOT_UNIQUE", "Every source transaction may be allocated at most once")
        if status == "CONSERVATION_FAILED":
            return reject(409, "CONSERVATION_FAILED", "The report has no valid conservation proof")
        return _report_response(report)

    @app.get("/v1/reports/{rid}/download")
    def download(rid: UUID, c=Depends(scope("report:read", store))):
        report = store.report(c["tenant_id"], str(rid))
        if not report:
            return reject(404, "RESOURCE_NOT_FOUND", "Report is not visible")
        download_token, expires = issue_download(c["tenant_id"], str(rid), report["artifact_sha"])
        return {
            "report_id": report["id"],
            "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat().replace("+00:00", "Z"),
            "download_token": download_token,
            "download_url": f"/v1/report-transfers/{rid}?token={download_token}",
            "source_revision": report["source_revision"],
            "totals": __import__("json").loads(report["totals_json"]),
        }

    @app.get("/v1/report-transfers/{rid}")
    def transfer_report(rid: UUID, token: str):
        claims = verify_download(token, str(rid))
        report = store.report(claims["tenant_id"], str(rid))
        if not report or not report["content_json"]:
            reject(409, "REPORT_BYTES_UNAVAILABLE", "Persisted report bytes are unavailable")
        body = report["content_json"].encode("utf-8")
        if hashlib.sha256(body).hexdigest() != claims["sha256"] or claims["sha256"] != report["artifact_sha"]:
            reject(409, "REPORT_INTEGRITY_FAILURE", "Report bytes do not match the signed digest")
        return Response(body, media_type="application/json", headers={"Content-Disposition": "attachment", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})

    @app.get("/v1/jobs/{jid}")
    def job(jid: UUID, c=Depends(scope("job:read", store))):
        with store.conn(c["tenant_id"]) as db:
            row = db.execute("SELECT * FROM runs WHERE tenant_id=? AND job_id=?", (c["tenant_id"], str(jid))).fetchone()
        if not row:
            return reject(404, "RESOURCE_NOT_FOUND", "Job is not visible")
        return {
            "id": row["job_id"], "kind": "reconciliation", "state": row["status"],
            "created_at": row["created_at"], "state_version": row["version"],
            "attempt_count": 1, "last_error_code": None,
        }

    return app


app = create_app(seed=os.getenv("RECONCILE_SEED_FIXTURE", "0") == "1")

