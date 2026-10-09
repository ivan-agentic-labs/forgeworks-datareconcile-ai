"""PostgreSQL runtime adapter; migrations are applied separately by the migration role."""
from __future__ import annotations

import inspect
import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from datareconcile_ai.infrastructure.store import Store

TENANT_CONTEXT = ContextVar("reconcile_tenant", default=None)
ROLE = "fw_datareconcile_ai_rw"
ALIASES = {"batches": "import_batches", "rows_": "import_rows", "runs": "reconcile_runs", "exceptions": "exception_cases"}
COLUMN_ALIASES = {"file_sha": "file_sha256", "left_batch": "left_batch_id", "right_batch": "right_batch_id", "rule": "rule_version", "unmatched": "unmatched_count", "reason": "reason_code", "ledger_sha": "ledger_sha256", "artifact_sha": "artifact_sha256"}
ACTIVE_CONNECTION = ContextVar("reconcile_connection", default=None)
INSERT_COLUMNS = {}


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def normalize(row):
    if row is None:
        return None
    return Row({({value: key for key, value in COLUMN_ALIASES.items()} | {"row_status": "status", "left_transaction_id": "left_id", "right_transaction_id": "right_id"}).get(key, key): str(value) if isinstance(value, UUID) else value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else json.dumps(value, sort_keys=True, separators=(",", ":")) if isinstance(value, (dict,list)) else value for key, value in row.items()})


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.rowcount = cursor.rowcount

    def fetchone(self):
        return normalize(self.cursor.fetchone())

    def fetchall(self):
        return [normalize(row) for row in self.cursor.fetchall()]


class Connection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement, parameters=()):
        if statement == "BEGIN IMMEDIATE":
            statement = "SELECT 1"  # The outer transaction already holds the tenant advisory lock.
        if re.search(r"\b(?:INTO|FROM|UPDATE) rows_\b", statement):
            statement = re.sub(r"\bstatus\b", "row_status", statement)
        if re.search(r"\b(?:INTO|FROM|UPDATE) exceptions\b", statement):
            statement = re.sub(r"\bleft_id\b", "left_transaction_id", statement)
            statement = re.sub(r"\bright_id\b", "right_transaction_id", statement)
        for source, target in COLUMN_ALIASES.items():
            statement = re.sub(r"\b" + source + r"\b", target, statement)
        for table, columns in INSERT_COLUMNS.items():
            statement = re.sub(r"\bINTO " + table + r" VALUES", "INTO " + table + "(" + columns + ") VALUES", statement)
        for source, target in ALIASES.items():
            statement = re.sub(r"\b" + source + r"\b", target, statement)
        statement = statement.replace("ORDER BY rowid", "ORDER BY id")
        if statement.startswith("INSERT OR IGNORE INTO"):
            statement = statement.replace("INSERT OR IGNORE INTO", "INSERT INTO", 1) + " ON CONFLICT DO NOTHING"
        statement = statement.replace("?", "%s")
        try:
            # A savepoint preserves SQLite's recoverable statement-failure semantics.
            with self.connection.transaction():
                cursor = self.connection.execute(statement, parameters)
            return Cursor(cursor)
        except psycopg.errors.UniqueViolation as error:
            raise sqlite3.IntegrityError("UNIQUE constraint rejected the command") from error
        except psycopg.IntegrityError as error:
            raise sqlite3.IntegrityError("Database integrity constraint rejected the command") from error


def tenant_method(method):
    @wraps(method)
    def wrapped(self, tenant, *args, **kwargs):
        tenant = str(UUID(str(tenant)))
        token = TENANT_CONTEXT.set(tenant)
        try:
            return method(self, tenant, *args, **kwargs)
        finally:
            TENANT_CONTEXT.reset(token)
    return wrapped


class PostgresStore(Store):
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.lock = threading.RLock()
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5) as db:
            role = db.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            if role["rolsuper"] or role["rolbypassrls"]:
                raise ValueError("Runtime must not use a superuser or BYPASSRLS role")
            if not db.execute("SELECT pg_has_role(current_user, %s, 'MEMBER') AS allowed", (ROLE,)).fetchone()["allowed"]:
                raise ValueError("Runtime login must be a member of the tenant application role")
            if db.execute("SELECT 1 FROM pg_tables WHERE schemaname=current_schema() AND tableowner=current_user AND tablename IN ('import_batches','import_rows','reconcile_runs','exception_cases','reports','memberships','allocations','resolutions','audit_events')").fetchone():
                raise ValueError("Runtime must not own product tables")
            attributes = db.execute("SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname=%s", (ROLE,)).fetchone()
            if not attributes or any(attributes.values()):
                raise ValueError("Tenant group role must be NOLOGIN, NOSUPERUSER and NOBYPASSRLS")
            if not db.execute("SELECT 1 FROM information_schema.columns WHERE table_name='reports' AND column_name='content_json'").fetchone():
                raise ValueError("Apply migration 002 with the migration role before starting runtime")

    @tenant_method
    def member(self, tenant, user):
        try:
            user = str(UUID(str(user)))
        except ValueError:
            return False  # No provisioned UUID identity mapping; fail closed before SQL.
        with self.conn() as db:
            return db.execute("SELECT 1 FROM memberships WHERE tenant_id=? AND user_id=? AND status='ACTIVE'", (tenant, user)).fetchone() is not None

    @contextmanager
    def conn(self, tenant=None):
        tenant = tenant or TENANT_CONTEXT.get()
        if tenant is None:
            raise ValueError("A transaction requires an explicit tenant context")
        tenant = str(UUID(str(tenant)))
        active = ACTIVE_CONNECTION.get()
        if active:
            if active[0] != id(self) or active[1] != tenant:
                raise ValueError("Nested transaction cannot change store or tenant")
            yield active[2]
            return
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5) as db:
            db.execute("SET LOCAL ROLE fw_datareconcile_ai_rw")
            db.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
            # Conservative serialization for this low-volume adapter. No pooling.
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (tenant,))
            connection = Connection(db)
            token = ACTIVE_CONNECTION.set((id(self), tenant, connection))
            try:
                yield connection
            finally:
                ACTIVE_CONNECTION.reset(token)

    def seed(self):
        raise ValueError("PostgreSQL provisioning requires a separate migration/provisioning role")

for name, method in inspect.getmembers(Store, predicate=inspect.isfunction):
    parameters = list(inspect.signature(method).parameters)
    if len(parameters) > 1 and parameters[1] == "tenant" and name not in PostgresStore.__dict__ and not isinstance(inspect.getattr_static(Store, name), staticmethod):
        setattr(PostgresStore, name, tenant_method(method))
