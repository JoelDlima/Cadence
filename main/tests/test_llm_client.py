"""Unit tests for the governed LLM client: chain, budget cap, circuit breaker."""

from __future__ import annotations

import json

import httpx
import pytest

from revive.agents.llm_client import BudgetExhausted, LLMClient
from revive.clock import FakeClock
from revive.config import LLMConfig
from revive.store.db import Database


def _config() -> LLMConfig:
    return LLMConfig(
        provider_order=["groq"],
        gemini_api_key="",
        groq_api_key="gkey",
        openrouter_api_key="",
        model_gemini="gemini-test",
        model_groq="llama-test",
        model_openrouter="or-test",
        daily_request_cap=2,
    )


class _Recorder:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        content = self.contents[min(self.calls - 1, len(self.contents) - 1)]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": content}}]},
        )


def _make_client(db: Database, clock: FakeClock, recorder: _Recorder) -> LLMClient:
    transport = httpx.MockTransport(recorder.handler)
    return LLMClient(cfg=_config(), db=db, clock=clock, transport=transport)


def test_happy_path_returns_parsed_json_and_records_spend(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    recorder = _Recorder(['{"intervention":"RETRY_PAYDAY"}'])
    client = _make_client(tmp_db, fake_clock, recorder)

    obj, provider = client.complete_json(system="sys", prompt="usr")

    assert obj == {"intervention": "RETRY_PAYDAY"}
    assert provider == "groq"
    assert recorder.calls == 1
    row = tmp_db.conn.execute(
        "SELECT requests FROM llm_spend WHERE day = '2026-08-22' AND provider = 'groq'"
    ).fetchone()
    assert row is not None and row["requests"] == 1


def test_budget_cap_blocks_third_call_before_http(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    recorder = _Recorder(['{"n":1}', '{"n":2}', '{"n":3}'])
    client = _make_client(tmp_db, fake_clock, recorder)

    client.complete_json(system="sys", prompt="usr")
    client.complete_json(system="sys", prompt="usr")
    with pytest.raises(BudgetExhausted):
        client.complete_json(system="sys", prompt="usr")

    assert recorder.calls == 2


def test_malformed_json_returns_none_and_records_failure(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    recorder = _Recorder(["definitely not json {"])
    client = _make_client(tmp_db, fake_clock, recorder)

    result = client.complete_json(system="sys", prompt="usr")

    assert result == (None, "")
    assert client._failures == {"groq": 1}
    assert tmp_db.conn.execute("SELECT requests FROM llm_spend").fetchall() == []


def test_circuit_opens_after_three_consecutive_failures(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    recorder = _Recorder(["bad {"] * 5)
    client = _make_client(tmp_db, fake_clock, recorder)

    for _ in range(3):
        assert client.complete_json(system="sys", prompt="usr") == (None, "")
    assert recorder.calls == 3

    assert client.complete_json(system="sys", prompt="usr") == (None, "")
    assert recorder.calls == 3


def test_code_fences_stripped_before_parsing(tmp_db: Database, fake_clock: FakeClock) -> None:
    fenced = '```json\n{"intervention":"RETRY_PAYDAY"}\n```'
    recorder = _Recorder([fenced])
    client = _make_client(tmp_db, fake_clock, recorder)

    obj, provider = client.complete_json(system="sys", prompt="usr")

    assert obj == {"intervention": "RETRY_PAYDAY"}
    assert provider == "groq"


def test_ollama_happy_path_posts_without_auth_header(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        assert request.url.host == "localhost"
        assert request.url.port == 11434
        assert str(request.url).endswith("/chat/completions")
        assert not any(name.lower() == "authorization" for name in request.headers)
        assert json.loads(request.content)["model"] == "llama3.1:8b"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": '{"ok":true}'}}]},
        )

    cfg = LLMConfig(
        provider_order=["ollama"],
        gemini_api_key="",
        groq_api_key="",
        openrouter_api_key="",
        model_gemini="",
        model_groq="",
        model_openrouter="",
        daily_request_cap=10,
        ollama_base_url="http://localhost:11434/v1",
        model_ollama="llama3.1:8b",
    )
    client = LLMClient(
        cfg=cfg, db=tmp_db, clock=fake_clock, transport=httpx.MockTransport(handler)
    )

    obj, provider = client.complete_json(system="sys", prompt="usr")

    assert obj == {"ok": True}
    assert provider == "ollama"
    row = tmp_db.conn.execute(
        "SELECT requests FROM llm_spend WHERE provider = 'ollama'"
    ).fetchone()
    assert row is not None and row["requests"] == 1


def test_chain_skips_keyless_groq_and_lands_on_ollama(
    tmp_db: Database, fake_clock: FakeClock
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": '{"ok":true}'}}]},
        )

    cfg = LLMConfig(
        provider_order=["groq", "ollama"],
        gemini_api_key="",
        groq_api_key="",
        openrouter_api_key="",
        model_gemini="",
        model_groq="llama-3.3-70b-versatile",
        model_openrouter="",
        daily_request_cap=10,
        ollama_base_url="http://localhost:11434/v1",
        model_ollama="llama3.1:8b",
    )
    client = LLMClient(
        cfg=cfg, db=tmp_db, clock=fake_clock, transport=httpx.MockTransport(handler)
    )

    obj, provider = client.complete_json(system="sys", prompt="usr")

    assert obj == {"ok": True}
    assert provider == "ollama"
    assert len(calls) == 1
