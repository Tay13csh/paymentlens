"""Local SQLite storage shared by the Streamlit app and webhook receiver."""

import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


DATABASE_PATH = Path(__file__).with_name("payguard.db")
MAX_PENDING_WEBHOOK_EVENTS = 1_000
MAX_STORED_WEBHOOK_EVENTS = 100_000
MAX_WEBHOOK_FIELD_LENGTH = 255
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
            "SELECT request_id, amount, currency, order_id, approval_url FROM order_creation_attempts WHERE request_id = ?",
            (request_id,),
        ).fetchone()
    return dict(row) if row else None


def complete_order_creation(request_id: str, order_id: str, approval_url: str) -> None:
    """Save the returned order and its attempt together, without losing retry identity."""
    initialize_database()
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        attempt = connection.execute(
            "SELECT amount, currency FROM order_creation_attempts WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if not attempt:
            raise ValueError("Unknown order creation attempt.")
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


def _process_webhook_event(connection: sqlite3.Connection, event_id: str) -> bool:
    """Apply saved, verified fields only; caller owns the write transaction."""
    event = connection.execute(
        "SELECT * FROM webhook_events WHERE event_id = ? AND processing_state = 'PENDING'",
        (event_id,),
    ).fetchone()
    if not event:
        return False
    order = connection.execute(
        "SELECT 1 FROM orders WHERE order_id = ?", (event["order_id"],)
    ).fetchone()
    if not order:
        return False
    applied = _apply_status_update(
        connection, event["order_id"], WEBHOOK_STATUS_BY_EVENT[event["event_type"]],
        event["capture_id"], allow_same_status=False,
    )
    connection.execute(
        """
        UPDATE webhook_events SET processing_state = ?, processed_at = CURRENT_TIMESTAMP
        WHERE event_id = ?
        """,
        ("APPLIED" if applied else "IGNORED", event_id),
    )
    return applied


def _valid_webhook_field(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_WEBHOOK_FIELD_LENGTH


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
        capture_id = resource.get("id")

    supported = event_type in WEBHOOK_STATUS_BY_EVENT
    if supported:
        if not _valid_webhook_field(order_id):
            raise InvalidWebhookEventError("Missing or oversized webhook order ID.")
        if capture_id is not None and not _valid_webhook_field(capture_id):
            raise InvalidWebhookEventError("Invalid webhook capture ID.")
    else:
        order_id, capture_id = None, None

    initialize_database()
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT 1 FROM webhook_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if existing:
            return _process_webhook_event(connection, event_id)
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
                (event_id, event_type, order_id, capture_id, processing_state, processed_at)
            VALUES (?, ?, ?, ?, ?, CASE WHEN ? THEN NULL ELSE CURRENT_TIMESTAMP END)
            """,
            (event_id, event_type, order_id, capture_id,
             "PENDING" if supported else "IGNORED", supported),
        )
        return _process_webhook_event(connection, event_id)
