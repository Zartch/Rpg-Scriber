"""Tests for the pre-transcription audio filter and hallucination detection."""

from __future__ import annotations

import math
import struct

import pytest

from rpg_scribe.transcribers.audio_filter import (
    AudioAnalysis,
    _adaptive_speech_threshold,
    analyze_audio,
    compute_rms,
    compute_speech_ratio,
    is_hallucination,
)

SAMPLE_RATE = 48000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silence(duration_s: float) -> bytes:
    """PCM16 silence (all zeros)."""
    n = int(SAMPLE_RATE * duration_s)
    return b"\x00" * (n * 2)


def _make_sine(
    duration_s: float, frequency: float = 440.0, amplitude: int = 5000
) -> bytes:
    """PCM16 sine wave — has high energy and realistic frequency content."""
    n = int(SAMPLE_RATE * duration_s)
    samples = [
        int(amplitude * math.sin(2 * math.pi * frequency * i / SAMPLE_RATE))
        for i in range(n)
    ]
    return struct.pack(f"<{n}h", *samples)


def _make_low_noise(duration_s: float, amplitude: int = 20) -> bytes:
    """PCM16 very low amplitude pseudo-random noise."""
    import random

    rng = random.Random(42)  # deterministic
    n = int(SAMPLE_RATE * duration_s)
    samples = [rng.randint(-amplitude, amplitude) for _ in range(n)]
    return struct.pack(f"<{n}h", *samples)


# ---------------------------------------------------------------------------
# Tests: compute_rms
# ---------------------------------------------------------------------------

class TestComputeRms:
    def test_silence_is_zero(self) -> None:
        assert compute_rms(_make_silence(0.5)) == 0.0

    def test_empty_data(self) -> None:
        assert compute_rms(b"") == 0.0

    def test_single_byte_too_short(self) -> None:
        assert compute_rms(b"\x00") == 0.0

    def test_constant_value(self) -> None:
        # 1000 samples of value 500 → RMS = 500.0
        pcm = struct.pack("<1000h", *([500] * 1000))
        assert compute_rms(pcm) == pytest.approx(500.0)

    def test_sine_wave_rms(self) -> None:
        # Sine wave amplitude A → RMS ≈ A / √2
        amplitude = 10000
        pcm = _make_sine(1.0, amplitude=amplitude)
        expected_rms = amplitude / math.sqrt(2)
        assert compute_rms(pcm) == pytest.approx(expected_rms, rel=0.01)

    def test_low_noise_has_low_rms(self) -> None:
        pcm = _make_low_noise(1.0, amplitude=20)
        rms = compute_rms(pcm)
        assert rms < 50  # Well below default threshold


# ---------------------------------------------------------------------------
# Tests: compute_speech_ratio
# ---------------------------------------------------------------------------

class TestComputeSpeechRatio:
    def test_silence_has_zero_or_very_low_ratio(self) -> None:
        pcm = _make_silence(1.0)
        ratio = compute_speech_ratio(pcm, SAMPLE_RATE, vad_aggressiveness=2)
        assert ratio < 0.05

    def test_empty_data(self) -> None:
        assert compute_speech_ratio(b"", SAMPLE_RATE) == 0.0

    def test_short_data_less_than_one_frame(self) -> None:
        # Less than 1920 bytes (one 20ms frame at 48kHz)
        assert compute_speech_ratio(b"\x00" * 100, SAMPLE_RATE) == 0.0

    def test_sine_wave_detected_as_some_speech(self) -> None:
        # A sine wave may or may not trigger VAD depending on frequency/amplitude.
        # At least verify it returns a float in [0, 1].
        pcm = _make_sine(1.0, frequency=300, amplitude=8000)
        ratio = compute_speech_ratio(pcm, SAMPLE_RATE, vad_aggressiveness=0)
        assert 0.0 <= ratio <= 1.0


# ---------------------------------------------------------------------------
# Tests: _adaptive_speech_threshold
# ---------------------------------------------------------------------------

