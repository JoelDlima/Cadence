"""Run the Cadence MCP server: 8 read-only tools over stdio for any AI agent client.

Built on the official `mcp` Python SDK v1.x. Same SDK used by the Razorpay
MCP server, Stripe MCP server, and the Anthropic MCP quickstart.

Config snippet for Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json`
on macOS, `%APPDATA%\\Claude\\claude_desktop_config.json` on Windows):

{
  "mcpServers": {
    "cadence": {
      "command": "python",
      "args": ["scripts/run_mcp.py"]
    }
  }
}

Config snippet for Cursor (`~/.cursor/mcp.json`):

{
  "mcpServers": {
    "cadence": {
      "command": "python",
      "args": ["scripts/run_mcp.py"]
    }
  }
}

Run from Cadence/:  python scripts/run_mcp.py   (JSON-RPC 2.0 frames on stdio)
Protocol frames go to stdout; logs go to stderr (handled by the SDK).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from revive.logging_setup import setup_logging
from revive.mcp_server import serve
from revive.store.db import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Cadence MCP (stdio) server.")
    parser.add_argument(
        "--db",
        default="data/revive.db",
        help="path to the Cadence SQLite database (default: data/revive.db)",
    )
    args = parser.parse_args()

    setup_logging("INFO")
    db = Database(args.db)
    try:
        serve(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()

