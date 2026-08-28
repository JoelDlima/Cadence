"""Governed LLM client: provider chain with timeouts, daily spend caps, circuit breaker."""

from __future__ import annotations

import json
import zoneinfo
from datetime import datetime, timedelta

import httpx

from revive.clock import Clock
from revive.config import LLMConfig
from revive.store.db import Database

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_FAILURE_THRESHOLD = 3
_CIRCUIT_OPEN_SECONDS = 300

_OPENAI_COMPATIBLE_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}


class BudgetExhausted(RuntimeError):
    """A provider's daily request cap is already fully spent."""


class LLMClient:
    def __init__(
        self,
        cfg: LLMConfig,
        db: Database,
        clock: Clock,
        transport: httpx.Client | httpx.BaseTransport | None = None,
    ) -> None:
        self._cfg = cfg
        self._db = db
        self._clock = clock
        if isinstance(transport, httpx.Client):
            self._client: httpx.Client = transport
        else:
            self._client = httpx.Client(transport=transport, timeout=cfg.timeout_seconds)
        self._failures: dict[str, int] = {}
        self._circuit_until: dict[str, datetime] = {}

    def close(self) -> None:
        self._client.close()

    def _today_ist(self) -> str:
        return self._clock.now().astimezone(_IST).strftime("%Y-%m-%d")

    def _check_budget(self, provider: str) -> None:
        row = self._db.conn.execute(
            "SELECT requests FROM llm_spend WHERE day = ? AND provider = ?",
            (self._today_ist(), provider),
        ).fetchone()
        if row is not None and row["requests"] >= self._cfg.daily_request_cap:
            raise BudgetExhausted(
                f"daily request cap {self._cfg.daily_request_cap} reached for {provider}"
            )

    def _record_spend(self, provider: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self._db.conn.execute(
            """
            INSERT INTO llm_spend(day, provider, requests, tokens_in, tokens_out)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(day, provider) DO UPDATE SET
                requests = requests + 1,
                tokens_in = tokens_in + excluded.tokens_in,
                tokens_out = tokens_out + excluded.tokens_out
            """,
            (self._today_ist(), provider, tokens_in, tokens_out),
        )

    def _circuit_open(self, provider: str) -> bool:
        until = self._circuit_until.get(provider)
        return until is not None and self._clock.now() < until

    def _register_failure(self, provider: str) -> None:
        self._failures[provider] = self._failures.get(provider, 0) + 1
        if self._failures[provider] >= _FAILURE_THRESHOLD:
            opened_for = timedelta(seconds=_CIRCUIT_OPEN_SECONDS)
            self._circuit_until[provider] = self._clock.now() + opened_for

    def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema_hint: dict | None = None,
        max_tokens: int = 500,
    ) -> tuple[dict | None, str]:
        budget_error: BudgetExhausted | None = None
        hard_failure = False
        for provider in self._cfg.provider_order:
            if not self._cfg.key_for(provider) or self._circuit_open(provider):
                continue
            try:
                self._check_budget(provider)
            except BudgetExhausted as exc:
                budget_error = exc
                continue
            try:
                text = self._call_provider(provider, system, prompt, schema_hint, max_tokens)
                obj = self._parse_json(text)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                hard_failure = True
                self._register_failure(provider)
                continue
            self._failures[provider] = 0
            self._record_spend(provider)
            return obj, provider
        if budget_error is not None and not hard_failure:
            raise budget_error
        return None, ""

    def _call_provider(
        self, provider: str, system: str, prompt: str, schema_hint: dict | None, max_tokens: int
    ) -> str:
        if provider == "gemini":
            return self._call_gemini(
                prompt, system, schema_hint, self._cfg.model_gemini, max_tokens
            )
        if provider == "ollama":
            return self._call_openai_compatible(
                provider,
                prompt,
                system,
                self._cfg.model_ollama,
                max_tokens,
                url=f"{self._cfg.ollama_base_url}/chat/completions",
                with_auth_header=False,
            )
        if provider not in _OPENAI_COMPATIBLE_URLS:
            raise ValueError(f"unsupported provider: {provider}")
        return self._call_openai_compatible(
            provider, prompt, system, getattr(self._cfg, f"model_{provider}"), max_tokens
        )

    def _call_gemini(
        self, prompt: str, system: str, schema_hint: dict | None, model: str, max_tokens: int
    ) -> str:
        generation_config: dict[str, object] = {
            "responseMimeType": "application/json",
            "maxOutputTokens": max_tokens,
        }
        if schema_hint:
            generation_config["responseSchema"] = schema_hint
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        resp = self._client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": self._cfg.gemini_api_key},
            json=body,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload["candidates"][0]["content"]["parts"][0]["text"]

    def _call_openai_compatible(
        self,
        provider: str,
        prompt: str,
        system: str,
        model: str,
        max_tokens: int,
        *,
        url: str | None = None,
        with_auth_header: bool = True,
    ) -> str:
        headers: dict[str, str] = {}
        if with_auth_header:
            headers["Authorization"] = f"Bearer {self._cfg.key_for(provider)}"
        resp = self._client.post(
            url if url is not None else _OPENAI_COMPATIBLE_URLS[provider],
            headers=headers,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_json(text: str) -> dict:
        stripped = text.strip()
        if stripped.startswith("```"):
            first_newline = stripped.find("\n")
            if first_newline != -1:
                stripped = stripped[first_newline + 1 :]
            closing = stripped.rfind("```")
            if closing != -1:
                stripped = stripped[:closing]
        obj = json.loads(stripped)
        if not isinstance(obj, dict):
            raise TypeError("expected a top-level JSON object")
        return obj
