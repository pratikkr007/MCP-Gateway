import hashlib
import logging
import os
import secrets
import sqlite3
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.upstream_security import (
    encrypt_credential,
    decrypt_credential,
)

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------
# Database helpers
# ---------------------------------------------------------

def connect_db():
    """Create a SQLite connection with row access and foreign keys."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def utc_now():
    """Return the current UTC time as an ISO 8601 string."""
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

            CREATE TABLE IF NOT EXISTS tool_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_type TEXT NOT NULL
                    CHECK (subject_type IN ('role', 'user')),
                subject TEXT NOT NULL,
                server_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                effect TEXT NOT NULL
                    CHECK (effect IN ('allow', 'deny')),
                created_at TEXT NOT NULL,
                UNIQUE (subject_type, subject, server_name, tool_name)
            );

            CREATE TABLE IF NOT EXISTS gateway_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
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
        _ensure_column(conn, "api_keys", "last_used_at", "TEXT")
        _ensure_column(conn, "api_keys", "key_prefix", "TEXT")

        # Audit migrations
        _ensure_column(conn, "audit_logs", "username", "TEXT")
        _ensure_column(conn, "audit_logs", "started_at", "TEXT")
        _ensure_column(conn, "audit_logs", "error_message", "TEXT")

        # Upstream authentication and health-state migrations.
        _ensure_column(
            conn,
            "upstreams",
            "auth_mode",
            "TEXT NOT NULL DEFAULT 'none'",
        )
        _ensure_column(
            conn,
            "upstreams",
            "credential_ciphertext",
            "TEXT",
        )
        _ensure_column(
            conn,
            "upstreams",
            "credential_nonce",
            "TEXT",
        )
        _ensure_column(
            conn,
            "upstreams",
            "custom_header_name",
            "TEXT",
        )
        _ensure_column(
            conn,
            "upstreams",
            "timeout_seconds",
            "INTEGER NOT NULL DEFAULT 15",
        )
        _ensure_column(
            conn,
            "upstreams",
            "connection_status",
            "TEXT NOT NULL DEFAULT 'unknown'",
        )
        _ensure_column(
            conn,
            "upstreams",
            "consecutive_failures",
            "INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(
            conn,
            "upstreams",
            "last_checked_at",
            "TEXT",
        )
        _ensure_column(
            conn,
            "upstreams",
            "last_success_at",
            "TEXT",
        )
        _ensure_column(
            conn,
            "upstreams",
            "last_discovery_at",
            "TEXT",
        )
        _ensure_column(
            conn,
            "upstreams",
            "last_error",
            "TEXT",
        )
        _ensure_column(
            conn,
            "upstreams",
            "circuit_open_until",
            "TEXT",
        )

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

        _seed_default_permissions(conn)


# ---------------------------------------------------------
# Persistent upstream configuration
# ---------------------------------------------------------

def _upstream_to_dict(row, include_secrets: bool = False):
    """
    Convert an upstream database row into a dictionary.

    Ciphertext and nonce are never returned. Plaintext credentials
    are included only when explicitly requested by internal code.
    """
    result = {
        "name": row["name"],
        "url": row["url"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "auth_mode": row["auth_mode"],
        "custom_header_name": row["custom_header_name"],
        "timeout_seconds": row["timeout_seconds"],
        "connection_status": row["connection_status"],
        "consecutive_failures": row["consecutive_failures"],
        "last_checked_at": row["last_checked_at"],
        "last_success_at": row["last_success_at"],
        "last_discovery_at": row["last_discovery_at"],
        "last_error": row["last_error"],
        "circuit_open_until": row["circuit_open_until"],
        "hasCredential": bool(row["credential_ciphertext"]),
    }

    if include_secrets:
        ciphertext = row["credential_ciphertext"]
        nonce = row["credential_nonce"]

        result["credential"] = (
            decrypt_credential(ciphertext, nonce)
            if ciphertext and nonce
            else None
        )

    return result


def save_upstream(
    name: str,
    url: str,
    enabled: bool = True,
    auth_mode: str = "none",
    credential: str | None = None,
    custom_header_name: str | None = None,
    timeout_seconds: int = 15,
):
    """
    Create or update a persisted upstream configuration.

    Credentials are encrypted before they are written to SQLite.
    Existing credentials are preserved when no replacement is supplied.
    """
    name = name.strip()
    url = url.strip()
    auth_mode = auth_mode.strip().lower()

    if not name:
        raise ValueError("Upstream name is required")

    if not url:
        raise ValueError("Upstream URL is required")

    if auth_mode not in {"none", "bearer", "custom_header"}:
        raise ValueError(
            "auth_mode must be none, bearer, or custom_header"
        )

    if auth_mode == "custom_header":
        custom_header_name = (custom_header_name or "").strip()

        if not custom_header_name:
            raise ValueError(
                "custom_header_name is required for custom_header mode"
            )

        # Reject invalid HTTP header names and header injection.
        if (
            any(char in custom_header_name for char in "\r\n:")
            or not all(
                char.isalnum() or char in "!#$%&'*+-.^_`|~"
                for char in custom_header_name
            )
        ):
            raise ValueError("Invalid custom_header_name")
    else:
        custom_header_name = None

    try:
        timeout_seconds = int(timeout_seconds)
    except (TypeError, ValueError):
        raise ValueError(
            "timeout_seconds must be between 1 and 120"
        ) from None

    if not 1 <= timeout_seconds <= 120:
        raise ValueError("timeout_seconds must be between 1 and 120")

    with connect_db() as conn:
        existing = conn.execute(
            """
            SELECT *
            FROM upstreams
            WHERE name = ?
            """,
            (name,),
        ).fetchone()

        created_at = (
            existing["created_at"]
            if existing
            else utc_now()
        )

        old_url = existing["url"] if existing else None
        old_auth_mode = (
            existing["auth_mode"] if existing else "none"
        )
        old_header_name = (
            existing["custom_header_name"]
            if existing
            else None
        )

        # Keep the existing encrypted credential unless a replacement
        # is supplied or authentication is disabled.
        ciphertext = (
            existing["credential_ciphertext"]
            if existing
            else None
        )
        nonce = (
            existing["credential_nonce"]
            if existing
            else None
        )

        if auth_mode == "none":
            ciphertext = None
            nonce = None

        elif credential is not None:
            if credential.strip():
                ciphertext, nonce = encrypt_credential(credential)
            else:
                # An explicitly empty credential clears the secret.
                ciphertext = None
                nonce = None

        credential_changed = (
            credential is not None
            and credential.strip() != ""
        )

        configuration_changed = (
            existing is None
            or old_url != url
            or old_auth_mode != auth_mode
            or old_header_name != custom_header_name
            or credential_changed
        )

        if configuration_changed:
            connection_status = "unknown"
            consecutive_failures = 0
            last_checked_at = None
            last_success_at = None
            last_discovery_at = None
            last_error = None
            circuit_open_until = None
        else:
            connection_status = existing["connection_status"]
            consecutive_failures = existing["consecutive_failures"]
            last_checked_at = existing["last_checked_at"]
            last_success_at = existing["last_success_at"]
            last_discovery_at = existing["last_discovery_at"]
            last_error = existing["last_error"]
            circuit_open_until = existing["circuit_open_until"]

        conn.execute(
            """
            INSERT INTO upstreams (
                name,
                url,
                enabled,
                created_at,
                auth_mode,
                credential_ciphertext,
                credential_nonce,
                custom_header_name,
                timeout_seconds,
                connection_status,
                consecutive_failures,
                last_checked_at,
                last_success_at,
                last_discovery_at,
                last_error,
                circuit_open_until
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                url = excluded.url,
                enabled = excluded.enabled,
                auth_mode = excluded.auth_mode,
                credential_ciphertext = excluded.credential_ciphertext,
                credential_nonce = excluded.credential_nonce,
                custom_header_name = excluded.custom_header_name,
                timeout_seconds = excluded.timeout_seconds,
                connection_status = excluded.connection_status,
                consecutive_failures = excluded.consecutive_failures,
                last_checked_at = excluded.last_checked_at,
                last_success_at = excluded.last_success_at,
                last_discovery_at = excluded.last_discovery_at,
                last_error = excluded.last_error,
                circuit_open_until = excluded.circuit_open_until
            """,
            (
                name,
                url,
                int(enabled),
                created_at,
                auth_mode,
                ciphertext,
                nonce,
                custom_header_name,
                timeout_seconds,
                connection_status,
                consecutive_failures,
                last_checked_at,
                last_success_at,
                last_discovery_at,
                last_error,
                circuit_open_until,
            ),
        )

        row = conn.execute(
            """
            SELECT *
            FROM upstreams
            WHERE name = ?
            """,
            (name,),
        ).fetchone()

    # Never return ciphertext, nonce, or plaintext credentials here.
    return _upstream_to_dict(row)


def load_upstreams(include_secrets: bool = False):
    """
    Load persisted upstream configurations.

    By default, this returns metadata only. Set include_secrets=True
    only for trusted internal gateway code that needs credentials.
    """
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM upstreams
            ORDER BY name
            """
        ).fetchall()

    return [
        _upstream_to_dict(
            row,
            include_secrets=include_secrets,
        )
        for row in rows
    ]


