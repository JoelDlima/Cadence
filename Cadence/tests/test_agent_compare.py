"""Tests for the PHASE 3 /api/eval/agent-compare endpoint."""
from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from revive.api.app import create_app
from revive.config import (
    AppConfig,
    ChannelConfig,
    CloudConfig,
    LLMConfig,
    PolicyConfig,
    RazorpayConfig,
)
from tests.test_api import _config


pytestmark = [pytest.mark.integration]


def test_agent_compare_endpoint_returns_both_arms(tmp_path: Path) -> None:
    """PHASE 3: the agent-compare endpoint runs the experiment live and
    returns both arms' deltas. n is capped at 200 to keep the live endpoint
    under 5s; we use 20 to keep the test fast."""
    cfg = _config(tmp_path / "compare.db")
    client = TestClient(create_app(cfg=cfg))
    r = client.get("/api/eval/agent-compare?n=20&seed=42")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["n"] == 20
    assert d["seed"] == 42
    assert d["cohort"] == "indian"
    assert d["source"] == "live_experiment"
    # Both arms should have recovered at least 0 INR
    assert d["naive_recovered_inr"] >= 0
    assert d["revive_recovered_inr"] >= 0
    # Uplift is well-defined (could be 0 if recovery rates match, otherwise >0)
    assert "uplift_pct" in d
    assert "recovered_delta" in d


def test_agent_compare_endpoint_caps_n_at_200(tmp_path: Path) -> None:
    cfg = _config(tmp_path / "compare2.db")
    client = TestClient(create_app(cfg=cfg))
    r = client.get("/api/eval/agent-compare?n=999&seed=42")
    assert r.status_code == 200
    assert r.json()["n"] == 200  # capped at 200


def test_agent_compare_endpoint_floor_n_at_10(tmp_path: Path) -> None:
    cfg = _config(tmp_path / "compare3.db")
    client = TestClient(create_app(cfg=cfg))
    r = client.get("/api/eval/agent-compare?n=1&seed=42")
    assert r.status_code == 200
    assert r.json()["n"] == 10  # floored at 10


def test_agent_compare_default_n_is_100(tmp_path: Path) -> None:
    cfg = _config(tmp_path / "compare4.db")
    client = TestClient(create_app(cfg=cfg))
    r = client.get("/api/eval/agent-compare?seed=42")
    assert r.status_code == 200
    assert r.json()["n"] == 100
