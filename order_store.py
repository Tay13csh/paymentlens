"""Local SQLite storage shared by the Streamlit app and webhook receiver."""

import sqlite3
import json
import hashlib
from urllib.parse import urlparse
from payment_evidence import money, normalize_capture, reconcile_sale
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


DATABASE_PATH = Path(__file__).with_name("payguard.db")
MAX_PENDING_WEBHOOK_EVENTS = 1_000
MAX_STORED_WEBHOOK_EVENTS = 100_000
MAX_WEBHOOK_FIELD_LENGTH = 255
MAX_CAPTURE_OBSERVATIONS = 100_000
MAX_OBSERVATIONS_PER_CAPTURE = 32
MAX_CAPTURE_EVIDENCE_RECORDS = 100_000
WEBHOOK_STATUS_BY_EVENT = {
    "CHECKOUT.ORDER.APPROVED": "APPROVED",
    "PAYMENT.CAPTURE.COMPLETED": "COMPLETED",
    "PAYMENT.CAPTURE.DENIED": "DENIED",
    "PAYMENT.CAPTURE.REFUNDED": "REFUNDED",
    "PAYMENT.CAPTURE.REVERSED": "REVERSED",
}
ALLOWED_STATUS_TRANSITIONS = {
    "CREATED": {"APPROVED", "COMPLETED", "DENIED", "REFUNDED", "REVERSED"},
    "APPROVED": {"COMPLETED", "DENIED", "REFUNDED", "REVERSED"},
    "COMPLETED": {"REFUNDED", "REVERSED"},
    "DENIED": set(),
    "REFUNDED": {"REVERSED"},
    "REVERSED": set(),
}


class WebhookStorageFullError(Exception):
    """Raised before acknowledging an event that cannot be stored safely."""