def delete_upstream_record(name: str):
    """Delete a persisted upstream configuration."""
    with connect_db() as conn:
        cursor = conn.execute(
            "DELETE FROM upstreams WHERE name = ?",
            (name.strip(),),
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
            INSERT INTO api_keys (user_id, key_hash, label, key_prefix, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, hash_key(raw_key), label, raw_key[:10], utc_now()),
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

        if row is None:
            return None

        cursor = conn.execute(
            """
            UPDATE api_keys
            SET last_used_at = ?
            WHERE id = ? AND revoked = 0
            """,
            (utc_now(), row["key_id"]),
        )

        if cursor.rowcount != 1:
            return None

        return dict(row)


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


def list_users():
    """List users with API-key usage summaries."""
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                u.id AS user_id,
                u.username,
                u.email,
                u.role,
                u.created_at,
                COUNT(CASE WHEN k.revoked = 0 THEN 1 END) AS active_keys,
                COUNT(k.id) AS total_keys,
                MAX(k.last_used_at) AS last_used_at
            FROM users AS u
            LEFT JOIN api_keys AS k ON k.user_id = u.id
            GROUP BY u.id
            ORDER BY u.created_at ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def _other_admin_count(conn, user_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND id != ?",
        (user_id,),
    ).fetchone()[0]


def update_user_role(user_id: str, role: str) -> bool:
    """Change a user's role. Refuses to demote the last admin."""
    if role not in {"admin", "member"}:
        raise ValueError("Role must be admin or member")

    with connect_db() as conn:
        row = conn.execute(
            "SELECT id, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()

        if row is None:
            return False

        if (
            row["role"] == "admin"
            and role != "admin"
            and _other_admin_count(conn, user_id) == 0
        ):
            raise ValueError("Cannot demote the last admin")

        conn.execute(
            "UPDATE users SET role = ? WHERE id = ?", (role, user_id)
        )

    return True


def delete_user(user_id: str) -> bool:
    """Delete a user and their API keys. Audit history is kept."""
    with connect_db() as conn:
        row = conn.execute(
            "SELECT id, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()

        if row is None:
            return False

        if row["role"] == "admin" and _other_admin_count(conn, user_id) == 0:
            raise ValueError("Cannot remove the last admin")

        conn.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
        conn.execute(
            "DELETE FROM tool_permissions "
            "WHERE subject_type = 'user' AND subject = ?",
            (user_id,),
        )
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    return True


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
    started_at: str | None = None,
):
    """Record a tool call's start time, completion time, duration, and outcome."""
    timestamp = utc_now()
    started_at = started_at or timestamp
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
                started_at,
                max(0, duration_ms),
                outcome,
                error_message,
                error_message,
            ),
        )


