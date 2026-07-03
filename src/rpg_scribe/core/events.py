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
    is_corrected: bool = False  # True if re-published after word replacement


@dataclass(frozen=True)
class SummaryUpdateEvent:
    """Emitted by a Summarizer when the summary is updated."""

    session_id: str
    session_summary: str  # Current session summary
    campaign_summary: str  # Accumulated campaign summary
    last_updated: float
    update_type: str  # "incremental", "revision", "final"
    session_chronology: str = ""  # Chronological timeline (generated at finalization)


@dataclass(frozen=True)
class SessionStartRequestEvent:
    """Published when a session begins (e.g. /scribe start)."""

    session_id: str
    source: str  # "discord", "file", "web", etc.


@dataclass(frozen=True)
class SessionEndRequestEvent:
    """Published when a session should be finalized (e.g. /scribe stop)."""

    session_id: str
    source: str  # "discord", "file", "web", etc.


@dataclass(frozen=True)
class SummaryRefreshRequestEvent:
    """Published when an on-demand summary refresh is requested."""

    session_id: str
    source: str  # "web", "discord", etc.


@dataclass(frozen=True)
class EntitiesUpdatedEvent:
    """Emitted when new NPCs, locations or relationships are discovered via extraction."""

    campaign_id: str
    session_id: str
    new_npcs: tuple[str, ...]  # Names of newly-saved NPCs
    new_locations: tuple[str, ...]  # Names of newly-saved locations
    new_entities: tuple[str, ...]  # Names of newly-saved entities (groups, factions…)
    new_relationships: tuple[str, ...]  # "source -> target: type" labels
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GenerationProgressEvent:
    """Progress update during summary/chronology/campaign generation."""

    target: str  # "narrative", "chronology", "campaign"
    message: str
    campaign_id: str = ""
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SystemStatusEvent:
    """System status for visualization."""

    component: str  # "listener", "transcriber", "summarizer"
    status: str  # "running", "error", "idle"
    message: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TriggerActivatedEvent:
    """Emitted by TriggerWatcher when a bot keyword command is fully captured.

    Published for observability (logging, future feed). The watcher does not
    rely on it to invoke the bot — the call to ``bot.handle()`` happens
    inline in the watcher.
    """

    session_id: str
    speaker_id: str
    speaker_name: str
    bot_keyword: str
    command: str
    started_at: float
    closed_at: float
    close_reason: str  # "timeout" | "close_word"


@dataclass(frozen=True)
class Citation:
    """Una referencia a manual + página usada en una respuesta de bot."""

    manual: str
    page: int
    section_path: str | None = None


@dataclass(frozen=True)
class BotTextResponseEvent:
    """Emitido por TriggerWatcher cuando un bot devuelve una respuesta escrita.

    Lo consume DiscordBotResponsePublisher para postear un embed. ``citations``
    puede ir vacío. ``voice_channel_id`` es el canal de voz donde se invocó al
    bot (resuelto por el watcher); el publisher lo usa como fallback cuando no
    hay un canal de texto dedicado configurado.
    """

    session_id: str
    bot_keyword: str
    speaker_name: str
    question: str
    answer_md: str
    citations: tuple[Citation, ...] = ()
    voice_channel_id: int | None = None
