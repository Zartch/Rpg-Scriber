"""Domain models and configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ListenerConfig:
    """Configuration for a listener."""

    chunk_duration_s: float = 10.0  # Target chunk duration
    silence_threshold_s: float = 1.5  # Silence duration to trigger chunk emit
    short_silence_threshold_s: float = 0.5  # Short pause threshold
    min_chunk_duration_s: float = 0.5  # Minimum chunk to emit
    sample_rate: int = 48000  # PCM sample rate
    channels: int = 1  # Mono
    sample_width: int = 2  # 16-bit = 2 bytes
    vad_aggressiveness: int = 2  # webrtcvad aggressiveness 0-3


@dataclass
class PlayerInfo:
    """A player and their character."""

    discord_id: str
    discord_name: str
    character_name: str
    character_description: str = ""


@dataclass
class NPCInfo:
    """A known NPC."""

    name: str
    description: str = ""


@dataclass
class CampaignContext:
    """Full campaign context used by the summarizer."""

    campaign_id: str
    name: str  # e.g. "La Marca del Este"
    game_system: str  # e.g. "Akelarre", "Fading Suns"
    language: str = "es"
    description: str = ""

    players: list[PlayerInfo] = field(default_factory=list)
    known_npcs: list[NPCInfo] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    campaign_summary: str = ""

    # Mapping Discord User → Character
    speaker_map: dict[str, str] = field(default_factory=dict)
    dm_speaker_id: str = ""

    custom_instructions: str = ""


@dataclass
class TranscriberConfig:
    """Configuration for a transcriber."""

    # OpenAI API settings
    model: str = "gpt-4o-transcribe"  # or "whisper-1"
    language: str = "es"  # ISO 639-1 language code
    api_timeout_s: float = 30.0  # Per-request timeout

    # Concurrency and queue
    max_concurrent_requests: int = 4  # Parallel API requests
    queue_max_size: int = 100  # Max pending chunks in queue

    # Retry settings
    max_retries: int = 3
    retry_base_delay_s: float = 1.0  # Exponential backoff base

    # Contextual prompt hints (character names, etc.)
    prompt_hint: str = ""  # e.g. "Nombres esperados: Rodrigo, Aelar, DM"

    # Local (FasterWhisper) settings
    local_model_size: str = "medium"  # tiny, base, small, medium, large-v3
    device: str = "auto"  # "auto", "cpu", "cuda"
    compute_type: str = "float16"  # float16, int8, etc.
