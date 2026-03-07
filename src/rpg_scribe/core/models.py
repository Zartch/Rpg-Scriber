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
class RelationshipTypeInfo:
    """A canonical relationship type inside a campaign thesaurus."""

    key: str
    label: str
    category: str = "general"


@dataclass
class CharacterRelationshipInfo:
    """A typed relationship between two entities in the campaign."""

    source_key: str
    target_key: str
    relation_type_key: str
    relation_type_label: str
    notes: str = ""



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
    relation_types: list[RelationshipTypeInfo] = field(default_factory=list)
    relationships: list[CharacterRelationshipInfo] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    campaign_summary: str = ""

    # Mapping Discord User -> Character
    speaker_map: dict[str, str] = field(default_factory=dict)
    dm_speaker_id: str = ""

    custom_instructions: str = ""

    # True when running without a campaign TOML (generic summarization)
    is_generic: bool = False

    @classmethod
    def create_generic(cls, language: str = "es") -> CampaignContext:
        """Create a minimal context for campaign-free summarization."""
        return cls(
            campaign_id="__generic__",
            name="Sesión sin campaña",
            game_system="",
            language=language,
            is_generic=True,
        )


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

    # Local (FasterWhisper) settings
    local_model_size: str = "medium"  # tiny, base, small, medium, large-v3
    device: str = "auto"  # "auto", "cpu", "cuda"
    compute_type: str = "float16"  # float16, int8, etc.

    # Pre-transcription audio filter
    audio_filter_enabled: bool = True
    audio_filter_rms_threshold: float = 200.0  # Min RMS energy (0-32768 scale)
    audio_filter_speech_ratio_threshold: float = 0.15  # Base min speech ratio (>2s chunks)
    audio_filter_vad_aggressiveness: int = 3  # webrtcvad aggressiveness 0-3

    # Post-transcription hallucination filter
    post_filter_enabled: bool = True
    post_filter_max_words_per_second: float = 6.0  # Max plausible speech rate

    # Debug: save discarded chunks as WAV files for analysis (dev)
    audio_debug_log_dir: str = ""  # "" = disabled; e.g. "logs/audio"


@dataclass
class SessionInfo:
    """Summary info for a past session."""

    session_id: str
    started_at: str = ""
    ended_at: str = ""
    summary: str = ""


@dataclass
class SummarizerConfig:
    """Configuration for a summarizer."""

    # Trigger thresholds
    update_interval_s: float = 120.0  # ~2 minutes between updates
    max_pending_transcriptions: int = 20  # Or trigger after N transcriptions

    # Claude API settings
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    api_timeout_s: float = 60.0

    # Retry settings
    max_retries: int = 3
    retry_base_delay_s: float = 1.0

    # Batch finalization - max chars per API call (~4 chars/token)
    max_input_chars: int = 600_000  # ~150K tokens, safe for Sonnet 200K


