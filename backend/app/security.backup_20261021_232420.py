
import hashlib
import os
import secrets
import sqlite3
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(
    os.getenv("GATEWAY_DB_PATH", str(DATA_DIR / "gateway.db"))
)

current_user_id: ContextVar[str] = ContextVar(
    "current_user_id", default="anonymous"
)
current_user_role: ContextVar[str] = ContextVar(
    "current_user_role", default="anonymous"
)
current_username: ContextVar[str] = ContextVar(
    "current_username", default="anonymous"
)


def connect_db():
    """Create a SQLite connection with row access and foreign keys."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def hash_key(raw_key: str) -> str:
    """Hash a high-entropy API key before storing or looking it up."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _ensure_column(
    conn,
    table: str,
    column: str,
    definition: str,
):
    """Add a column only when it does not already exist."""
    columns = {
        row["name"]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }

    if column not in columns:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


# ---------------------------------------------------------
# Database initialization and safe migrations
# ---------------------------------------------------------

def init_db():
    """
    Initialize tables and apply additive migrations.

    Existing database records are preserved.
    """
    with connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL
                    CHECK (role IN ('admin', 'member')),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE,
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                server_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS upstreams (
                name TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            """
        )

        # User migrations
        _ensure_column(conn, "users", "username", "TEXT")

        # API-key migrations
        _ensure_column(
            conn,
            "api_keys",
            "label",
            "TEXT NOT NULL DEFAULT 'default'",
        )
        _ensure_column(conn, "api_keys", "revoked_at", "TEXT")

        # Audit migrations
        _ensure_column(conn, "audit_logs", "username", "TEXT")
        _ensure_column(conn, "audit_logs", "started_at", "TEXT")
        _ensure_column(conn, "audit_logs", "error_message", "TEXT")

        # Populate usernames for older records.
        conn.execute(
            """
            UPDATE users
            SET username = email
            WHERE username IS NULL OR username = ''
            """
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
            ON users(username)
            """
        )


# ---------------------------------------------------------
# Persistent upstream configuration
# ---------------------------------------------------------

def save_upstream(
    name: str,
    url: str,
    enabled: bool = True,
):
    """Create or update a persisted upstream configuration."""
    name = name.strip()
    url = url.strip()

    if not name:
        raise ValueError("Upstream name is required")

    if not url:
        raise ValueError("Upstream URL is required")

    with connect_db() as conn:
        existing = conn.execute(
            "SELECT created_at FROM upstreams WHERE name = ?",
            (name,),
        ).fetchone()

        created_at = existing["created_at"] if existing else utc_now()

        conn.execute(
            """
            INSERT INTO upstreams (name, url, enabled, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                url = excluded.url,
                enabled = excluded.enabled
            """,
            (name, url, int(enabled), created_at),
        )

    return {
        "name": name,
        "url": url,
        "enabled": bool(enabled),
        "created_at": created_at,
    }


def load_upstreams():
    """Load persisted upstream configurations."""
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT name, url, enabled, created_at
            FROM upstreams
            ORDER BY name
            """
        ).fetchall()

    return [
        {
            "name": row["name"],
            "url": row["url"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def delete_upstream_record(name: str):
    """Delete a persisted upstream configuration."""
    with connect_db() as conn:
        cursor = conn.execute(
            "DELETE FROM upstreams WHERE name = ?",
            (name,),
        )

    return cursor.rowcount > 0


# ---------------------------------------------------------
# User and API-key management
# ---------------------------------------------------------

def create_user(
    username: str,
    role: str = "member",
    email: str | None = None,
):
    """Create a user with the admin or member role."""
    username = username.strip()

    if not 2 <= len(username) <= 80:
        raise ValueError("Username must be between 2 and 80 characters")

    if role not in {"admin", "member"}:
        raise ValueError("Role must be admin or member")

    email = (email or f"{username}@local.invalid").strip().lower()

    if not email:
        raise ValueError("Email is required")

    user_id = secrets.token_hex(12)

    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO users (id, username, email, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, username, email, role, utc_now()),
        )

    return user_id


def issue_api_key(user_id: str, label: str = "default"):
    """
    Issue a new API key.

    The raw key is returned once. Only its SHA-256 hash is stored.
    """
    label = label.strip()

    if not label:
        raise ValueError("API key label is required")

    raw_key = "tmcp_" + secrets.token_urlsafe(32)

    with connect_db() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if user is None:
            raise ValueError("User not found")

        cursor = conn.execute(
            """
            INSERT INTO api_keys (user_id, key_hash, label, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, hash_key(raw_key), label, utc_now()),
        )

        key_id = cursor.lastrowid

    return {
        "key_id": key_id,
        "user_id": user_id,
        "label": label,
        "api_key": raw_key,
        "warning": "Save this key now; it will not be shown again.",
    }


