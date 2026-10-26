from fastapi.middleware.cors import CORSMiddleware
from fastapi import HTTPException

import asyncio

from fastapi import Request
import httpx
import json
import inspect
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from backend.app.upstream_security import (
    build_auth_headers,
    validate_upstream_url as validate_secure_upstream_url,
)

from backend.app.security import (
    GatewayAuthMiddleware,
    init_db,
    create_user,
    issue_api_key,
    revoke_api_key,
    list_users,
    update_user_role,
    delete_user,
    connect_db,
    current_user_id,
    current_user_role,
    current_username,
    write_audit,
    load_upstreams,
    save_upstream,
    delete_upstream_record,
    get_user,
    is_tool_allowed,
    list_tool_permissions,
    set_tool_permission,
    delete_tool_permission,
)

# --------------------------------------------------
# Configuration
# --------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-gateway")

DEFAULT_UPSTREAMS = {
    "woocommerce": os.getenv(
        "WOOCOMMERCE_MCP_URL",
        "http://127.0.0.1:8000/mcp",
    ),
    "notes": os.getenv(
        "NOTES_MCP_URL",
        "http://127.0.0.1:8002/mcp",
    ),
    "inventory": os.getenv(
        "INVENTORY_MCP_URL",
        "http://127.0.0.1:8003/mcp",
    ),
}

UPSTREAMS: dict[str, str] = {}
UPSTREAM_ENABLED: dict[str, bool] = {}
UPSTREAM_CONFIG: dict[str, dict[str, Any]] = {}
UPSTREAM_FAILURES: dict[str, int] = {}

UPSTREAM_CONNECT_TIMEOUT_SECONDS = int(
    os.getenv("UPSTREAM_CONNECT_TIMEOUT_SECONDS", "5")
)
UPSTREAM_DISCOVERY_TIMEOUT_SECONDS = int(
    os.getenv("UPSTREAM_DISCOVERY_TIMEOUT_SECONDS", "10")
)
UPSTREAM_TOOL_TIMEOUT_SECONDS = int(
    os.getenv("UPSTREAM_TOOL_TIMEOUT_SECONDS", "20")
)
UPSTREAM_HEALTH_CHECK_INTERVAL_SECONDS = max(
    5, int(os.getenv("UPSTREAM_HEALTH_CHECK_INTERVAL_SECONDS", "30"))
)
UPSTREAM_FAILURE_THRESHOLD = max(
    1, int(os.getenv("UPSTREAM_FAILURE_THRESHOLD", "3"))
)
UPSTREAM_CIRCUIT_OPEN_SECONDS = max(
    1, int(os.getenv("UPSTREAM_CIRCUIT_OPEN_SECONDS", "60"))
)

TOOL_ROUTES: dict[str, dict[str, str]] = {}
REGISTRATION_LOCK = asyncio.Lock()


# --------------------------------------------------
# Gateway MCP server
# --------------------------------------------------

class PermissionedFastMCP(FastMCP):
    """FastMCP that hides tools the calling user may not use."""

    async def list_tools(self):
        tools = await super().list_tools()
        user_id = current_user_id.get()
        role = current_user_role.get()

        visible = []
        for tool in tools:
            route = TOOL_ROUTES.get(tool.name)
            if route is None:
                continue
            if is_tool_allowed(user_id, role, route["server"], route["tool"]):
                visible.append(tool)
        return visible


gateway_mcp = PermissionedFastMCP(
    "team-mcp-gateway",
    host="0.0.0.0",
    port=8081,
    stateless_http=True,
)


# --------------------------------------------------
# MCP upstream helpers
# --------------------------------------------------

def get_upstream_config(server_name: str) -> dict[str, Any]:
    config = UPSTREAM_CONFIG.get(server_name)
    if not config:
        raise RuntimeError(f"Unknown upstream server: {server_name}")
    if not config.get("enabled", False):
        raise RuntimeError(f"Upstream '{server_name}' is disabled")
    return config


def get_upstream_headers(config: dict[str, Any]) -> dict[str, str]:
    return build_auth_headers(
        auth_mode=config.get("auth_mode", "none"),
        credential=config.get("credential"),
        custom_header_name=config.get("custom_header_name"),
    )


def circuit_is_open(config: dict[str, Any]) -> bool:
    value = config.get("circuit_open_until")
    if not value:
        return False
    try:
        until = datetime.fromisoformat(value)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < until
    except (TypeError, ValueError):
        return False