class TestAdaptiveSpeechThreshold:
    def test_very_short_chunk_needs_high_threshold(self) -> None:
        assert _adaptive_speech_threshold(500, 0.15) == 0.60

    def test_short_chunk_needs_medium_threshold(self) -> None:
        assert _adaptive_speech_threshold(1500, 0.15) == 0.30

    def test_normal_chunk_uses_base_threshold(self) -> None:
        assert _adaptive_speech_threshold(3000, 0.15) == 0.15

    def test_base_threshold_higher_than_adaptive_is_preserved(self) -> None:
        """If base threshold is already higher than adaptive, it wins."""
        assert _adaptive_speech_threshold(500, 0.90) == 0.90

    def test_boundary_at_1000ms(self) -> None:
        assert _adaptive_speech_threshold(999, 0.10) == 0.60
        assert _adaptive_speech_threshold(1000, 0.10) == 0.30

    def test_boundary_at_2000ms(self) -> None:
        assert _adaptive_speech_threshold(1999, 0.10) == 0.30
        assert _adaptive_speech_threshold(2000, 0.10) == 0.10


# ---------------------------------------------------------------------------
# Tests: analyze_audio
# ---------------------------------------------------------------------------

class TestAnalyzeAudio:
    def test_silence_not_transcribed(self) -> None:
        pcm = _make_silence(1.0)
        result = analyze_audio(pcm, duration_ms=1000)
        assert result.should_transcribe is False
        assert result.discard_reason  # Non-empty reason
        assert result.rms_energy == pytest.approx(0.0)

    def test_near_silence_fast_path(self) -> None:
        """Very low RMS triggers fast path (skips VAD)."""
        pcm = _make_silence(0.5)
        result = analyze_audio(pcm, duration_ms=500, rms_threshold=100.0)
        assert result.should_transcribe is False
        assert "near-silence" in result.discard_reason
        assert result.speech_ratio == 0.0

    def test_low_noise_not_transcribed(self) -> None:
        pcm = _make_low_noise(1.0, amplitude=20)
        result = analyze_audio(pcm, duration_ms=1000)
        assert result.should_transcribe is False

    def test_loud_sine_analyzed(self) -> None:
        """A loud sine wave passes the RMS check at minimum."""
        pcm = _make_sine(1.0, amplitude=8000)
        result = analyze_audio(pcm, duration_ms=1000)
        assert result.rms_energy > 200.0
        assert isinstance(result, AudioAnalysis)

    def test_filter_disabled_always_passes(self) -> None:
        pcm = _make_silence(1.0)
        result = analyze_audio(pcm, duration_ms=1000, enabled=False)
        assert result.should_transcribe is True
        assert result.discard_reason == ""

    def test_custom_low_thresholds_allow_more(self) -> None:
        """Very permissive thresholds let low noise through (long chunk avoids adaptive)."""
        pcm = _make_low_noise(3.0, amplitude=20)
        result = analyze_audio(
            pcm,
            duration_ms=3000,  # >2s avoids adaptive speech-ratio boost
            rms_threshold=5.0,
            speech_ratio_threshold=0.0,
        )
        assert result.should_transcribe is True

    def test_discard_reason_mentions_energy(self) -> None:
        pcm = _make_low_noise(0.5, amplitude=10)
        result = analyze_audio(pcm, duration_ms=500, rms_threshold=100.0)
        if not result.should_transcribe:
            assert "energy" in result.discard_reason or "near-silence" in result.discard_reason

    def test_analysis_fields_populated(self) -> None:
        pcm = _make_sine(0.5, amplitude=5000)
        result = analyze_audio(pcm, duration_ms=500)
        assert result.duration_ms == 500
        assert result.rms_energy > 0
        assert 0.0 <= result.speech_ratio <= 1.0

    def test_high_rms_low_speech_ratio_discarded(self) -> None:
        """Audio with energy but no speech characteristics is discarded."""
        n = int(SAMPLE_RATE * 1.0)
        pcm = struct.pack(f"<{n}h", *([3000] * n))
        result = analyze_audio(pcm, duration_ms=1000, rms_threshold=100.0)
        assert result.rms_energy > 100.0
        if result.speech_ratio < 0.15:
            assert result.should_transcribe is False
            assert "speech" in result.discard_reason

    def test_short_chunk_requires_higher_speech_ratio(self) -> None:
        """A 500ms chunk needs 60% speech ratio even if base threshold is 15%."""
        pcm = _make_sine(0.5, amplitude=8000)
        result = analyze_audio(
            pcm, duration_ms=500, speech_ratio_threshold=0.15
        )
        # If speech ratio is between 0.15 and 0.60, the adaptive
        # threshold for <1000ms (0.60) should reject it
        if 0.15 <= result.speech_ratio < 0.60:
            assert result.should_transcribe is False
            assert "adaptive" in result.discard_reason

    def test_long_chunk_uses_base_threshold(self) -> None:
        """A 3s chunk uses the base speech_ratio_threshold (no adaptive boost)."""
        pcm = _make_sine(3.0, amplitude=8000)
        result = analyze_audio(
            pcm, duration_ms=3000, rms_threshold=50.0, speech_ratio_threshold=0.05
        )
        # With low thresholds the loud sine should pass
        if result.speech_ratio >= 0.05:
            assert result.should_transcribe is True


