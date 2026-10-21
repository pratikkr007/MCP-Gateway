
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP


UPSTREAMS = {
    "woocommerce": "http://127.0.0.1:8000/mcp",
}

gateway_mcp = FastMCP(
    "team-mcp-gateway",
    host="0.0.0.0",
    port=8081,
    stateless_http=True,
)


async def call_upstream(tool_name: str, arguments: dict):
    """Call a tool on the configured WooCommerce MCP server."""
    url = UPSTREAMS["woocommerce"]

    async with streamablehttp_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

            return [
                item.model_dump(mode="json")
                for item in result.content
            ]


@gateway_mcp.tool()
async def list_products(search: str = "") -> list:
    """List WooCommerce products, optionally filtered by search text."""
    return await call_upstream(
        "list_products",
        {"search": search},
    )


@gateway_mcp.tool()
async def create_product(name: str, regular_price: str, description: str = "") -> list:
    """Create a published WooCommerce product."""
    return await call_upstream(
        "create_product",
        {
            "name": name,
            "regular_price": regular_price,
            "description": description,
        },
    )


@gateway_mcp.tool()
async def list_orders(after: str = "", before: str = "") -> list:
    """List WooCommerce orders with optional ISO-8601 date filters."""
    return await call_upstream(
        "list_orders",
        {
            "after": after,
            "before": before,
        },
    )


@gateway_mcp.tool()
async def get_order(order_id: int) -> list:
    """Retrieve details for one WooCommerce order."""
    return await call_upstream(
        "get_order",
        {"order_id": order_id},
    )


@gateway_mcp.tool()
async def update_order_status(order_id: int, status: str) -> list:
    """Update a WooCommerce order's status."""
    return await call_upstream(
        "update_order_status",
        {
            "order_id": order_id,
            "status": status,
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with gateway_mcp.session_manager.run():
        yield


app = FastAPI(
    title="MCP Gateway",
    description="Central gateway for multiple MCP servers",
    version="0.2.0",
    lifespan=lifespan,
)

app.mount("/mcp", gateway_mcp.streamable_http_app())


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "mcp-gateway",
    }