def update_upstream_status(
    name: str,
    status: str,
    *,
    error: str | None = None,
    discovery_succeeded: bool = False,
):
    """Persist safe connection/health metadata without storing secrets."""
    now = datetime.now(timezone.utc).isoformat()
    config = UPSTREAM_CONFIG.get(name, {})
    failures = UPSTREAM_FAILURES.get(
        name, int(config.get("consecutive_failures") or 0)
    )

    if status == "connected":
        failures = 0
        circuit_open_until = None
        last_success_at = now
        last_error = None
    elif status == "disabled":
        failures = 0
        circuit_open_until = None
        last_success_at = config.get("last_success_at")
        last_error = None
    elif status == "circuit_open":
        circuit_open_until = (
            datetime.now(timezone.utc)
            + timedelta(seconds=UPSTREAM_CIRCUIT_OPEN_SECONDS)
        ).isoformat()
        last_success_at = config.get("last_success_at")
        last_error = (error or "Circuit breaker open")[:500]
    else:
        failures += 1
        circuit_open_until = None
        last_success_at = config.get("last_success_at")
        last_error = (error or status)[:500]
        if failures >= UPSTREAM_FAILURE_THRESHOLD:
            status = "circuit_open"
            circuit_open_until = (
                datetime.now(timezone.utc)
                + timedelta(seconds=UPSTREAM_CIRCUIT_OPEN_SECONDS)
            ).isoformat()

    UPSTREAM_FAILURES[name] = failures
    config.update({
        "connection_status": status,
        "consecutive_failures": failures,
        "last_checked_at": now,
        "last_success_at": last_success_at,
        "last_error": last_error,
        "circuit_open_until": circuit_open_until,
    })
    if discovery_succeeded:
        config["last_discovery_at"] = now

    with connect_db() as conn:
        conn.execute(
            """
            UPDATE upstreams
            SET connection_status = ?,
                consecutive_failures = ?,
                last_checked_at = ?,
                last_success_at = ?,
                last_discovery_at = ?,
                last_error = ?,
                circuit_open_until = ?
            WHERE name = ?
            """,
            (
                status,
                failures,
                now,
                last_success_at,
                config.get("last_discovery_at"),
                last_error,
                circuit_open_until,
                name,
            ),
        )


def record_upstream_success(
    server_name: str,
    discovery_succeeded: bool = False,
):
    update_upstream_status(
        server_name,
        "connected",
        discovery_succeeded=discovery_succeeded,
    )


def record_upstream_failure(server_name: str, exc: Exception):
    update_upstream_status(
        server_name,
        "error",
        error=f"{type(exc).__name__}: {str(exc)}",
    )


async def discover_upstream_tools(server_name: str, url: str):
    """Discover tools from one upstream using its configured auth and timeout."""
    config = get_upstream_config(server_name)
    headers = get_upstream_headers(config)
    timeout_seconds = min(
        UPSTREAM_DISCOVERY_TIMEOUT_SECONDS,
        int(config.get("timeout_seconds") or UPSTREAM_DISCOVERY_TIMEOUT_SECONDS),
    )

    async with streamablehttp_client(
        url,
        headers=headers,
        timeout=timedelta(seconds=UPSTREAM_CONNECT_TIMEOUT_SECONDS),
        sse_read_timeout=timedelta(seconds=timeout_seconds),
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(
                session.initialize(),
                timeout=timeout_seconds,
            )
            result = await asyncio.wait_for(
                session.list_tools(),
                timeout=timeout_seconds,
            )
            return result.tools


async def call_upstream(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
):
    """Call an upstream MCP tool with authentication, timeout and breaker."""
    config = get_upstream_config(server_name)

    if circuit_is_open(config):
        raise RuntimeError(
            f"Upstream '{server_name}' circuit breaker is open until "
            f"{config.get('circuit_open_until')}"
        )

    url = config["url"]
    headers = get_upstream_headers(config)
    timeout_seconds = min(
        UPSTREAM_TOOL_TIMEOUT_SECONDS,
        int(config.get("timeout_seconds") or UPSTREAM_TOOL_TIMEOUT_SECONDS),
    )

    try:
        async with streamablehttp_client(
            url,
            headers=headers,
            timeout=UPSTREAM_CONNECT_TIMEOUT_SECONDS,
            sse_read_timeout=timeout_seconds,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await asyncio.wait_for(
                    session.initialize(),
                    timeout=timeout_seconds,
                )
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments),
                    timeout=timeout_seconds,
                )

        if result.isError:
            record_upstream_failure(
                server_name,
                RuntimeError("Upstream tool returned an error"),
            )
        else:
            record_upstream_success(server_name)

        return {
            "isError": result.isError,
            "content": [
                item.model_dump(mode="json")
                for item in result.content
            ],
        }
    except Exception as exc:
        record_upstream_failure(server_name, exc)
        raise