# ---------------------------------------------------------
# Tool permissions
# ---------------------------------------------------------

# Seeded once on first start. Admins can change or delete these in the dashboard.
DEFAULT_MEMBER_DENIES = [
    ("notes", "create_note"),
    ("woocommerce", "create_product"),
    ("woocommerce", "update_order_status"),
]


def _seed_default_permissions(conn):
    """Insert default member restrictions exactly once."""
    already = conn.execute(
        "SELECT value FROM gateway_settings "
        "WHERE key = 'default_permissions_seeded'"
    ).fetchone()
    if already:
        return

    for server_name, tool_name in DEFAULT_MEMBER_DENIES:
        conn.execute(
            """
            INSERT OR IGNORE INTO tool_permissions
                (subject_type, subject, server_name, tool_name,
                 effect, created_at)
            VALUES ('role', 'member', ?, ?, 'deny', ?)
            """,
            (server_name, tool_name, utc_now()),
        )

    conn.execute(
        "INSERT INTO gateway_settings (key, value) "
        "VALUES ('default_permissions_seeded', '1')"
    )


def get_user(user_id: str):
    with connect_db() as conn:
        row = conn.execute(
            "SELECT id, username, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def is_tool_allowed(
    user_id: str,
    role: str,
    server_name: str,
    tool_name: str,
) -> bool:
    """
    Decide whether a user may see or call an upstream tool.

    - admin: always allowed
    - unknown role: denied
    - otherwise the most specific matching rule wins:
        user rule > role rule, then exact tool > server-wide > global,
        then deny > allow. No matching rule means allowed.
    """
    if role == "admin":
        return True
    if role != "member":
        return False

    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT subject_type, server_name, tool_name, effect
            FROM tool_permissions
            WHERE (
                    (subject_type = 'role' AND subject = ?)
                 OR (subject_type = 'user' AND subject = ?)
                  )
              AND server_name IN (?, '*')
              AND tool_name IN (?, '*')
            """,
            (role, user_id, server_name, tool_name),
        ).fetchall()

    best_key = None
    best_effect = None

    for row in rows:
        # A wildcard server with a specific tool is meaningless.
        if row["server_name"] == "*" and row["tool_name"] != "*":
            continue

        level = 1 if row["subject_type"] == "user" else 0
        if row["tool_name"] != "*":
            specificity = 2
        elif row["server_name"] != "*":
            specificity = 1
        else:
            specificity = 0
        deny_bonus = 1 if row["effect"] == "deny" else 0

        key = (level, specificity, deny_bonus)
        if best_key is None or key > best_key:
            best_key = key
            best_effect = row["effect"]

    return best_effect != "deny"


def list_tool_permissions():
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id,
                p.subject_type,
                p.subject,
                CASE WHEN p.subject_type = 'user'
                     THEN COALESCE(u.username, p.subject)
                     ELSE p.subject END AS subject_label,
                p.server_name,
                p.tool_name,
                p.effect,
                p.created_at
            FROM tool_permissions AS p
            LEFT JOIN users AS u
                ON p.subject_type = 'user' AND u.id = p.subject
            ORDER BY p.server_name, p.tool_name,
                     p.subject_type, p.subject
            """
        ).fetchall()
    return [dict(row) for row in rows]


