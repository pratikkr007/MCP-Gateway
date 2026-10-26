
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "inventory-mcp",
    host="0.0.0.0",
    port=8003,
    stateless_http=True,
)

INVENTORY = {
    "DEMO-001": {"name": "Demo Product", "stock": 25},
    "CABLE-002": {"name": "USB-C Cable", "stock": 100},
}


@mcp.tool()
def check_stock(sku: str) -> dict:
    """Check available inventory for a SKU."""
    item = INVENTORY.get(sku.upper())
    if item is None:
        return {"found": False, "sku": sku}
    return {"found": True, "sku": sku.upper(), **item}


@mcp.tool()
def list_inventory() -> list[dict]:
    """List all inventory items."""
    return [
        {"sku": sku, **item}
        for sku, item in INVENTORY.items()
    ]


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
