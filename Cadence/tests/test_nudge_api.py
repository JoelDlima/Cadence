"""API tests for the Indic-language recovery nudge preview endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cadence.api.app import create_app
from tests.test_api import _config

pytestmark = [pytest.mark.integration]


def test_nudge_preview_default_language_is_hinglish(tmp_path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    r = client.get("/api/nudge/preview?amount_minor=49900&link_url=https://pay.test/x")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["language"] == "hinglish"
    assert "Aapka" in body["text"]
    assert "https://pay.test/x" in body["text"]
    assert "supported_languages" in body
    assert sorted(body["supported_languages"]) == sorted(
        {"hi", "ta", "te", "bn", "mr", "gu", "hinglish"}
    )


def test_nudge_preview_hindi_uses_devanagari_words(tmp_path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    r = client.get("/api/nudge/preview?language=hi&amount_minor=49900&link_url=https://pay.test/x")
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "hi"
    assert "Namaste" in body["text"]
    assert "Aapki" in body["text"]


def test_nudge_preview_unknown_language_falls_back_to_hinglish(tmp_path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    r = client.get("/api/nudge/preview?language=xx&amount_minor=49900")
    assert r.status_code == 200
    body = r.json()
    assert body["language"] == "xx"
    assert body["text"].startswith("Hi!")


def test_nudge_preview_no_link_renders_link_free(tmp_path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    r = client.get("/api/nudge/preview?language=hi&amount_minor=49900")
    assert r.status_code == 200
    body = r.json()
    assert "Namaste" in body["text"]
    assert "https://" not in body["text"]


def test_nudge_preview_all_six_languages_return_200(tmp_path) -> None:
    app = create_app(cfg=_config(tmp_path / "t.db"))
    client = TestClient(app)
    for lang in ("hi", "ta", "te", "bn", "mr", "gu", "hinglish"):
        r = client.get(f"/api/nudge/preview?language={lang}&amount_minor=49900")
        assert r.status_code == 200, f"{lang} failed: {r.text}"
        assert len(r.json()["text"]) > 0
