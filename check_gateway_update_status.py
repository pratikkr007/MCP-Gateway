
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main():
    url = "http://127.0.0.1:8081/mcp/mcp"

    # Dedicated test order created in WooCommerce.
    test_order_id = 23

    async with streamablehttp_client(url) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "woocommerce__update_order_status",
                {
                    "order_id": test_order_id,
                    "status": "on-hold",
                },
            )

            print("Tool call completed.")
            print("MCP error:", result.isError)

            for item in result.content:
                if hasattr(item, "text"):
                    print(item.text)


if __name__ == "__main__":
    asyncio.run(main())
