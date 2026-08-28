# Cadence MCP Server — Integration Guide

The Cadence MCP (Model Context Protocol) server exposes a **read-only** view
of recovery operations to any AI agent client. It is built on the official
[`mcp` Python SDK](https://pypi.org/project/mcp/) (v1.x, the same SDK used by
the Razorpay MCP server, Stripe MCP server, and the Anthropic MCP quickstart).

## What it does

When an AI agent (Claude Desktop, Cursor, VS Code, OpenAI Agents SDK, …)
connects to the Cadence MCP server, it gains access to **eight read-only tools**
that answer questions about recovery state:

| Tool | What it returns |
|---|---|
| `revive_list_journeys` | Paginated list of recovery journeys (open first, then closed) |
| `revive_get_timeline` | Hash-chained event timeline for one journey (by journey_id or subscription_id) |
| `revive_get_metrics` | Control-room totals: recovered INR, journeys by state, LLM requests today, Guardian veto count |
| `revive_list_dead_letters` | Queue tasks that exhausted retries |
| `revive_get_status` | DEMO/LIVE mode + which keys are present (Razorpay, Resend, Supabase, LLM) |
| `revive_get_attention` | Journeys flagged for human review, high value, or paused by bank-outage shield |
| `revive_audit_verify` | Hash-chain integrity check (returns `chain_ok` and `first_bad_seq` on tamper) |
| `revive_get_guardian_stats` | Guardian veto counts grouped by reason |

**There is no write tool. There never will be.** Cadence is the place where
money decisions are made; the MCP server is the read-only window that lets
agents inspect those decisions. Writing must go through the FastAPI control
plane, which is itself a deliberate bottleneck.

## Run it

From `Cadence/`:

```bash
pip install -e ".[dev]"
python scripts/run_mcp.py            # stdio transport
python scripts/run_mcp.py --db /path/to/cadence.db  # custom DB path
```

The server speaks MCP over stdio. Logs go to stderr; the protocol frames
go to stdout. The SDK handles protocol negotiation against the current MCP
specification (2026-07-28).

## Configure your AI client

### Claude Desktop (Anthropic)

`%APPDATA%\Claude\claude_desktop_config.json` (Windows) or
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "cadence": {
      "command": "python",
      "args": ["C:/path/to/Revive/Cadence/scripts/run_mcp.py"]
    }
  }
}
```

Restart Claude Desktop. A 🔌 icon appears at the bottom of the chat box;
the eight Cadence tools show up under the tools panel.

### Cursor

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "cadence": {
      "command": "python",
      "args": ["/path/to/Revive/Cadence/scripts/run_mcp.py"]
    }
  }
}
```

### VS Code (Copilot agent mode)

`.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "cadence": {
      "type": "stdio",
      "command": "python",
      "args": ["${workspaceFolder}/Cadence/scripts/run_mcp.py"]
    }
  }
}
```

### OpenAI Agents SDK (Python)

```python
from agents import Agent
from mcp import MCPServerStdio

cadence = MCPServerStdio(
    command="python",
    args=["/path/to/Revive/Cadence/scripts/run_mcp.py"],
)
agent = Agent(
    name="Recovery Inspector",
    mcp_servers=[cadence],
    instructions="Use the Cadence read-only tools to answer questions about the recovery loop.",
)
```

## Example queries

Once connected, the agent can answer:

- *"How many journeys recovered today, and what's the average contacts per recovery?"*
- *"Show me the last 10 events for journey `j_abc123`."*
- *"Has anyone in the last 24 hours hit the touch cap or quiet hours?"*
- *"Verify the audit chain — is anything tampered?"*
- *"What's the current DEMO/LIVE mode and which integrations are live?"*

## Security posture

| Concern | Cadence's posture |
|---|---|
| Can the MCP server move money? | **No.** No write tool exists. |
| Can the agent escalate privileges? | **No.** The agent has the same read access as any other MCP client. |
| Can the agent read PII? | **Only what the events table contains.** Customer IDs, amounts, and root causes. No card numbers, VPAs, or API secrets are stored. |
| Can logs leak to a third party? | **No.** Logs go to stderr only; stdout is reserved for the protocol. |
| Can the agent crash the engine? | **No.** The MCP server is a read-only reader. It cannot enqueue tasks, mutate journeys, or flip the kill switch. |

For money-adjacent systems, the convention in 2026 is: **MCP = read-only,
in-app API = the write surface.** Cadence follows that convention. Any
write tool that becomes useful in the future must (a) be explicitly added
behind a confirmation step, (b) be tagged with `readOnlyHint: false` in its
schema, and (c) be audited separately.

## Why the official SDK (and not raw JSON-RPC)?

The first version of Cadence's MCP server was hand-rolled JSON-RPC over
stdio. It worked, but the official `mcp` Python SDK v1.x is now stable
(2026-07-28 spec) and is the convention used by the Razorpay and Stripe
MCP servers. The SDK gives us:

- **Type-hint-driven tool schemas.** No more hand-written JSON Schema.
- **Protocol negotiation.** The SDK tracks the current MCP spec.
- **In-process testing.** `mcp.shared.memory.create_connected_server_and_client_session`
  lets unit tests drive the full protocol lifecycle without subprocess management.
- **Logging safety.** The SDK enforces "no stdout writes" — the #1 stdio
  server footgun.

See `tests/test_mcp_server.py` for the in-process test pattern.

