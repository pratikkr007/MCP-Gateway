import asyncio
import base64
import hashlib
import hmac
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp import FastMCP


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

STORE_URL = os.getenv("WOOCOMMERCE_URL", "").rstrip("/")
CONSUMER_KEY = os.getenv("WOOCOMMERCE_CONSUMER_KEY", "")
CONSUMER_SECRET = os.getenv("WOOCOMMERCE_CONSUMER_SECRET", "")
REQUEST_TIMEOUT = float(os.getenv("WOOCOMMERCE_TIMEOUT", "20"))
STORE_TIMEZONE = os.getenv("STORE_TIMEZONE", "UTC")

ALLOWED_ORDER_STATUSES = {
    "pending",
    "processing",
    "on-hold",
    "completed",
    "cancelled",
    "refunded",
    "failed",
}


# ---------------------------------------------------------
# MCP server
# ---------------------------------------------------------

mcp = FastMCP(
    "woocommerce-mcp",
    host="0.0.0.0",
    port=8000,
    stateless_http=True,
)


# ---------------------------------------------------------
# Configuration and validation helpers
# ---------------------------------------------------------

def validate_configuration() -> None:
    """Validate required configuration without exposing credentials."""
    if not STORE_URL:
        raise RuntimeError("WOOCOMMERCE_URL is not configured.")

    parsed = urlsplit(STORE_URL)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(
            "WOOCOMMERCE_URL must be a valid HTTP(S) URL."
        )

    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(
            "WOOCOMMERCE_URL must not contain credentials, "
            "query parameters, or fragments."
        )

    if not CONSUMER_KEY or not CONSUMER_SECRET:
        raise RuntimeError(
            "WooCommerce API credentials are not configured."
        )

    if REQUEST_TIMEOUT <= 0:
        raise RuntimeError("WOOCOMMERCE_TIMEOUT must be greater than zero.")

    try:
        ZoneInfo(STORE_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise RuntimeError(
            "STORE_TIMEZONE must be a valid IANA timezone, "
            "such as Asia/Kolkata."
        ) from exc


def api_base_url() -> str:
    """Build the WooCommerce REST API base URL."""
    validate_configuration()
    return f"{STORE_URL}/wp-json/wc/v3"


def _pct(value: str) -> str:
    """OAuth percent encoding."""
    return quote(str(value), safe="~-._")


def _positive_price(value: str) -> str:
    """Validate and normalize a non-negative product price."""
    try:
        price = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            "regular_price must be a valid decimal number."
        ) from None

    if not price.is_finite() or price < 0:
        raise ValueError(
            "regular_price must be a finite, non-negative number."
        )

    return format(price, "f")


def _parse_datetime(value: str, field_name: str) -> datetime:
    """Parse an ISO-8601 datetime that includes a timezone."""
    try:
        parsed = datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        )
    except ValueError:
        raise ValueError(
            f"{field_name} must be a valid ISO-8601 datetime."
        ) from None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            f"{field_name} must include a timezone offset."
        )

    return parsed


# ---------------------------------------------------------
# WooCommerce REST API / OAuth 1.0a
# ---------------------------------------------------------

def _oauth_params(method: str, url: str, params: dict) -> dict:
    """Sign a WooCommerce REST request using HMAC-SHA256."""
    if not CONSUMER_KEY or not CONSUMER_SECRET:
        raise RuntimeError(
            "WooCommerce API credentials are not configured."
        )

    oauth = {
        "oauth_consumer_key": CONSUMER_KEY,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA256",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }

    all_params = [
        (str(key), str(value))
        for key, value in {**params, **oauth}.items()
        if value is not None
    ]

    encoded_params = sorted(
        (_pct(key), _pct(value))
        for key, value in all_params
    )
    normalized = "&".join(
        f"{key}={value}" for key, value in encoded_params
    )

    parsed = urlsplit(url)
    base_url = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", "")
    )

    base_string = "&".join(
        [
            method.upper(),
            _pct(base_url),
            _pct(normalized),
        ]
    )

    signing_key = f"{_pct(CONSUMER_SECRET)}&"
    digest = hmac.new(
        signing_key.encode(),
        base_string.encode(),
        hashlib.sha256,
    ).digest()

    oauth["oauth_signature"] = base64.b64encode(digest).decode()
    return oauth


