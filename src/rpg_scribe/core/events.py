"""Typed event dataclasses for the RPG Scribe event bus."""

from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass(frozen=True)
class AudioChunkEvent:
    """Emitted by a Listener when an audio chunk is ready."""

    session_id: str
    speaker_id: str  # Platform user ID
    speaker_name: str  # Human-readable name
    audio_data: bytes  # PCM 16-bit 48kHz mono
    timestamp: float  # Unix timestamp of chunk start
    duration_ms: int  # Duration in milliseconds
    source: str  # "discord", "teams", "file", etc.


@dataclass(frozen=True)
class TranscriptionEvent:
    """Emitted by a Transcriber when text is ready."""

    session_id: str
    speaker_id: str
    speaker_name: str
    text: str
    timestamp: float
    confidence: float  # 0.0 - 1.0
    is_partial: bool  # True if partial/streaming transcription


@dataclass(frozen=True)
class SummaryUpdateEvent:
    """Emitted by a Summarizer when the summary is updated."""

    session_id: str
    session_summary: str  # Current session summary
    campaign_summary: str  # Accumulated campaign summary
    last_updated: float
    update_type: str  # "incremental", "revision", "final"


@dataclass(frozen=True)
class SystemStatusEvent:
    """System status for visualization."""

    component: str  # "listener", "transcriber", "summarizer"
    status: str  # "running", "error", "idle"
    message: str
    timestamp: float = field(default_factory=time.time)
