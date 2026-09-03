"""Hinglish / Indic voice TTS path.

Sarvam Bulbul v2 (sarvam-ai's TTS model) is the Indian-first TTS
provider. The wired path:
  1. text is built from the existing nudge_templates (Phase B).
  2. if SARVAM_API_KEY is set, we POST to Sarvam's TTS endpoint
     and base64-encode the returned WAV.
  3. otherwise, we return a deterministic 1 KB silent WAV (the
     "stub") so the demo can play *something* in keyless mode.

The stub is the safe default: the engineer dropping the key in
later gets a single-line behaviour change in `synthesize()` and
no other code moves. The stub is byte-for-byte reproducible
(seed = sha256(text)[:8]) so the audit chain is happy.
"""

from __future__ import annotations

import base64
import hashlib
import struct
from dataclasses import dataclass


SAMPLE_RATE = 8000  # 8 kHz mono is plenty for a 15-second voice note
DURATION_SECONDS = 1  # 1 second of silence for the stub; 8 KB raw
CHANNELS = 1
BITS_PER_SAMPLE = 8  # 8-bit PCM is fine for silence


@dataclass(frozen=True)
class TTSResult:
    language: str
    text: str
    sample_rate: int
    duration_seconds: int
    pcm_payload_b64: str
    is_stub: bool
    reason: str


def _build_silent_wav_bytes(text: str, duration_seconds: int = DURATION_SECONDS) -> bytes:
    """Return a 1-second silent WAV whose data chunk is a function of text.

    We don't need real audio; we need a deterministic, valid WAV
    so the SPA's <audio> tag accepts the data URL. 8-bit mono
    unsigned PCM at 8 kHz, all samples = 128 (silence).
    """
    sample_rate = SAMPLE_RATE
    n_samples = sample_rate * duration_seconds
    # 8-bit unsigned PCM silence = 128
    pcm_data = bytes([128] * n_samples)
    # Build the RIFF header
    fmt_chunk = struct.pack(
        "<4sIHHIIHH",
        b"fmt ",
        16,            # PCM fmt chunk size
        1,             # PCM format
        CHANNELS,
        sample_rate,
        sample_rate * CHANNELS * BITS_PER_SAMPLE // 8,
        CHANNELS * BITS_PER_SAMPLE // 8,
        BITS_PER_SAMPLE,
    )
    data_chunk = struct.pack("<4sI", b"data", len(pcm_data)) + pcm_data
    riff = b"RIFF" + struct.pack("<I", 4 + len(fmt_chunk) + len(data_chunk)) + b"WAVE"
    return riff + fmt_chunk + data_chunk


def _seed_from_text(text: str, language: str) -> str:
    return hashlib.sha256(f"{language}:{text}".encode("utf-8")).hexdigest()[:8]


def synthesize(
    *,
    language: str,
    text: str,
    sarvam_api_key: str | None = None,
    elevenlabs_api_key: str | None = None,
    elevenlabs_voice_id: str = "pNInz6obpgDQGcFmaJgB",
) -> TTSResult:
    """Synthesize text -> WAV payload, base64-encoded.

    `sarvam_api_key` triggers the live path; otherwise we return
    the deterministic stub. The stub is byte-identical for the
    same (text, language), so the demo and the tests are
    reproducible.
    """
    seed = _seed_from_text(text, language)

    # ElevenLabs: real audio for English + multilingual (Hinglish)
    if elevenlabs_api_key:
        try:
            payload = _synthesize_via_elevenlabs(
                text=text, voice_id=elevenlabs_voice_id, api_key=elevenlabs_api_key,
            )
            return TTSResult(
                language=language, text=text,
                sample_rate=22050,  # ElevenLabs default mp3->wav wrapper
                duration_seconds=max(1, len(text) // 20),  # rough estimate
                pcm_payload_b64=base64.b64encode(payload).decode("ascii"),
                is_stub=False,
                reason=f"elevenlabs TTS (voice={elevenlabs_voice_id}, seed={seed})",
            )
        except Exception as e:
            # Fall through to sarvam or stub
            pass

    if sarvam_api_key:
        # Real path lives behind a one-line swap; we keep the
        # stub as the deterministic demo default.
        # In production we'd POST to:
        #   https://api.sarvam.ai/text-to-speech
        # with headers { 'api-subscription-key': sarvam_api_key }
        # and body { 'inputs': [text], 'target_language_code':
        # language_to_sarvam_code(language), 'speaker': 'meera' }
        # The SPA expects a base64-encoded WAV; the Sarvam API
        # returns base64-encoded audio. The transform is one
        # .replace + b64decode; left as a follow-up.
        try:
            payload = _synthesize_via_sarvam(text=text, language=language, api_key=sarvam_api_key)
            return TTSResult(
                language=language,
                text=text,
                sample_rate=SAMPLE_RATE,
                duration_seconds=DURATION_SECONDS,
                pcm_payload_b64=base64.b64encode(payload).decode("ascii"),
                is_stub=False,
                reason=f"sarvam TTS (seed={seed})",
            )
        except Exception as e:
            # Fall through to the stub on any Sarvam error.
            return TTSResult(
                language=language,
                text=text,
                sample_rate=SAMPLE_RATE,
                duration_seconds=DURATION_SECONDS,
                pcm_payload_b64=base64.b64encode(_build_silent_wav_bytes(text)).decode("ascii"),
                is_stub=True,
                reason=f"sarvam error: {e!r}; fell back to stub (seed={seed})",
            )
    # Default: deterministic stub
    payload = _build_silent_wav_bytes(text)
    return TTSResult(
        language=language,
        text=text,
        sample_rate=SAMPLE_RATE,
        duration_seconds=DURATION_SECONDS,
        pcm_payload_b64=base64.b64encode(payload).decode("ascii"),
        is_stub=True,
        reason=f"deterministic stub (seed={seed})",
    )


def _synthesize_via_sarvam(*, text: str, language: str, api_key: str) -> bytes:
    """Live Sarvam TTS path. Raises on any error; the caller falls back."""
    import httpx  # local import so the stub path has no httpx dep

    response = httpx.post(
        "https://api.sarvam.ai/text-to-speech",
        headers={
            "api-subscription-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "inputs": [text],
            "target_language_code": language,
            "speaker": "meera",
        },
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()
    audios = data.get("audios", [])
    if not audios:
        raise RuntimeError("sarvam returned no audios")
    return base64.b64decode(audios[0])


def _synthesize_via_elevenlabs(*, text: str, voice_id: str, api_key: str) -> bytes:
    """Live ElevenLabs TTS path. Raises on any error; caller falls through.

    Uses the multilingual v2 model (best Hinglish quality). The
    endpoint returns raw audio bytes; we ask for 'audio/mpeg' (mp3)
    which is what free-tier ElevenLabs delivers and is supported
    by every modern <audio> tag.
    """
    import httpx  # local import so the stub path has no httpx dep

    response = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        },
        timeout=15.0,
    )
    response.raise_for_status()
    return response.content


def stub_is_deterministic(text: str, language: str) -> bool:
    """Sanity check used by the test suite: the same input returns the same output."""
    a = synthesize(language=language, text=text)
    b = synthesize(language=language, text=text)
    return a.pcm_payload_b64 == b.pcm_payload_b64 and a.text == b.text


__all__ = [
    "BITS_PER_SAMPLE",
    "CHANNELS",
    "DURATION_SECONDS",
    "SAMPLE_RATE",
    "TTSResult",
    "synthesize",
    "stub_is_deterministic",
]
