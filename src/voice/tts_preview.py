"""TTS preview + measured-duration gate (plan §17, §20.4, V1C).

Replaces the WPM-based duration ESTIMATE (`narration/short_generator.py`'s
`PLANNING_WPM`) with a real measured spoken duration for shorts, where an
estimate's own error margin genuinely matters against a hard duration cap
(up to 120s, plan §20.4). Uses `edge-tts` (Microsoft Edge's free, keyless
TTS service) with
the `en-IN-PrabhatNeural` voice, chosen deliberately (user decision,
2026-09-11) over a paid provider -- no new credential, no per-short cost.

Duration comes from the engine's own `SentenceBoundary` events (offset +
duration, in 100-nanosecond units), not from decoding the saved audio
file afterward -- this is the exact timing edge-tts itself used to
synthesize the speech, more authoritative than re-measuring the output,
and avoids adding an audio-decoding dependency for something the engine
already reports directly.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import edge_tts

EDGE_TTS_VOICE = "en-IN-PrabhatNeural"
_HUNDRED_NS_PER_SECOND = 10_000_000


@dataclass
class TtsPreviewResult:
    audio_bytes: bytes
    measured_duration_seconds: float


async def _synthesize_async(text: str, voice: str) -> TtsPreviewResult:
    communicate = edge_tts.Communicate(text, voice)
    audio_chunks: list[bytes] = []
    last_end_100ns = 0

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        elif chunk["type"] == "SentenceBoundary":
            end = chunk["offset"] + chunk["duration"]
            last_end_100ns = max(last_end_100ns, end)

    return TtsPreviewResult(
        audio_bytes=b"".join(audio_chunks),
        measured_duration_seconds=last_end_100ns / _HUNDRED_NS_PER_SECOND,
    )


def synthesize_narration_preview(text: str, voice: str = EDGE_TTS_VOICE) -> TtsPreviewResult:
    """Sync entry point -- callers in this codebase are sync throughout;
    edge-tts's API is async-only, so this owns the one asyncio.run()."""
    return asyncio.run(_synthesize_async(text, voice))