async def wc_request(
    method: str,
    endpoint: str,
    *,
    params: dict | None = None,
    payload: dict | None = None,
):
    """Call WooCommerce and return parsed JSON."""
    url = f"{api_base_url()}/{endpoint.lstrip('/')}"
    query = {
        key: value
        for key, value in (params or {}).items()
        if value is not None
    }
    query.update(_oauth_params(method, url, query))

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT
        ) as client:
            response = await client.request(
                method,
                url,
                params=query,
                json=payload,
            )
    except httpx.TimeoutException:
        raise RuntimeError(
            f"WooCommerce API request timed out after "
            f"{REQUEST_TIMEOUT:g} seconds."
        ) from None
    except httpx.RequestError as exc:
        # Do not include the request URL, query parameters, or credentials.
        raise RuntimeError(
            f"Could not connect to WooCommerce "
            f"({type(exc).__name__})."
        ) from None

    if not response.is_success:
        message = (
            f"WooCommerce API returned HTTP {response.status_code}."
        )

        try:
            body = response.json()
            if isinstance(body, dict):
                api_message = body.get("message")
                api_code = body.get("code")

                if isinstance(api_code, str):
                    message += f" Error code: {api_code}."
                if isinstance(api_message, str):
                    message += f" {api_message[:300]}"
        except ValueError:
            message += " The response was not valid JSON."

        raise RuntimeError(message)

    try:
        return response.json()
    except ValueError:
        raise RuntimeError(
            "WooCommerce API returned invalid JSON."
        ) from None


# ---------------------------------------------------------
# Product formatting
# ---------------------------------------------------------

def _format_product(product: dict) -> dict:
    return {
        "id": product.get("id"),
        "name": product.get("name"),
        "sku": product.get("sku"),
        "price": product.get("price"),
        "regular_price": product.get("regular_price"),
        "status": product.get("status"),
        "stock_status": product.get("stock_status"),
        "permalink": product.get("permalink"),
    }


# ---------------------------------------------------------
# MCP tool 1: list_products
# ---------------------------------------------------------

@mcp.tool()
async def list_products(
    search: str = "",
    per_page: int = 20,
) -> list[dict]:
    """List products, optionally filtered by search text."""
    if not isinstance(search, str) or len(search) > 200:
        raise ValueError("search must be a string of at most 200 characters.")

    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100.")

    result = await wc_request(
        "GET",
        "products",
        params={
            "search": search.strip() or None,
            "per_page": per_page,
        },
    )

    if not isinstance(result, list):
        raise RuntimeError("Unexpected response while listing products.")

    return [_format_product(item) for item in result]


# ---------------------------------------------------------
# MCP tool 2: create_product
# ---------------------------------------------------------

@mcp.tool()
async def create_product(
    name: str,
    regular_price: str,
    description: str = "",
) -> dict:
    """Create a published WooCommerce product."""
    if not isinstance(name, str):
        raise ValueError("Product name must be a string.")

    name = name.strip()

    if not name or len(name) > 200:
        raise ValueError("Product name must contain 1â€“200 characters.")

    if not isinstance(description, str) or len(description) > 10000:
        raise ValueError(
            "description must be a string of at most 10000 characters."
        )

    price = _positive_price(regular_price)

    result = await wc_request(
        "POST",
        "products",
        payload={
            "name": name,
            "regular_price": price,
            "description": description,
            "status": "publish",
        },
    )

    return _format_product(result)


# ---------------------------------------------------------
# MCP tool 3: list_orders
# ---------------------------------------------------------

