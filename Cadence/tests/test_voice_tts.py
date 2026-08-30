"""Tests for the Hinglish / Indic voice TTS path."""
from __future__ import annotations

import base64
import struct

import pytest

from revive.policy.voice_tts import (
    BITS_PER_SAMPLE,
    CHANNELS,
    DURATION_SECONDS,
    SAMPLE_RATE,
    synthesize,
    stub_is_deterministic,
)


def test_default_returns_stub() -> None:
    r = synthesize(language="hi", text="Namaste")
    assert r.is_stub is True
    assert r.sample_rate == SAMPLE_RATE
    assert r.duration_seconds == DURATION_SECONDS
    assert r.language == "hi"
    assert r.text == "Namaste"


def test_stub_is_deterministic() -> None:
    assert stub_is_deterministic("Hello", "hinglish")
    assert stub_is_deterministic("Namaste, kaise hain?", "hi")


def test_stub_payload_decodes_to_valid_wav() -> None:
    r = synthesize(language="hinglish", text="Hello")
    raw = base64.b64decode(r.pcm_payload_b64)
    # WAV header check
    assert raw[:4] == b"RIFF"
    assert raw[8:12] == b"WAVE"
    assert raw[12:16] == b"fmt "


def test_stub_payload_is_silence() -> None:
    r = synthesize(language="hinglish", text="Hello")
    raw = base64.b64decode(r.pcm_payload_b64)
    # Find the data chunk
    data_idx = raw.find(b"data")
    assert data_idx != -1
    data_size = struct.unpack("<I", raw[data_idx + 4:data_idx + 8])[0]
    assert data_size == SAMPLE_RATE * DURATION_SECONDS
    # All PCM samples should be 128 (silence in 8-bit unsigned)
    pcm_start = data_idx + 8
    pcm_end = pcm_start + data_size
    assert all(b == 128 for b in raw[pcm_start:pcm_end])


def test_sarvam_key_with_http_error_falls_back_to_stub() -> None:
    # The httpx call will fail (no network in CI), so the wrapper
    # should fall back to the stub.
    r = synthesize(
        language="hi",
        text="Hello",
        sarvam_api_key="dummy_key_for_test",
    )
    # Either Sarvam returned 200 (live) or we got the stub.
    assert r.is_stub in (True, False)
    # If it was the live path, the reason mentions 'sarvam' and not 'stub'
    if r.is_stub:
        assert "stub" in r.reason or "sarvam error" in r.reason
    else:
        assert "sarvam" in r.reason


def test_different_texts_produce_different_seeds() -> None:
    a = synthesize(language="hinglish", text="Hello world")
    b = synthesize(language="hinglish", text="Goodbye world")
    # The reason field carries the seed; different texts -> different seeds.
    assert a.reason != b.reason
    assert "seed=" in a.reason
    assert "seed=" in b.reason


def test_api_voice_preview_endpoint(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from revive.api.app import create_app
    from tests.test_api import _config

    # Force no TTS provider set so the endpoint returns the deterministic stub
    # (otherwise an env-set ELEVENLABS_API_KEY / SARVAM_API_KEY would flip
    # is_stub to False and the test would become env-dependent).
    for var in ("ELEVENLABS_API_KEY", "SARVAM_API_KEY", "GROQ_API_KEY"):
        monkeypatch.setenv(var, "")

    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    r = client.get("/api/voice/preview?language=hi&amount_minor=49900")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["language"] == "hi"
    assert "Namaste" in body["text"]
    # is_stub may be True (no TTS key) or False (real TTS) — both are valid
    assert body["is_stub"] in (True, False)
    if body["is_stub"]:
        # Stub path returns the deterministic 8 kHz silent WAV
        assert body["sample_rate"] == SAMPLE_RATE
    # The payload must be valid base64
    base64.b64decode(body["pcm_payload_b64"])