# --------------------------------------------------
# Dynamic tool registration
# --------------------------------------------------

def safe_tool_name(name: str) -> str:
    """Convert a name into a predictable identifier."""
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    return normalized.strip("_") or "unnamed_tool"


def make_proxy(
    server_name: str,
    upstream_tool_name: str,
    input_schema: dict,
):
    """Create a dynamically typed proxy for an upstream tool."""
    properties = input_schema.get("properties", {})
    required_fields = set(input_schema.get("required", []))

    parameters = []

    for name, details in properties.items():
        schema_type = details.get("type", "string")

        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "object": dict,
            "array": list,
        }

        annotation = type_mapping.get(schema_type, Any)

        if name in required_fields:
            default = inspect.Parameter.empty
        else:
            if "default" in details:
                default = details["default"]
            elif schema_type == "integer":
                default = 10 if name == "per_page" else None
            else:
                default = None

            if default is None:
                annotation = Any

        parameters.append(
            inspect.Parameter(
                name=name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )

    async def proxy(**arguments):
        arguments = {
            key: value
            for key, value in arguments.items()
            if value is not None
        }

        audit_started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        outcome = "success"
        error_message = None

        user_id = current_user_id.get()
        username = current_username.get()

        try:
            user_role = current_user_role.get()

            if not is_tool_allowed(
                user_id, user_role, server_name, upstream_tool_name
            ):
                raise PermissionError(
                    f"You are not permitted to call "
                    f"{server_name}.{upstream_tool_name}"
                )

            result = await call_upstream(
                server_name,
                upstream_tool_name,
                arguments,
            )

            if result.get("isError"):
                outcome = "error"
                error_message = "Upstream tool returned an error"

            return result

        except Exception as exc:
            if isinstance(exc, PermissionError):
                outcome = "denied"
            elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                outcome = "timeout"
            else:
                outcome = "error"
            error_message = str(exc)[:500] or type(exc).__name__
            raise

        finally:
            duration_ms = int(
                (time.perf_counter() - started) * 1000
            )

            try:
                write_audit(
                    user_id=user_id,
                    username=username,
                    server_name=server_name,
                    tool_name=upstream_tool_name,
                    duration_ms=duration_ms,
                    outcome=outcome,
                    error_message=error_message,
                    started_at=audit_started_at,
                )
            except Exception:
                logger.exception(
                    "Failed to write MCP tool audit record"
                )

    proxy.__name__ = f"{server_name}_{upstream_tool_name}"
    proxy.__doc__ = f"Proxy for {server_name}.{upstream_tool_name}"
    proxy.__signature__ = inspect.Signature(parameters)

    return proxy


async def refresh_upstream_tools() -> dict[str, int]:
    """
    Discover enabled upstreams concurrently.

    Temporary failures do not remove previously registered tools. Disabled
    and deleted upstreams have their tools removed from the gateway.
    """
    candidates = [
        (name, config["url"])
        for name, config in list(UPSTREAM_CONFIG.items())
        if config.get("enabled", False)
    ]

    async def discover_one(name: str, url: str):
        config = UPSTREAM_CONFIG.get(name, {})
        if circuit_is_open(config):
            # Do not count a skipped probe as another failure.
            return name, [], None, False

        try:
            tools = await discover_upstream_tools(name, url)
            record_upstream_success(name, discovery_succeeded=True)
            return name, tools, None, True
        except Exception as exc:
            record_upstream_failure(name, exc)
            logger.warning(
                "Discovery failed for upstream '%s': %s",
                name,
                str(exc)[:300],
            )
            return name, [], exc, False

    results = await asyncio.gather(
        *(discover_one(name, url) for name, url in candidates),
        return_exceptions=False,
    )

    discovered: dict[str, list[Any]] = {}
    successful_names: set[str] = set()

    for name, tools, error, succeeded in results:
        if succeeded:
            discovered[name] = tools
            successful_names.add(name)

    registered_count = 0

    async with REGISTRATION_LOCK:
        for server_name, tools in discovered.items():
            new_routes: dict[str, dict[str, str]] = {}

            for upstream_tool in tools:
                gateway_name = (
                    f"{safe_tool_name(server_name)}__"
                    f"{safe_tool_name(upstream_tool.name)}"
                )
                route = {
                    "server": server_name,
                    "tool": upstream_tool.name,
                }
                existing = TOOL_ROUTES.get(gateway_name)

                if existing and existing != route:
                    logger.error(
                        "Tool name collision for '%s'",
                        gateway_name,
                    )
                    continue

                if existing == route:
                    new_routes[gateway_name] = route
                    registered_count += 1
                    continue

                try:
                    proxy = make_proxy(
                        server_name,
                        upstream_tool.name,
                        upstream_tool.inputSchema,
                    )
                    gateway_mcp.add_tool(
                        proxy,
                        name=gateway_name,
                        description=(
                            upstream_tool.description
                            or f"Proxy for {upstream_tool.name}"
                        ),
                    )
                    new_routes[gateway_name] = route
                    registered_count += 1
                except Exception:
                    logger.exception(
                        "Could not register tool '%s'",
                        gateway_name,
                    )

            # Remove stale tools only after successful discovery.
            old_names = [
                name
                for name, route in TOOL_ROUTES.items()
                if route["server"] == server_name
                and name not in new_routes
            ]
            for old_name in old_names:
                gateway_mcp.remove_tool(old_name)
                TOOL_ROUTES.pop(old_name, None)

            TOOL_ROUTES.update(new_routes)

        # Remove tools belonging to disabled or deleted upstreams.
        inactive_names = [
            name
            for name, route in TOOL_ROUTES.items()
            if route["server"] not in UPSTREAM_CONFIG
            or not UPSTREAM_ENABLED.get(route["server"], False)
        ]
        for name in inactive_names:
            gateway_mcp.remove_tool(name)
            TOOL_ROUTES.pop(name, None)

    return {
        "upstreams_discovered": len(successful_names),
        "tools_registered": registered_count,
    }


async def upstream_monitor_loop():
    """Periodically refresh upstream health and tool catalogues."""
    while True:
        await asyncio.sleep(UPSTREAM_HEALTH_CHECK_INTERVAL_SECONDS)
        try:
            await refresh_upstream_tools()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background upstream refresh failed")


# --------------------------------------------------
# Upstream models and validation
# --------------------------------------------------

class UpstreamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    url: str = Field(min_length=1, max_length=500)
    enabled: bool = True
    auth_mode: str = Field(
        default="none",
        pattern="^(none|bearer|custom_header)$",
    )
    credential: str | None = Field(default=None, max_length=4096)
    custom_header_name: str | None = Field(default=None, max_length=100)
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class UpstreamUpdate(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    auth_mode: str | None = Field(
        default=None,
        pattern="^(none|bearer|custom_header)$",
    )
    credential: str | None = Field(default=None, max_length=4096)
    custom_header_name: str | None = Field(default=None, max_length=100)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)


def validate_upstream_url(url: str) -> str:
    try:
        return validate_secure_upstream_url(url)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

# --------------------------------------------------
# Persistent upstream configuration
# --------------------------------------------------

def load_saved_upstreams():
    """Load persisted upstreams and decrypt credentials for runtime use."""
    saved = load_upstreams()

    if not saved:
        for name, url in DEFAULT_UPSTREAMS.items():
            save_upstream(
                name=name,
                url=url,
                enabled=True,
                auth_mode="none",
            )

    saved = load_upstreams(include_secrets=True)

    UPSTREAMS.clear()
    UPSTREAM_ENABLED.clear()
    UPSTREAM_CONFIG.clear()
    UPSTREAM_FAILURES.clear()

    for upstream in saved:
        name = upstream["name"]
        UPSTREAMS[name] = upstream["url"]
        UPSTREAM_ENABLED[name] = upstream["enabled"]
        UPSTREAM_CONFIG[name] = dict(upstream)
        UPSTREAM_FAILURES[name] = upstream.get(
            "consecutive_failures", 0
        )

    logger.info("Loaded %d upstream configurations", len(saved))


# --------------------------------------------------
# Application lifecycle
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    load_saved_upstreams()

    # Gateway startup must not fail merely because an upstream is down.
    try:
        await refresh_upstream_tools()
    except Exception:
        logger.exception("Initial upstream discovery failed")

    monitor_task = asyncio.create_task(
        upstream_monitor_loop(),
        name="upstream-monitor",
    )
    try:
        async with gateway_mcp.session_manager.run():
            yield
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


# --------------------------------------------------
# FastAPI application
# --------------------------------------------------

app = FastAPI(
    title="MCP Gateway",
    description="Dynamic gateway for multiple MCP servers",
    version="0.8.0",
    lifespan=lifespan,
)

app.add_middleware(GatewayAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------
# User and API-key administration models
# --------------------------------------------------

class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    email: str | None = Field(default=None, max_length=254)
    role: str = Field(
        default="member",
        pattern="^(admin|member)$",
    )


class KeyCreate(BaseModel):
    label: str = Field(
        default="default",
        min_length=1,
        max_length=80,
    )


# --------------------------------------------------
# Admin user and API-key endpoints
# --------------------------------------------------

@app.get("/admin/users")
async def admin_list_users():
    return {"users": list_users()}

@app.post("/admin/users", status_code=201)
async def admin_create_user(payload: UserCreate):
    try:
        user_id = create_user(
            payload.username,
            payload.role,
            payload.email,
        )
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(
                status_code=409,
                detail="Username or email already exists",
            ) from exc

        if isinstance(exc, ValueError):
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc

        raise

    return {
        "user_id": user_id,
        "username": payload.username,
        "role": payload.role,
    }


@app.post("/admin/users/{user_id}/keys", status_code=201)
async def admin_issue_key(user_id: str, payload: KeyCreate):
    try:
        result = issue_api_key(user_id, payload.label)
        try:
            write_audit(
                user_id=str(current_user_id.get() or "unknown"),
                username=str(current_username.get() or "unknown"),
                server_name="gateway",
                tool_name="api_key.issue",
                duration_ms=0,
                outcome="success",
                error_message=None,
            )
        except Exception:
            logger.exception("Failed to audit API key issuance")
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.get("/admin/keys")
async def admin_list_keys():
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                k.id AS key_id,
                k.user_id,
                u.username,
                k.label,
                k.created_at,
                k.revoked_at,
                k.revoked
            FROM api_keys AS k
            JOIN users AS u ON u.id = k.user_id
            ORDER BY k.id DESC
            LIMIT 500
            """
        ).fetchall()

    return {"keys": [dict(row) for row in rows]}


@app.post("/admin/keys/{key_id}/revoke")
async def admin_revoke_key(key_id: int):
    if not revoke_api_key(key_id):
        raise HTTPException(
            status_code=404,
            detail="Active API key not found",
        )
    try:
        write_audit(
            user_id=str(current_user_id.get() or "unknown"),
            username=str(current_username.get() or "unknown"),
            server_name="gateway",
            tool_name="api_key.revoke",
            duration_ms=0,
            outcome="success",
            error_message=None,
        )
    except Exception:
        logger.exception("Failed to audit API key revocation")
    return {
        "message": "API key revoked",
        "key_id": key_id,
    }


# --------------------------------------------------
# Member self-service API-key endpoints
# --------------------------------------------------

@app.get("/api/tools")
async def list_my_tools():
    """List tools from enabled upstreams for any authenticated API user."""
    registered = await gateway_mcp.list_tools()

    tools = []
    for tool in registered:
        route = TOOL_ROUTES.get(tool.name)
        if route is None:
            continue

        server_name = route["server"]
        config = UPSTREAM_CONFIG.get(server_name)

        # Do not expose tools from disabled, deleted, or unknown upstreams.
        if not config or not config.get("enabled", False):
            continue

        tools.append({
            "gateway_name": tool.name,
            "upstream_server": server_name,
            "upstream_tool": route["tool"],
            "description": tool.description,
            "input_schema": tool.inputSchema,
        })

    tools.sort(key=lambda item: (
        item["upstream_server"],
        item["upstream_tool"],
    ))
    return {"tools": tools}


@app.get("/api/me")
async def get_current_member():
    """Return the identity associated with the supplied API key."""
    return {
        "user_id": current_user_id.get(),
        "username": current_username.get(),
        "role": current_user_role.get(),
    }


@app.get("/api/me/keys")
async def list_my_api_keys():
    """List only API keys belonging to the authenticated user."""
    user_id = current_user_id.get()

    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                id AS key_id,
                label,
                created_at,
                revoked_at,
                revoked
            FROM api_keys
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,),
        ).fetchall()

    return {"keys": [dict(row) for row in rows]}


@app.post("/api/me/keys", status_code=201)
async def create_my_api_key(payload: KeyCreate):
    """Create an API key for the authenticated user."""
    user_id = current_user_id.get()

    try:
        return issue_api_key(user_id, payload.label)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc


@app.post("/api/me/keys/{key_id}/revoke")
async def revoke_my_api_key(key_id: int):
    """Revoke a key only if it belongs to the authenticated user."""
    user_id = current_user_id.get()

    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM api_keys
            WHERE id = ? AND user_id = ? AND revoked = 0
            """,
            (key_id, user_id),
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Active API key not found",
        )

    if not revoke_api_key(key_id):
        raise HTTPException(
            status_code=409,
            detail="API key could not be revoked",
        )

    return {
        "message": "API key revoked",
        "key_id": key_id,
    }


# --------------------------------------------------
# Tool permission endpoints (admin)
# --------------------------------------------------

class PermissionRule(BaseModel):
    subject_type: str = Field(pattern="^(role|user)$")
    subject: str = Field(min_length=1, max_length=80)
    server_name: str = Field(min_length=1, max_length=50)
    tool_name: str = Field(default="*", min_length=1, max_length=100)
    effect: str = Field(pattern="^(allow|deny)$")


@app.get("/admin/permissions")
async def admin_list_permissions():
    return {"permissions": list_tool_permissions()}


@app.put("/admin/permissions")
async def admin_set_permission(payload: PermissionRule):
    if (
        payload.server_name != "*"
        and payload.server_name not in UPSTREAM_CONFIG
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown upstream server '{payload.server_name}'",
        )

    try:
        return set_tool_permission(
            payload.subject_type,
            payload.subject,
            payload.server_name,
            payload.tool_name,
            payload.effect,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/admin/permissions/{permission_id}")
async def admin_delete_permission(permission_id: int):
    if not delete_tool_permission(permission_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"message": "Rule removed", "id": permission_id}


@app.get("/admin/permissions/effective/{user_id}")
async def admin_effective_permissions(user_id: str):
    """Show exactly which gateway tools a user can and cannot use."""
    user = get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    allowed, denied = [], []
    for gateway_name, route in sorted(TOOL_ROUTES.items()):
        ok = is_tool_allowed(
            user["id"], user["role"], route["server"], route["tool"]
        )
        (allowed if ok else denied).append(gateway_name)

    return {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "allowed": allowed,
        "denied": denied,
    }


# --------------------------------------------------
# Audit endpoints
# --------------------------------------------------

@app.get("/admin/audit")
async def admin_audit(
    limit: int = 100,
    offset: int = 0,
    user_id: str | None = None,
    username: str | None = None,
    server_name: str | None = None,
    tool_name: str | None = None,
    outcome: str | None = None,
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    filters = []
    values = []

    for column, value in (
        ("user_id", user_id),
        ("username", username),
        ("server_name", server_name),
        ("tool_name", tool_name),
        ("outcome", outcome),
    ):
        if value is not None and value.strip():
            filters.append(f"{column} = ?")
            values.append(value.strip())

    where_clause = (
        " WHERE " + " AND ".join(filters)
        if filters else ""
    )

    with connect_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM audit_logs{where_clause}",
            values,
        ).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT
                id,
                user_id,
                username,
                server_name,
                tool_name,
                started_at,
                timestamp,
                duration_ms,
                outcome,
                error_message
            FROM audit_logs
            {where_clause}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            [*values, limit, offset],
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "audit": [dict(row) for row in rows],
    }


# --------------------------------------------------
# Health and tool endpoints
# --------------------------------------------------

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "mcp-gateway",
        "registered_tools": len(TOOL_ROUTES),
    }


