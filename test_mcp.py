
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    url = "http://127.0.0.1:8000/mcp"

    async with streamablehttp_client(url) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.list_tools()

            print("Available MCP tools:")
            for tool in result.tools:
                print(f"- {tool.name}")

            expected = {
                "list_products",
                "create_product",
                "list_orders",
                "get_order",
                "update_order_status",
            }

            actual = {tool.name for tool in result.tools}
            missing = expected - actual

            if missing:
                raise RuntimeError(
                    f"Missing MCP tools: {sorted(missing)}"
                )

            print("\nTesting list_products...")
            response = await session.call_tool(
                "list_products",
                {"per_page": 5},
            )

            if response.isError:
                raise RuntimeError(
                    f"list_products failed: {response.content}"
                )

            print("list_products succeeded.")
            print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