def set_tool_permission(
    subject_type: str,
    subject: str,
    server_name: str,
    tool_name: str,
    effect: str,
):
    """Create or update a rule. Returns the stored rule."""
    subject_type = subject_type.strip().lower()
    subject = subject.strip()
    server_name = server_name.strip()
    tool_name = (tool_name or "*").strip() or "*"
    effect = effect.strip().lower()

    if subject_type not in {"role", "user"}:
        raise ValueError("subject_type must be 'role' or 'user'")
    if effect not in {"allow", "deny"}:
        raise ValueError("effect must be 'allow' or 'deny'")
    if not subject or not server_name:
        raise ValueError("subject and server_name are required")
    if server_name == "*" and tool_name != "*":
        raise ValueError("A specific tool requires a specific server")

    if subject_type == "role" and subject != "member":
        raise ValueError(
            "Role rules apply to 'member' only; admins always have "
            "full access"
        )

    with connect_db() as conn:
        if subject_type == "user":
            exists = conn.execute(
                "SELECT 1 FROM users WHERE id = ?", (subject,)
            ).fetchone()
            if exists is None:
                raise ValueError("User not found")

        conn.execute(
            """
            INSERT INTO tool_permissions
                (subject_type, subject, server_name, tool_name,
                 effect, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(subject_type, subject, server_name, tool_name)
            DO UPDATE SET effect = excluded.effect
            """,
            (subject_type, subject, server_name, tool_name,
             effect, utc_now()),
        )

        row = conn.execute(
            """
            SELECT id, subject_type, subject, server_name,
                   tool_name, effect, created_at
            FROM tool_permissions
            WHERE subject_type = ? AND subject = ?
              AND server_name = ? AND tool_name = ?
            """,
            (subject_type, subject, server_name, tool_name),
        ).fetchone()

    return dict(row)


