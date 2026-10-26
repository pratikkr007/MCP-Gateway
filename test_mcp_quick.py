import asyncio
import os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SERVERS = {
    "WooCommerce": "http://127.0.0.1:8000/mcp",
    "Notes": "http://127.0.0.1:8002/mcp",
    "Inventory": "http://127.0.0.1:8003/mcp",
    "Gateway": "http://127.0.0.1:8081/mcp/mcp",
}

async def test_server(name, url, headers=None):
    print(f"\n--- {name} ---")
    try:
        async with streamablehttp_client(
            url, headers=headers or {}, timeout=10
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                names = [tool.name for tool in result.tools]
                print("PASS: Connected")
                print(f"Tools ({len(names)}): {names}")

                if name == "Notes" and "search_notes" in names:
                    result = await session.call_tool(
                        "search_notes", {"query": "gateway"}
                    )
                    print("search_notes result:", result.content)

                if name == "Inventory" and "check_stock" in names:
                    result = await session.call_tool(
                        "check_stock", {"sku": "DEMO-001"}
                    )
                    print("check_stock result:", result.content)

                if name == "Gateway":
                    for required in (
                        "notes__search_notes",
                        "inventory__check_stock",
                        "inventory__list_inventory",
                    ):
                        print(
                            f"{required}:",
                            "PASS" if required in names else "MISSING"
                        )
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")

async def main():
    for name in ("WooCommerce", "Notes", "Inventory"):
        await test_server(name, SERVERS[name])

    key = os.getenv("GATEWAY_TEST_API_KEY", "")
    if not key:
        print(
            "\nSKIP: Gateway test requires GATEWAY_TEST_API_KEY. "
            "Set it to a valid, non-revoked member API key."
        )
    else:
        await test_server(
            "Gateway",
            SERVERS["Gateway"],
            {"x-api-key": key},
        )

asyncio.run(main())
