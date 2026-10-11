"""Bounded verified CSV artifacts using private S3 or a development byte store."""
import base64
import csv
import hashlib
import io
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException
from datareconcile_ai.infrastructure.store import Store, StoreValidationError, now

MAX_BYTES = 1024 * 1024


def reject(status, code, detail):
    raise HTTPException(status, {"type":"about:blank", "title":"Artifact rejected", "status":status, "code":code, "detail":detail, "request_id":"runtime"})


class ArtifactIngestion:
    def __init__(self, store):
        self.store = store
        self.objects = None
        if os.getenv("S3_ENDPOINT"):
            from datareconcile_ai.infrastructure.object_storage import ObjectStorage
            self.objects = ObjectStorage("datareconcile-ai", MAX_BYTES)

    def secret(self):
        if self.objects is None and os.getenv("APP_ENV", "development") not in {"development", "test"}:
            reject(503, "EXTERNAL_STORAGE_REQUIRED", "Database artifact transfers are restricted to development/test")
        secret = os.getenv("ARTIFACT_SIGNING_SECRET", "")
        if len(secret.encode()) < 32 or secret == os.getenv("DEV_AUTH_SECRET"):
            reject(503, "STORAGE_NOT_CONFIGURED", "A separate artifact signing secret of at least 32 bytes is required")
        return secret

    @contextmanager
    def transaction(self, tenant, lock_key):
        with self.store.conn(tenant) as db:
            if hasattr(self.store, "dsn"):
                db.execute("SELECT pg_advisory_xact_lock(hashtextextended(?, 0))", (lock_key,))
            else:
                db.execute("BEGIN IMMEDIATE")
            yield db

    def record(self, tenant, artifact):
        with self.store.conn(tenant) as db:
            return db.execute("SELECT * FROM source_artifacts WHERE tenant_id=? AND id=?", (tenant, artifact)).fetchone()

    def replay(self, db, tenant, actor, action, key, digest):
        if not key or not 16 <= len(key) <= 128:
            reject(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key must be 16–128 characters")
        old = db.execute("SELECT * FROM source_artifact_commands WHERE tenant_id=? AND actor=? AND action=? AND command_key=?", (tenant, actor, action, key)).fetchone()
        if old and old["request_sha"] != digest:
            reject(409, "IDEMPOTENCY_CONFLICT", "Key was already used with another request")
        return old

    @staticmethod
    def command(db, tenant, actor, action, key, digest, artifact):
        db.execute("INSERT INTO source_artifact_commands VALUES(?,?,?,?,?,?)", (tenant, actor, action, key, digest, artifact))

    def intent(self, tenant, actor, key, values, session_id=None):
        self.secret()
        if values["kind"] != "source" or values["declared_media_type"] not in {None, "text/csv"}:
            reject(422, "ARTIFACT_TYPE_UNSUPPORTED", "Only source CSV artifacts are supported")
        digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        with self.transaction(tenant, f"{tenant}:{actor}:upload:{key}") as db:
            old = self.replay(db, tenant, actor, "upload", key, digest)
            if old:
                artifact = old["artifact_id"]
            else:
                artifact = str(uuid4())
                db.execute("INSERT INTO source_artifacts(tenant_id,id,kind,filename,sha256,size_bytes,declared_media_type,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (tenant, artifact, values["kind"], values["filename"], values["sha256"], values["size_bytes"], values["declared_media_type"], "INTENT_ISSUED", now()))
                self.command(db, tenant, actor, "upload", key, digest, artifact)
        url, expires = self.capability(tenant, artifact, "upload", actor=actor, session_id=session_id)
        return {"artifact_id":artifact, "status":"INTENT_ISSUED", "upload_url":url, "expires_at":expires, "required_headers":{"Content-Type":"text/csv"}}

    def capability(self, tenant, artifact, action, generation=None, actor=None, session_id=None):
        # Signed links in Supabase mode are bound to an online-revocable
        # login session, not merely a still-active tenant membership.
        if os.getenv("AUTH_MODE") == "supabase":
            try:
                session_id = str(UUID(session_id))
            except (ValueError, TypeError, AttributeError):
                reject(503, "ARTIFACT_SESSION_BINDING_REQUIRED", "Authenticated session binding is required")
        expires = int(time.time()) + 300
        token = jwt.encode({"iss":"datareconcile-artifacts", "aud":"artifact-transfer", "sub":artifact, "tenant_id":tenant, "actor_id":actor, "action":action, "generation":generation, "jti":str(uuid4()), "exp":expires, "session_id":session_id}, self.secret(), algorithm="HS256")
        return f"/v1/artifact-transfers/{artifact}?token={token}", datetime.fromtimestamp(expires, timezone.utc).isoformat().replace("+00:00", "Z")

    def verify_capability(self, token, artifact, action):
        try:
            claims = jwt.decode(token, self.secret(), algorithms=["HS256"], issuer="datareconcile-artifacts", audience="artifact-transfer", options={"require":["exp","sub","tenant_id","actor_id","action","jti"]})
            if claims["sub"] != artifact or claims["action"] != action:
                raise jwt.InvalidTokenError("binding")
            tenant = str(UUID(claims["tenant_id"]))
            actor = str(UUID(claims["actor_id"]))
            if os.getenv("AUTH_MODE") == "supabase":
                try:
                    session_id = str(UUID(claims["session_id"]))
                except (KeyError, ValueError, TypeError, AttributeError):
                    raise jwt.InvalidTokenError("session binding missing") from None
                check = getattr(self.store, "session_active", None)
                if not callable(check):
                    reject(503, "ARTIFACT_SESSION_CHECK_UNAVAILABLE", "Session verification backend is unavailable")
                try:
                    active = check(tenant, actor, session_id)
                except Exception:
                    reject(503, "ARTIFACT_SESSION_CHECK_UNAVAILABLE", "Session verification backend is unavailable")
                if not active:
                    raise jwt.InvalidTokenError("session revoked")
            if not self.store.member(tenant, actor):
                raise jwt.InvalidTokenError("membership revoked")
            return claims
        except (jwt.PyJWTError, ValueError):
            reject(403, "INVALID_ARTIFACT_CAPABILITY", "Invalid or expired transfer capability")

    def put(self, tenant, artifact, body):
        self.secret()
        if len(body) > MAX_BYTES:
            reject(413, "ARTIFACT_TOO_LARGE", "CSV source exceeds 1 MiB")
        with self.transaction(tenant, f"artifact:{tenant}:{artifact}") as db:
            row = db.execute("SELECT * FROM source_artifacts WHERE tenant_id=? AND id=?", (tenant, artifact)).fetchone()
            if not row:
                reject(404, "RESOURCE_NOT_FOUND", "Artifact is not visible")
            if len(body) != row["size_bytes"] or hashlib.sha256(body).hexdigest() != row["sha256"]:
                reject(409, "ARTIFACT_DIGEST_MISMATCH", "Bytes do not match declared size and digest")
            if row["content_base64"] is not None:
                self.bytes(row)
                return row["object_generation"]
            if row["status"] != "INTENT_ISSUED":
                reject(409, "ARTIFACT_STATE_INVALID", "Artifact is not pending upload")
            if self.objects:
                generation = self.objects.put(tenant, artifact, body, row["sha256"], row["size_bytes"])["generation"]
                encoded = "s3:" + generation  # Legacy locator field, immutable after upload.
            else:
                generation = str(uuid4())
                encoded = base64.b64encode(body).decode()
            db.execute("UPDATE source_artifacts SET content_base64=?,object_generation=?,status='QUARANTINED' WHERE tenant_id=? AND id=?", (encoded, generation, tenant, artifact))
            return generation

    def bytes(self, row):
        if not row or row["content_base64"] is None:
            reject(409, "ARTIFACT_BYTES_MISSING", "Uploaded bytes are required")
        if str(row["content_base64"]).startswith("s3:"):
            if not self.objects or row["content_base64"] != "s3:" + row["sha256"]:
                reject(409, "ARTIFACT_INTEGRITY_FAILURE", "Invalid external object locator")
            return self.objects.read(row["tenant_id"], row["id"], row["object_generation"], row["sha256"], row["size_bytes"])
        try:
            body = base64.b64decode(row["content_base64"], validate=True)
        except ValueError:
            reject(409, "ARTIFACT_INTEGRITY_FAILURE", "Invalid stored encoding")
        if len(body) > MAX_BYTES or len(body) != row["size_bytes"] or hashlib.sha256(body).hexdigest() != row["sha256"]:
            reject(409, "ARTIFACT_INTEGRITY_FAILURE", "Stored bytes do not match metadata")
        return body

    def commit(self, tenant, actor, artifact, key, values):
        self.secret()
        digest = hashlib.sha256(json.dumps({"artifact":artifact, **values}, sort_keys=True).encode()).hexdigest()
        with self.transaction(tenant, f"{tenant}:{actor}:commit:{key}") as db:
            old = self.replay(db, tenant, actor, "commit", key, digest)
            row = db.execute("SELECT * FROM source_artifacts WHERE tenant_id=? AND id=?", (tenant, artifact)).fetchone()
            if not row:
                reject(404, "RESOURCE_NOT_FOUND", "Artifact is not visible")
            if any(row[name] != values[name] for name in ("sha256", "size_bytes", "object_generation")):
                reject(409, "ARTIFACT_GENERATION_MISMATCH", "Committed metadata differs from uploaded object")
            body = self.bytes(row)
            try:
                text = body.decode("utf-8")
                if "\x00" in text:
                    raise ValueError("NUL")
                first = next(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))), None)
                Store.parse_csv(text, first.get("currency", "") if first else "")
            except (csv.Error, ValueError) as error:
                code = error.code if isinstance(error, StoreValidationError) else "CSV_SOURCE_INVALID"
                reject(422, code, "Source must be valid UTF-8 CSV with the import schema")
            if row["status"] not in {"QUARANTINED", "AVAILABLE"}:
                reject(409, "ARTIFACT_STATE_INVALID", "Artifact is not eligible for commit")
            db.execute("UPDATE source_artifacts SET status='AVAILABLE' WHERE tenant_id=? AND id=?", (tenant, artifact))
            if not old:
                self.command(db, tenant, actor, "commit", key, digest, artifact)
        return self.record(tenant, artifact)

    def source(self, tenant, artifact, digest):
        self.secret()
        row = self.record(tenant, artifact)
        if not row or row["status"] != "AVAILABLE":
            reject(409, "SOURCE_ARTIFACT_NOT_AVAILABLE", "A verified source artifact is required")
        if row["sha256"] != digest:
            reject(409, "SOURCE_DIGEST_MISMATCH", "Import digest differs from source artifact")
        return self.bytes(row).decode("utf-8")

    def download(self, tenant, actor, artifact, key, session_id=None):
        self.secret()
        digest = hashlib.sha256(artifact.encode()).hexdigest()
        with self.transaction(tenant, f"{tenant}:{actor}:download:{key}") as db:
            old = self.replay(db, tenant, actor, "download", key, digest)
            row = db.execute("SELECT * FROM source_artifacts WHERE tenant_id=? AND id=?", (tenant, artifact)).fetchone()
            if not row or row["status"] != "AVAILABLE":
                reject(409, "ARTIFACT_NOT_AVAILABLE", "A verified artifact is required")
            self.bytes(row)
            if not old:
                self.command(db, tenant, actor, "download", key, digest, artifact)
        url, expires = self.capability(tenant, artifact, "download", row["object_generation"], actor=actor, session_id=session_id)
        return {"artifact_id":artifact, "download_url":url, "expires_at":expires, "object_generation":row["object_generation"]}
