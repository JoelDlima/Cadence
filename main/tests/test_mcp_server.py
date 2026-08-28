"""MCP server slice tests: tool discovery + in-process invocation.

Uses the official `mcp` Python SDK v1.x in-process client/server pair
(`mcp.shared.memory.create_connected_server_and_client_session`) so each
test runs the full MCP protocol lifecycle without subprocess management.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from revive.events import AGG_JOURNEY, E_CLASSIFICATION_COMPLETED, E_JOURNEY_OPENED
from revive.mcp_server import mcp
from revive.store.db import Database
from revive.store.event_store import EventStore
from revive.store.journey_repo import JourneyRepo

pytestmark = [pytest.mark.unit]

T0 = "2026-08-22T10:00:00+00:00"
T1 = "2026-08-22T10:00:01+00:00"


def _result_payload(result: Any) -> Any:
    """Parse the SDK's CallToolResult into a Python value.

    FastMCP v1 returns two parallel encodings:
      - result.content[0].text for any text-yielding tool
      - result.structuredContent when the function has a typed (non-str) return
    For tools that return an empty list, content is empty and only
    structuredContent is populated. This helper handles both.
    """
    if getattr(result, "structuredContent", None) is not None:
        return result.structuredContent.get("result", result.structuredContent)
    if result.content and hasattr(result.content[0], "text"):
        return json.loads(result.content[0].text)
    return result.content


@pytest.fixture
def seeded_db(tmp_path) -> Database:
    """One journey, two events. Used as the live DB the MCP server reads from."""
    db = Database(tmp_path / "mcp.db")
    journeys = JourneyRepo(db)
    store = EventStore(db)
    journeys.create(
        journey_id="j_abc123",
        subscription_id="sub_1",
        customer_id="cust_1",
        amount_minor=49900,
        currency="INR",
        failure_code="insufficient_funds",
        opened_at=T0,
    )
    store.append(
        event_type=E_JOURNEY_OPENED,
        aggregate_type=AGG_JOURNEY,
        aggregate_id="sub_1",
        payload={"journey_id": "j_abc123"},
        occurred_at=T0,
        recorded_at=T0,
        event_id="e_open",
    )
    store.append(
        event_type=E_CLASSIFICATION_COMPLETED,
        aggregate_type=AGG_JOURNEY,
        aggregate_id="sub_1",
        payload={"root_cause": "NO_FUNDS", "source": "table"},
        occurred_at=T1,
        recorded_at=T1,
        event_id="e_class",
    )
    return db


@pytest.mark.asyncio
async def test_list_tools_advertises_eight_read_only_tools(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.list_tools()
    names = sorted(t.name for t in result.tools)
    assert names == sorted([
        "revive_list_journeys",
        "revive_get_timeline",
        "revive_get_metrics",
        "revive_list_dead_letters",
        "revive_get_status",
        "revive_get_attention",
        "revive_audit_verify",
        "revive_get_guardian_stats",
    ])


@pytest.mark.asyncio
async def test_revive_list_journeys_returns_seeded_journey(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_list_journeys", {"limit": 10})
    parsed = _result_payload(result)
    assert isinstance(parsed, list)
    assert any(j["journey_id"] == "j_abc123" for j in parsed)
    assert any(j["state"] == "OPENED" for j in parsed)


@pytest.mark.asyncio
async def test_revive_get_metrics_reports_recovered_inr_and_states(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_get_metrics", {})
    metrics = _result_payload(result)
    assert metrics["recovered_inr_major"] == 0.0
    assert metrics["journeys_by_state"] == {"OPENED": 1}
    assert set(metrics) >= {"recovered_inr_major", "journeys_by_state", "llm_requests_today", "violations"}


@pytest.mark.asyncio
async def test_revive_get_timeline_returns_events_in_seq_order(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_get_timeline", {"journey_key": "j_abc123"})
    parsed = _result_payload(result)
    assert parsed["journey_id"] == "j_abc123"
    seqs = [e["seq"] for e in parsed["events"]]
    assert seqs == sorted(seqs)
    assert {e["type"] for e in parsed["events"]} == {E_JOURNEY_OPENED, E_CLASSIFICATION_COMPLETED}


@pytest.mark.asyncio
async def test_revive_get_timeline_404_like_for_unknown_key(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_get_timeline", {"journey_key": "sub_nope"})
    parsed = _result_payload(result)
    assert "error" in parsed


@pytest.mark.asyncio
async def test_revive_get_status_reports_demo_mode_with_no_keys(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_get_status", {})
    parsed = _result_payload(result)
    assert parsed["mode"] == "DEMO"
    assert parsed["razorpay_keys_present"] is False
    assert parsed["llm_keys_present"] is False
    assert parsed["supabase_keys_present"] is False
    assert parsed["db_event_count"] == 2  # the two seeded events


@pytest.mark.asyncio
async def test_revive_audit_verify_reports_chain_ok_on_fresh_db(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_audit_verify", {})
    parsed = _result_payload(result)
    assert parsed["chain_ok"] is True
    assert parsed["event_count"] == 2
    assert parsed["first_bad_seq"] is None
    assert len(parsed["last_hash"]) == 64


@pytest.mark.asyncio
async def test_revive_audit_verify_detects_tamper(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    # Tamper with the first event's payload
    seeded_db.conn.execute(
        "UPDATE events SET payload = ? WHERE event_id = ?",
        ('{"event":"subscription.cancelled"}', "e_open"),
    )
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_audit_verify", {})
    parsed = _result_payload(result)
    assert parsed["chain_ok"] is False
    assert parsed["first_bad_seq"] == 1


@pytest.mark.asyncio
async def test_revive_get_guardian_stats_aggregates_veto_reasons(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db
    from datetime import datetime, UTC

    _set_db(seeded_db)
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    counter = 0
    for reason, n in [("touch_cap_reached", 3), ("kill_switch", 1)]:
        for _ in range(n):
            counter += 1
            seeded_db.conn.execute(
                "INSERT INTO events (event_id, occurred_at, recorded_at, type, "
                "aggregate_type, aggregate_id, payload, prev_hash, hash) "
                "VALUES (?, ?, ?, 'intervention.vetoed', 'journey', ?, "
                "?, '0' * 64, 'a' * 64)",
                (f"mcp_vet_{counter}", now, now, f"sub_mcp_{counter}",
                 f'{{"reason":"{reason}"}}'),
            )
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_get_guardian_stats", {})
    parsed = _result_payload(result)
    assert parsed["total_vetoes"] == 4
    assert parsed["by_reason"]["touch_cap_reached"] == 3
    assert parsed["by_reason"]["kill_switch"] == 1


@pytest.mark.asyncio
async def test_revive_list_dead_letters_returns_empty_when_queue_healthy(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_list_dead_letters", {"limit": 10})
    parsed = _result_payload(result)
    assert parsed == []


@pytest.mark.asyncio
async def test_revive_get_attention_returns_empty_for_fresh_db(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_get_attention", {"limit": 8})
    parsed = _result_payload(result)
    assert parsed == []


@pytest.mark.asyncio
async def test_revive_get_attention_returns_empty_for_fresh_db(seeded_db):
    from mcp.shared.memory import create_connected_server_and_client_session
    from revive.mcp_server import _set_db

    _set_db(seeded_db)
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        result = await client.call_tool("revive_get_attention", {"limit": 8})
    parsed = _result_payload(result)
    assert parsed == []