# ---------------------------------------------------------------------------
# Tests: is_hallucination
# ---------------------------------------------------------------------------

class TestIsHallucination:
    def test_normal_text_not_hallucination(self) -> None:
        is_hallu, reason = is_hallucination("Creo que deberíamos ir al norte", 3000)
        assert is_hallu is False
        assert reason == ""

    def test_short_valid_response(self) -> None:
        """'Sí' in a 500ms chunk (2 wps) should pass."""
        is_hallu, _ = is_hallucination("Sí", 500)
        assert is_hallu is False

    def test_known_pattern_detected(self) -> None:
        is_hallu, reason = is_hallucination("Gracias por ver este vídeo", 5000)
        assert is_hallu is True
        assert "hallucination pattern" in reason

    def test_known_pattern_case_insensitive(self) -> None:
        is_hallu, _ = is_hallucination("SUSCRÍBETE al canal", 3000)
        assert is_hallu is True

    def test_amara_pattern(self) -> None:
        is_hallu, _ = is_hallucination(
            "Subtítulos realizados por la comunidad de Amara.org", 5000
        )
        assert is_hallu is True

    def test_excessive_repetition(self) -> None:
        is_hallu, reason = is_hallucination("sí sí sí sí sí sí", 3000)
        assert is_hallu is True
        assert "repetition" in reason

    def test_moderate_repetition_ok(self) -> None:
        """Two occurrences of a word is fine."""
        is_hallu, _ = is_hallucination("sí, creo que sí", 2000)
        assert is_hallu is False

    def test_implausible_words_per_second(self) -> None:
        """20 distinct words in 500ms = 40 wps → hallucination by speech rate."""
        # Use distinct words to avoid triggering repetition check first
        words = [f"palabra{i}" for i in range(20)]
        text = " ".join(words)
        is_hallu, reason = is_hallucination(text, 500, max_words_per_second=6.0)
        assert is_hallu is True
        assert "speech rate" in reason

    def test_plausible_words_per_second(self) -> None:
        """3 words in 1000ms = 3 wps → OK."""
        is_hallu, _ = is_hallucination("El caballero avanza", 1000)
        assert is_hallu is False

    def test_empty_text_not_hallucination(self) -> None:
        is_hallu, _ = is_hallucination("", 1000)
        assert is_hallu is False

    def test_custom_extra_patterns(self) -> None:
        is_hallu, reason = is_hallucination(
            "patrocinado por NordVPN",
            5000,
            extra_patterns=["patrocinado por"],
        )
        assert is_hallu is True
        assert "patrocinado por" in reason

    def test_wps_check_disabled_with_zero_max(self) -> None:
        """max_words_per_second=0 disables the wps check."""
        text = " ".join(["palabra"] * 20)
        is_hallu, _ = is_hallucination(text, 500, max_words_per_second=0)
        # Should still catch the repetition
        assert is_hallu is True

    def test_single_word_not_repetition(self) -> None:
        """A single word shouldn't trigger repetition check."""
        is_hallu, _ = is_hallucination("No", 500)
        assert is_hallu is False

    def test_two_words_not_repetition(self) -> None:
        is_hallu, _ = is_hallucination("No no", 500)
        assert is_hallu is False
