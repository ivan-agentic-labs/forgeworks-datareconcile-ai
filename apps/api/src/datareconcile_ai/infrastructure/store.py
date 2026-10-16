from __future__ import annotations

import csv
from collections import Counter, defaultdict, deque
import hashlib
import io
import json
import os
import re
import unicodedata
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

TENANT = "00000000-0000-0000-0000-000000000001"
USER = "00000000-0000-0000-0000-000000000010"
MAX_INT64 = 2**63 - 1
MAX_CSV_BYTES = 1_048_576
MAX_IMPORT_ROWS = 10_000
MIN_INT64 = -(2**63)
AMOUNT_RE = re.compile(r"^-?(0|[1-9][0-9]*)$")
CSV_REQUIRED = ("external_ref", "currency", "amount_minor", "occurred_at")
CSV_ALLOWED = set(CSV_REQUIRED) | {"transaction_type"}
TRANSACTION_TYPES = {"normal", "refund", "reversal"}
RESOLUTION_DECISIONS = {
    "accept-as-investigated",
    "accept-as-refund",
    "accept-as-reversal",
    "reject",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso(value: str) -> str:
    # fromisoformat accepts arbitrary date/time separators, truncated clock
    # components and silently discards fractional precision beyond 6 digits.
    # Do not normalize ambiguous financial source timestamps into audit rows.
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
        value,
    ):
        raise ValueError("occurred_at requires RFC3339 seconds, an offset, and at most 6 fractional digits")
    # RFC3339 -00:00 denotes an unknown local offset. Collapsing it to UTC
    # would falsely claim the original financial event timezone was known.
    if value.endswith("-00:00"):
        raise ValueError("occurred_at has an unknown timezone offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("occurred_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("occurred_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class StoreValidationError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class Store:
    def __init__(self, path: str):
        self.path = path
        self.allow_exact_reference_date_rule = (
            os.getenv("APP_ENV", "development").lower() in {"development", "test"}
            and os.getenv("ENABLE_EXACT_REFERENCE_DATE_RULE", "").lower() in {"1", "true", "yes"}
        )
        self.allow_fixture_imports = False
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def conn(self, tenant=None) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def init(self) -> None:
        with self.conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenants(
                    id TEXT PRIMARY KEY, slug TEXT, status TEXT
                );
                CREATE TABLE IF NOT EXISTS source_artifacts(
                    tenant_id TEXT NOT NULL,id TEXT NOT NULL,kind TEXT NOT NULL,
                    filename TEXT NOT NULL,sha256 TEXT NOT NULL,size_bytes INTEGER NOT NULL,
                    declared_media_type TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL,
                    object_generation TEXT,content_base64 TEXT,PRIMARY KEY(tenant_id,id)
                );
                CREATE TABLE IF NOT EXISTS source_artifact_commands(
                    tenant_id TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,
                    command_key TEXT NOT NULL,request_sha TEXT NOT NULL,artifact_id TEXT NOT NULL,
                    PRIMARY KEY(tenant_id,actor,action,command_key)
                );
                CREATE TABLE IF NOT EXISTS memberships(
                    tenant_id TEXT, user_id TEXT, role TEXT, status TEXT,
                    PRIMARY KEY(tenant_id,user_id)
                );
                CREATE TABLE IF NOT EXISTS batches(
                    tenant_id TEXT, id TEXT, source_label TEXT, file_sha TEXT,
                    currency TEXT, profile_version TEXT NOT NULL DEFAULT 'strict-v1',
                    artifact_id TEXT, row_count INTEGER, status TEXT, job_id TEXT,
                    created_at TEXT, PRIMARY KEY(tenant_id,id),
                    UNIQUE(tenant_id,file_sha)
                );
                CREATE TABLE IF NOT EXISTS rows_(
                    tenant_id TEXT, id TEXT, batch_id TEXT, external_ref TEXT,
                    currency TEXT, amount_minor INTEGER, occurred_at TEXT,
                    transaction_type TEXT NOT NULL DEFAULT 'normal', row_number INTEGER,
                    raw_row_sha TEXT, status TEXT, PRIMARY KEY(tenant_id,id),
                    UNIQUE(tenant_id,batch_id,external_ref),
                    UNIQUE(tenant_id,batch_id,row_number)
                );
                CREATE TABLE IF NOT EXISTS runs(
                    tenant_id TEXT, id TEXT, left_batch TEXT, right_batch TEXT,
                    rule TEXT, status TEXT, job_id TEXT, unmatched INTEGER,
                    version INTEGER, source_revision TEXT, created_at TEXT,
                    PRIMARY KEY(tenant_id,id),
                    UNIQUE(tenant_id,left_batch,right_batch,rule)
                );
                CREATE TABLE IF NOT EXISTS allocations(
                    tenant_id TEXT, id TEXT, run_id TEXT, left_id TEXT, right_id TEXT,
                    rule TEXT, matched_amount_minor INTEGER, currency TEXT,
                    PRIMARY KEY(tenant_id,id),
                    UNIQUE(tenant_id,run_id,left_id),
                    UNIQUE(tenant_id,run_id,right_id)
                );
                CREATE TABLE IF NOT EXISTS exceptions(
                    tenant_id TEXT, id TEXT, run_id TEXT, reason TEXT, left_id TEXT,
                    right_id TEXT, status TEXT, version INTEGER,
                    resolution_policy TEXT, PRIMARY KEY(tenant_id,id)
                );
                CREATE TABLE IF NOT EXISTS resolutions(
                    tenant_id TEXT, id TEXT, exception_id TEXT, reviewer_id TEXT,
                    decision TEXT, evidence_sha TEXT, expected_version INTEGER,
                    created_at TEXT, PRIMARY KEY(tenant_id,id),
                    UNIQUE(tenant_id,exception_id,expected_version)
                );
                CREATE TABLE IF NOT EXISTS reports(
                    tenant_id TEXT, id TEXT, run_id TEXT, ledger_sha TEXT,
                    artifact_sha TEXT, finalized_at TEXT, source_revision TEXT,
                    totals_json TEXT, approved_summary_sha TEXT, run_version INTEGER,
                    PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,run_id)
                );
                CREATE TABLE IF NOT EXISTS audit_events(
                    tenant_id TEXT, id TEXT, event_type TEXT, aggregate_id TEXT,
                    aggregate_version INTEGER, actor_id TEXT, occurred_at TEXT,
                    payload_json TEXT, PRIMARY KEY(tenant_id,id)
                );
                """
            )
            # The MVP database may be reused during local development. Additive
            # upgrades keep old synthetic stores readable without destructive DDL.
            self._ensure_columns(c, "batches", {
                "profile_version": "TEXT NOT NULL DEFAULT 'strict-v1'",
                "artifact_id": "TEXT",
            })
            self._ensure_columns(c, "rows_", {
                "transaction_type": "TEXT NOT NULL DEFAULT 'normal'",
                "row_number": "INTEGER",
                "raw_row_sha": "TEXT",
            })
            self._ensure_columns(c, "runs", {
                "source_revision": "TEXT",
                "created_at": "TEXT",
            })
            self._ensure_columns(c, "exceptions", {"resolution_policy": "TEXT"})
            self._ensure_columns(c, "resolutions", {
                "expected_version": "INTEGER",
                "created_at": "TEXT",
            })
            self._ensure_columns(c, "reports", {
                "source_revision": "TEXT",
                "totals_json": "TEXT",
                "approved_summary_sha": "TEXT",
                "run_version": "INTEGER",
                "content_json": "TEXT",
            })
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_aggregate ON audit_events(tenant_id,aggregate_id)")

    @staticmethod
    def _ensure_columns(c: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in c.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def seed(self) -> None:
        if os.getenv("APP_ENV", "development") not in {"development", "test"}:
            raise ValueError("Synthetic fixture provisioning is restricted to development/test")
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO tenants VALUES(?,?,?)", (TENANT, "synthetic-demo", "ACTIVE"))
            c.execute(
                "INSERT OR IGNORE INTO memberships VALUES(?,?,?,?)",
                (TENANT, USER, "editor", "ACTIVE"),
            )
        self.allow_fixture_imports = True

    def member_role(self, tenant: str, user: str) -> str | None:
        """Read current ACTIVE member role without trusting JWT-supplied role."""
        with self.conn() as db:
            row = db.execute(
                "SELECT role FROM memberships WHERE tenant_id=? AND user_id=? AND status='ACTIVE'",
                (tenant, user),
            ).fetchone()
            return str(row["role"]) if row else None

    def member(self, tenant: str, user: str) -> bool:
        with self.conn() as c:
            return c.execute(
                "SELECT 1 FROM memberships WHERE tenant_id=? AND user_id=? AND status='ACTIVE'",
                (tenant, user),
            ).fetchone() is not None

    @staticmethod
    def _fixture_rows(label: str) -> list[dict[str, object]]:
        # Synthetic demo sides have equal totals while retaining reviewed mismatches.
        values = [(100, "r1"), (200, "r2"), (300, "r3")] if label == "left-fixture" else [(100, "s1"), (250, "s2"), (250, "s3")]
        timestamp = now()
        return [
            {
                "external_ref": ref,
                "currency": "",
                "amount_minor": amount,
                "occurred_at": timestamp,
                "transaction_type": "normal",
            }
            for amount, ref in values
        ]

    @staticmethod
    def parse_csv(csv_content: str, currency: str) -> list[dict[str, object]]:
        try:
            return Store._parse_csv(csv_content, currency)
        except csv.Error as error:
            raise StoreValidationError("CSV_SCHEMA_INVALID", "Malformed CSV quoting or field size") from error

    @staticmethod
    def _parse_csv(csv_content: str, currency: str) -> list[dict[str, object]]:
        if not isinstance(csv_content, str) or not csv_content.strip():
            raise StoreValidationError("CSV_EMPTY", "csv_content must contain a header and at least one data row")
        try:
            encoded_csv = csv_content.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise StoreValidationError("CSV_INVALID_UNICODE", "CSV source must contain valid UTF-8") from exc
        if len(encoded_csv) > MAX_CSV_BYTES:
            raise StoreValidationError("CSV_BUDGET_EXCEEDED", "CSV source exceeds the 1 MiB import budget")
        if csv_content.startswith("\ufeff"):
            csv_content = csv_content[1:]
        try:
            reader = csv.DictReader(io.StringIO(csv_content, newline=""), strict=True)
        except csv.Error as exc:
            raise StoreValidationError("CSV_SCHEMA_INVALID", str(exc)) from exc
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or set(headers) != set(CSV_REQUIRED) and set(headers) != CSV_ALLOWED:
            raise StoreValidationError(
                "CSV_SCHEMA_INVALID",
                "CSV header must contain exactly external_ref,currency,amount_minor,occurred_at with optional transaction_type",
            )
        if any(not isinstance(header, str) or header != header.strip() for header in headers):
            raise StoreValidationError("CSV_SCHEMA_INVALID", "CSV headers may not contain whitespace")
        rows: list[dict[str, object]] = []
        refs: set[str] = set()
        for line_number, raw in enumerate(reader, start=2):
            if len(rows) >= MAX_IMPORT_ROWS:
                raise StoreValidationError("CSV_BUDGET_EXCEEDED", "CSV source exceeds 10000 data rows")
            if None in raw or any(value is None for value in raw.values()):
                raise StoreValidationError("CSV_SCHEMA_INVALID", f"row {line_number} has the wrong number of columns")
            ref = str(raw["external_ref"])
            if len(ref) > 256:
                raise StoreValidationError("CSV_EXTERNAL_REF_INVALID", f"external_ref exceeds 256 characters at row {line_number}")
            if not ref or ref.strip() != ref or ref in refs:
                raise StoreValidationError("CSV_DUPLICATE_EXTERNAL_REF", f"external_ref is empty, padded, or duplicated at row {line_number}")
            # References become reconciliation identifiers and audit evidence.
            # Quoted CSV can legally contain control bytes (including newlines);
            # they must not silently create ambiguous or multiline identities.
            if any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in ref):
                raise StoreValidationError("CSV_EXTERNAL_REF_INVALID", f"external_ref contains invisible or control characters at row {line_number}")
            refs.add(ref)
            row_currency = str(raw["currency"])
            if not re.fullmatch(r"[A-Z]{3}", row_currency) or row_currency != currency:
                raise StoreValidationError("CSV_CURRENCY_INVALID", f"row {line_number} currency must equal batch currency {currency}")
            amount_text = str(raw["amount_minor"])
            if not AMOUNT_RE.fullmatch(amount_text):
                raise StoreValidationError("CSV_AMOUNT_INVALID", f"row {line_number} amount_minor must be a canonical integer minor unit")
            if len(amount_text) > 20:
                raise StoreValidationError("CSV_AMOUNT_INVALID", f"row {line_number} amount_minor is outside the signed 64-bit range")
            amount = int(amount_text)
            if amount == 0 or amount < MIN_INT64 or amount > MAX_INT64:
                raise StoreValidationError("CSV_AMOUNT_INVALID", f"row {line_number} amount_minor is outside the non-zero signed 64-bit range")
            try:
                occurred_at = _iso(str(raw["occurred_at"]))
            except ValueError as exc:
                raise StoreValidationError("CSV_TIMESTAMP_INVALID", f"row {line_number}: {exc}") from exc
            transaction_type = str(raw.get("transaction_type") or "normal")
            if transaction_type not in TRANSACTION_TYPES:
                raise StoreValidationError("CSV_TRANSACTION_TYPE_INVALID", f"row {line_number} transaction_type is unsupported")
            if transaction_type in {"refund", "reversal"} and amount >= 0:
                raise StoreValidationError("CSV_SIGN_POLICY_VIOLATION", f"row {line_number} {transaction_type} must use a negative amount_minor")
            rows.append({
                "external_ref": ref,
                "currency": row_currency,
                "amount_minor": amount,
                "occurred_at": occurred_at,
                "transaction_type": transaction_type,
            })
        if not rows:
            raise StoreValidationError("CSV_EMPTY", "CSV must contain at least one data row")
        return rows

    @staticmethod
    def _normalized_reference(value: str) -> str:
        """Normalize only the explicitly configured identity transformations.

        Prefix stripping is intentionally absent until a source-specific prefix
        policy is configured; guessing prefixes could merge distinct accounts.
        """
        return " ".join(unicodedata.normalize("NFC", value).strip().upper().split())

    def batch(
        self,
        tenant: str,
        label: str,
        sha: str,
        currency: str,
        *,
        profile_version: str = "strict-v1",
        artifact_id: str | None = None,
        csv_content: str | None = None,
    ) -> sqlite3.Row:
        if not label.strip():
            raise StoreValidationError("SOURCE_LABEL_INVALID", "source_label must not be empty")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise StoreValidationError("CURRENCY_INVALID", "currency must be an uppercase ISO-style three-letter code")
        if csv_content is not None:
            try:
                csv_bytes = csv_content.encode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise StoreValidationError("CSV_INVALID_UNICODE", "CSV source must contain valid UTF-8") from exc
            actual_sha = hashlib.sha256(csv_bytes).hexdigest()
            if actual_sha != sha:
                raise StoreValidationError("SOURCE_DIGEST_MISMATCH", "file_sha256 does not match csv_content")
            values = self.parse_csv(csv_content, currency)
        else:
            if not getattr(self, "allow_fixture_imports", False) or os.getenv("APP_ENV", "development") not in {"development", "test"}:
                raise StoreValidationError("SOURCE_BYTES_REQUIRED", "Verified CSV source bytes are required; artifact metadata alone is not an import")
            values = self._fixture_rows(label)
            for value in values:
                value["currency"] = currency
        bid, jid, created = str(uuid.uuid4()), str(uuid.uuid4()), now()
        source_revision = hashlib.sha256((sha + profile_version).encode()).hexdigest()
        with self.conn() as c:
            try:
                c.execute(
                    "INSERT INTO batches(tenant_id,id,source_label,file_sha,currency,profile_version,artifact_id,row_count,status,job_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (tenant, bid, label, sha, currency, profile_version, artifact_id, len(values), "IMPORTED", jid, created),
                )
                for row_number, value in enumerate(values, start=1):
                    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
                    c.execute(
                        "INSERT INTO rows_(tenant_id,id,batch_id,external_ref,currency,amount_minor,occurred_at,transaction_type,row_number,raw_row_sha,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (tenant, str(uuid.uuid4()), bid, value["external_ref"], currency, value["amount_minor"], value["occurred_at"], value["transaction_type"], row_number, hashlib.sha256(raw.encode()).hexdigest(), "IMPORTED"),
                    )
                self._audit(c, tenant, "import.batch_validated", bid, 1, None, {
                    "batch_id": bid, "file_sha256": sha, "source_revision": source_revision,
                    "currency": currency, "accepted_rows": len(values), "rejected_rows": 0,
                    "profile_version": profile_version,
                })
            except sqlite3.IntegrityError as exc:
                if "file_sha" in str(exc) or "UNIQUE" in str(exc):
                    raise StoreValidationError("DUPLICATE_IMPORT", "This file digest was already imported") from exc
                raise
        return self.get_batch(tenant, bid)

    def get_batch(self, tenant: str, bid: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM batches WHERE tenant_id=? AND id=?", (tenant, bid)).fetchone()

    def rows(self, tenant: str, bid: str) -> list[sqlite3.Row]:
        with self.conn() as c:
            return c.execute("SELECT * FROM rows_ WHERE tenant_id=? AND batch_id=? ORDER BY row_number", (tenant, bid)).fetchall()

    def run(self, tenant: str, left: str, right: str, rule: str, *, actor: str | None = None, idempotency_key: str | None = None) -> sqlite3.Row:
        # Never silently execute the legacy matching algorithm under a
        # caller-supplied, unimplemented policy name.
        if rule not in {"exact", "exact-v1", "exact-1to1-v1", "unambiguous-amount-v2", "exact-reference-date-v1"}:
            raise StoreValidationError("UNSUPPORTED_RECONCILIATION_RULE", "Unknown reconciliation rule version")
        if rule == "exact-reference-date-v1" and not self.allow_exact_reference_date_rule:
            raise StoreValidationError(
                "RECONCILIATION_RULE_DISABLED",
                "exact-reference-date-v1 is disabled unless explicitly enabled in development/test; production requires a separately reviewed release",
            )
        if left == right:
            raise StoreValidationError("IDENTICAL_SOURCE_BATCHES", "A source import cannot be reconciled against itself")
        left_batch, right_batch = self.get_batch(tenant, left), self.get_batch(tenant, right)
        if not left_batch or not right_batch:
            raise StoreValidationError("RESOURCE_NOT_FOUND", "Import is not visible")
        if left_batch["currency"] != right_batch["currency"]:
            raise StoreValidationError("CURRENCY_MISMATCH", "Only same-currency matching is supported")
        source_revision = hashlib.sha256(
            (left_batch["file_sha"] + right_batch["file_sha"] + left_batch["profile_version"] + right_batch["profile_version"] + rule).encode()
        ).hexdigest()
        request_sha = hashlib.sha256(json.dumps({"left_batch_id": left, "right_batch_id": right, "rule_version": rule}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if idempotency_key and (not actor or not 16 <= len(idempotency_key) <= 128):
            raise StoreValidationError("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key must be 16–128 characters")
        with self.conn() as c:
            # Serialize the read/insert pair.  A pre-transaction read is not
            # sufficient: two workers can both observe no run and then race
            # on the business-key UNIQUE constraint.
            c.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                command = c.execute("SELECT * FROM source_artifact_commands WHERE tenant_id=? AND actor=? AND action='reconcile' AND command_key=?", (tenant, actor, idempotency_key)).fetchone()
                if command:
                    if command["request_sha"] != request_sha:
                        raise StoreValidationError("IDEMPOTENCY_CONFLICT", "Key was already used with another reconciliation request")
                    replay = c.execute("SELECT * FROM runs WHERE tenant_id=? AND id=?", (tenant, command["artifact_id"])).fetchone()
                    if replay:
                        return replay
                    raise StoreValidationError("IDEMPOTENCY_RECONCILIATION_REQUIRED", "The idempotent reconciliation result is unavailable")
            existing = c.execute(
                "SELECT * FROM runs WHERE tenant_id=? AND left_batch=? AND right_batch=? AND rule=?",
                (tenant, left, right, rule),
            ).fetchone()
            if existing:
                if idempotency_key:
                    c.execute("INSERT INTO source_artifact_commands VALUES(?,?,?,?,?,?)", (tenant, actor, "reconcile", idempotency_key, request_sha, existing["id"]))
                return existing
            rid, jid, created = str(uuid.uuid4()), str(uuid.uuid4()), now()
            try:
                c.execute(
                    "INSERT INTO runs(tenant_id,id,left_batch,right_batch,rule,status,job_id,unmatched,version,source_revision,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (tenant, rid, left, right, rule, "SUCCEEDED", jid, 0, 1, source_revision, created),
                )
            except sqlite3.IntegrityError:
                # A compatible schema may enforce the same key concurrently;
                # return the committed winner rather than duplicating work.
                existing = c.execute(
                    "SELECT * FROM runs WHERE tenant_id=? AND left_batch=? AND right_batch=? AND rule=?",
                    (tenant, left, right, rule),
                ).fetchone()
                if existing:
                    return existing
                raise
            left_rows, right_rows = self.rows(tenant, left), self.rows(tenant, right)
            used: set[str] = set()
            unmatched = 0
            matched = 0
            if rule == "exact-reference-date-v1":
                # Owner P0 candidate rule: require a unique exact transaction
                # identity on both sides. Timestamps were canonicalized to UTC
                # at import; reference normalization is NFC + trim + uppercase
                # + whitespace collapse. Never guess a removable prefix.
                identity_key = lambda row: (
                    row["currency"], self._normalized_reference(row["external_ref"]),
                    row["occurred_at"], row["transaction_type"],
                )
                left_groups, right_groups = defaultdict(list), defaultdict(list)
                for row in left_rows:
                    left_groups[identity_key(row)].append(row)
                for row in right_rows:
                    right_groups[identity_key(row)].append(row)
                for a in left_rows:
                    key = identity_key(a)
                    left_group, right_group = left_groups[key], right_groups[key]
                    if len(left_group) > 1 or len(right_group) > 1:
                        reason, right_id = "AMBIGUOUS_IDENTITY", None
                    elif len(right_group) == 1:
                        b = right_group[0]
                        used.add(b["id"])
                        if a["amount_minor"] == b["amount_minor"]:
                            matched += 1
                            c.execute(
                                "INSERT INTO allocations(tenant_id,id,run_id,left_id,right_id,rule,matched_amount_minor,currency) VALUES(?,?,?,?,?,?,?,?)",
                                (tenant, str(uuid.uuid4()), rid, a["id"], b["id"], rule, a["amount_minor"], a["currency"]),
                            )
                            continue
                        reason, right_id = "AMOUNT_MISMATCH", b["id"]
                    else:
                        reason, right_id = "MISSING_RIGHT", None
                    unmatched += 1
                    policy = a["transaction_type"] if a["transaction_type"] in {"refund", "reversal"} else "investigated"
                    c.execute(
                        "INSERT INTO exceptions(tenant_id,id,run_id,reason,left_id,right_id,status,version,resolution_policy) VALUES(?,?,?,?,?,?,?,?,?)",
                        (tenant, str(uuid.uuid4()), rid, reason, a["id"], right_id, "OPEN", 1, policy),
                    )
                for b in right_rows:
                    if b["id"] in used:
                        continue
                    key = identity_key(b)
                    reason = "AMBIGUOUS_IDENTITY" if len(left_groups[key]) > 1 or len(right_groups[key]) > 1 else "MISSING_LEFT"
                    unmatched += 1
                    policy = b["transaction_type"] if b["transaction_type"] in {"refund", "reversal"} else "investigated"
                    c.execute(
                        "INSERT INTO exceptions(tenant_id,id,run_id,reason,left_id,right_id,status,version,resolution_policy) VALUES(?,?,?,?,?,?,?,?,?)",
                        (tenant, str(uuid.uuid4()), rid, reason, None, b["id"], "OPEN", 1, policy),
                    )
            else:
                right_candidates = defaultdict(deque)
                for row in right_rows:
                    right_candidates[(row["currency"], row["amount_minor"], row["transaction_type"])].append(row)
                # Opt-in amount-only rule remains available for reproducibility;
                # the new identity rule above is stricter and separately versioned.
                unambiguous = rule == "unambiguous-amount-v2"
                key_of = lambda row: (row["currency"], row["amount_minor"], row["transaction_type"])
                left_key_counts = Counter(key_of(row) for row in left_rows) if unambiguous else Counter()
                right_key_counts = Counter(key_of(row) for row in right_rows) if unambiguous else Counter()
                pending_left = []
                for a in left_rows:
                    key = key_of(a)
                    candidates = right_candidates[key]
                    ambiguous = unambiguous and (left_key_counts[key] != 1 or right_key_counts[key] != 1)
                    match = candidates.popleft() if candidates and not ambiguous else None
                    if match:
                        matched += 1
                        used.add(match["id"])
                        c.execute(
                            "INSERT INTO allocations(tenant_id,id,run_id,left_id,right_id,rule,matched_amount_minor,currency) VALUES(?,?,?,?,?,?,?,?)",
                            (tenant, str(uuid.uuid4()), rid, a["id"], match["id"], rule, a["amount_minor"], a["currency"]),
                        )
                        continue
                    pending_left.append(a)
                remaining_right = deque(b for b in right_rows if b["id"] not in used)
                for a in pending_left:
                    candidate = remaining_right.popleft() if remaining_right and not unambiguous else None
                    if candidate:
                        used.add(candidate["id"])
                        reason, right_id = "AMOUNT_MISMATCH", candidate["id"]
                    elif unambiguous and (left_key_counts[key_of(a)] > 1 or right_key_counts[key_of(a)] > 1):
                        reason, right_id = "AMBIGUOUS_AMOUNT", None
                    else:
                        reason, right_id = "MISSING_RIGHT", None
                    unmatched += 1
                    policy = a["transaction_type"] if a["transaction_type"] in {"refund", "reversal"} else "investigated"
                    c.execute(
                        "INSERT INTO exceptions(tenant_id,id,run_id,reason,left_id,right_id,status,version,resolution_policy) VALUES(?,?,?,?,?,?,?,?,?)",
                        (tenant, str(uuid.uuid4()), rid, reason, a["id"], right_id, "OPEN", 1, policy),
                    )
                for b in right_rows:
                    if b["id"] not in used:
                        unmatched += 1
                        policy = b["transaction_type"] if b["transaction_type"] in {"refund", "reversal"} else "investigated"
                        reason = "AMBIGUOUS_AMOUNT" if unambiguous and (left_key_counts[key_of(b)] > 1 or right_key_counts[key_of(b)] > 1) else "MISSING_LEFT"
                        c.execute(
                            "INSERT INTO exceptions(tenant_id,id,run_id,reason,left_id,right_id,status,version,resolution_policy) VALUES(?,?,?,?,?,?,?,?,?)",
                            (tenant, str(uuid.uuid4()), rid, reason, None, b["id"], "OPEN", 1, policy),
                        )
            c.execute("UPDATE runs SET unmatched=? WHERE tenant_id=? AND id=?", (unmatched, tenant, rid))
            self._audit(c, tenant, "reconciliation.run_completed", rid, 1, None, {
                "run_id": rid, "source_revision": source_revision, "matched_count": matched,
                "exception_count": unmatched, "rule_version": rule,
            })
            if idempotency_key:
                c.execute("INSERT INTO source_artifact_commands VALUES(?,?,?,?,?,?)", (tenant, actor, "reconcile", idempotency_key, request_sha, rid))
        return self.get_run(tenant, rid)

    def get_run(self, tenant: str, rid: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM runs WHERE tenant_id=? AND id=?", (tenant, rid)).fetchone()

    def exceptions(self, tenant: str, rid: str) -> list[sqlite3.Row]:
        with self.conn() as c:
            return c.execute("SELECT * FROM exceptions WHERE tenant_id=? AND run_id=? ORDER BY id", (tenant, rid)).fetchall()

    def exception(self, tenant: str, eid: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM exceptions WHERE tenant_id=? AND id=?", (tenant, eid)).fetchone()

    def _resolution_policy_ok(self, c: sqlite3.Connection, tenant: str, exception: sqlite3.Row, decision: str) -> bool:
        if decision == "accept-as-investigated":
            return True
        if decision == "reject":
            return True
        if decision == "accept-as-refund":
            return exception["resolution_policy"] == "refund"
        if decision == "accept-as-reversal":
            return exception["resolution_policy"] == "reversal"
        return False

    def resolve(self, tenant: str, eid: str, reviewer: str, decision: str, evidence: str, version: int) -> tuple[str | sqlite3.Row | None, str]:
        if decision not in RESOLUTION_DECISIONS:
            return None, "INVALID_DECISION"
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            exception = c.execute("SELECT * FROM exceptions WHERE tenant_id=? AND id=?", (tenant, eid)).fetchone()
            if not exception:
                return None, "NOT_FOUND"
            if exception["status"] != "OPEN":
                return exception, "STALE"
            if exception["version"] != version:
                return exception, "STALE"
            if not self._resolution_policy_ok(c, tenant, exception, decision):
                return exception, "POLICY_VIOLATION"
            resolution_id = str(uuid.uuid4())
            try:
                c.execute(
                    "INSERT INTO resolutions(tenant_id,id,exception_id,reviewer_id,decision,evidence_sha,expected_version,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (tenant, resolution_id, eid, reviewer, decision, evidence, version, now()),
                )
                updated = c.execute(
                    "UPDATE exceptions SET status='RESOLVED',version=version+1 WHERE tenant_id=? AND id=? AND status='OPEN' AND version=?",
                    (tenant, eid, version),
                ).rowcount
                if updated != 1:
                    return exception, "STALE"
            except sqlite3.IntegrityError:
                return exception, "STALE"
            self._audit(c, tenant, "exception.resolved", eid, version + 1, reviewer, {
                "exception_id": eid, "decision": decision, "evidence_sha256": evidence,
                "expected_version": version,
            })
            return resolution_id, "OK"

    def partition_valid(self, tenant: str, rid: str) -> bool:
        """Every source row occurs once in allocations or exceptions, never both."""
        run = self.get_run(tenant, rid)
        if not run:
            return False
        with self.conn() as c:
            left = {row["id"]: row for row in c.execute("SELECT * FROM rows_ WHERE tenant_id=? AND batch_id=?", (tenant, run["left_batch"])).fetchall()}
            right = {row["id"]: row for row in c.execute("SELECT * FROM rows_ WHERE tenant_id=? AND batch_id=?", (tenant, run["right_batch"])).fetchall()}
            allocations = c.execute("SELECT * FROM allocations WHERE tenant_id=? AND run_id=?", (tenant, rid)).fetchall()
            exceptions = c.execute("SELECT * FROM exceptions WHERE tenant_id=? AND run_id=?", (tenant, rid)).fetchall()
        seen_left, seen_right = [], []
        for allocation in allocations:
            a, b = left.get(allocation["left_id"]), right.get(allocation["right_id"])
            if not a or not b or any(a[key] != b[key] for key in ("amount_minor", "currency", "transaction_type")):
                return False
            if allocation["matched_amount_minor"] != a["amount_minor"] or allocation["currency"] != a["currency"] or allocation["rule"] != run["rule"]:
                return False
            if allocation["rule"] == "exact-reference-date-v1" and (
                a["occurred_at"] != b["occurred_at"]
                or self._normalized_reference(a["external_ref"]) != self._normalized_reference(b["external_ref"])
            ):
                return False
            seen_left.append(a["id"]); seen_right.append(b["id"])
        for exception in exceptions:
            a, b = exception["left_id"], exception["right_id"]
            if a is None and b is None or a is not None and a not in left or b is not None and b not in right:
                return False
            if a is not None: seen_left.append(a)
            if b is not None: seen_right.append(b)
        return (len(exceptions) == run["unmatched"]
                and len(seen_left) == len(set(seen_left)) == len(left)
                and len(seen_right) == len(set(seen_right)) == len(right)
                and set(seen_left) == set(left) and set(seen_right) == set(right))

    def totals(self, tenant: str, rid: str) -> dict[str, object] | None:
        run = self.get_run(tenant, rid)
        if not run:
            return None
        with self.conn() as c:
            def exact_total(statement, params):
                values = c.execute(statement, params).fetchall()
                return {"total": sum(int(value[0]) for value in values), "count": len(values)}
            # Each source value fits int64; aggregate totals may legitimately not.
            # Python integer accumulation avoids SQLite SUM overflow and float loss.
            left = exact_total("SELECT amount_minor FROM rows_ WHERE tenant_id=? AND batch_id=?", (tenant, run["left_batch"]))
            right = exact_total("SELECT amount_minor FROM rows_ WHERE tenant_id=? AND batch_id=?", (tenant, run["right_batch"]))
            allocated = exact_total("SELECT matched_amount_minor FROM allocations WHERE tenant_id=? AND run_id=?", (tenant, rid))
            allocated_left = exact_total("SELECT r.amount_minor FROM allocations a JOIN rows_ r ON r.tenant_id=a.tenant_id AND r.id=a.left_id WHERE a.tenant_id=? AND a.run_id=?", (tenant, rid))
            allocated_right = exact_total("SELECT r.amount_minor FROM allocations a JOIN rows_ r ON r.tenant_id=a.tenant_id AND r.id=a.right_id WHERE a.tenant_id=? AND a.run_id=?", (tenant, rid))
            open_count = c.execute("SELECT COUNT(*) FROM exceptions WHERE tenant_id=? AND run_id=? AND status='OPEN'", (tenant, rid)).fetchone()[0]
            rejected_count = c.execute("SELECT COUNT(*) FROM exceptions e JOIN resolutions r ON r.tenant_id=e.tenant_id AND r.exception_id=e.id WHERE e.tenant_id=? AND e.run_id=? AND r.decision='reject'", (tenant, rid)).fetchone()[0]
            return {
                "left_total_minor": int(left["total"]),
                "right_total_minor": int(right["total"]),
                "allocated_total_minor": int(allocated["total"]),
                "allocated_left_total_minor": int(allocated_left["total"]),
                "allocated_right_total_minor": int(allocated_right["total"]),
                "source_unbalanced_minor": int(left["total"]) - int(right["total"]),
                "conservation_discrepancy_minor": int(allocated_left["total"]) - int(allocated_right["total"]),
                "left_row_count": int(left["count"]),
                "right_row_count": int(right["count"]),
                "matched_count": int(allocated["count"]),
                "exception_count": int(run["unmatched"]),
                "open_exception_count": int(open_count),
                "rejected_exception_count": int(rejected_count),
                "currency": self.get_batch(tenant, run["left_batch"])["currency"],
                "row_partition_valid": self.partition_valid(tenant, rid),
                "proof": "allocated-left-equals-allocated-right-and-each-source-used-at-most-once",
            }

    def finalize(self, tenant: str, rid: str, summary: str, version: int) -> tuple[sqlite3.Row | None, str]:
        # HTTP validation is not the only path into the storage layer. An
        # unchecked label must never be signed as an approved evidence digest.
        if type(summary) is not str or not re.fullmatch(r"[0-9a-f]{64}", summary):
            raise StoreValidationError("APPROVED_SUMMARY_DIGEST_INVALID", "Approved summary must be a canonical SHA-256 digest")
        if type(version) is not int or version < 1:
            raise StoreValidationError("REPORT_VERSION_INVALID", "Run version must be a positive integer")
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            run = c.execute("SELECT * FROM runs WHERE tenant_id=? AND id=?", (tenant, rid)).fetchone()
            if not run:
                return None, "NOT_FOUND"
            existing = c.execute("SELECT * FROM reports WHERE tenant_id=? AND run_id=?", (tenant, rid)).fetchone()
            if existing:
                return existing, "ALREADY_FINALIZED"
            if run["version"] != version:
                return run, "STALE"
            open_count = c.execute("SELECT COUNT(*) FROM exceptions WHERE tenant_id=? AND run_id=? AND status='OPEN'", (tenant, rid)).fetchone()[0]
            if open_count:
                return run, "OPEN_EXCEPTIONS"
            duplicate = c.execute(
                "SELECT COUNT(*) FROM (SELECT left_id FROM allocations WHERE tenant_id=? AND run_id=? GROUP BY left_id HAVING COUNT(*)>1 UNION ALL SELECT right_id FROM allocations WHERE tenant_id=? AND run_id=? GROUP BY right_id HAVING COUNT(*)>1)",
                (tenant, rid, tenant, rid),
            ).fetchone()[0]
            if duplicate:
                return run, "ALLOCATION_NOT_UNIQUE"
            if not self.partition_valid(tenant, rid):
                return run, "CONSERVATION_FAILED"
            totals = self.totals(tenant, rid)
            if (not totals
                    or totals["allocated_total_minor"] < 0 and totals["matched_count"] == 0
                    or totals["source_unbalanced_minor"] != 0
                    or totals["conservation_discrepancy_minor"] != 0):
                return run, "CONSERVATION_FAILED"
            # Exact-match allocations carry their own equality proof. Exceptions
            # are an explicit reviewed scope and never become transfers.
            canonical = json.dumps({"source_revision": run["source_revision"], "rule_version": run["rule"], "totals": totals, "approved_summary_sha256": summary}, sort_keys=True, separators=(",", ":"))
            ledger = hashlib.sha256(canonical.encode()).hexdigest()
            artifact = hashlib.sha256(canonical.encode()).hexdigest()
            report_id, finalized = str(uuid.uuid4()), now()
            c.execute(
                "INSERT INTO reports(tenant_id,id,run_id,ledger_sha,artifact_sha,finalized_at,source_revision,totals_json,approved_summary_sha,run_version,content_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (tenant, report_id, rid, ledger, artifact, finalized, run["source_revision"], json.dumps(totals, sort_keys=True, separators=(",", ":")), summary, version, canonical),
            )
            c.execute("UPDATE runs SET status='FINALIZED' WHERE tenant_id=? AND id=?", (tenant, rid))
            self._audit(c, tenant, "report.finalized", report_id, 1, None, {
                "run_id": rid, "report_id": report_id, "report_sha256": artifact,
                "source_revision": run["source_revision"], "totals": totals,
                "approved_summary_sha256": summary,
            })
        return self.report(tenant, report_id), "OK"

    def report(self, tenant: str, rid: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM reports WHERE tenant_id=? AND id=?", (tenant, rid)).fetchone()

    def audit_events(self, tenant: str, aggregate_id: str) -> list[sqlite3.Row]:
        with self.conn() as c:
            return c.execute("SELECT * FROM audit_events WHERE tenant_id=? AND aggregate_id=? ORDER BY occurred_at", (tenant, aggregate_id)).fetchall()

    @staticmethod
    def _audit(c: sqlite3.Connection, tenant: str, event_type: str, aggregate_id: str, version: int, actor: str | None, payload: dict[str, object]) -> None:
        c.execute(
            "INSERT INTO audit_events(tenant_id,id,event_type,aggregate_id,aggregate_version,actor_id,occurred_at,payload_json) VALUES(?,?,?,?,?,?,?,?)",
            (tenant, str(uuid.uuid4()), event_type, aggregate_id, version, actor, now(), json.dumps(payload, sort_keys=True, separators=(",", ":"))),
        )
