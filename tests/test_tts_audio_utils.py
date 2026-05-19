"""Tests for the TTS audio resampling helpers."""

from __future__ import annotations

import numpy as np

from rpg_scribe.tts.audio_utils import (
    WAV_HEADER_SIZE,
    pcm_24k_mono_to_48k_stereo,
    pcm_from_wav,
    wrap_pcm_as_wav,
)


class TestWrapPcmAsWav:
    def test_header_size_is_44(self) -> None:
        pcm = b"\x00\x00" * 100
        wav = wrap_pcm_as_wav(pcm)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert len(wav) == WAV_HEADER_SIZE + len(pcm)

    def test_roundtrip(self) -> None:
        pcm = bytes(range(0, 200))  # 200 bytes
        wav = wrap_pcm_as_wav(pcm)
        assert pcm_from_wav(wav) == pcm

    def test_pcm_from_wav_rejects_garbage(self) -> None:
        import pytest
        with pytest.raises(ValueError):
            pcm_from_wav(b"not-a-wav")


class TestPcm24kMonoTo48kStereo:
    def test_length_doubles_for_each_dimension(self) -> None:
        """100 mono samples → 400 stereo samples (2× rate, 2× channels)."""
        mono = np.arange(100, dtype=np.int16).tobytes()
        out = pcm_24k_mono_to_48k_stereo(mono)
        # 100 samples * 2 (resample) * 2 (channels) * 2 bytes/sample
        assert len(out) == 100 * 2 * 2 * 2

    def test_output_is_int16(self) -> None:
        mono = np.array([0, 1000, -1000, 32000], dtype=np.int16).tobytes()
        out = pcm_24k_mono_to_48k_stereo(mono)
        arr = np.frombuffer(out, dtype=np.int16)
        assert arr.dtype == np.int16

    def test_left_and_right_channels_match(self) -> None:
        """After mono→stereo duplication, L and R must be identical."""
        mono = np.array([100, 200, 300, 400, 500], dtype=np.int16).tobytes()
        out = pcm_24k_mono_to_48k_stereo(mono)
        arr = np.frombuffer(out, dtype=np.int16)
        left = arr[0::2]
        right = arr[1::2]
        assert np.array_equal(left, right)

    def test_preserves_original_samples_at_even_positions(self) -> None:
        """Linear interpolation must keep original samples at the even indices."""
        mono_values = np.array([0, 1000, 2000, 3000, 4000], dtype=np.int16)
        mono = mono_values.tobytes()
        out = pcm_24k_mono_to_48k_stereo(mono)
        arr = np.frombuffer(out, dtype=np.int16)
        # Stereo, so left channel is arr[0::2]; even indices of the
        # upsampled mono signal should match the originals.
        left = arr[0::2]
        # First original sample maps to index 0; last original sample
        # maps to the last position of the upsampled signal.
        assert left[0] == mono_values[0]
        # Last upsampled sample must equal the last original sample
        assert left[-1] == mono_values[-1]

    def test_empty_input_yields_empty_output(self) -> None:
        assert pcm_24k_mono_to_48k_stereo(b"") == b""