@mcp.tool()
async def list_orders(
    after: str = "",
    before: str = "",
    per_page: int = 20,
    today: bool = False,
) -> list[dict]:
    """
    List orders by date.

    Set today=True to filter from midnight to midnight in STORE_TIMEZONE.
    Otherwise, optionally provide timezone-aware ISO-8601 after/before values.
    """
    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be between 1 and 100.")

    after = after.strip()
    before = before.strip()

    if today and (after or before):
        raise ValueError(
            "Use today=True or provide after/before, not both."
        )

    query = {
        "per_page": per_page,
        "orderby": "date",
        "order": "desc",
    }

    if today:
        try:
            store_tz = ZoneInfo(STORE_TIMEZONE)
        except (ZoneInfoNotFoundError, ValueError):
            raise RuntimeError(
                "STORE_TIMEZONE is not a valid timezone."
            ) from None

        now_local = datetime.now(store_tz)
        start_local = now_local.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_local = start_local + timedelta(days=1)

        # Convert local calendar-day boundaries to UTC instants.
        # This also handles daylight-saving transitions correctly.
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)

        query["after"] = start_utc.isoformat()
        query["before"] = end_utc.isoformat()

    else:
        if after:
            query["after"] = _parse_datetime(after, "after").isoformat()

        if before:
            query["before"] = _parse_datetime(before, "before").isoformat()

    result = await wc_request(
        "GET",
        "orders",
        params=query,
    )

    if not isinstance(result, list):
        raise RuntimeError("Unexpected response while listing orders.")

    return [
        {
            "id": order.get("id"),
            "number": order.get("number"),
            "status": order.get("status"),
            "date_created": order.get("date_created"),
            "total": order.get("total"),
            "currency": order.get("currency"),
            "payment_method_title": order.get("payment_method_title"),
            "line_items": [
                {
                    "product_id": item.get("product_id"),
                    "name": item.get("name"),
                    "quantity": item.get("quantity"),
                    "total": item.get("total"),
                }
                for item in order.get("line_items", [])
            ],
        }
        for order in result
    ]


# ---------------------------------------------------------
# MCP tool 4: get_order
# ---------------------------------------------------------

@mcp.tool()
async def get_order(order_id: int) -> dict:
    """Retrieve details for a single WooCommerce order."""
    if order_id <= 0:
        raise ValueError("order_id must be a positive integer.")

    order = await wc_request("GET", f"orders/{order_id}")

    return {
        "id": order.get("id"),
        "number": order.get("number"),
        "status": order.get("status"),
        "date_created": order.get("date_created"),
        "total": order.get("total"),
        "currency": order.get("currency"),
        "payment_method_title": order.get("payment_method_title"),
        "billing": {
            "first_name": order.get("billing", {}).get("first_name"),
            "last_name": order.get("billing", {}).get("last_name"),
        },
        "line_items": [
            {
                "product_id": item.get("product_id"),
                "name": item.get("name"),
                "quantity": item.get("quantity"),
                "total": item.get("total"),
            }
            for item in order.get("line_items", [])
        ],
    }


# ---------------------------------------------------------
# MCP tool 5: update_order_status
# ---------------------------------------------------------

@mcp.tool()
async def update_order_status(
    order_id: int,
    status: str,
) -> dict:
    """Update an order to an allowed WooCommerce status."""
    if order_id <= 0:
        raise ValueError("order_id must be a positive integer.")

    if not isinstance(status, str):
        raise ValueError("status must be a string.")

    status = status.strip().lower()

    if status not in ALLOWED_ORDER_STATUSES:
        raise ValueError(
            "Unsupported status. Allowed values: "
            f"{', '.join(sorted(ALLOWED_ORDER_STATUSES))}."
        )

    order = await wc_request(
        "PUT",
        f"orders/{order_id}",
        payload={"status": status},
    )

    return {
        "id": order.get("id"),
        "number": order.get("number"),
        "status": order.get("status"),
    }


# ---------------------------------------------------------
# FastAPI application and health checks
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="WooCommerce MCP Server",
    description="Custom MCP tools backed by the WooCommerce REST API",
    version="1.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Backward-compatible health endpoint."""
    return {
        "status": "healthy",
        "service": "woocommerce-mcp",
    }


@app.get("/healthz")
async def healthz():
    """Liveness check: confirms the process is responding."""
    return {
        "status": "alive",
        "service": "woocommerce-mcp",
    }


@app.get("/readyz")
async def readyz():
    """
    Readiness check: confirms configuration and WooCommerce API access.
    Returns HTTP 503 when the store cannot be reached or authenticated.
    """
    try:
        await wc_request(
            "GET",
            "products",
            params={"per_page": 1},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "reason": str(exc)[:300],
            },
        ) from None

    return {
        "status": "ready",
        "service": "woocommerce-mcp",
    }


# Mount the MCP Streamable HTTP endpoint.
app.mount("/", mcp.streamable_http_app())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
