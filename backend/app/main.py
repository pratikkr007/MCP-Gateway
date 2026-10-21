
import asyncio
import inspect
import logging
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.fastmcp import FastMCP


# --------------------------------------------------
# Configuration
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-gateway")

UPSTREAMS = {
    "woocommerce": "http://127.0.0.1:8000/mcp",
}

UPSTREAM_TIMEOUT_SECONDS = 15

TOOL_ROUTES: dict[str, dict[str, str]] = {}
REGISTRATION_LOCK = asyncio.Lock()


# --------------------------------------------------
# Gateway MCP server
# --------------------------------------------------

gateway_mcp = FastMCP(
    "team-mcp-gateway",
    host="0.0.0.0",
    port=8081,
    stateless_http=True,
)


# --------------------------------------------------
# MCP upstream helpers
# --------------------------------------------------

async def discover_upstream_tools(server_name: str, url: str):
    """Discover tools exposed by an upstream MCP server."""
    async with streamablehttp_client(url) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(
                session.initialize(),
                timeout=UPSTREAM_TIMEOUT_SECONDS,
            )

            result = await asyncio.wait_for(
                session.list_tools(),
                timeout=UPSTREAM_TIMEOUT_SECONDS,
            )

            return result.tools


async def call_upstream(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
):
    """Call a tool on its original upstream MCP server."""
    url = UPSTREAMS[server_name]

    async with streamablehttp_client(url) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await asyncio.wait_for(
                session.initialize(),
                timeout=UPSTREAM_TIMEOUT_SECONDS,
            )

            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments),
                timeout=UPSTREAM_TIMEOUT_SECONDS,
            )

            return {
                "isError": result.isError,
                "content": [
                    item.model_dump(mode="json")
                    for item in result.content
                ],
            }


# --------------------------------------------------
# Dynamic tool registration
# --------------------------------------------------

def safe_tool_name(name: str) -> str:
    """Convert a name into a predictable identifier."""
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    return normalized.strip("_") or "unnamed_tool"



def make_proxy(server_name: str, upstream_tool_name: str, input_schema: dict):
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
            # Preserve a meaningful default for optional arguments.
            if "default" in details:
                default = details["default"]
            elif schema_type == "integer":
                default = 10 if name == "per_page" else None
            else:
                default = None

            # Avoid passing None to typed upstream parameters.
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
        # Remove unspecified optional arguments so the upstream server
        # can apply its own Python defaults.
        arguments = {
            key: value
            for key, value in arguments.items()
            if value is not None
        }

        return await call_upstream(
            server_name,
            upstream_tool_name,
            arguments,
        )

    proxy.__name__ = f"{server_name}_{upstream_tool_name}"
    proxy.__doc__ = f"Proxy for {server_name}.{upstream_tool_name}"
    proxy.__signature__ = inspect.Signature(parameters)

    return proxy



async def refresh_upstream_tools() -> dict[str, int]:
    """Discover and register tools without blocking other upstreams."""
    discovered: dict[str, list[Any]] = {}

    for server_name, url in UPSTREAMS.items():
        try:
            tools = await discover_upstream_tools(server_name, url)
            discovered[server_name] = tools

            logger.info(
                "Discovered %d tools from upstream '%s'",
                len(tools),
                server_name,
            )
        except Exception:
            logger.exception(
                "Could not discover tools from upstream '%s'",
                server_name,
            )

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

                # Reuse existing registrations during refresh.
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

            # Remove obsolete tools only after successful discovery
            # of this particular upstream.
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

    return {
        "upstreams_discovered": len(discovered),
        "tools_registered": registered_count,
    }


# --------------------------------------------------
# Application lifecycle
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await refresh_upstream_tools()

    async with gateway_mcp.session_manager.run():
        yield


# --------------------------------------------------
# FastAPI application
# --------------------------------------------------

app = FastAPI(
    title="MCP Gateway",
    description="Dynamic gateway for multiple MCP servers",
    version="0.4.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "mcp-gateway",
        "registered_tools": len(TOOL_ROUTES),
    }


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


# Keep the existing working MCP endpoint.
app.mount("/mcp", gateway_mcp.streamable_http_app())