@app.get("/readyz")
async def readyz():
    try:
        with connect_db() as conn:
            conn.execute("SELECT 1").fetchone()

        return {"status": "ready"}

    except Exception:
        logger.exception("Readiness check failed")
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/admin/refresh-tools")
async def refresh_tools_endpoint():
    return await refresh_upstream_tools()


@app.get("/admin/tools")
async def list_registered_tools():
    return {
        "tools": [
            {
                "gateway_name": name,
                "upstream_server": route["server"],
                "upstream_tool": route["tool"],
            }
            for name, route in sorted(TOOL_ROUTES.items())
        ]
    }


# --------------------------------------------------
# Upstream management endpoints
# --------------------------------------------------

@app.get("/admin/upstreams")
async def list_upstreams():
    # load_upstreams() intentionally omits credentials and ciphertext.
    return {"upstreams": load_upstreams()}


@app.post("/admin/upstreams", status_code=201)
async def add_upstream(payload: UpstreamCreate):
    name = safe_tool_name(payload.name)

    if len(name) < 2:
        raise HTTPException(
            status_code=400,
            detail="Upstream name must contain at least two valid characters",
        )

    if name in UPSTREAM_CONFIG:
        raise HTTPException(
            status_code=409,
            detail=f"Upstream '{name}' already exists",
        )

    url = validate_upstream_url(payload.url)

    try:
        save_upstream(
            name=name,
            url=url,
            enabled=payload.enabled,
            auth_mode=payload.auth_mode,
            credential=payload.credential,
            custom_header_name=payload.custom_header_name,
            timeout_seconds=payload.timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        write_audit(
            user_id=str(current_user_id.get() or "unknown"),
            username=str(current_username.get() or "unknown"),
            server_name=name,
            tool_name="upstream.create",
            duration_ms=0,
            outcome="success",
            error_message=None,
        )
    except Exception:
        logger.exception("Failed to audit upstream creation")

    load_saved_upstreams()
    result = await refresh_upstream_tools()
    saved = next(
        item for item in load_upstreams() if item["name"] == name
    )

    return {
        "message": "Upstream added",
        **saved,
        **result,
    }


@app.patch("/admin/upstreams/{name}")
async def update_upstream(name: str, payload: UpstreamUpdate):
    current = UPSTREAM_CONFIG.get(name)
    if current is None:
        raise HTTPException(status_code=404, detail="Upstream not found")

    old_enabled = current["enabled"]

    new_url = (
        validate_upstream_url(payload.url)
        if payload.url is not None
        else current["url"]
    )
    new_enabled = (
        payload.enabled
        if payload.enabled is not None
        else current["enabled"]
    )
    new_auth_mode = (
        payload.auth_mode
        if payload.auth_mode is not None
        else current.get("auth_mode", "none")
    )
    new_header_name = (
        payload.custom_header_name
        if payload.custom_header_name is not None
        else current.get("custom_header_name")
    )
    new_timeout = (
        payload.timeout_seconds
        if payload.timeout_seconds is not None
        else current.get("timeout_seconds", 20)
    )

    try:
        save_upstream(
            name=name,
            url=new_url,
            enabled=new_enabled,
            auth_mode=new_auth_mode,
            credential=payload.credential,
            custom_header_name=new_header_name,
            timeout_seconds=new_timeout,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if old_enabled != new_enabled:
        action = "upstream.enable" if new_enabled else "upstream.disable"
        try:
            write_audit(
                user_id=str(current_user_id.get() or "unknown"),
                username=str(current_username.get() or "unknown"),
                server_name=name,
                tool_name=action,
                duration_ms=0,
                outcome="success",
                error_message=None,
            )
        except Exception:
            logger.exception("Failed to audit upstream state change")

    load_saved_upstreams()

    if not new_enabled:
        update_upstream_status(name, "disabled")

    result = await refresh_upstream_tools()
    updated = next(
        item for item in load_upstreams() if item["name"] == name
    )

    return {
        "message": "Upstream updated",
        **updated,
        **result,
    }


@app.delete("/admin/upstreams/{name}")
async def delete_upstream(name: str):
    if name not in UPSTREAM_CONFIG:
        raise HTTPException(status_code=404, detail="Upstream not found")

    UPSTREAMS.pop(name, None)
    UPSTREAM_ENABLED.pop(name, None)
    UPSTREAM_CONFIG.pop(name, None)
    UPSTREAM_FAILURES.pop(name, None)
    delete_upstream_record(name)

    try:
        write_audit(
            user_id=str(current_user_id.get() or "unknown"),
            username=str(current_username.get() or "unknown"),
            server_name=name,
            tool_name="upstream.delete",
            duration_ms=0,
            outcome="success",
            error_message=None,
        )
    except Exception:
        logger.exception("Failed to audit upstream deletion")

    async with REGISTRATION_LOCK:
        old_names = [
            tool_name
            for tool_name, route in TOOL_ROUTES.items()
            if route["server"] == name
        ]
        for tool_name in old_names:
            gateway_mcp.remove_tool(tool_name)
            TOOL_ROUTES.pop(tool_name, None)

    return {
        "message": "Upstream removed",
        "name": name,
        "removed_tools": len(old_names),
    }


@app.get("/admin/upstream-status")
async def upstream_status():
    return {
        "upstreams": [
            {
                "name": item["name"],
                "enabled": item["enabled"],
                "status": item["connection_status"],
                "consecutive_failures": item["consecutive_failures"],
                "last_checked_at": item["last_checked_at"],
                "last_success_at": item["last_success_at"],
                "last_discovery_at": item["last_discovery_at"],
                "last_error": item["last_error"],
                "circuit_open_until": item["circuit_open_until"],
            }
            for item in load_upstreams()
        ]
    }



class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None


@app.post("/api/chat")
async def chat_with_agent(payload: ChatRequest, request: Request):
    """Chat with an LLM that can invoke tools through this MCP gateway."""
    import json
    import os
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    
    api_key = request.headers.get("x-api-key")

    llm_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL")
    gateway_url = os.getenv(
        "GATEWAY_MCP_URL",
        "http://127.0.0.1:8081/mcp/mcp",
    )

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing gateway API key.",
        )

    if not llm_key:
        raise HTTPException(
            status_code=503,
            detail="Chat model is not configured. Set LLM_API_KEY.",
        )

    if not base_url:
        raise HTTPException(
            status_code=503,
            detail="LLM_BASE_URL is not configured.",
        )

    if not model:
        raise HTTPException(
            status_code=503,
            detail="LLM_MODEL is not configured.",
        )

    if not payload.message.strip():
        raise HTTPException(
            status_code=422,
            detail="Message cannot be empty.",
        )

    base_url = base_url.rstrip("/")

    messages = [{
        "role": "system",
        "content": (
            "You are a helpful team assistant. Use the available MCP tools "
            "when needed to answer questions or perform requested actions. "
            "Never claim an action succeeded unless a tool result confirms it. "
            "Ask for clarification when required arguments are missing."
        )
    }]

    # Accept only ordinary conversation history, not client-supplied tool results.
    for item in (payload.history or [])[-12:]:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": payload.message})
    executed_calls = []

    mcp_http_client = httpx.AsyncClient(
        headers={"x-api-key": api_key},
        timeout=60.0,
    )
    try:
        async with streamable_http_client(
            gateway_url,
            http_client=mcp_http_client,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()

                llm_tools = []
                for tool in listed.tools:
                    llm_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or tool.name,
                            "parameters": tool.inputSchema or {
                                "type": "object", "properties": {}
                            },
                        },
                    })

                async with httpx.AsyncClient(timeout=60.0) as client:
                    for _ in range(6):
                        body = {
                            "model": model,
                            "messages": messages,
                        }
                        if llm_tools:
                            body["tools"] = llm_tools
                            body["tool_choice"] = "auto"

                        response = await client.post(
                            f"{base_url}/chat/completions",
                            headers={"Authorization": f"Bearer {llm_key}"},
                            json=body,
                        )
                        response.raise_for_status()
                        choice = response.json()["choices"][0]
                        assistant_message = choice["message"]
                        calls = assistant_message.get("tool_calls") or []

                        if not calls:
                            return {
                                "answer": assistant_message.get("content") or "",
                                "tool_calls": executed_calls,
                                "model": model,
                            }

                        messages.append(assistant_message)

                        for call in calls:
                            function = call["function"]
                            tool_name = function["name"]

                            try:
                                arguments = json.loads(
                                    function.get("arguments") or "{}"
                                )
                                result = await session.call_tool(
                                    tool_name, arguments=arguments
                                )

                                content = []
                                for item in (result.content or []):
                                    text_value = getattr(item, "text", None)
                                    if text_value is not None:
                                        content.append(text_value)
                                    elif hasattr(item, "model_dump"):
                                        content.append(
                                            item.model_dump(mode="json")
                                        )
                                    else:
                                        content.append(str(item))

                                tool_output = json.dumps({
                                    "isError": bool(result.isError),
                                    "content": content,
                                }, ensure_ascii=False)

                                executed_calls.append({
                                    "tool": tool_name,
                                    "arguments": arguments,
                                    "result": tool_output[:4000],
                                    "isError": bool(result.isError),
                                })
                            except Exception as exc:
                                tool_output = json.dumps({
                                    "error": str(exc)[:1000]
                                })
                                executed_calls.append({
                                    "tool": tool_name,
                                    "error": str(exc)[:1000],
                                })

                            messages.append({
                                "role": "tool",
                                "tool_call_id": call["id"],
                                "content": tool_output,
                            })

                return {
                    "answer": "The tool-call limit was reached. Please refine your request.",
                    "tool_calls": executed_calls,
                    "model": model,
                }

    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Chat provider returned HTTP {exc.response.status_code}."
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="The chat provider timed out."
        ) from exc
    except Exception as exc:
        logger.exception("Chat agent failed with an unexpected exception")
        raise HTTPException(
            status_code=502,
            detail=f"Chat agent failed: {type(exc).__name__}. Check gateway logs."
        ) from exc
    finally:
        await mcp_http_client.aclose()



# MCP endpoint: http://127.0.0.1:8081/mcp/mcp
app.mount(
    "/mcp",
    gateway_mcp.streamable_http_app(),
)
