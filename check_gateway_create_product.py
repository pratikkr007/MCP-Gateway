
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    url = "http://127.0.0.1:8081/mcp/mcp"

    async with streamablehttp_client(url) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "woocommerce__create_product",
                {
                    "name": "Gateway API Test Product Oct 2026",
                    "regular_price": "29.99",
                    "description": "Temporary test product created through the MCP Gateway.",
                },
            )

            print("Tool call completed.")
            print("MCP error:", result.isError)

            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text)


if __name__ == "__main__":
    asyncio.run(main())
