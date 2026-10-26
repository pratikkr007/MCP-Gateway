
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "notes-mcp",
    host="0.0.0.0",
    port=8002,
    stateless_http=True,
)

NOTES = {
    1: {
        "title": "Gateway setup",
        "content": "The team MCP gateway routes requests to registered upstream servers.",
    },
    2: {
        "title": "WooCommerce demo",
        "content": "Use the storefront to place a test order with cash on delivery.",
    },
}


@mcp.tool()
def search_notes(query: str = "") -> list[dict]:
    """Search notes by title or content."""
    query_lower = query.lower()
    return [
        {"id": note_id, **note}
        for note_id, note in NOTES.items()
        if query_lower in note["title"].lower()
        or query_lower in note["content"].lower()
    ]


@mcp.tool()
def create_note(title: str, content: str) -> dict:
    """Create a note and return its ID."""
    note_id = max(NOTES.keys(), default=0) + 1
    NOTES[note_id] = {"title": title, "content": content}
    return {"id": note_id, **NOTES[note_id]}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