def authenticate_api_key(raw_key: str):
    """Return the user associated with a valid, non-revoked key."""
    if not raw_key:
        return None

    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT
                u.id,
                u.username,
                u.email,
                u.role,
                k.id AS key_id
            FROM api_keys AS k
            JOIN users AS u ON u.id = k.user_id
            WHERE k.key_hash = ?
              AND k.revoked = 0
            """,
            (hash_key(raw_key),),
        ).fetchone()

    return dict(row) if row else None


def revoke_api_key(key_id: int):
    """Revoke an active API key."""
    with connect_db() as conn:
        cursor = conn.execute(
            """
            UPDATE api_keys
            SET revoked = 1, revoked_at = ?
            WHERE id = ? AND revoked = 0
            """,
            (utc_now(), key_id),
        )

    return cursor.rowcount > 0


# ---------------------------------------------------------
# MCP audit logging
# ---------------------------------------------------------

def write_audit(
    user_id: str,
    username: str,
    server_name: str,
    tool_name: str,
    duration_ms: int,
    outcome: str,
    error_message: str | None = None,
):
    """Record a tool call's identity, duration, and outcome."""
    timestamp = utc_now()
    error_message = error_message[:500] if error_message else None

    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (
                user_id,
                username,
                server_name,
                tool_name,
                timestamp,
                started_at,
                duration_ms,
                outcome,
                error,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                server_name,
                tool_name,
                timestamp,
                timestamp,
                max(0, duration_ms),
                outcome,
                error_message,
                error_message,
            ),
        )


# ---------------------------------------------------------
# Authentication and role-based authorization
# ---------------------------------------------------------

class GatewayAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Kubernetes liveness/readiness check.
        if path == "/health":
            return await call_next(request)

        is_admin_path = (
            path == "/admin" or path.startswith("/admin/")
        )

        is_mcp_path = (
            path == "/mcp" or path.startswith("/mcp/")
        )

        # API-key-protected endpoints for logged-in users.
        is_member_api_path = (
            path == "/api" or path.startswith("/api/")
        )

        user = None

        if is_admin_path:
            # Bootstrap token supports initial administration.
            expected = os.getenv("ADMIN_BOOTSTRAP_TOKEN", "")
            supplied = request.headers.get("x-admin-token", "")

            if (
                expected
                and supplied
                and secrets.compare_digest(supplied, expected)
            ):
                user = {
                    "id": "bootstrap-admin",
                    "username": "bootstrap-admin",
                    "email": "bootstrap-admin",
                    "role": "admin",
                }
            else:
                # A registered admin may use an individual API key.
                user = authenticate_api_key(
                    request.headers.get("x-api-key", "")
                )

            if user is None:
                return JSONResponse(
                    {"detail": "Invalid admin credentials"},
                    status_code=401,
                )

            if user.get("role") != "admin":
                return JSONResponse(
                    {"detail": "Admin role required"},
                    status_code=403,
                )

        elif is_mcp_path or is_member_api_path:
            # MCP tools and member API endpoints require a valid key.
            user = authenticate_api_key(
                request.headers.get("x-api-key", "")
            )

            if user is None:
                return JSONResponse(
                    {
                        "detail": (
                            "Missing, invalid, or revoked API key"
                        )
                    },
                    status_code=401,
                )

        else:
            # Unprotected routes, such as non-sensitive documentation.
            return await call_next(request)

        # Make the authenticated identity available to route handlers
        # and audit logging for the duration of this request.
        user_token = current_user_id.set(user["id"])
        role_token = current_user_role.set(user["role"])
        username_token = current_username.set(
            user.get("username") or user["email"]
        )

        request.state.user = user

        try:
            return await call_next(request)
        finally:
            current_user_id.reset(user_token)
            current_user_role.reset(role_token)
            username_token and current_username.reset(username_token)