class InvalidWebhookEventError(ValueError):
    """Raised when required normalized event fields are missing or too large."""


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL,
                capture_id TEXT,
                capture_state TEXT NOT NULL DEFAULT 'READY',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        event_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(webhook_events)").fetchall()
        }
        # Old rows have no replay fields. Preserve their deduplication identity
        # without claiming they were applied or inventing missing order IDs.
        for column, definition in (
            ("order_id", "TEXT"),
            ("capture_id", "TEXT"),
            ("processing_state", "TEXT NOT NULL DEFAULT 'LEGACY'"),
            ("processed_at", "TEXT"),
            ("capture_evidence_json", "TEXT"),
        ):
            if column not in event_columns:
                connection.execute(f"ALTER TABLE webhook_events ADD COLUMN {column} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS webhook_pending_orders ON webhook_events (processing_state, order_id)"
        )
        order_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(orders)").fetchall()
        }
        if "capture_state" not in order_columns:
            connection.execute(
                "ALTER TABLE orders ADD COLUMN capture_state TEXT NOT NULL DEFAULT 'READY'"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS order_creation_attempts (
                request_id TEXT PRIMARY KEY,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                order_id TEXT,
                approval_url TEXT
            )
            """
        )

        attempt_columns = {row["name"] for row in connection.execute("PRAGMA table_info(order_creation_attempts)")}
        if "sale_id" not in attempt_columns:
            connection.execute("ALTER TABLE order_creation_attempts ADD COLUMN sale_id TEXT")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_attempt_per_sale ON order_creation_attempts(sale_id) WHERE sale_id IS NOT NULL")
        connection.execute("""CREATE TABLE IF NOT EXISTS merchant_sales_orders (
            sale_id TEXT PRIMARY KEY, description TEXT NOT NULL,
            amount TEXT NOT NULL, currency TEXT NOT NULL CHECK(currency='CAD'),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, locked_at TEXT,
            paypal_order_id TEXT UNIQUE
        )""")
        connection.execute("""CREATE TRIGGER IF NOT EXISTS immutable_merchant_terms
            BEFORE UPDATE OF description, amount, currency ON merchant_sales_orders
            WHEN NEW.description IS NOT OLD.description OR NEW.amount IS NOT OLD.amount OR NEW.currency IS NOT OLD.currency
            BEGIN SELECT RAISE(ABORT, 'Saved merchant terms are immutable'); END""")
        connection.execute("""CREATE TABLE IF NOT EXISTS capture_evidence (
            capture_id TEXT PRIMARY KEY, order_id TEXT NOT NULL,
            amount TEXT, currency TEXT, status TEXT, final_capture INTEGER,
            occurred_at TEXT, source TEXT NOT NULL, conflict INTEGER NOT NULL DEFAULT 0,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS evidence_order ON capture_evidence(order_id)")
        evidence_columns = {row["name"] for row in connection.execute("PRAGMA table_info(capture_evidence)")}
        for column, definition in (
            ("amount_pair_valid", "INTEGER NOT NULL DEFAULT 0"),
            ("provider_order_amount", "TEXT"),
            ("provider_order_currency", "TEXT"),
            ("full_capture_verified", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in evidence_columns:
                connection.execute(f"ALTER TABLE capture_evidence ADD COLUMN {column} {definition}")
        connection.execute("""CREATE TABLE IF NOT EXISTS capture_observations (
            observation_key TEXT PRIMARY KEY, capture_id TEXT NOT NULL, order_id TEXT NOT NULL,
            amount TEXT, currency TEXT, status TEXT, final_capture INTEGER,
            provider_order_amount TEXT, provider_order_currency TEXT, full_capture_verified INTEGER NOT NULL,
            source TEXT NOT NULL, occurred_at TEXT,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS observations_capture ON capture_observations(capture_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS webhook_pending_capture ON webhook_events(capture_id, processing_state)")
        connection.execute("""CREATE TABLE IF NOT EXISTS capture_evidence_issues (
            order_id TEXT NOT NULL, issue TEXT NOT NULL,
            PRIMARY KEY(order_id, issue)
        )""")


def begin_order_creation(amount: str) -> str:
    """Persist a new explicit creation attempt before any PayPal request."""
    initialize_database()
    request_id = str(uuid.uuid4())
    with _connect() as connection:
        connection.execute(
            "INSERT INTO order_creation_attempts (request_id, amount, currency) VALUES (?, ?, 'CAD')",
            (request_id, amount),
        )
    return request_id


def get_order_creation_attempt(request_id: str) -> Optional[Dict[str, Any]]:
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            "SELECT request_id, amount, currency, order_id, approval_url, sale_id FROM order_creation_attempts WHERE request_id = ?",
            (request_id,),
        ).fetchone()
    return dict(row) if row else None


def complete_order_creation(request_id: str, order_id: str, approval_url: str) -> None:
    """Save the returned order and its attempt together, without losing retry identity."""
    initialize_database()
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        attempt = connection.execute(
            "SELECT * FROM order_creation_attempts WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if not attempt:
            raise ValueError("Unknown order creation attempt.")
        if attempt["order_id"] and attempt["order_id"] != order_id:
            raise ValueError("A creation attempt cannot be rebound to another PayPal order.")
        if attempt["sale_id"]:
            other = connection.execute("SELECT sale_id FROM merchant_sales_orders WHERE paypal_order_id = ?", (order_id,)).fetchone()
            if other and other["sale_id"] != attempt["sale_id"]:
                raise ValueError("This PayPal order is already linked to another sale.")
            connection.execute("UPDATE merchant_sales_orders SET paypal_order_id = ? WHERE sale_id = ?", (order_id, attempt["sale_id"]))
        _save_order(connection, order_id, attempt["amount"], attempt["currency"])
        connection.execute(
            "UPDATE order_creation_attempts SET order_id = ?, approval_url = ? WHERE request_id = ?",
            (order_id, approval_url, request_id),
        )


def save_order(order_id: str, amount: str, currency: str = "CAD") -> None:
    initialize_database()
    with _connect() as connection:
        _save_order(connection, order_id, amount, currency)


def _save_order(connection: sqlite3.Connection, order_id: str, amount: str, currency: str) -> None:
    connection.execute(
        """
        INSERT INTO orders (order_id, amount, currency, status)
        VALUES (?, ?, ?, 'CREATED')
        ON CONFLICT(order_id) DO UPDATE SET
            amount = excluded.amount,
            currency = excluded.currency
        """,
        (order_id, amount, currency),
    )
    pending = connection.execute(
        """
        SELECT event_id FROM webhook_events
        WHERE processing_state = 'PENDING' AND order_id = ?
        ORDER BY received_at, rowid
        """,
        (order_id,),
    ).fetchall()
    for row in pending:
        _process_webhook_event(connection, row["event_id"])


def _apply_status_update(
    connection: sqlite3.Connection,
    order_id: str,
    status: str,
    capture_id: Optional[str] = None,
    capture_ready: bool = False,
    allow_same_status: bool = True,
) -> bool:
    """Check the current status and apply an allowed transition atomically."""
    previous_statuses = [
        previous for previous, targets in ALLOWED_STATUS_TRANSITIONS.items()
        if status in targets or (allow_same_status and previous == status)
    ]
    if not previous_statuses:
        return False
    placeholders = ", ".join("?" for _ in previous_statuses)
    updated = connection.execute(
        f"""
        UPDATE orders
        SET status = ?,
            capture_id = COALESCE(?, capture_id),
            capture_state = CASE
                WHEN ? = 'COMPLETED' THEN 'COMPLETED'
                WHEN ? AND ? = 'APPROVED' THEN 'READY'
                ELSE capture_state
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE order_id = ? AND status IN ({placeholders})
        """,
        (status, capture_id, status, capture_ready, status, order_id, *previous_statuses),
    )
    return updated.rowcount > 0


def update_order_status(order_id: str, status: str, capture_id: Optional[str] = None) -> None:
    initialize_database()
    with _connect() as connection:
        _apply_status_update(connection, order_id, status, capture_id)
        if capture_id:
            _replay_pending_capture_events(connection, capture_id)


def get_order(order_id: str) -> Optional[Dict[str, Any]]:
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT order_id, amount, currency, status, capture_id, capture_state, updated_at
            FROM orders
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()
    return dict(row) if row else None


def begin_capture(order_id: str) -> bool:
    """Atomically reserve a ready order for one Capture request."""
    initialize_database()
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT status, capture_state FROM orders WHERE order_id = ?",
            (order_id,),
        ).fetchone()
        if not row or row["status"] not in {"CREATED", "APPROVED"} or row["capture_state"] != "READY":
            return False
        connection.execute(
            "UPDATE orders SET capture_state = 'IN_PROGRESS', updated_at = CURRENT_TIMESTAMP WHERE order_id = ?",
            (order_id,),
        )
    return True


def mark_capture_unknown(order_id: str) -> None:
    initialize_database()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE orders
            SET capture_state = 'UNKNOWN', updated_at = CURRENT_TIMESTAMP
            WHERE order_id = ? AND capture_state = 'IN_PROGRESS'
            """,
            (order_id,),
        )


def release_capture(order_id: str) -> None:
    """Return a definitively rejected Capture attempt to the ready state."""
    initialize_database()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE orders
            SET capture_state = 'READY', updated_at = CURRENT_TIMESTAMP
            WHERE order_id = ? AND capture_state = 'IN_PROGRESS'
            """,
            (order_id,),
        )


def mark_capture_ready(order_id: str) -> None:
    """Allow an explicit Capture retry after PayPal confirms the order is approved."""
    initialize_database()
    with _connect() as connection:
        _apply_status_update(connection, order_id, "APPROVED", capture_ready=True)


def get_orders(limit: int = 20) -> List[Dict[str, Any]]:
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT order_id, amount, currency, status, capture_id, updated_at
            FROM orders
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_order_events(order_id: str) -> List[Dict[str, Any]]:
    """Read linked event evidence without creating, migrating, or updating a database."""
    if not DATABASE_PATH.is_file():
        return []
    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(webhook_events)")}
        required = {"event_id", "event_type", "order_id", "capture_id", "processing_state", "received_at", "processed_at"}
        if not required.issubset(columns):
            # Old records without order references cannot be safely attributed.
            return []
        rows = connection.execute(
            """
            SELECT event_id, event_type, capture_id, processing_state, received_at, processed_at
            FROM webhook_events WHERE order_id = ?
            ORDER BY received_at, rowid
            """,
            (order_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def _order_for_capture(connection, capture_id):
    """Resolve an exact Capture reference only when all saved bindings agree."""
    rows = connection.execute("""SELECT order_id FROM capture_evidence WHERE capture_id=?
        UNION SELECT order_id FROM orders WHERE capture_id=?
        UNION SELECT order_id FROM capture_observations WHERE capture_id=?""",
        (capture_id, capture_id, capture_id)).fetchall()
    return rows[0]["order_id"] if len(rows) == 1 else None


def _replay_pending_capture_events(connection, capture_id):
    pending = connection.execute("""SELECT event_id FROM webhook_events
        WHERE processing_state='PENDING' AND capture_id=?
          AND event_type IN ('PAYMENT.CAPTURE.REFUNDED', 'PAYMENT.CAPTURE.REVERSED')
        ORDER BY received_at, rowid""", (capture_id,)).fetchall()
    for row in pending:
        _process_webhook_event(connection, row["event_id"])


def _process_webhook_event(connection: sqlite3.Connection, event_id: str) -> bool:
    """Apply saved, verified fields only; caller owns the write transaction."""
    event = connection.execute(
        "SELECT * FROM webhook_events WHERE event_id = ? AND processing_state = 'PENDING'",
        (event_id,),
    ).fetchone()
    if not event:
        return False
    order_id = event["order_id"]
    if not order_id and event["capture_id"]:
        order_id = _order_for_capture(connection, event["capture_id"])
        if not order_id:
            return False
        connection.execute("UPDATE webhook_events SET order_id=? WHERE event_id=?", (order_id, event_id))
    order = connection.execute(
        "SELECT 1 FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    if not order:
        return False
    if event["capture_evidence_json"]:
        evidence = json.loads(event["capture_evidence_json"])
        _store_capture_evidence(connection, order_id, [evidence], "VERIFIED_WEBHOOK", [])
    applied = _apply_status_update(
        connection, order_id, WEBHOOK_STATUS_BY_EVENT[event["event_type"]],
        event["capture_id"], allow_same_status=False,
    )
    connection.execute(
        """
        UPDATE webhook_events SET processing_state = ?, processed_at = CURRENT_TIMESTAMP
        WHERE event_id = ?
        """,
        ("APPLIED" if applied else "IGNORED", event_id),
    )
    if event["event_type"] == "PAYMENT.CAPTURE.COMPLETED" and event["capture_id"]:
        _replay_pending_capture_events(connection, event["capture_id"])
    return applied


def _valid_webhook_field(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_WEBHOOK_FIELD_LENGTH


def create_merchant_sale(description: str, amount: str) -> str:
    """Create immutable CAD-only test sale; no provider call and no personal data."""
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 120:
        raise ValueError("Use a test description between 1 and 120 characters.")
    amount = money(amount)
    initialize_database()
    sale_id = "SALE-" + str(uuid.uuid4())
    with _connect() as connection:
        connection.execute(
            "INSERT INTO merchant_sales_orders(sale_id, description, amount, currency) VALUES (?, ?, ?, 'CAD')",
            (sale_id, description.strip(), amount),
        )
    return sale_id


def get_merchant_sales() -> List[Dict[str, Any]]:
    initialize_database()
    with _connect() as connection:
        return [dict(row) for row in connection.execute("""SELECT sale.*, attempt.request_id AS creation_request_id
            FROM merchant_sales_orders AS sale LEFT JOIN order_creation_attempts AS attempt
              ON attempt.sale_id = sale.sale_id
            ORDER BY sale.created_at DESC, sale.rowid DESC""")]


def begin_sale_creation(sale_id: str) -> str:
    """Lock a sale and reserve exactly one durable creation attempt, atomically."""
    initialize_database()
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        sale = connection.execute("SELECT * FROM merchant_sales_orders WHERE sale_id = ?", (sale_id,)).fetchone()
        if not sale:
            raise ValueError("Unknown merchant sale.")
        existing = connection.execute("SELECT request_id FROM order_creation_attempts WHERE sale_id = ?", (sale_id,)).fetchone()
        if existing:
            return existing["request_id"]
        if sale["paypal_order_id"]:
            raise ValueError("Sale already has a payment; no second attempt is permitted.")
        request_id = str(uuid.uuid4())
        connection.execute("UPDATE merchant_sales_orders SET locked_at = CURRENT_TIMESTAMP WHERE sale_id = ?", (sale_id,))
        connection.execute(
            "INSERT INTO order_creation_attempts(request_id, amount, currency, sale_id) VALUES (?, ?, ?, ?)",
            (request_id, sale["amount"], sale["currency"], sale_id),
        )
    return request_id


def _log_capture_observation(connection, order_id, capture, source, recorded_at=None):
    """Keep bounded, immutable monetary snapshots, deduplicated without raw payloads."""
    fields = {key: capture.get(key) for key in (
        "capture_id", "amount", "currency", "status", "final_capture",
        "provider_order_amount", "provider_order_currency", "occurred_at",
    )}
    fields["final_capture"] = None if fields["final_capture"] is None else int(fields["final_capture"])
    fields["full_capture_verified"] = int(bool(capture.get("full_capture_verified")))
    fields.update(order_id=order_id, source=source)
    identity = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
    if connection.execute("SELECT 1 FROM capture_observations WHERE observation_key=?", (identity,)).fetchone():
        return
    total = connection.execute("SELECT COUNT(*) FROM capture_observations").fetchone()[0]
    per_capture = connection.execute("SELECT COUNT(*) FROM capture_observations WHERE capture_id=?", (capture["capture_id"],)).fetchone()[0]
    if total >= MAX_CAPTURE_OBSERVATIONS or per_capture >= MAX_OBSERVATIONS_PER_CAPTURE:
        raise WebhookStorageFullError("Capture observation storage is full; no observation was discarded.")
    connection.execute("""INSERT INTO capture_observations
        (observation_key, capture_id, order_id, amount, currency, status, final_capture,
         provider_order_amount, provider_order_currency, full_capture_verified, source, occurred_at, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
        (identity, capture["capture_id"], order_id, fields["amount"], fields["currency"], fields["status"],
         fields["final_capture"], fields["provider_order_amount"], fields["provider_order_currency"],
         fields["full_capture_verified"], source, fields["occurred_at"], recorded_at))


def _store_capture_evidence(connection, order_id, captures, source, issues):
    """Merge only complete monetary pairs; retain both sides of contradictions."""
    for issue in issues:
        connection.execute("INSERT OR IGNORE INTO capture_evidence_issues VALUES (?, ?)", (order_id, issue))
    for capture in captures:
        previous = connection.execute("SELECT * FROM capture_evidence WHERE capture_id=?", (capture["capture_id"],)).fetchone()
        if previous and not connection.execute("SELECT 1 FROM capture_observations WHERE capture_id=?", (capture["capture_id"],)).fetchone():
            _log_capture_observation(connection, previous["order_id"], dict(previous), previous["source"], previous["recorded_at"])
        _log_capture_observation(connection, order_id, capture, source)
        if previous and previous["order_id"] != order_id:
            for affected in (order_id, previous["order_id"]):
                connection.execute("INSERT OR IGNORE INTO capture_evidence_issues VALUES (?, 'Capture belongs to conflicting orders')", (affected,))
            connection.execute("UPDATE capture_evidence SET conflict=1 WHERE capture_id=?", (capture["capture_id"],))
            continue
        pair_valid = bool(capture["amount"] and capture["currency"])
        if not previous:
            if connection.execute("SELECT COUNT(*) FROM capture_evidence").fetchone()[0] >= MAX_CAPTURE_EVIDENCE_RECORDS:
                raise WebhookStorageFullError("Capture evidence storage is full.")
            connection.execute("""INSERT INTO capture_evidence
                (capture_id, order_id, amount, currency, status, final_capture, occurred_at, source,
                 amount_pair_valid, provider_order_amount, provider_order_currency, full_capture_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (capture["capture_id"], order_id, capture["amount"], capture["currency"], capture["status"],
                 capture["final_capture"], capture["occurred_at"], source, int(pair_valid),
                 capture.get("provider_order_amount"), capture.get("provider_order_currency"),
                 int(bool(capture.get("full_capture_verified")))))
            continue
        old_pair = previous["amount_pair_valid"]
        conflict = bool(previous["conflict"])
        if old_pair and pair_valid and (previous["amount"], previous["currency"]) != (capture["amount"], capture["currency"]):
            conflict = True
        for key in ("final_capture", "provider_order_amount", "provider_order_currency"):
            if previous[key] is not None and capture.get(key) is not None and previous[key] != capture[key]:
                conflict = True
        status = previous["status"]
        if status in (None, "PENDING"):
            status = capture["status"] or status
        elif capture["status"] and status != capture["status"]:
            conflict = True
        # A migrated row is not trusted as a complete pair without a new valid observation.
        replace_pair = not old_pair and pair_valid
        amount = capture["amount"] if replace_pair else previous["amount"]
        currency = capture["currency"] if replace_pair else previous["currency"]
        provider_amount = previous["provider_order_amount"] or capture.get("provider_order_amount")
        provider_currency = previous["provider_order_currency"] or capture.get("provider_order_currency")
        full = bool(previous["full_capture_verified"] or capture.get("full_capture_verified"))
        connection.execute("""UPDATE capture_evidence SET amount=?, currency=?, status=?,
            amount_pair_valid=?, final_capture=COALESCE(final_capture, ?), occurred_at=COALESCE(occurred_at, ?),
            conflict=?, source=?, provider_order_amount=?, provider_order_currency=?, full_capture_verified=?
            WHERE capture_id=?""",
            (amount, currency, status, int(bool(old_pair or pair_valid)), capture["final_capture"],
             capture["occurred_at"], int(conflict), source if replace_pair else previous["source"],
             provider_amount, provider_currency, int(full), capture["capture_id"]))


def record_payment_observation(order_id, observation) -> None:
    """Persist API evidence and allowed state transitions in one transaction."""
    if getattr(observation, "order_id", order_id) != order_id:
        raise ValueError("Provider observation belongs to a different local payment.")
    initialize_database()
    status, capture_id = observation
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not connection.execute("SELECT 1 FROM orders WHERE order_id=?", (order_id,)).fetchone():
            raise ValueError("Unknown local payment.")
        _store_capture_evidence(
            connection, order_id, getattr(observation, "captures", []),
            getattr(observation, "source", "LEGACY_API_RESULT"), getattr(observation, "issues", []),
        )
        _apply_status_update(connection, order_id, status, capture_id, capture_ready=status == "APPROVED")
        for reference in {capture["capture_id"] for capture in getattr(observation, "captures", [])} | ({capture_id} if capture_id else set()):
            _replay_pending_capture_events(connection, reference)


def _read_sale_reconciliation(connection, order_id):
    """Materialize shared evidence and rule results within the caller's snapshot."""
    sale_row = connection.execute("SELECT * FROM merchant_sales_orders WHERE paypal_order_id=?", (order_id,)).fetchone()
    order_row = connection.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    captures = [dict(row) for row in connection.execute("SELECT * FROM capture_evidence WHERE order_id=? ORDER BY capture_id", (order_id,))]
    issues = [row[0] for row in connection.execute("SELECT issue FROM capture_evidence_issues WHERE order_id=?", (order_id,))]
    observations = [dict(row) for row in connection.execute(
        "SELECT * FROM capture_observations WHERE order_id=? ORDER BY recorded_at, rowid", (order_id,))]
    sale, order = dict(sale_row) if sale_row else None, dict(order_row) if order_row else None
    result = reconcile_sale(sale, order, captures, issues)
    return {"sale": sale, "order": order, "captures": captures, "issues": issues, "observations": observations, "result": result}


def get_sale_reconciliation(order_id):
    """Read every reconciliation input from one explicit, finite snapshot."""
    initialize_database()
    connection = _connect()
    try:
        with connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            return _read_sale_reconciliation(connection, order_id)
    finally:
        connection.close()


def _connect_review_view():
    connection = sqlite3.connect(DATABASE_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def get_review_view_snapshot(retained_ids=()):
    """Read recent 20 and retained references without creating/migrating the database."""
    if not DATABASE_PATH.is_file():
        return {"payments": [], "by_id": {}}
    connection = _connect_review_view()
    try:
        with connection:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            recent_ids = [row["order_id"] for row in connection.execute(
                "SELECT order_id FROM orders ORDER BY updated_at DESC, order_id LIMIT 20")]
            by_id = {order_id: _read_sale_reconciliation(connection, order_id) for order_id in recent_ids}
            for order_id in retained_ids:
                if (isinstance(order_id, str) and order_id not in by_id
                        and connection.execute("SELECT 1 FROM orders WHERE order_id=?", (order_id,)).fetchone()):
                    evidence = _read_sale_reconciliation(connection, order_id)
                    if evidence["order"]:
                        by_id[order_id] = evidence
            return {"payments": [by_id[order_id] for order_id in recent_ids], "by_id": by_id}
    finally:
        connection.close()


def record_webhook_event(event: Dict[str, Any]) -> bool:
    """Store minimal verified fields durably; return whether an update was applied."""
    event_id = event.get("id")
    event_type = event.get("event_type")
    resource = event.get("resource", {})
    if not _valid_webhook_field(event_id) or not _valid_webhook_field(event_type):
        raise InvalidWebhookEventError("Missing or oversized webhook event identity.")
    if not isinstance(resource, dict):
        resource = {}

    order_id: Optional[str] = None
    capture_id: Optional[str] = None
    if event_type == "CHECKOUT.ORDER.APPROVED":
        order_id = resource.get("id")
    elif event_type.startswith("PAYMENT.CAPTURE."):
        supplementary_data = resource.get("supplementary_data", {})
        related_ids = supplementary_data.get("related_ids", {}) if isinstance(supplementary_data, dict) else {}
        order_id = related_ids.get("order_id") if isinstance(related_ids, dict) else None
        # REFUNDED resources are refunds, not captures. Never save refund money as Capture evidence.
        if event_type == "PAYMENT.CAPTURE.REFUNDED":
            capture_id = related_ids.get("capture_id") if isinstance(related_ids, dict) else None
            # Refund resources may carry only an 'up' link to the original Capture.
            if not capture_id and isinstance(resource.get("links"), list):
                for link in resource["links"]:
                    if not isinstance(link, dict) or link.get("rel") != "up" or not isinstance(link.get("href"), str):
                        continue
                    parsed = urlparse(link["href"])
                    if parsed.scheme == "https" and parsed.hostname in {"api.sandbox.paypal.com", "api-m.sandbox.paypal.com"}:
                        prefix = "/v2/payments/captures/"
                        if parsed.path.startswith(prefix):
                            candidate = parsed.path[len(prefix):]
                            if candidate and "/" not in candidate:
                                capture_id = candidate
        else:
            capture_id = resource.get("id")


    supported = event_type in WEBHOOK_STATUS_BY_EVENT
    if supported:
        capture_only_terminal = (
            order_id is None and _valid_webhook_field(capture_id)
            and event_type in {"PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"}
        )
        if not _valid_webhook_field(order_id) and not capture_only_terminal:
            raise InvalidWebhookEventError("Missing or oversized webhook order ID.")
        if capture_id is not None and not _valid_webhook_field(capture_id):
            raise InvalidWebhookEventError("Invalid webhook capture ID.")
    else:
        order_id, capture_id = None, None

    capture_json = None
    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        normalized = normalize_capture(resource)
        if normalized:
            capture_json = json.dumps(normalized)
    initialize_database()
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT 1 FROM webhook_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if existing:
            return _process_webhook_event(connection, event_id)
        if not order_id and capture_id:
            order_id = _order_for_capture(connection, capture_id)
        total = connection.execute("SELECT COUNT(*) FROM webhook_events").fetchone()[0]
        if total >= MAX_STORED_WEBHOOK_EVENTS:
            raise WebhookStorageFullError("Webhook event storage is full.")
        order_exists = supported and connection.execute(
            "SELECT 1 FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if supported and not order_exists:
            pending = connection.execute(
                "SELECT COUNT(*) FROM webhook_events WHERE processing_state = 'PENDING'"
            ).fetchone()[0]
            if pending >= MAX_PENDING_WEBHOOK_EVENTS:
                raise WebhookStorageFullError("Pending webhook event storage is full.")
        connection.execute(
            """
            INSERT INTO webhook_events
                (event_id, event_type, order_id, capture_id, processing_state, processed_at, capture_evidence_json)
            VALUES (?, ?, ?, ?, ?, CASE WHEN ? THEN NULL ELSE CURRENT_TIMESTAMP END, ?)
            """,
            (event_id, event_type, order_id, capture_id,
             "PENDING" if supported else "IGNORED", supported, capture_json),
        )
        return _process_webhook_event(connection, event_id)
