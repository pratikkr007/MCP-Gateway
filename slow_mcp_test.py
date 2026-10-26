import asyncio
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Slow Test Server")

@mcp.tool()
async def slow_tool() -> str:
    """Test gateway timeout handling; intentionally waits 30 seconds."""
    await asyncio.sleep(30)
    return "Finished after 30 seconds"

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
