"""Pre-transcription audio filter and post-transcription hallucination detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

try:
    import webrtcvad

    _has_webrtcvad = True
except ImportError:
    webrtcvad = None  # type: ignore[assignment]
    _has_webrtcvad = False
    logger.warning("webrtcvad not available — audio filter will use RMS-only mode")

# Audio constants (48 kHz, 16-bit mono PCM)
_SAMPLE_RATE = 48000
_SAMPLE_WIDTH = 2  # bytes per sample
_FRAME_MS = 20
_FRAME_BYTES = _SAMPLE_RATE * _SAMPLE_WIDTH * _FRAME_MS // 1000  # 1920

# ---------------------------------------------------------------------------
# Known Whisper / gpt-4o-transcribe hallucination phrases
# ---------------------------------------------------------------------------
_HALLUCINATION_PATTERNS: list[str] = [
    "subtítulos realizados por",
    "amara.org",
    "gracias por ver",
    "suscríbete",
    "thanks for watching",
    "thank you for watching",
    "subscribe",
    "please subscribe",
    "like and subscribe",
    "copyright",
    "music playing",
    "música de fondo",
    "aplausos",
    "risas",
    "subtitulado por",
    "traducción por",
]


# ---------------------------------------------------------------------------
# Pre-transcription: audio analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioAnalysis:
    """Result of analyzing an audio chunk for speech content."""

    rms_energy: float
    speech_ratio: float
    duration_ms: int
    should_transcribe: bool
    discard_reason: str


def compute_rms(pcm_data: bytes) -> float:
    """Compute RMS energy of 16-bit PCM audio.

    Returns a value on the 0–32768 scale.
    """
    if len(pcm_data) < _SAMPLE_WIDTH:
        return 0.0
    samples = np.frombuffer(pcm_data, dtype=np.int16)
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def compute_speech_ratio(
    pcm_data: bytes,
    sample_rate: int = _SAMPLE_RATE,
    vad_aggressiveness: int = 3,
) -> float:
    """Return fraction of 20 ms frames classified as speech by webrtcvad (0.0–1.0).

    Falls back to 1.0 (assume all speech) if webrtcvad is unavailable.
    """
    if not _has_webrtcvad:
        return 1.0

    frame_bytes = sample_rate * _SAMPLE_WIDTH * _FRAME_MS // 1000
    if len(pcm_data) < frame_bytes:
        return 0.0

    vad = webrtcvad.Vad(vad_aggressiveness)
    total_frames = 0
    speech_frames = 0
    offset = 0

    while offset + frame_bytes <= len(pcm_data):
        frame = pcm_data[offset : offset + frame_bytes]
        total_frames += 1
        try:
            if vad.is_speech(frame, sample_rate):
                speech_frames += 1
        except Exception:
            # On error, conservatively assume speech
            speech_frames += 1
        offset += frame_bytes

    if total_frames == 0:
        return 0.0
    return speech_frames / total_frames


def _adaptive_speech_threshold(duration_ms: int, base_threshold: float) -> float:
    """Return a speech-ratio threshold that scales with chunk duration.

    Shorter chunks require a higher percentage of speech frames to pass,
    because brief noise (keyboard clicks, coughs) can fool the energy check.
    Longer chunks use the base threshold since noise averages out.
    """
    if duration_ms < 1000:
        return max(base_threshold, 0.60)
    if duration_ms < 2000:
        return max(base_threshold, 0.30)
    return base_threshold


def analyze_audio(
    pcm_data: bytes,
    duration_ms: int,
    *,
    sample_rate: int = _SAMPLE_RATE,
    rms_threshold: float = 200.0,
    speech_ratio_threshold: float = 0.15,
    vad_aggressiveness: int = 3,
    enabled: bool = True,
) -> AudioAnalysis:
    """Analyze an audio chunk and decide whether it should be transcribed.

    Combines RMS energy check with adaptive VAD speech-ratio analysis.
    Shorter chunks require a higher speech ratio to pass.
    """
    if not enabled:
        return AudioAnalysis(
            rms_energy=0.0,
            speech_ratio=1.0,
            duration_ms=duration_ms,
            should_transcribe=True,
            discard_reason="",
        )

    rms = compute_rms(pcm_data)

    # Fast path: near-silence — skip VAD entirely
    if rms < rms_threshold * 0.1:
        return AudioAnalysis(
            rms_energy=rms,
            speech_ratio=0.0,
            duration_ms=duration_ms,
            should_transcribe=False,
            discard_reason=f"near-silence (RMS={rms:.1f})",
        )

    speech_ratio = compute_speech_ratio(pcm_data, sample_rate, vad_aggressiveness)

    # Adaptive threshold: short chunks need denser speech
    effective_threshold = _adaptive_speech_threshold(duration_ms, speech_ratio_threshold)

    # Discard if EITHER energy is too low OR speech ratio is below adaptive threshold
    should_transcribe = rms >= rms_threshold and speech_ratio >= effective_threshold

    reason = ""
    if not should_transcribe:
        parts: list[str] = []
        if rms < rms_threshold:
            parts.append(f"low energy (RMS={rms:.1f} < {rms_threshold})")
        if speech_ratio < effective_threshold:
            parts.append(
                f"low speech ({speech_ratio:.1%} < {effective_threshold:.0%}"
                f"{' adaptive' if effective_threshold != speech_ratio_threshold else ''})"
            )
        reason = "; ".join(parts)

    return AudioAnalysis(
        rms_energy=rms,
        speech_ratio=speech_ratio,
        duration_ms=duration_ms,
        should_transcribe=should_transcribe,
        discard_reason=reason,
    )


# ---------------------------------------------------------------------------
# Post-transcription: hallucination detection
# ---------------------------------------------------------------------------


def is_hallucination(
    text: str,
    duration_ms: int,
    *,
    max_words_per_second: float = 6.0,
    extra_patterns: list[str] | None = None,
) -> tuple[bool, str]:
    """Detect known Whisper hallucination patterns in transcribed text.

    Returns ``(True, reason)`` if the text looks like a hallucination,
    ``(False, "")`` otherwise.

    Checks (in order):
    1. Known hallucination phrases (Whisper "phantom" strings).
    2. Excessive word repetition (same token ≥ 3× and ≥ 60% of words).
    3. Implausible words-per-second ratio (too much text for the audio length).
    """
    lower = text.lower().strip()
    if not lower:
        return False, ""

    # 1. Known hallucination phrases
    all_patterns = _HALLUCINATION_PATTERNS + (extra_patterns or [])
    for pattern in all_patterns:
        if pattern in lower:
            return True, f"hallucination pattern: '{pattern}'"

    # 2. Excessive word repetition
    words = lower.split()
    if len(words) >= 3:
        for word in set(words):
            count = words.count(word)
            if count >= 3 and count >= len(words) * 0.6:
                return True, f"excessive repetition: '{word}' x{count}/{len(words)}"

    # 3. Words-per-second ratio
    if duration_ms > 0 and max_words_per_second > 0:
        duration_s = duration_ms / 1000.0
        wps = len(words) / duration_s
        if wps > max_words_per_second:
            return True, f"implausible speech rate ({wps:.1f} wps > {max_words_per_second})"

    return False, ""