def delete_tool_permission(permission_id: int) -> bool:
    with connect_db() as conn:
        cursor = conn.execute(
            "DELETE FROM tool_permissions WHERE id = ?",
            (permission_id,),
        )
    return cursor.rowcount > 0


# ---------------------------------------------------------
# Authentication and role-based authorization
# ---------------------------------------------------------

def extract_api_key(request: Request) -> str:
    """Accept API keys from x-api-key or Authorization: Bearer."""
    api_key = request.headers.get("x-api-key", "").strip()
    if api_key:
        return api_key
    authorization = request.headers.get("authorization", "").strip()
    scheme, separator, credential = authorization.partition(" ")
    if separator and scheme.lower() == "bearer":
        return credential.strip()
    return ""


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
                user = authenticate_api_key(extract_api_key(request))

            if user is None:
                try:
                    write_audit(
                        user_id="anonymous",
                        username="anonymous",
                        server_name="gateway",
                        tool_name="auth.admin",
                        duration_ms=0,
                        outcome="denied",
                        error_message="Invalid admin credentials",
                    )
                except Exception:
                    logger.exception(
                        "Failed to audit rejected admin authentication"
                    )
                return JSONResponse(
                    {"detail": "Invalid admin credentials"},
                    status_code=401,
                )

            if user.get("role") != "admin":
                try:
                    write_audit(
                        user_id=str(user.get("id") or "unknown"),
                        username=str(user.get("username") or "unknown"),
                        server_name="gateway",
                        tool_name="auth.admin",
                        duration_ms=0,
                        outcome="denied",
                        error_message="Admin access denied: insufficient role",
                    )
                except Exception:
                    logger.exception(
                        "Failed to audit admin authorization denial"
                    )
                return JSONResponse(
                    {"detail": "Admin role required"},
                    status_code=403,
                )

        elif is_mcp_path or is_member_api_path:
            # MCP tools and member API endpoints require a valid key.
            user = authenticate_api_key(extract_api_key(request))

            if user is None:
                try:
                    write_audit(
                        user_id="anonymous",
                        username="anonymous",
                        server_name="gateway",
                        tool_name="auth.api",
                        duration_ms=0,
                        outcome="denied",
                        error_message="Missing, invalid, or revoked API key",
                    )
                except Exception:
                    logger.exception(
                        "Failed to audit rejected API authentication"
                    )
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
            current_username.reset(username_token)

            