
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

            # Display available MCP tools
            print("\nAvailable MCP tools:")
            tools = await session.list_tools()

            for tool in tools.tools:
                print(f"- {tool.name}")

            # Test read-only tools
            tests = [
                ("list_products", {}),
                ("list_orders", {"per_page": 5}),
                ("get_order", {"order_id": 15}),
            ]

            for tool_name, arguments in tests:
                print("\n" + "=" * 50)
                print(f"Testing {tool_name}...")
                print("=" * 50)

                try:
                    result = await session.call_tool(
                        tool_name,
                        arguments,
                    )

                    for item in result.content:
                        if hasattr(item, "text"):
                            print(item.text)

                    if result.isError:
                        print(f"{tool_name} returned an error.")
                    else:
                        print(f"{tool_name} completed successfully.")

                except Exception as error:
                    print(f"Error testing {tool_name}: {error}")

            # Test create_product
            print("\n" + "=" * 50)
            print("Testing create_product...")
            print("=" * 50)

            try:
                result = await session.call_tool(
                    "create_product",
                    {
                        "name": "MCP Test Product",
                        "regular_price": "99.00",
                        "description": "Product created by MCP client test",
                    },
                )

                for item in result.content:
                    if hasattr(item, "text"):
                        print(item.text)

                if result.isError:
                    print("create_product returned an error.")
                else:
                    print("create_product completed successfully.")

            except Exception as error:
                print(f"Error testing create_product: {error}")

            # Test update_order_status
            print("\n" + "=" * 50)
            print("Testing update_order_status...")
            print("=" * 50)

            try:
                result = await session.call_tool(
                    "update_order_status",
                    {
                        "order_id": 15,
                        "status": "completed",
                    },
                )

                for item in result.content:
                    if hasattr(item, "text"):
                        print(item.text)

                if result.isError:
                    print("update_order_status returned an error.")
                else:
                    print("update_order_status completed successfully.")

            except Exception as error:
                print(f"Error testing update_order_status: {error}")


if __name__ == "__main__":
    asyncio.run(main())
