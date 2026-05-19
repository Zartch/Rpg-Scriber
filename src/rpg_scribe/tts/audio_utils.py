"""Audio format helpers used to bridge TTS output to Discord voice.

OpenAI TTS with ``response_format="pcm"`` returns raw 24 kHz mono int16 LE.
Discord voice expects 48 kHz stereo int16 LE (3,840 bytes per 20 ms frame).
We resample, duplicate the channel, and wrap as WAV here so the result can
be both played natively by browsers (``<audio src="...wav">``) and fed to
``discord.PCMAudio`` after stripping the WAV header — without invoking
ffmpeg.
"""
from __future__ import annotations

import struct

import numpy as np

WAV_HEADER_SIZE = 44


def wrap_pcm_as_wav(pcm_bytes: bytes, sample_rate: int = 48000, channels: int = 2) -> bytes:
    """Prepend a canonical 44-byte WAV header to a PCM int16 LE payload."""
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm_bytes)

    header = b"RIFF"
    header += struct.pack("<I", 36 + data_size)
    header += b"WAVE"
    header += b"fmt "
    header += struct.pack("<I", 16)              # PCM fmt chunk size
    header += struct.pack("<H", 1)               # PCM format
    header += struct.pack("<H", channels)
    header += struct.pack("<I", sample_rate)
    header += struct.pack("<I", byte_rate)
    header += struct.pack("<H", block_align)
    header += struct.pack("<H", bits_per_sample)
    header += b"data"
    header += struct.pack("<I", data_size)
    return header + pcm_bytes


def pcm_from_wav(wav_bytes: bytes) -> bytes:
    """Strip the canonical 44-byte WAV header to recover raw PCM bytes.

    Assumes the WAV was produced by :func:`wrap_pcm_as_wav` (no extra
    chunks between ``fmt`` and ``data``).
    """
    if len(wav_bytes) < WAV_HEADER_SIZE or wav_bytes[:4] != b"RIFF":
        raise ValueError("Not a WAV file")
    return wav_bytes[WAV_HEADER_SIZE:]


def pcm_24k_mono_to_48k_stereo(pcm_bytes: bytes) -> bytes:
    """Convert raw 24 kHz mono int16 LE PCM to 48 kHz stereo int16 LE PCM.

    The output is interleaved (``L R L R ...``) as Discord expects.
    """
    mono = np.frombuffer(pcm_bytes, dtype=np.int16)
    if mono.size == 0:
        return b""

    # Linear interpolation 1× → 2× the sample count. Keeping ``num = 2*N``
    # with the default ``endpoint=True`` preserves both endpoints exactly,
    # which keeps consecutive chunks seamless when concatenated.
    new_idx = np.linspace(0, mono.size - 1, mono.size * 2)
    up = np.interp(new_idx, np.arange(mono.size), mono.astype(np.float32))
    up = np.round(up).clip(-32768, 32767).astype(np.int16)

    # Mono → interleaved stereo (L R L R …).
    stereo = np.stack([up, up], axis=-1).reshape(-1)
    return stereo.tobytes()
